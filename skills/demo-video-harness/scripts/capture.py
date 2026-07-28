#!/usr/bin/env python3
"""Deterministic per-cut screen capture via Playwright.

Usage: python3 capture.py timeline/example.yaml [cut-id ...]
Records each capture-type cut as assets/captures/<id>.webm and renders
card-type cuts as assets/cards/<id>.png. Idempotent: pass cut ids to
re-capture only those; with no ids, (re)captures everything.

A capture cut points at either `base_url + capture.path` (a live page — your
app, running anywhere: localhost, staging, a deployed URL) or a local
`capture.scene` file (an HTML file loaded via file://, no server needed —
handy for a fully offline example).

Action DSL (capture.actions), executed in order after page load:
  - {wait: 2.5}                     sleep seconds
  - {click: "#selector"}            click element
  - {fill: {sel: "#q", text: "…"}}  fill input
  - {press: "Enter"}                keyboard press
  - {eval: "js expression"}         page.evaluate
  - {wait_for: "#selector"}         wait for element visible
  - {mic_hold: 6}                   hold a mic/push-to-talk element for N s
                                     while `fake_mic_wav` streams as the
                                     fake audio input device

Each capture also writes assets/captures/<id>.events.json — a timestamp per
action, so timelines can pin slices to moments ("@click#0 - 2") instead of
guessed seconds. See references/TIMELINE.md.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

CARD_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
  body {{ margin:0; width:1920px; height:1080px; display:flex; flex-direction:column;
        justify-content:center; align-items:center; gap:28px;
        background: radial-gradient(1200px 600px at 50% -10%, #10151d 0%, #05070a 60%);
        font-family: 'Helvetica Neue', Arial, sans-serif; color:#eef2f7; }}
  h1 {{ font-size:72px; font-weight:700; letter-spacing:-1px; margin:0; text-align:center; }}
  p  {{ font-size:30px; color:#8593a4; margin:0; text-align:center; }}
  .bar {{ width:88px; height:5px; background:#ff5a63; border-radius:3px; }}
</style></head><body>
  <div class="bar"></div><h1>{heading}</h1><p>{sub}</p>
</body></html>"""

