#!/usr/bin/env python3
"""Render per-cut narration to audio.

Usage: python3 tts.py timeline/example.yaml [cut-id ...]
Engines (timeline `tts_engine`):
  say (default) - macOS `say` with `tts_voice` (omit tts_voice to use the
    system default voice). Zero setup, works offline.
  elevenlabs - ElevenLabs TTS. Needs ELEVENLABS_API_KEY in ~/.env;
    tts_voice is the ElevenLabs voice id.

Neither engine is required — `say` is macOS-only, so on Linux/Windows either
add ELEVENLABS_API_KEY or bring your own engine: this file only has two
render_*() functions, add a third (same signature: text, voice, out_wav) and
route to it in main() to plug in any other TTS backend (a local model, a
company voice service, etc.) — nothing here assumes network access.

Output contract either way: assets/tts/<id>.wav, 48kHz mono.

Prints a fit report: narration audio must fit inside cut duration - 0.4s.
"""
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def render_say(text, voice, out_wav):
    aiff = out_wav.with_suffix(".aiff")
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    cmd += ["-o", str(aiff), text]
    subprocess.run(cmd, check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
         "-ar", "48000", "-ac", "1", str(out_wav)],
        check=True,
    )
    aiff.unlink()


def render_elevenlabs(text, voice_id, out_wav):
    """ElevenLabs TTS. Key: ELEVENLABS_API_KEY in ~/.env. voice_id from the
    timeline's tts_voice when tts_engine: elevenlabs."""
    import json
    import urllib.request

    key = None
    envf = Path.home() / ".env"
    if envf.exists():
        import re as _re
        m = _re.search(r"^ELEVENLABS_API_KEY=[\"']?([A-Za-z0-9_-]+)",
                       envf.read_text(), _re.M)
        key = m.group(1) if m else None
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not in ~/.env")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8,
                                "style": 0.35},
        }).encode(),
        headers={"Content-Type": "application/json", "xi-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        audio = r.read()
    tmp = out_wav.with_suffix(".mp3")
    tmp.write_bytes(audio)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
         # cuts low-frequency rumble some synthesized voices carry (reads as
         # a bass hum on full-range speakers) — tune/remove per your voice
         "-af", "highpass=f=85:p=2", "-ar", "48000", "-ac", "1", str(out_wav)],
        check=True)
    tmp.unlink()


def duration_of(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def main():
    doc = yaml.safe_load(open(sys.argv[1]))
    only = set(sys.argv[2:])
    engine = doc.get("tts_engine", "say")
    voice = doc.get("tts_voice")
    (ROOT / "assets/tts").mkdir(parents=True, exist_ok=True)

    overruns = 0
    for cut in doc["cuts"]:
        cid, text = cut["id"], cut.get("narration", "").strip()
        if not text or (only and cid not in only):
            continue
        out = ROOT / f"assets/tts/{cid}.wav"
        if engine == "elevenlabs":
            render_elevenlabs(text, voice, out)
        else:
            render_say(text, voice, out)
        # per-cut pace variation (0.9..1.1) fights TTS monotony; atempo keeps pitch
        tempo = float(cut.get("tempo", 1.0))
        if abs(tempo - 1.0) > 0.001:
            tmp = out.with_suffix(".t.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(out),
                 "-af", f"atempo={tempo}", str(tmp)], check=True)
            tmp.replace(out)
        audio_s = duration_of(out)
        budget = cut["duration"] - 0.4
        flag = "ok" if audio_s <= budget else "OVERRUN"
        if flag != "ok":
            overruns += 1
        print(f"[tts] {cid}: {audio_s:.1f}s / {cut['duration']}s cut [{flag}]")

    if overruns:
        if doc.get("gates", {}).get("auto_fit"):
            print(f"\n{overruns} narration(s) exceed their yaml duration; "
                  "auto_fit will stretch those cuts at assemble time.")
        else:
            print(f"\n{overruns} narration(s) exceed their cut. Shorten text or extend cut.")
            sys.exit(1)


if __name__ == "__main__":
    main()
