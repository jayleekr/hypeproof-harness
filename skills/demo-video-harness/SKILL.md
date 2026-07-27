---
name: demo-video-harness
description: Turn a live web app, local page, or any URL into a polished narrated demo MP4. A YAML "timeline" describes a sequence of cuts (screen captures via headless Chromium, title cards, narration, captions, stat call-outs); a 4-stage pipeline (lint -> capture -> tts -> assemble) renders it with Playwright + ffmpeg into out/<name>.mp4, plus a timing report and a QC contact sheet. Not tied to any company, product, or stack — works against localhost, a staging URL, or a local static HTML file with zero network access. Use this whenever the user wants to record or produce a demo video, product walkthrough, narrated screen capture, or asks to "turn this page/app into a video", "make a demo video of X", "record a narrated walkthrough of this URL", "screen-record and narrate this flow" — even if they don't say "video harness" explicitly.
user_invocable: true
triggers:
  - "demo video"
  - "demo-video-harness"
  - "record a demo"
  - "walkthrough video"
  - "narrated demo"
  - "make a video of this app"
  - "screen record and narrate"
argument_hint: "[timeline/<name>.yaml] — optional; defaults to timeline/example.yaml"
---

# demo-video-harness

Turns a timeline YAML + a live page (or a local HTML file) into a narrated
MP4, deterministically. This is a port of a working internal video harness,
generalized so it carries zero company/product coupling — it works against
any web-based demo, with no baked-in backend, TTS service, or infra.

```
timeline/<name>.yaml ──> lint.py ──> capture.py ──> tts.py ──> assemble.py ──> out/<name>.mp4
                          (gates)     (Playwright)   (say/     (ffmpeg)
                                       records webm)  elevenlabs)
```

Capture drives the target page in a headless Chromium and records each shot;
TTS renders narration; assemble cuts, overlays captions/stats, mixes audio,
and writes `out/<name>.mp4` + a timing report + a QC contact sheet.

## When to reach for this

- The user has a web app (running locally, on staging, or deployed) and
  wants a short narrated video of it — a demo reel, an onboarding clip, a
  feature walkthrough, a bug repro with voiceover.
- The user wants deterministic, re-buildable output: change the narration
  text or timing, re-run, get a new MP4 — not a one-off manual screen
  recording.
- The user wants captions/stat call-outs burned in, or wants the video to
  hit a specific duration budget (auto-fit shrinks cuts to match narration).

Not a fit: multi-camera or in-person video editing, or anything that isn't
ultimately "record a web page and narrate it."

## Quickstart

```bash
# from this skill's directory
bash scripts/preflight.sh                       # checks local deps, prints fixes
python3 -m venv .venv && source .venv/bin/activate
pip install playwright pyyaml
playwright install chromium
brew install ffmpeg          # or: apt install ffmpeg

bash scripts/build.sh timeline/example.yaml
# result: out/example.mp4 + out/example-report.md + out/example-sheet.png
open out/example.mp4         # macOS; use xdg-open on Linux
```

`timeline/example.yaml` is fully self-contained — it records
`assets/example/page.html` via `file://`, so it builds with zero network
access. This is the fastest way to confirm the pipeline works before
authoring a real timeline.

## Authoring a timeline for the user's app

1. Copy `timeline/example.yaml` to `timeline/<name>.yaml`.
2. Set `base_url` to wherever the user's app is running (localhost, a
   staging URL, whatever — this harness has no default and makes no
   assumptions about network access; local-only pages should use
   `capture.scene` instead, see below).
3. Replace the example's `cuts` with the user's actual flow: what to click,
   what to wait for, what to say about each step. Read
   `references/TIMELINE.md` for the full cut-type/action-DSL schema before
   authoring anything beyond a trivial timeline — it covers `capture` /
   `slice` / `card` / `gen` cuts, the action DSL, symbolic slice offsets
   (`start_at: "@click#0 - 2"`), and the auto_fit tuning workflow.
4. Run `bash scripts/build.sh timeline/<name>.yaml`. Iterate with
   `--skip-capture` once the captures look right and you're only tuning
   narration/timing (see `references/TIMELINE.md` for the fast iteration
   loop — re-running capture is the slow part).
5. Read `out/<name>-report.md` (per-cut timing, PASS/FAIL against the
   duration budget) and `out/<name>-sheet.png` (one labeled frame per cut)
   before calling it done.

## Narration (TTS)

Default is macOS `say` — zero setup, offline, but macOS-only. For
Linux/Windows, or for a better voice, set `tts_engine: elevenlabs` and put
`ELEVENLABS_API_KEY` in `~/.env`. To plug in anything else (a local TTS
model, a company voice service), add a `render_*()` function to
`scripts/tts.py` and route to it — the file is deliberately small so this is
a five-minute change; see the docstring at the top of `scripts/tts.py`.

## Content gates

`scripts/lint.py` runs duration-budget and caption-coverage checks
unconditionally, and only enforces banned-term/banned-character/ASCII-only
rules if the timeline opts in under a `lint:` block — this harness ships
with no denylist of its own, since what's off-limits is specific to each
user's own content policy. See `references/TIMELINE.md`.

## Reference

- `references/TIMELINE.md` — full timeline schema, dependency matrix,
  auto_fit/slice tuning workflow, troubleshooting. Read before authoring
  anything past a trivial timeline, or when a build fails and the fix isn't
  obvious.
- `scripts/build.sh` — the end-to-end driver (preflight -> lint -> capture ->
  tts -> assemble).
- `scripts/preflight.sh`, `scripts/lint.py`, `scripts/capture.py`,
  `scripts/tts.py`, `scripts/assemble.py` — the four pipeline stages, each
  independently runnable for fast iteration.
