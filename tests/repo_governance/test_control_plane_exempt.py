"""control-plane 면제 경로가 의도한 만큼만 뚫려 있는지 본다.

면제는 게이트를 약하게 만드는 변경이라, "뚫렸다"와 "그 옆까지 뚫렸다"를 반드시 갈라야
한다. 그래서 이 테스트는 통과 하나로 끝내지 않고 **면제되지 않은 이웃 경로가 여전히
걸리는지**를 같이 본다 (policy/repos.yaml, policy/control-plane.yaml).

배경: 2026-08-18. `policy/members.yaml` 을 면제했다. 멤버 한 줄 추가마다 승인자가
한 명뿐인 게이트가 우회됐고, 매번 우회되는 게이트는 게이트가 아니라 통행세다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "repo-governance" / "check_control_plane.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_control_plane", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_members_yaml_is_exempt_but_its_neighbours_are_not() -> None:
    module = load_checker()
    policy = module.load_policy()

    # 면제된 파일만 바뀐 PR 은 control-plane PR 이 아니다 → 승인 요구 없음.
    assert module.control_plane_hits(["policy/members.yaml"], policy) == []

    # 같은 글롭 안의 다른 파일은 그대로 막힌다. 면제가 `policy/**` 를 통째로
    # 무력화했다면 아래가 빈 목록이 되고, 그건 조용한 사고다.
    for neighbour in ("policy/repos.yaml", "policy/control-plane.yaml"):
        assert module.control_plane_hits([neighbour], policy) == [neighbour], neighbour

    # 섞여 있으면 면제되지 않은 쪽 때문에 여전히 control-plane PR 이다.
    mixed = module.control_plane_hits(["policy/members.yaml", "policy/repos.yaml"], policy)
    assert mixed == ["policy/repos.yaml"]


def test_exempt_list_is_explicit_and_small() -> None:
    """면제가 조용히 늘어나지 않게 한다.

    목록이 길어지는 것 자체가 신호다. 늘려야 한다면 이 테스트를 같이 고치게 해서,
    '왜 늘렸나'가 diff 에 남도록 한다.
    """
    module = load_checker()
    exempt = [p["path"] for p in module.load_policy().get("exempt_paths", [])]
    assert exempt == ["policy/members.yaml"], exempt

    # 면제 항목은 왜 뺐는지, 무엇을 잃는지, 무엇이 대신 잡는지를 적어야 한다.
    for item in module.load_policy().get("exempt_paths", []):
        for field in ("why", "residual_risk", "detection"):
            assert item.get(field), "%s 에 %s 가 없다" % (item["path"], field)
