# Timeline reference

Full schema for the YAML "timeline" that drives `demo-video-harness`, plus
the dependency matrix and troubleshooting. Read this when authoring or
debugging a timeline; `SKILL.md` covers the workflow, this covers the
details.

## Contents

- [Dependency matrix](#dependency-matrix)
- [Top-level keys](#top-level-keys)
- [Cut types](#cut-types)
- [Capture action DSL](#capture-action-dsl)
- [Symbolic slice offsets (event manifest)](#symbolic-slice-offsets-event-manifest)
- [auto_fit / slice tuning workflow](#auto_fit--slice-tuning-workflow)
- [Assets: committed vs generated](#assets-committed-vs-generated)
- [Troubleshooting](#troubleshooting)

## Dependency matrix

| Dependency | Install | Used by |
|---|---|---|
| Python 3.9+ | preinstalled on macOS, or your package manager | all scripts |
| ffmpeg (with `libx264` + `aac` + `overlay`/`adelay`/`amix` filters — all in a stock build) | `brew install ffmpeg` / `apt install ffmpeg` | tts.py, assemble.py |
| Playwright (pip) | `pip install playwright` | capture.py |
| Chromium (browser binary) | `playwright install chromium` | capture.py |
| PyYAML | `pip install pyyaml` | all scripts |
| macOS `say` | preinstalled (macOS only) | tts.py default engine |
| ImageMagick (optional) | `brew install imagemagick` / `apt install imagemagick` | assemble.py QC contact sheet (best-effort — build succeeds without it) |

Not required: node, any specific cloud API key. `tts_engine: elevenlabs` needs
`ELEVENLABS_API_KEY` in `~/.env` only if you opt into that engine.

## Top-level keys

```yaml
video: example                  # output basename -> out/example.mp4
title: ...                      # human label (not rendered)
gates:
  max_duration_s: 30            # lint fails / assemble marks FAIL if over
  width: 1280
  height: 720
  fps: 30
  auto_fit: true                # shrink each cut to its narration length + fit_pad
  fit_pad: 0.4                  # seconds of tail padding when auto_fit is on
tts_engine: say                 # say (default, macOS) | elevenlabs
tts_voice: null                 # say voice name, or ElevenLabs voice id
base_url: http://localhost:3000 # your app's origin — omit if every capture uses `scene`
fake_mic_wav: assets/mic/utterance.wav   # optional: streamed to the page mic for mic_hold
bgm:
  file: assets/sfx/bed.wav
  gain: 0.16                    # bed volume; swells over the last 4s
  highpass_hz: 170              # cut low rumble from the bed (0 to disable)
lint:                           # all optional, see scripts/lint.py
  banned_terms: []
  banned_chars: {}
  require_ascii_captions: false
```

## Cut types

| `type` | What it does | Key fields |
|---|---|---|
| `capture` | Loads a page and records a `.webm` | `capture.path` (with `base_url`) or `capture.scene` (a local HTML file, `file://`, no server needed), `capture.record_s`, `capture.actions`, `capture.start_at`, `capture.pre_shell` |
| `slice` | Reuses another cut's captured webm (a different window of it) | `src_capture` (a capture cut id), `start_at` |
| `card` | Full-screen title card rendered from HTML | `card.heading`, `card.sub` |
| `gen` | Pre-generated clip file (any video you already have — a screen recording, a rendered animation, etc.) | `src` (path under the skill's working directory) |

Common per-cut fields: `id` (unique), `duration` (seconds; auto-fit may
shrink), `min_s` (floor so a visual beat isn't over-shrunk), `narration` (VO
text; also becomes the caption), `caption` (overrides caption text), `stat`
(big centered number overlay, e.g. `"21 DAYS EARLY"`), `crop: [x, y]`
(1280x720 punch-in window -> 1.5x zoom), `sfx` (basename in `assets/sfx/`),
`start_at` (window start into the source webm), `tempo` (0.9-1.1 narration
pace variation).

## Capture action DSL

`capture.actions` is an ordered list, executed after the page loads:

| Step | Effect |
|---|---|
| `{wait: 2.5}` | sleep N seconds |
| `{wait_for: "#sel"}` | wait until selector is visible (timeout 240s) |
| `{click: "#sel"}` | click element (CSS or Playwright text selector) |
| `{fill: {sel: "#q", text: "..."}}` | type into an input |
| `{press: "Enter"}` | keyboard press |
| `{eval: "location.hash='x'"}` | run JS in the page |
| `{mic_hold: 6}` | press-and-hold `#mic` for N s while `fake_mic_wav` streams as the audio device (push-to-talk) |

`record_s` is total recording length; actions run inside that window and the
recorder pads out any remaining time. `start_at` (capture-level) is the
default window start used by assemble when slicing; assemble otherwise takes
the **last** `duration` seconds of the webm (skips page-load settle).

`capture.pre_shell` is an optional shell command run before the recording
starts (e.g. to reset your own app's demo state). There is no default
command — bring your own, and set `SKIP_PRE_SHELL=1` to skip all of them for
a run (e.g. on a machine that can't run your reset command).

## Symbolic slice offsets (event manifest)

Every `capture` run writes `assets/captures/<id>.events.json` with a
timestamp per action (name a step with `name:` or use the default
`<verb>#<idx>`). Slices can then pin themselves to moments instead of
guessed seconds:

```yaml
- id: after-click
  type: slice
  src_capture: home
  start_at: "@click#0 - 1"   # 1s before the click, whatever the app's latency
```

Numeric `start_at` still works. Re-capturing never breaks symbolic slices —
that's the point: latency varies run-to-run, but the *event* still happens
at whatever moment it happens, and the slice follows it.

## auto_fit / slice tuning workflow

Because your app's own timing (network calls, animations, whatever) varies
run-to-run, the exact second a beat lands inside a webm can drift. Tune
slices empirically:

1. Capture once: `python3 scripts/capture.py timeline/example.yaml <capture-id>`
2. Inspect the webm length and content:
   ```bash
   ffprobe -v error -show_entries format=duration -of csv=p=0 assets/captures/<id>.webm
   ffmpeg -i assets/captures/<id>.webm -vf fps=1 /tmp/frame-%03d.png   # 1 frame/s to eyeball beats
   ```
3. Adjust each slice's `start_at` to the second the beat appears (or better,
   use a symbolic `@event` offset so it survives re-capture).
4. Re-assemble only: `python3 scripts/assemble.py timeline/example.yaml`.

Iterate on one stage without re-capturing (captures are the slow part):

```bash
bash scripts/build.sh timeline/example.yaml --skip-capture   # reuse existing webms
python3 scripts/capture.py timeline/example.yaml home         # re-capture ONE cut by id
python3 scripts/tts.py timeline/example.yaml                  # re-render narration only
python3 scripts/assemble.py timeline/example.yaml             # re-cut/mux only
```

Each build also writes `out/<name>-sheet.png`: one labeled frame per cut for
one-glance QC.

## Assets: committed vs generated

Committed (ready on clone): `assets/example/page.html`, `assets/sfx/*.wav`
(placeholder tone/bed — swap for your own). Generated locally (gitignored,
created by the pipeline): `assets/captures/` (webm recordings), `assets/tts/`
(narration wavs), `assets/cards/` (rendered title/caption/stat PNGs), `out/`
(segments + final mp4 + report + contact sheet).

Delivery: the final file is `out/<video>.mp4`; every build also archives a
copy to `out/versions/<video>-vNNN.mp4` so a later build never silently loses
an earlier one.

## Troubleshooting

- **`missing assets for cuts: [...]`** — the timeline references captures
  that don't exist yet. Run `python3 scripts/capture.py timeline/<name>.yaml`
  first (or drop `--skip-capture` from `build.sh`).
- **Capture hangs / `wait_for` never resolves** — the page was slow to load,
  or the selector doesn't exist. Page loads use `wait_until="domcontentloaded"`
  (not `networkidle`, which never settles on apps with any polling/websocket
  traffic) and `wait_for` has a 240s timeout. If you still hang, open the page
  in a real browser and confirm the selector exists.
- **`playwright` import error / no browser** — you skipped
  `playwright install chromium`, or you're not in the right virtualenv.
- **TTS falls back to `say` unexpectedly** — you're on `tts_engine: elevenlabs`
  without `ELEVENLABS_API_KEY` in `~/.env`, or the API call failed; check the
  printed error.
- **`SYNC GATE FAIL`** — a narrated cut has no audible audio near its start;
  usually the `.wav` failed to render (check the `tts` step's output) or the
  cut's `duration` is shorter than the narration.
- **Duration `[FAIL]` in the report** — total exceeds `gates.max_duration_s`.
  Enable `auto_fit`, shorten narration, or trim cut `duration`s.
- **TLS / cert warnings against your `base_url`** — capture sets
  `ignore_https_errors: true`, so self-signed certs on your own dev server
  are expected to work; this only matters if you're pointing at `https://`.
