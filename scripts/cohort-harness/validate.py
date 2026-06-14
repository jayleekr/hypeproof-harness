#!/usr/bin/env python3
"""Cohort profile validator — pure Python standard library.

Reads a JSON array of cohort profiles (the shape emitted by studio's
`listProfiles()` → `dump-profiles.ts`, system_prompt included) from a path or
stdin, applies the guardrails declared in rules.yaml, and prints a human table
(or `--json`). Exit code:

    0   no FAIL findings (WARN findings still pass)
    1   one or more FAIL findings
    2   usage / input error (bad JSON, unreadable rules, wrong shape)

Like docs-harness/check.py, this intentionally uses only the standard library
so every consumer repo can vendor and run it with no package manager. The check
*logic* lives here; the *parameters* (enum, thresholds, keywords, severities)
live in rules.yaml, so guardrails are tunable without touching Python.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parent / "rules.yaml"


# --------------------------------------------------------------------------- #
# rules.yaml reader — small indentation-based parser for the documented subset.
# --------------------------------------------------------------------------- #
def _scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    low = value.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_rules_yaml(text: str):
    """Parse the constrained YAML subset used by rules.yaml.

    Supports nested maps, scalar values, and lists of scalars with consistent
    2-space indentation. Full-line comments and blanks are skipped. No
    list-of-maps, anchors, or multiline scalars (none are used by rules.yaml).
    """
    lines: list[tuple[int, str]] = []
    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, stripped))

    pos = 0

    def parse_block(indent: int):
        nonlocal pos
        if pos < len(lines) and lines[pos][1].startswith("- "):
            items = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                items.append(_scalar(lines[pos][1][2:]))
                pos += 1
            return items
        block: dict = {}
        while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
            match = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", lines[pos][1])
            if not match:
                pos += 1
                continue
            key, rest = match.group(1), match.group(2)
            if rest != "":
                block[key] = _scalar(rest)
                pos += 1
            else:
                pos += 1
                if pos < len(lines) and lines[pos][0] > indent:
                    block[key] = parse_block(lines[pos][0])
                else:
                    block[key] = None
        return block

    if not lines:
        return {}
    return parse_block(lines[0][0])


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #
class Finding:
    def __init__(self, profile_id: str, check: str, severity: str, message: str) -> None:
        self.profile_id = profile_id
        self.check = check
        self.severity = severity
        self.message = message

    def as_dict(self) -> dict:
        return {
            "profile": self.profile_id,
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
        }


def add(findings: list, rules: dict, pid: str, check: str, message: str, severity: str | None = None) -> None:
    sv = severity or rules.get("severity", {}).get(check, "fail")
    findings.append(Finding(pid, check, sv, message))


def dotted_get(obj, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def find_promise_hits(prompt: str, rules: dict) -> list:
    pub = rules.get("publishing", {}) or {}
    phrases = pub.get("promise_phrases") or []
    deferrals = pub.get("deferral_markers") or []
    hits = []
    for segment in re.split(r"[\n。.!?！？]", prompt):
        if any(d in segment for d in deferrals):
            continue
        for phrase in phrases:
            if phrase in segment:
                hits.append(phrase)
                break
    return hits


# --------------------------------------------------------------------------- #
# Per-profile checks
# --------------------------------------------------------------------------- #
def check_profile(p: dict, rules: dict, findings: list, seen_ids: set, cohort_totals: dict) -> None:
    pid = p.get("id") or "<no-id>"
    assets = rules.get("assets") or []
    th = rules.get("thresholds", {}) or {}

    # --- id presence + cross-profile uniqueness ---
    if not p.get("id"):
        add(findings, rules, pid, "id_unique", "profile is missing a non-empty id")
    elif p["id"] in seen_ids:
        add(findings, rules, pid, "id_unique", f"duplicate id: {p['id']}")
    if p.get("id"):
        seen_ids.add(p["id"])

    # --- assets_focus: non-empty, subset of enum, no duplicates ---
    af = p.get("assets_focus")
    if not isinstance(af, list) or len(af) == 0:
        add(findings, rules, pid, "assets_focus_empty", "assets_focus must be a non-empty list")
    else:
        unknown = [a for a in af if a not in assets]
        if unknown:
            add(findings, rules, pid, "asset_enum_unknown", f"assets_focus has unknown asset(s): {unknown}")
        if len(af) != len(set(af)):
            dupes = sorted({a for a in af if af.count(a) > 1})
            add(findings, rules, pid, "assets_focus_duplicate", f"assets_focus has duplicate(s): {dupes}")

    # --- session: series_index range, hours, cohort consistency ---
    s = p.get("session") or {}
    st, si, hours = s.get("series_total"), s.get("series_index"), s.get("hours")
    if isinstance(st, int) and isinstance(si, int):
        if not (1 <= si <= st):
            add(findings, rules, pid, "series_index_range", f"series_index {si} not in [1, {st}]")
    else:
        add(findings, rules, pid, "series_index_range", f"series_index/series_total must be ints (got {si}/{st})")
    if not (isinstance(hours, (int, float)) and not isinstance(hours, bool) and hours > 0):
        add(findings, rules, pid, "hours_positive", f"session.hours must be > 0 (got {hours!r})")
    cid = s.get("cohort_id")
    if cid and isinstance(st, int):
        cohort_totals.setdefault(cid, []).append((pid, st))

    # --- welcome.example_prompts ---
    welcome = p.get("welcome") or {}
    eps = welcome.get("example_prompts")
    if not isinstance(eps, list) or len(eps) == 0:
        add(findings, rules, pid, "example_prompts_empty", "welcome.example_prompts is empty")

    # --- ux.suggestions + coach naming ---
    ux = p.get("ux") or {}
    sug = ux.get("suggestions") or {}
    initial = sug.get("initial") or []
    goods = [c for c in initial if isinstance(c, dict) and c.get("style") == "good"]
    if len(goods) < 1:
        add(findings, rules, pid, "suggestions_no_good", "ux.suggestions.initial needs at least one 'good' chip")
    for group in ("initial", "follow_up"):
        for chip in (sug.get(group) or []):
            if isinstance(chip, dict) and chip.get("style") == "weak" and not (chip.get("caption") or "").strip():
                text = (chip.get("text") or "")[:30]
                add(findings, rules, pid, "weak_chip_no_caption", f"weak chip without caption in {group}: {text!r}")
    coach = ux.get("coach") or {}
    nm = coach.get("naming_mode")
    if nm and nm != "fixed" and not (coach.get("naming_prompt_md") or "").strip():
        add(findings, rules, pid, "naming_prompt_missing", f"naming_mode='{nm}' requires non-empty naming_prompt_md")

    # --- publishing ↔ prompt contract ---
    pub = p.get("publishing") or {}
    strat = pub.get("strategy")
    enabled = pub.get("enabled")
    prompt = p.get("system_prompt") or ""
    if strat and strat not in (rules.get("publishing", {}).get("strategies") or []):
        add(findings, rules, pid, "publishing_strategy_unknown", f"unknown publishing.strategy: {strat!r}")
    if enabled is True and strat == "local_only":
        add(findings, rules, pid, "publishing_enabled_local_only", "publishing.enabled=true but strategy=local_only")
    if enabled is False:
        hits = find_promise_hits(prompt, rules)
        if hits:
            add(findings, rules, pid, "publishing_promise_contradiction",
                f"publishing.enabled=false but system_prompt promises publishing: {hits[0]!r}")

    # --- system_prompt presence + length band ---
    if not prompt.strip():
        add(findings, rules, pid, "system_prompt_empty", "system_prompt is empty")
    else:
        n = len(prompt)
        lo, hi = th.get("system_prompt_min_chars", 0), th.get("system_prompt_max_chars", 10 ** 9)
        if n < lo or n > hi:
            add(findings, rules, pid, "system_prompt_length", f"system_prompt {n} chars outside [{lo}, {hi}]")

    # --- child cohort guardrails (age_range max ≤ child_age_max) ---
    aud = p.get("audience") or {}
    ar = aud.get("age_range")
    child_max = th.get("child_age_max", 12)
    is_child = (
        isinstance(ar, list)
        and len(ar) == 2
        and isinstance(ar[1], (int, float))
        and not isinstance(ar[1], bool)
        and ar[1] <= child_max
    )
    if is_child:
        child_rules = rules.get("child", {}) or {}
        analytics = p.get("analytics") or {}
        if analytics.get("log_user_messages") is True:
            add(findings, rules, pid, "child_log_user_messages",
                "HARD FAIL: child cohort must set analytics.log_user_messages=false (no PII without consent)")
        if strat == "per_user_github_pages":
            consent = dotted_get(p, child_rules.get("publish_consent_key", ""))
            if consent:
                add(findings, rules, pid, "child_per_user_pages",
                    "child cohort uses per_user_github_pages (allowed via consent flag)", severity="warn")
            else:
                add(findings, rules, pid, "child_per_user_pages",
                    "child cohort uses per_user_github_pages without a consent flag")
        req = child_rules.get("required_prompt_phrase")
        if req and req not in prompt:
            add(findings, rules, pid, "child_missing_url_ban",
                f"child cohort system_prompt missing required phrase: {req!r}")


def check_cohort_consistency(cohort_totals: dict, rules: dict, findings: list) -> None:
    for cid, entries in cohort_totals.items():
        totals = {st for _, st in entries}
        if len(totals) > 1:
            for pid, _ in entries:
                add(findings, rules, pid, "cohort_series_total_consistent",
                    f"cohort '{cid}' has inconsistent series_total across profiles: {sorted(totals)}")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def load_profiles(path: str | None) -> list:
    if path and path != "-":
        raw = Path(path).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    data = json.loads(raw)
    if isinstance(data, dict):
        if isinstance(data.get("profiles"), list):
            return data["profiles"]
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError("expected a JSON array of profiles (or a single profile object)")


def run(profiles: list, rules: dict, json_output: bool) -> int:
    findings: list = []
    seen_ids: set = set()
    cohort_totals: dict = {}
    for p in profiles:
        if not isinstance(p, dict):
            findings.append(Finding("<non-object>", "shape", "fail", f"profile entry is not an object: {p!r:.60}"))
            continue
        check_profile(p, rules, findings, seen_ids, cohort_totals)
    check_cohort_consistency(cohort_totals, rules, findings)

    fail = [f for f in findings if f.severity == "fail"]
    warn = [f for f in findings if f.severity == "warn"]

    if json_output:
        print(json.dumps({
            "profiles_checked": len(profiles),
            "totals": {"fail": len(fail), "warn": len(warn)},
            "ok": len(fail) == 0,
            "findings": [f.as_dict() for f in findings],
        }, indent=2, ensure_ascii=False))
    else:
        if not findings:
            print(f"✓ cohort-harness: all {len(profiles)} profile(s) pass (0 FAIL · 0 WARN)")
        else:
            mark = "✗" if fail else "△"
            print(f"{mark} cohort-harness: {len(fail)} FAIL · {len(warn)} WARN  ({len(profiles)} profile(s) checked)")
            print()
            for f in fail + warn:
                print(f"  {f.severity.upper():4}  [{f.check}]  {f.profile_id}")
                print(f"        {f.message}")

    return 1 if fail else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate cohort profiles against rules.yaml.")
    parser.add_argument("path", nargs="?", default="-",
                        help="path to a JSON profile array (default: stdin, or '-')")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="path to rules.yaml")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        rules = parse_rules_yaml(Path(args.rules).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: cannot read rules file {args.rules}: {exc}", file=sys.stderr)
        return 2
    if not rules.get("assets"):
        print(f"error: rules file {args.rules} has no 'assets' enum — is it valid?", file=sys.stderr)
        return 2

    try:
        profiles = load_profiles(args.path)
    except FileNotFoundError as exc:
        print(f"error: cannot read profiles: {exc}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"error: invalid profile input: {exc}", file=sys.stderr)
        return 2

    return run(profiles, rules, args.json)


if __name__ == "__main__":
    sys.exit(main())
