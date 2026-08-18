"""문서의 lens 표가 정본(policy/members.yaml)과 갈라지지 않았는지 본다.

`docs/HYPE-REVIEW.ko.md` 의 "기본 매핑" 표는 사람이 읽는 **사본**이다. 정본은
`policy/members.yaml` 의 `review_lenses` 이고 스킬이 읽는 것도 그쪽이다.

사본은 조용히 갈라진다. 실제로 rabqatab(2026-07 합류)이 정본에는 있는데 표에는 없었고,
아무도 몰랐다 — 표를 안 고쳐도 아무것도 실패하지 않았기 때문이다. 이 테스트가 그
"아무것도 실패하지 않음"을 없앤다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "HYPE-REVIEW.ko.md"
POLICY = ROOT / "policy" / "members.yaml"

# | `handle` | `lens`, `lens` |
ROW = re.compile(r"^\|\s*`([A-Za-z0-9_-]+)`\s*\|\s*(.+?)\s*\|\s*$")


def _doc_lenses() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        handle, cell = m.group(1), m.group(2)
        lenses = [x.strip().strip("`") for x in cell.split(",") if x.strip()]
        # lens 표가 아닌 표(첫 칸이 백틱인 다른 표)를 걸러낸다 — lens 는 전부 소문자 낱말이다.
        if lenses and all(re.fullmatch(r"[a-z]+", x) for x in lenses):
            out[handle] = lenses
    return out


def _policy_lenses() -> dict[str, list[str]]:
    doc = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    return {k: list(v) for k, v in (doc.get("review_lenses") or {}).items()}


def test_docs_lens_table_matches_policy() -> None:
    policy = _policy_lenses()
    doc = _doc_lenses()

    missing = sorted(set(policy) - set(doc))
    extra = sorted(set(doc) - set(policy))
    assert not missing, (
        "docs/HYPE-REVIEW.ko.md 의 lens 표에 없는 멤버: %s — 정본에는 있다. "
        "멤버를 늘릴 때 표도 같이 고쳐라." % missing
    )
    assert not extra, (
        "docs 표에만 있고 정본에 없는 멤버: %s — 나간 사람이거나 오타다." % extra
    )

    mismatched = {h: (policy[h], doc[h]) for h in policy if policy[h] != doc[h]}
    assert not mismatched, "lens 값이 다르다 (정본, 문서): %s" % mismatched
