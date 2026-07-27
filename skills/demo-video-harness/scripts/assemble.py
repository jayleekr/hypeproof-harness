#!/usr/bin/env python3
"""Assemble final video from timeline + captured assets.

Usage: python3 assemble.py timeline/example.yaml
Pipeline per cut: normalize (scale/pad/fps) + trim to duration -> segment.
Then: concat segments, overlay narration audio at cut offsets, composite
caption/stat overlays, mix music/sfx, write out/<video>.mp4 +
out/<video>-report.md + out/<video>-sheet.png (QC contact sheet).
"""
import os
import re
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def sh(args):
    subprocess.run(args, check=True)


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


_EVENT_RE = re.compile(r"^@([\w#.:-]+)\s*([+-]\s*[\d.]+)?$")


def resolve_start_at(cut):
    """start_at may be a number or "@event_name [+/- seconds]" referring to
    the source capture's event manifest (assets/captures/<src>.events.json,
    written by capture.py). Times in the manifest are recording-relative, so
    they map 1:1 onto webm offsets."""
    raw = cut.get("start_at", (cut.get("capture") or {}).get("start_at"))
    if raw is None or isinstance(raw, (int, float)):
        return raw
    m = _EVENT_RE.match(str(raw).strip())
    if not m:
        raise SystemExit(f"[assemble] bad start_at {raw!r} on cut {cut['id']}")
    src = cut.get("src_capture", cut["id"])
    manifest = ROOT / f"assets/captures/{src}.events.json"
    if not manifest.exists():
        raise SystemExit(f"[assemble] {cut['id']}: start_at {raw!r} needs "
                         f"{manifest.name} (re-run capture.py for {src})")
    events = {e["name"]: e["t"] for e in json.loads(manifest.read_text())["events"]}
    if m.group(1) not in events:
        raise SystemExit(f"[assemble] {cut['id']}: event {m.group(1)!r} not in "
                         f"{manifest.name} (has: {', '.join(events)})")
    off = float(m.group(2).replace(" ", "")) if m.group(2) else 0.0
    return max(0.0, events[m.group(1)] + off)


