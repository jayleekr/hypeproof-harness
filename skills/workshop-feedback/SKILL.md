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
- **Sustained use is the real proof.** Workshop-day satisfaction is weak evidence. The follow-up form (D+30) measures whether the tool is still used — the recurring-value (AX Care) signal.

## Which agent creates the forms, and when

This is recurring **operations** (`cap.automation`: job = prompt + schedule + budget), **not** a dynamically-created mission specialist.

- **Now — on-demand:** the engagement-prep step (operator or agent) runs this skill at **D-7** to generate the three form specs + the operator checklist, then builds the Google Forms.
- **Later — autonomous D-7 trigger:** a cron job keyed off the roadmap/weekly board (dates already exist) detects "engagement is D-7 away", runs this skill, and notifies the operator with the specs. `cron-prompts/column-deadline.md` is the existing date-trigger precedent. Wire this only once a real recurring cadence justifies it (schema first, adapter later).

## How to run

**1) Generate the spec (runs here / CI — verified):**
```bash
python3 skills/workshop-feedback/form_spec_generator.py CONFIG.yaml -o forms.spec.json --strict
# -> 3 forms, ~21 items. Fixed core + this engagement's topic slot.
```
Config lives in the consumer repo per engagement; copy a template:
- `templates/feedback.config.example.dental.yaml` (7/29 치과, filled)
- `templates/feedback.config.example.generic.yaml` (any profession — fill 2 topic slots)

Only the topic slot + roles + retention change per lecture. The core does not.

**2) Render to Google Forms (runs in Google — reference impl, validate there):**
Paste `forms.spec.json` into `apps-script/build-forms.gs` `SPEC`, run `buildAll()` at script.google.com. It creates pre/post/follow-up forms + a **separate** re-contact form/sheet. See `apps-script/README.md`.

**3) Collect → reflect:**
Anonymous responses → `workshop.yaml` (`comments`, distribution counts, `measurement.confidence_*`) → the result-report pipeline (`products/workshop-result-report/run_all.sh`) → Sediment. Contact responses → separate internal sheet, joined by participant code only when needed.

## Privacy gate (non-negotiable)

- Feedback forms: `setCollectEmail(false)`. No real names/contact in the feedback track.
- Re-contact = separate opt-in form + separate sheet, `internal_only`; never enters any sales deliverable.
- `internal_only` items (F4, F5, recontact) stay out of external outputs.
- Before rendering any sales output, re-check the downstream sales gate + grep for client name / contact = 0.

## Honest limits

- `form_spec_generator.py` — verified (produces 3 forms/21 items from a config).
- `apps-script/build-forms.gs` — reference implementation; validate in Google Apps Script (not executable in-repo).
- `measurement.confidence_*` / `followups` are a **workshop.yaml schema extension** the result-report pipeline does not yet auto-consume — for now a human records them; pipeline consumption is a schema-v2 task. Do not fabricate these into deliverables.
