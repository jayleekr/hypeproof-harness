"""waiver 가 지적을 덮되, 은폐가 되지 않는지 본다.

waiver 는 게이트를 약하게 만드는 기능이라 "동작한다"만 확인하면 안 된다.
확인해야 할 것은 셋이다.

  1. 덮는다        — 받아들이기로 한 항목이 판정에서 빠진다
  2. **만료된다**  — 기한이 지나면 지적이 저절로 돌아온다
  3. 보인다        — 덮인 것이 출력에 남는다 (조용히 사라지면 waiver 가 곧 은폐다)

배경: 2026-08-18. hypeprooflab 의 감사가 3건을 계속 지적했고 셋 다 못 고치거나 안 고치기로
한 것이었다. 매주 빨간 지적은 옆의 진짜 드리프트까지 안 읽히게 만든다.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "repo-governance" / "audit.py"


def load():
    # sys.modules 등록이 없으면 dataclass 생성이 3.9 에서 깨진다 (test_policy.py 와 같은 방식).
    spec = importlib.util.spec_from_file_location("repo_governance_audit", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _repo(expires: str):
    return {
        "waivers": [{
            "id": "w1", "owner": "someone", "reason": "때문에",
            "expires_at": expires, "waives": ["repo_settings.allow_forking"],
        }]
    }


def _findings(module):
    return [
        module.Finding("o/r", "repo_settings", "medium", "allow_forking", False, True),
        module.Finding("o/r", "branch_protection", "high", "protected", True, False),
    ]


def test_active_waiver_covers_only_its_field() -> None:
    m = load()
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    out = m.apply_waivers("o/r", _repo(future), _findings(m))

    by_field = {f.field: f for f in out}
    # 덮인 것은 info 로 남는다 — 사라지지 않는다.
    assert by_field["allow_forking"].severity == "info"
    assert "w1" in by_field["allow_forking"].message
    # 덮이지 않은 지적은 그대로 high 다. waiver 하나가 옆 항목까지 지우면 안 된다.
    assert by_field["protected"].severity == "high"


def test_expired_waiver_stops_covering() -> None:
    m = load()
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    out = m.apply_waivers("o/r", _repo(past), _findings(m))

    by_field = {f.field: f for f in out}
    assert by_field["allow_forking"].severity == "medium", "만료된 waiver 는 덮으면 안 된다"


def test_malformed_waiver_covers_nothing() -> None:
    m = load()
    broken = {"waivers": [{"id": "w", "owner": "x", "reason": "y",
                           "expires_at": "언젠가", "waives": ["repo_settings.allow_forking"]}]}
    out = m.apply_waivers("o/r", broken, _findings(m))
    assert all(f.severity != "info" for f in out), "날짜를 못 읽는 waiver 가 무언가를 덮으면 안 된다"


def test_policy_validation_requires_owner_reason_and_expiry() -> None:
    """waiver 는 exceptions 와 같은 무게로 검사받는다."""
    m = load()
    policy = m.load_policy()
    repo = next(r for r in policy["repos"]["repositories"] if r["name"] == "hypeprooflab")

    assert repo.get("waivers"), "이 테스트는 실제 waiver 가 있는 상태를 전제한다"
    for waiver in repo["waivers"]:
        for field in ("id", "owner", "reason", "expires_at", "waives"):
            assert waiver.get(field), f"{waiver.get('id')} 에 {field} 가 없다"
        dt.date.fromisoformat(str(waiver["expires_at"]))  # 형식이 아니면 던진다
        for target in waiver["waives"]:
            assert target.count(".") == 1, f"waives 는 <module>.<field> 형식이다: {target}"


def test_live_waivers_are_not_indefinite() -> None:
    """만료 없는 유예를 만들지 않는다 — 그건 정책 변경이지 유예가 아니다."""
    m = load()
    policy = m.load_policy()
    horizon = dt.date.today() + dt.timedelta(days=730)
    for repo in policy["repos"]["repositories"]:
        for waiver in repo.get("waivers", []) or []:
            expires = dt.date.fromisoformat(str(waiver["expires_at"]))
            assert expires <= horizon, f"{waiver['id']} 의 기한이 2년을 넘는다 — 사실상 영구 면제다"
