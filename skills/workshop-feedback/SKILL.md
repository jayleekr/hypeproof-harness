---
name: workshop-feedback
description: "Generate reusable pre/post/follow-up feedback forms for any professional-lecture or workshop engagement, from one per-engagement config. Use this skill whenever the user is preparing a lecture, workshop, training, or customer engagement and mentions feedback, surveys, Google Forms, pre/post measurement, NPS, learner confidence, follow-up, or wants to keep collecting and reflecting customer feedback over time — even if they don't say 'form' explicitly. Owns the org-standard fixed-core question set; only the topic slot changes per engagement. Emits a forms.spec.json that an Apps Script renders into Google Forms, and maps responses back to workshop.yaml for the result-report pipeline."
metadata:
  short-description: "Reusable pre/post/follow-up workshop feedback forms + generator (harness canonical)"
---

# Workshop Feedback

Turn one engagement config into **three** feedback forms — **pre** (D-7, remote), **post** (D0, on-site), **follow-up** (D+30, opt-in) — with an org-standard fixed core so results stay comparable across every lecture and pre→post→follow-up deltas are measurable.

**This is the canonical home.** Consumer repos (lab engagements) provide only a small per-engagement config; they never fork the core. Never patch a vendored copy — patch here, then vendor.

## Why this design (the load-bearing ideas)

- **Fixed core + topic slot.** The core (confidence baseline, value, NPS, sustained-use) is identical for every lecture — that's what lets you compare cohorts and measure the confidence delta (PC3→AC2→F2). Only the **topic slot** changes per engagement. The core lives in `form_spec_generator.py`, not in config, on purpose.
- **Own the noun, rent the surface.** The form is a rentable surface (Google Forms today, Tally/Studio tomorrow). What we own = the **question schema** (this skill) and the **feedback record** (`workshop.yaml`). The generator is the single source of truth; Apps Script is one renderer.
- **Two tracks, physically separate.** The feedback track is anonymous (participant code + phone-last-4 rejoin key). The **re-contact track** (name/contact, opt-in) is `internal_only` and must land in a **different sheet** — never mixed into anonymous feedback, or sales collateral is contaminated. This is how a one-off becomes an ongoing relationship: consented contact is the `cap.identity` Contact record.
- **Continued-use intent is a separate signal from satisfaction.** "강의가 좋았다"(AC1/AC4) and
  "이 도구를 계속 쓰겠다"(AC6) are different answers, and only the second is a product signal.
  AC6→AC7 asks *whether* and *under what condition* — the condition list is the roadmap input.
  Phrasing rule: hypothetical only ("만약 계속 쓰신다면"), never price, plan, or launch timing —
  an unshipped subscription must not be implied by a survey. Product name comes from
  `product.name` in config; `product.extra_features` appends to the core list, never replaces it.
- **Sustained use is the real proof.** Workshop-day satisfaction is weak evidence. The follow-up form (D+30) measures whether the tool is still used — the recurring-value (AX Care) signal.

## Which agent creates the forms, and when

This is recurring **operations** (`cap.automation`: job = prompt + schedule + budget), **not** a dynamically-created mission specialist.

- **Now — on-demand:** the engagement-prep step (operator or agent) runs this skill at **D-7** to generate the three form specs + the operator checklist, then builds the Google Forms.
- **Later — autonomous D-7 trigger:** a cron job keyed off the roadmap/weekly board (dates already exist) detects "engagement is D-7 away", runs this skill, and notifies the operator with the specs. `cron-prompts/column-deadline.md` is the existing date-trigger precedent. Wire this only once a real recurring cadence justifies it (schema first, adapter later).

## How to run

**1) Generate the spec (runs here / CI — verified):**
```bash
python3 skills/workshop-feedback/form_spec_generator.py CONFIG.yaml -o forms.spec.json --strict
# -> 3 forms, ~24 items. Fixed core + this engagement's topic slot.
```
Config lives in the consumer repo per engagement; copy a template:
- `templates/feedback.config.example.dental.yaml` (7/29 치과, filled)
- `templates/feedback.config.example.generic.yaml` (any profession — fill 2 topic slots)

Only the topic slot + roles + retention change per lecture. The core does not.

**2) Render to Google Forms (runs in Google — reference impl, validate there):**
Paste `forms.spec.json` into `apps-script/build-forms.gs` `SPEC`, run `buildAll()` at script.google.com. It creates pre/post/follow-up forms + a **separate** re-contact form/sheet. See `apps-script/README.md`.

**3) Collect (token-based, no browser):**
```bash
python3 fetch_responses.py --manifest engagements/<date>/forms/sheets.manifest.json [--dump]
```
Reads each form's linked response sheet via the Sheets REST API. Credential (a HUMAN
step to issue — cap.governance) comes from `~/.env` / env: `GOOGLE_APPLICATION_CREDENTIALS`
(SA key path), `GOOGLE_SERVICE_ACCOUNT_JSON` (inline JSON), or ADC. Share each response
sheet with the service-account email (Viewer). `internal_only` forms (연락처) are counted
but rows stay redacted unless `--include-internal`. Do NOT open a browser to check
responses — that is not automation.

**4) Reflect:**
Anonymous responses → `workshop.yaml` (`comments`, distribution counts, `measurement.confidence_*`)
→ the result-report pipeline (`products/workshop-result-report/run_all.sh`) → Sediment.
Contact responses → separate internal sheet, joined by participant code only when needed.

## Durability (non-negotiable — nothing lost to scratch)

The human must not have to babysit where outputs land. Every artifact this skill
produces is filed into the **engagement directory and committed** — job tmp / loose
files are scratch only and are assumed to disappear.

- Per engagement, create `products/workshop-result-report/engagements/<date>/forms/`
  and put there, committed: the engagement `feedback.config.yaml`, the generated
  `forms.spec.json`, the built `*.gs`, and a `LIVE-URLS.md` recording every created
  form's viewform/edit/response-sheet URL.
- Live form URLs also get a durable pointer the human can find without a git checkout
  (a stable file and/or a memory note) — a form built but whose URL is only in a
  transcript is a lost form.
- "Not recorded in the repo = not done." This is the same `cap.proof` discipline as
  the evidence pipeline: an output that isn't durably filed did not happen.

## Privacy gate (non-negotiable)

- Feedback forms: `setCollectEmail(false)`. No real names/contact in the feedback track.
- Re-contact = separate opt-in form + separate sheet, `internal_only`; never enters any sales deliverable.
- `internal_only` items (F4, F5, recontact) stay out of external outputs.
- Before rendering any sales output, re-check the downstream sales gate + grep for client name / contact = 0.

## Honest limits

- `form_spec_generator.py` — verified (produces 3 forms/21 items from a config).
- `apps-script/build-forms.gs` — reference implementation; validate in Google Apps Script (not executable in-repo).
- `measurement.confidence_*` / `followups` are a **workshop.yaml schema extension** the result-report pipeline does not yet auto-consume — for now a human records them; pipeline consumption is a schema-v2 task. Do not fabricate these into deliverables.
