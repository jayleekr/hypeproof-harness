"""Real-git preparation contracts; GitHub transport is replaced by pinned git objects."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/hype-pr"))
import preparation as prep


def run(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, message="change"):
    run(root, "add", "-A")
    run(root, "commit", "-qm", message)
    return run(root, "rev-parse", "HEAD")


def node(nid, stage, path, parents=(), owner="alice"):
    return {"id": nid, "stage": stage, "owner": owner, "sources": [{"path": path}], "depends_on": list(parents)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    names = ["hypeprooflab", "hypeproof-studio", "hypeproof-harness"]
    repos = {f"jayleekr/{name}": tmp_path / name for name in names}
    definitions = [
        [node("PH-A", "philosophy", "PHILOSOPHY.md"), node("MI-A", "mission", "MISSION.md", ["PH-A"])],
        [node("INT-A", "intent", "INTENT.md", ["MI-A"]), node("IMP-A", "implementation", "app.py", ["REQ-A"]), node("TEST-A", "test", "test_app.py", ["REQ-A"])],
        [node("REQ-A", "requirement", "REQ.md", ["INT-A"])],
    ]
    for (repo, root), nodes in zip(repos.items(), definitions):
        root.mkdir()
        run(root, "init", "-qb", "main")
        run(root, "config", "user.email", "test@example.com")
        run(root, "config", "user.name", "Fixture")
        run(root, "remote", "add", "origin", f"https://github.com/{repo}.git")
        (root / "config").mkdir()
        (root / "config/traceability.json").write_text(json.dumps({"version": 1, "repository": repo, "nodes": nodes}))
        for n in nodes:
            (root / n["sources"][0]["path"]).write_text("Original criterion.\n")
        commit(root, "base")
    canonical = tmp_path / "canonical"
    (canonical / "policy").mkdir(parents=True)
    (canonical / "policy/change-impact.json").write_text(json.dumps({"repositories": {
        r: {"manifest": "config/traceability.json", "watch_prefixes": ["docs/", "extra.py", "PARTIAL.md"]} for r in repos}, "canon_owner": "alice"}))
    monkeypatch.setattr(prep, "ROOT", canonical)
    monkeypatch.setattr(prep, "tool_version", lambda: "tool-v1")
    overrides = {}
    def api(path):
        path, _, query = path.partition("?")
        parts = path.split("/")
        repo = "/".join(parts[1:3])
        root = repos[repo]
        resource, ref = parts[3], "/".join(parts[4:])
        if resource == "commits":
            return {"sha": overrides.get((repo, ref), run(root, "rev-parse", ref))}
        assert resource == "contents"
        sha = parse_qs(query)["ref"][0]
        data = subprocess.check_output(["git", "-C", str(root), "show", f"{sha}:{ref}"])
        return {"encoding": "base64", "content": base64.b64encode(data).decode()}
    monkeypatch.setattr(prep.impact, "gh", api)
    repo = "jayleekr/hypeproof-studio"
    target = repos[repo]
    run(target, "switch", "-qc", "feat/example")
    (target / "app.py").write_text("Changed runtime behavior.\n")
    commit(target)
    return repos, target, repo, overrides


def report(world):
    _, target, repo, _ = world
    return prep.inspect(target, repo, members=["alice"])


def assessment(r):
    a = prep.assessment_template(r)
    a["summary"] = "This runtime change satisfies the linked requirement and test contract."
    for entry in a["reviews"].values():
        entry.update(disposition="satisfied", reason="The recorded behavior and parent requirement remain consistent.")
    a["validation"] = [{"check": "fixture verification", "result": "pass", "evidence": "Executed the fixture checks at the committed source version."}]
    for entry in a["path_links"].values():
        entry.update(kind="implementation", nodes=["REQ-A", "TEST-A"], reason="The implementation satisfies the requirement and its executable test.")
    return a


def test_committed_graph_and_receipt_verify_without_provider_key(world, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = report(world)
    assert r["paths"] == ["app.py"] and r["changed_nodes"] == ["IMP-A"]
    assert not r["blockers"]
    path = prep.prepare(r, assessment(r), tmp_path / "receipt.json")
    _, target, repo, _ = world
    assert prep.verify(path, target, repo, "main", "feat/example", ["alice"]) == r
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("change", ["commit", "dirty", "untracked", "base", "dependency", "tool", "remote", "branch", "tamper"])
def test_create_rejects_stale_or_wrong_preparation(world, tmp_path, monkeypatch, change):
    repos, target, repo, overrides = world
    r = report(world)
    path = prep.prepare(r, assessment(r), tmp_path / "receipt.json")
    branch = "feat/example"
    if change in {"commit", "dirty"}:
        (target / "app.py").write_text("A different behavior.\n")
        if change == "commit": commit(target)
    elif change == "untracked": (target / "new.py").write_text("unreviewed")
    elif change == "base":
        run(target, "switch", "-q", "main")
        (target / "base.txt").write_text("new base")
        commit(target)
        run(target, "switch", "-q", branch)
    elif change == "dependency":
        (repos["jayleekr/hypeprooflab"] / "MISSION.md").write_text("A changed mission.\n")
        commit(repos["jayleekr/hypeprooflab"])
    elif change == "tool": monkeypatch.setattr(prep, "tool_version", lambda: "tool-v2")
    elif change == "remote": overrides[(repo, branch)] = "f" * 40
    elif change == "branch": branch = "feat/other"
    elif change == "tamper":
        data = json.loads(path.read_text()); data["report"]["paths"] = []; path.write_text(json.dumps(data))
    with pytest.raises(ValueError): prep.verify(path, target, repo, "main", branch, ["alice"])


def test_wrong_checkout_or_missing_receipt_fails(world):
    _, target, _, _ = world
    with pytest.raises(ValueError, match="origin"):
        prep.inspect(target, "jayleekr/hypeprooflab", members=["alice"])
    with pytest.raises(ValueError, match="required"):
        prep.verify(None, target, "jayleekr/hypeproof-studio", "main", "feat/example", ["alice"])


def test_new_criteria_need_registration_and_owner(world):
    _, target, _, _ = world
    path = target / "docs/requirements/new.md"
    path.parent.mkdir(parents=True); path.write_text("A new success criterion.")
    commit(target)
    assert any("register new criteria" in b for b in report(world)["blockers"])
    manifest = target / "config/traceability.json"
    doc = json.loads(manifest.read_text())
    doc["nodes"].append(node("REQ-NEW", "requirement", "docs/requirements/new.md", ["INT-A"], owner=None))
    manifest.write_text(json.dumps(doc)); commit(target)
    assert any("new/unassigned owner" in b for b in report(world)["blockers"])
    doc["nodes"][-1]["owner"] = "alice"; manifest.write_text(json.dumps(doc)); commit(target)
    assert not report(world)["blockers"]


def test_new_stage_gap_is_not_grandfathered(world):
    _, target, _, _ = world
    manifest = target / "config/traceability.json"; doc = json.loads(manifest.read_text())
    doc["nodes"][1]["depends_on"] = ["MI-A"]
    manifest.write_text(json.dumps(doc)); commit(target)
    assert any("new missing parent stage" in b for b in report(world)["blockers"])


def test_unmapped_implementation_requires_req_and_test_links(world):
    _, target, _, _ = world
    (target / "extra.py").write_text("new behavior")
    commit(target)
    r = report(world); a = assessment(r)
    assert r["unmapped"] == ["extra.py"]
    a["path_links"]["extra.py"]["nodes"] = ["INT-A"]
    with pytest.raises(ValueError, match="requirement and test"): prep.validate_assessment(r, a)
    a["path_links"]["extra.py"]["nodes"] = ["REQ-A", "TEST-A"]
    prep.validate_assessment(r, a)


@pytest.mark.parametrize("change", ["missing-review", "stale", "unknown", "failed-test", "unrun", "unknown-node"])
def test_semantic_and_validation_obligations(world, change):
    r = report(world); a = assessment(r)
    if change == "missing-review": a["reviews"] = {}
    if change == "stale": a["fingerprint"] = "old"
    if change == "unknown": a["reviews"]["IMP-A"]["disposition"] = "unknown"
    if change == "failed-test": a["validation"][0]["result"] = "fail"
    if change == "unrun": a["validation"] = []
    if change == "unknown-node": a["reviews"]["INVENTED"] = a["reviews"]["IMP-A"]
    with pytest.raises(ValueError): prep.validate_assessment(r, a)


def test_unresolved_downstream_work_can_be_tracked_without_claiming_approval(world):
    r = report(world); a = assessment(r)
    a["reviews"]["IMP-A"].update(disposition="change-required", followups=["https://github.com/jayleekr/hypeproof-studio/issues/1"])
    prep.validate_assessment(r, a)
    assert "not independent human approval" in prep.summary(r)
    assert a["reviews"]["IMP-A"]["reason"] not in prep.summary(r)


def test_consumer_install_is_repeatable_preserves_local_rules_and_delegates(world, monkeypatch):
    spec = importlib.util.spec_from_file_location("install_pr", ROOT / "scripts/hype-pr/install.py")
    install = importlib.util.module_from_spec(spec); spec.loader.exec_module(install)
    _, target, _, _ = world
    (target / "CLAUDE.md").write_text("# Local rules\nKeep the native product contract.\n")
    install.install(target)
    first = (target / "CLAUDE.md").read_text(); install.install(target)
    assert (target / "CLAUDE.md").read_text() == first
    assert "Keep the native product contract." in first
    assert (target / ".agents/skills/hype-pr/SKILL.md").read_bytes() == (ROOT / "skills/hype-pr/SKILL.md").read_bytes()
    proc = subprocess.run([sys.executable, str(target / "scripts/hype-pr/pr.py"), "plan", "--repo", "hypeproof-studio", "--author", "jayleekr"], cwd=target, env={**os.environ, "HYPEPROOF_HARNESS": str(ROOT)}, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["repo"] == "jayleekr/hypeproof-studio"


def test_existing_owner_debt_is_reported_without_blocking_the_change(world):
    _, target, _, _ = world
    run(target, "switch", "-q", "main")
    path = target / "config/traceability.json"; doc = json.loads(path.read_text())
    doc["nodes"][1]["owner"] = None; path.write_text(json.dumps(doc)); commit(target)
    run(target, "switch", "-q", "feat/example"); run(target, "rebase", "main")
    r = report(world)
    assert not r["blockers"]
    assert any("IMP-A: existing unassigned owner" == d for d in r["existing_debt"])


def test_partial_section_registration_does_not_hide_other_changes(world):
    _, target, _, _ = world
    run(target, "switch", "-q", "main")
    path = target / "config/traceability.json"; doc = json.loads(path.read_text())
    doc["nodes"][0]["sources"] = [{"path": "PARTIAL.md", "section": "## Intent"}]
    path.write_text(json.dumps(doc))
    (target / "PARTIAL.md").write_text("## Intent\nFixed outcome.\n## Other\nOriginal.\n")
    commit(target)
    run(target, "switch", "-q", "feat/example"); run(target, "rebase", "main")
    (target / "PARTIAL.md").write_text("## Intent\nFixed outcome.\n## Other\nNew obligations.\n")
    commit(target)
    r = report(world)
    assert "INT-A" not in r["changed_nodes"] and "PARTIAL.md" in r["unmapped"]