def main():
    doc = yaml.safe_load(open(sys.argv[1]))
    name = doc["video"]
    g = doc.get("gates", {})
    w, h, fps = g.get("width", 1920), g.get("height", 1080), g.get("fps", 30)

    # shorts-style pacing: shrink each cut to its narration length (+pad) so
    # there is no dead air. Per-cut min_s protects visual beats that need to
    # play out (an animation, a chart render, etc).
    if g.get("auto_fit"):
        pad = g.get("fit_pad", 0.6)
        for cut in doc["cuts"]:
            wav = ROOT / f"assets/tts/{cut['id']}.wav"
            if wav.exists():
                fit = ffprobe_duration(wav) + pad
                cut["duration"] = round(max(cut.get("min_s", 2.5), fit), 2)

    seg_dir = ROOT / "out/_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)

    vf_norm = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps},format=yuv420p"
    )

    segments, missing = [], []
    for cut in doc["cuts"]:
        cid, dur = cut["id"], cut["duration"]
        seg = seg_dir / f"{cid}.mp4"
        if cut["type"] in ("card", "image"):
            src = (ROOT / cut["src"]) if cut["type"] == "image" \
                else ROOT / f"assets/cards/{cid}.png"
            if not src.exists():
                missing.append(cid)
                continue
            sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                "-i", str(src), "-t", str(dur), "-vf", vf_norm,
                "-c:v", "libx264", "-preset", "fast", "-an", str(seg)])
        else:
            if cut["type"] == "gen":
                src = ROOT / cut["src"]
            elif cut["type"] == "slice":
                src = ROOT / f"assets/captures/{cut['src_capture']}.webm"
            else:
                src = ROOT / f"assets/captures/{cid}.webm"
            if not src.exists():
                missing.append(cid)
                continue
            # default: take the LAST `dur` seconds (skips page-load settle).
            # start_at (cut-level for slices, capture-level otherwise) pins
            # the window start for cuts whose motion happens early.
            raw = ffprobe_duration(src)
            start_at = resolve_start_at(cut)
            if start_at is not None:
                start = min(float(start_at), max(0, raw - dur))
            else:
                start = max(0, raw - dur)
            vf = vf_norm
            if cut.get("crop"):  # punch-in: 1280x720 window -> 1.5x zoom
                cx, cy = cut["crop"]
                vf = f"crop=1280:720:{cx}:{cy},scale={w}:{h},fps={fps},format=yuv420p"
            sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start),
                "-i", str(src), "-t", str(dur), "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-an", str(seg)])
        segments.append((cut, seg))

    if missing:
        print(f"missing assets for cuts: {missing} (run capture.py first)")
        sys.exit(1)

    # concat video
    concat_txt = seg_dir / "concat.txt"
    concat_txt.write_text("".join(f"file '{s}'\n" for _, s in segments))
    silent = ROOT / f"out/_{name}-video.mp4"
    sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(silent)])

    # narration track: delay each cut's wav to its offset, mix
    offsets, t = [], 0.0
    for cut, _ in segments:
        offsets.append((cut, t))
        t += cut["duration"]
    total = t

    inputs, filters, tags = [], [], []
    n_in = 0  # audio/image inputs appended after the base video (input 0)

    for i, (cut, off) in enumerate(offsets):
        wav = ROOT / f"assets/tts/{cut['id']}.wav"
        if not wav.exists():
            continue
        inputs += ["-i", str(wav)]
        n_in += 1
        ms = int(off * 1000)
        # de-boom: many synthesized voices carry a low-frequency fundamental
        # that reads as bass rumble on laptop speakers. HPF the sub-voice
        # band and shelve the low fundamentals down; tune per your TTS voice.
        filters.append(
            f"[{n_in}:a]highpass=f=95,bass=g=-9:f=190:w=0.6,"
            f"adelay={ms}|{ms}[a{i}]")
        tags.append(f"[a{i}]")

    # per-cut SFX (whoosh/impact/tick), landing on the cut boundary
    for i, (cut, off) in enumerate(offsets):
        sfx = cut.get("sfx")
        if not sfx:
            continue
        f = ROOT / f"assets/sfx/{sfx}.wav"
        if not f.exists():
            continue
        inputs += ["-i", str(f)]
        n_in += 1
        ms = max(0, int((off - 0.15) * 1000))  # lead the cut slightly
        filters.append(f"[{n_in}:a]adelay={ms}|{ms},volume=0.9[s{i}]")
        tags.append(f"[s{i}]")

    # music bed: loop under everything, ducked; swell over the last 4s
    bgm = doc.get("bgm")
    if bgm:
        inputs += ["-stream_loop", "-1", "-i", str(ROOT / bgm["file"])]
        n_in += 1
        gn = bgm.get("gain", 0.26)
        # kill low-end rumble from the bed: everything below highpass_hz is
        # felt as bass noise on laptop speakers, not music
        hp = bgm.get("highpass_hz", 170)
        hpf = f"highpass=f={hp}," if hp else ""
        swell = (f"volume='if(gte(t,{total-4:.2f}),"
                 f"min({gn*2.2:.3f},{gn}+(t-{total-4:.2f})*{gn*0.35:.3f}),{gn})'"
                 ":eval=frame")
        filters.append(f"[{n_in}:a]atrim=0:{total},{hpf}{swell}[bgm]")
        tags.append("[bgm]")

    # overlays: bottom caption strips + centered stat cards, time-gated.
    # (works even without libass/drawtext — overlay is always available)
    cap_inputs, cap_specs = [], []
    for cut, off in offsets:
        if cut["type"] != "card":
            png = ROOT / f"assets/cards/cap-{cut['id']}.png"
            if png.exists():
                # -loop 1: a bare still image EOFs after one frame and the
                # overlay never fires mid-timeline; looping keeps it alive
                cap_inputs += ["-loop", "1", "-i", str(png)]
                n_in += 1
                # full-cut window: the next caption replaces this one on the
                # exact cut boundary, so text never blinks out between cuts
                cap_specs.append((n_in, off, off + cut["duration"], "0:H-h"))
        spng = ROOT / f"assets/cards/stat-{cut['id']}.png"
        if cut.get("stat") and spng.exists():
            cap_inputs += ["-loop", "1", "-i", str(spng)]
            n_in += 1
            cap_specs.append((n_in, off + 0.1, off + cut["duration"] - 0.1,
                              "0:0"))

    vprev = "[0:v]"
    for k, (idx, t0, t1, pos) in enumerate(cap_specs):
        vout = "[vout]" if k == len(cap_specs) - 1 else f"[v{k}]"
        filters.append(
            f"{vprev}[{idx}:v]overlay={pos}:enable='between(t,{t0:.2f},{t1:.2f})'{vout}"
        )
        vprev = f"[v{k}]"
    video_map = "[vout]" if cap_specs else "0:v"

    final = ROOT / f"out/{name}.mp4"
    fc = ";".join(
        filters + [f"{''.join(tags)}amix=inputs={len(tags)}:normalize=0[aout]"]
    )
    if os.environ.get("DEBUG_CMD"):
        dbg = ROOT / "out/_last-cmd.txt"
        dbg.write_text("INPUTS:\n" + "\n".join(inputs + cap_inputs) + "\n\nFC:\n" + fc + "\n")

    # Two-pass assembly: mixing many delayed wavs and image overlays in ONE
    # filtergraph can silently corrupt the audio mix (delayed inputs vanish).
    # Render video+overlays and the narration mix separately, then mux. Each
    # half is verified working in isolation.
    n_wavs = len([x for x in inputs if str(x).endswith(".wav")])

    def reindex(expr, kind, shift):
        # rewrite [N:kind] refs by -shift, only for N >= shift ([0:v] stays)
        return re.sub(
            rf"\[(\d+):{kind}\]",
            lambda m: f"[{int(m.group(1)) - shift}:{kind}]"
            if int(m.group(1)) >= shift else m.group(0),
            expr)

    vid_fc = ";".join(f for f in filters if "overlay" in f)
    aud_fc = ";".join(f for f in filters if "adelay" in f) + \
        f";{''.join(tags)}amix=inputs={len(tags)}:normalize=0[aout]"

    vid_tmp = ROOT / f"out/_{name}-vidcap.mp4"
    if cap_specs:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(silent), *cap_inputs,
             "-filter_complex", reindex(vid_fc, "v", n_wavs),
             "-map", video_map, "-an",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-t", str(total), str(vid_tmp)],
            check=True, cwd=str(ROOT))
    else:
        vid_tmp = silent

    aud_tmp = ROOT / f"out/_{name}-aout.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         *inputs, "-filter_complex", reindex(aud_fc, "a", 1),
         "-map", "[aout]", "-t", str(total), str(aud_tmp)],
        check=True, cwd=str(ROOT))

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(vid_tmp), "-i", str(aud_tmp),
         "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-t", str(total), str(final)],
        check=True, cwd=str(ROOT))

    # sync gate: every narrated cut must have audible audio near its start
    sync_fail, n_checked = [], 0
    for cut, off in offsets:
        if not (ROOT / f"assets/tts/{cut['id']}.wav").exists():
            continue
        n_checked += 1
        probe = subprocess.run(
            ["ffmpeg", "-ss", str(off + 0.2), "-t", "2", "-i", str(final),
             "-map", "0:a", "-af", "volumedetect", "-f", "null", "/dev/null"],
            capture_output=True, text=True)
        m = re.search(r"max_volume: (-?[\d.]+)", probe.stderr)
        if not m or float(m.group(1)) < -60:
            sync_fail.append(cut["id"])
    if sync_fail:
        print(f"[assemble] SYNC GATE FAIL: no audio at cut start for {sync_fail}")
        sys.exit(1)
    print(f"[assemble] sync gate: {n_checked}/{n_checked} narrated cuts audible")

    # never lose a build: archive every output as an auto-incrementing
    # version next to the canonical out/<name>.mp4 (which stays the latest)
    vdir = ROOT / "out/versions"
    vdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(vdir.glob(f"{name}-v*.mp4"))
    next_v = 1 + max(
        [int(f.stem.rsplit("-v", 1)[1]) for f in existing if f.stem.rsplit("-v", 1)[1].isdigit()],
        default=0)
    versioned = vdir / f"{name}-v{next_v:03d}.mp4"
    shutil.copy2(final, versioned)
    print(f"[assemble] archived {versioned.relative_to(ROOT)}")

    actual = ffprobe_duration(final)
    budget = g.get("max_duration_s", 90)
    status = "PASS" if actual <= budget + 0.1 else "FAIL"  # container rounding slack
    report = ROOT / f"out/{name}-report.md"
    rows = "\n".join(
        f"| {c['id']} | {c['type']} | {c['duration']}s | {off:.1f}s |"
        for (c, off) in offsets
    )
    report.write_text(
        f"# Build report: {name}\n\n"
        f"- output: `out/{name}.mp4`\n"
        f"- duration: **{actual:.1f}s** / {budget}s budget [{status}]\n"
        f"- resolution: {w}x{h}@{fps}\n\n"
        f"| cut | type | length | starts at |\n|---|---|---|---|\n{rows}\n"
    )
    print(f"[assemble] {final.name}: {actual:.1f}s / {budget}s [{status}]")
    # QC contact sheet: one labeled frame per cut, tiled into a single PNG so
    # a whole build is reviewable at a glance (out/<name>-sheet.png).
    try:
        sheet_dir = ROOT / "out/_sheet"
        sheet_dir.mkdir(parents=True, exist_ok=True)
        tiles = []
        for k, (cut, off) in enumerate(offsets):
            mid = off + cut["duration"] / 2.0
            tile = sheet_dir / f"{k:02d}.png"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{mid:.2f}",
                 "-i", str(final), "-frames:v", "1", "-vf", "scale=480:-1",
                 str(tile)], check=True)
            tiles += ["-label", f"{cut['id']} @{off:.1f}s", str(tile)]
        sheet = ROOT / f"out/{name}-sheet.png"
        font = next((f for f in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if Path(f).exists()), None)
        fontargs = ["-font", font] if font else []
        subprocess.run(
            ["magick", "montage", *fontargs, *tiles, "-tile", "4x",
             "-geometry", "+4+4", "-background", "#101418", "-fill", "white",
             str(sheet)],
            check=True)
        print(f"[assemble] contact sheet -> {sheet.relative_to(ROOT)}")
    except Exception as e:  # sheet is best-effort QC, never fails the build
        print(f"[assemble] contact sheet skipped ({e})")


if __name__ == "__main__":
    main()