# Big centered stat overlay (pattern-interrupt number card), transparent
STAT_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
  body {{ margin:0; width:1920px; height:1080px; display:flex;
        justify-content:center; align-items:center; background:transparent;
        font-family: 'Helvetica Neue', Arial, sans-serif; }}
  .stat {{ font-size:150px; font-weight:800; letter-spacing:-2px; color:#fff;
        text-shadow: 0 0 60px rgba(255,90,99,0.55), 0 4px 30px rgba(0,0,0,0.9);
        border-bottom: 8px solid #ff5a63; padding-bottom: 12px; }}
</style></head><body><div class="stat">{text}</div></body></html>"""

# Transparent caption strip, composited by assemble.py via ffmpeg overlay
# (works even when the local ffmpeg build has no libass/drawtext). .scrim is
# a full-width bottom gradient band so the pill stays legible over bright UI.
CAPTION_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
  body {{ margin:0; width:1920px; height:110px; display:flex;
        justify-content:center; align-items:flex-end; background:transparent;
        font-family: 'Helvetica Neue', Arial, sans-serif; }}
  .scrim {{ position:absolute; left:0; right:0; bottom:0; height:110px;
        background:linear-gradient(rgba(3,6,10,0), rgba(3,6,10,0.55)); }}
  .pill {{ position:relative; max-width:1680px; margin-bottom:10px; padding:9px 22px;
        background:rgba(3,6,10,0.85); border-radius:10px; color:#f2f5f9;
        font-size:24px; line-height:1.4; text-align:center; }}
</style></head><body><div class="scrim"></div><div class="pill">{text}</div></body></html>"""

# Caption strip with a chapter eyebrow above the pill (fed by a cut's
# `chapter:` field). When the cut has a chapter but no caption/narration text
# the pill is empty and the eyebrow renders alone.
CAPTION_EYEBROW_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
  body {{ margin:0; width:1920px; height:110px; display:flex;
        flex-direction:column; justify-content:flex-end; align-items:center;
        gap:6px; background:transparent;
        font-family: 'Helvetica Neue', Arial, sans-serif; }}
  .scrim {{ position:absolute; left:0; right:0; bottom:0; height:110px;
        background:linear-gradient(rgba(3,6,10,0), rgba(3,6,10,0.55)); }}
  .eyebrow {{ position:relative; color:#9fb0c8; font-size:22px; font-weight:600;
        letter-spacing:.12em; text-transform:uppercase; text-align:center; }}
  .pill {{ position:relative; max-width:1680px; margin-bottom:10px; padding:9px 22px;
        background:rgba(3,6,10,0.85); border-radius:10px; color:#f2f5f9;
        font-size:24px; line-height:1.4; text-align:center; }}
</style></head><body><div class="scrim"></div>{eyebrow}{pill}</body></html>"""


def run_actions(page, actions, t0=None, events=None):
    """Execute the action DSL. When t0/events are given, append
    {name, t} per step so slices can reference moments symbolically
    (start_at: "@name - 2"). A step names itself with an optional
    `name:` key; default is <verb>#<index>."""
    for idx, step in enumerate(actions or []):
        if "wait" in step:
            time.sleep(float(step["wait"]))
        elif "click" in step:
            page.click(step["click"])
        elif "fill" in step:
            page.fill(step["fill"]["sel"], step["fill"]["text"])
        elif "press" in step:
            page.keyboard.press(step["press"])
        elif "eval" in step:
            page.evaluate(step["eval"])
        elif "wait_for" in step:
            page.wait_for_selector(step["wait_for"], state="visible", timeout=240000)
        elif "mic_hold" in step:
            # push-to-talk: hold #mic while the fake audio device streams the
            # configured fake_mic_wav (--use-file-for-fake-audio-capture)
            box = page.locator("#mic").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2)
            page.mouse.down()
            time.sleep(float(step["mic_hold"]))
            page.mouse.up()
        if t0 is not None and events is not None:
            verb = next(k for k in step if k != "name")
            events.append({"name": step.get("name", f"{verb}#{idx}"),
                           "t": round(time.time() - t0, 2)})


def main():
    doc = yaml.safe_load(open(sys.argv[1]))
    only = set(sys.argv[2:])
    gates = doc.get("gates", {})
    w, h = gates.get("width", 1920), gates.get("height", 1080)
    base_url = doc.get("base_url", "")

    (ROOT / "assets/captures").mkdir(parents=True, exist_ok=True)
    (ROOT / "assets/cards").mkdir(parents=True, exist_ok=True)

    launch_args = []
    fake_mic = doc.get("fake_mic_wav")
    if fake_mic:
        wav = (ROOT / fake_mic).resolve()
        launch_args += [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={wav}",
        ]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=launch_args)
        for cut in doc["cuts"]:
            cid = cut["id"]
            if only and cid not in only:
                continue

            if cut.get("stat"):
                page = browser.new_page(viewport={"width": w, "height": h})
                page.set_content(STAT_HTML.format(text=cut["stat"]))
                page.screenshot(path=str(ROOT / f"assets/cards/stat-{cid}.png"),
                                omit_background=True)
                page.close()

            cap_text = cut.get("caption", cut.get("narration", "")).strip()
            chapter = str(cut.get("chapter", "")).strip()
            if (cap_text or chapter) and cut["type"] not in ("card", "image"):
                page = browser.new_page(viewport={"width": w, "height": 150})
                if chapter:
                    pill = f'<div class="pill">{cap_text}</div>' if cap_text else ""
                    page.set_content(CAPTION_EYEBROW_HTML.format(
                        eyebrow=f'<div class="eyebrow">{chapter}</div>', pill=pill))
                else:
                    page.set_content(CAPTION_HTML.format(text=cap_text))
                out = ROOT / f"assets/cards/cap-{cid}.png"
                page.screenshot(path=str(out), omit_background=True)
                page.close()

            if cut["type"] == "card":
                page = browser.new_page(viewport={"width": w, "height": h})
                page.set_content(CARD_HTML.format(**cut["card"]))
                out = ROOT / f"assets/cards/{cid}.png"
                page.screenshot(path=str(out))
                page.close()
                print(f"[card]    {cid} -> {out.name}")

            elif cut["type"] == "capture":
                cap = cut["capture"]
                if cap.get("pre_shell") and not os.environ.get("SKIP_PRE_SHELL"):
                    # user-supplied hook (e.g. reset your own app's demo
                    # state before recording) — no default command is
                    # bundled, this repo has no opinion on your backend.
                    subprocess.run(["sh", "-c", cap["pre_shell"]],
                                   check=True, cwd=str(ROOT))
                record_s = cap.get("record_s", cut["duration"] + 4)
                ctx = browser.new_context(
                    viewport={"width": w, "height": h},
                    record_video_dir=str(ROOT / "assets/captures/_tmp"),
                    record_video_size={"width": w, "height": h},
                    ignore_https_errors=True,
                    permissions=["microphone"],
                )
                page = ctx.new_page()
                t0 = time.time()
                if cap.get("scene"):  # local static/animated HTML, no server needed
                    target = f"file://{(ROOT / cap['scene']).resolve()}"
                else:
                    target = base_url + cap["path"]
                page.goto(target, wait_until="domcontentloaded")
                events = [{"name": "loaded", "t": round(time.time() - t0, 2)}]
                run_actions(page, cap.get("actions"), t0=t0, events=events)
                remaining = record_s - (time.time() - t0)
                if remaining > 0:
                    time.sleep(remaining)
                video = page.video
                page.close()
                ctx.close()
                out = ROOT / f"assets/captures/{cid}.webm"
                Path(video.path()).rename(out)
                # event manifest: reusable timelines slice by moment, not by
                # guessed seconds (start_at: "@name - 2"). Times are relative
                # to recording start, i.e. directly usable as webm offsets.
                (ROOT / f"assets/captures/{cid}.events.json").write_text(
                    json.dumps({"capture": cid, "record_s": record_s,
                                "events": events}, indent=1))
                names = ",".join(e["name"] for e in events)
                print(f"[capture] {cid} -> {out.name} ({record_s}s recorded; events: {names})")

            elif cut["type"] == "slice":
                src = ROOT / f"assets/captures/{cut['src_capture']}.webm"
                mark = "found" if src.exists() else "MISSING"
                print(f"[slice]   {cid} -> reuses {cut['src_capture']}.webm [{mark}]")

            elif cut["type"] == "gen":
                src = ROOT / cut["src"]
                mark = "found" if src.exists() else "MISSING"
                print(f"[gen]     {cid} -> {cut['src']} [{mark}]")

        browser.close()
    subprocess.run(["rm", "-rf", str(ROOT / "assets/captures/_tmp")])


if __name__ == "__main__":
    main()
