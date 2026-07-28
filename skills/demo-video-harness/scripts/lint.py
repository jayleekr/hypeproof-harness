#!/usr/bin/env python3
"""Text + duration gates for demo-video timelines.

Usage: python3 lint.py timeline/example.yaml
Exit 0 = all gates pass, 1 = violations found.

All content gates are opt-in and configured per-timeline under a top-level
`lint:` block — this script ships with no hardcoded denylists, since what
counts as a banned term/character is specific to each user's own content
policy, not something a shared harness should assume.

  lint:
    banned_terms: ["internal-codename", "unreleased-feature-x"]  # case-insensitive substrings
    banned_chars: {"—": "em-dash"}                                # exact-char bans
    require_ascii_captions: false   # true = caption/narration must be ASCII-only
"""
import re
import sys

import yaml


def walk_text(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from walk_text(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_text(v, f"{path}[{i}]")


NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")


def main(path):
    doc = yaml.safe_load(open(path))
    lint_cfg = doc.get("lint", {})
    banned_terms = [t.lower() for t in lint_cfg.get("banned_terms", [])]
    banned_chars = lint_cfg.get("banned_chars", {})
    require_ascii = bool(lint_cfg.get("require_ascii_captions", False))
    violations = []

    for loc, text in walk_text(doc):
        low = text.lower()
        for term in banned_terms:
            if term in low:
                violations.append(f"TERM   {loc}: contains banned term '{term}'")
        for ch, name in banned_chars.items():
            if ch in text:
                violations.append(f"CHAR   {loc}: contains banned char ({name})")

    if require_ascii:
        for c in doc.get("cuts", []):
            cid = c.get("id", "?")
            for field in ("caption", "narration"):
                t = c.get(field)
                if t and NON_ASCII_RE.search(str(t)):
                    violations.append(
                        f"ASCII  {cid}.{field}: contains non-ASCII text "
                        "(set lint.require_ascii_captions: false to permit)")

    # Coverage gate: every capture/slice cut should carry subtitle text
    # (caption, or narration which capture.py falls back to for the PNG).
    # This one is unconditional — it's a content-quality check, not a
    # site-specific policy, so it stays on by default.
    for c in doc.get("cuts", []):
        if c.get("type") in ("capture", "slice"):
            text = (c.get("caption") or c.get("narration") or "").strip()
            if not text:
                violations.append(
                    f"COVER  {c.get('id', '?')}: capture/slice cut has no caption or narration")

    total = sum(c.get("duration", 0) for c in doc.get("cuts", []))
    budget = doc.get("gates", {}).get("max_duration_s", 90)
    status = "OK" if total <= budget else "OVER"
    print(f"duration: {total}s / {budget}s budget [{status}]")
    if total > budget:
        violations.append(f"GATE   total duration {total}s > {budget}s")

    if violations:
        print(f"\n{len(violations)} violation(s):")
        for v in violations:
            print(" ", v)
        return 1
    print("lint: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
