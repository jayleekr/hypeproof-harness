"""Behavioral contracts for authority, source integrity and retry-safe propagation."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("impact", ROOT / "scripts/change-impact/impact.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def node(nid, parents=(), rev="old", stage="intent", repo="jayleekr/hypeprooflab"):
    return {"id": nid, "depends_on": list(parents), "revision": rev, "stage": stage,
            "repo": repo, "owner": None, "text": "source evidence " + nid,
            "sources": [{"path": nid + ".md"}]}


def snap(*nodes):
    return {"commits": {n["repo"]: "a" * 40 for n in nodes}, "nodes": {n["id"]: n for n in nodes}}


def test_intent_change_reviews_descendants_and_upward_consistency_not_siblings():
    before = snap(node("MISSION"), node("INT-A", ["MISSION"]), node("INT-B", ["MISSION"]),
                  node("REQ-A", ["INT-A"]), node("TEST-A", ["REQ-A"], stage="test"))
    after = copy.deepcopy(before)
    after["nodes"]["INT-A"]["revision"] = "new"
    tasks = m.plan(before, after)["tasks"]
    assert {t["id"] for t in tasks} == {"INT-A", "REQ-A", "TEST-A"}
    assert next(t for t in tasks if t["id"] == "INT-A")["parents"] == ["MISSION"]


def test_removed_mapping_still_propagates_old_edges():
    before = snap(node("INT-A"), node("REQ-A", ["INT-A"]))
    after = snap(node("REQ-A", rev="new"))
    tasks = m.plan(before, after)["tasks"]
    assert {t["id"] for t in tasks} == {"INT-A", "REQ-A"}
    assert next(t for t in tasks if t["id"] == "INT-A")["removed"]


@pytest.mark.parametrize("nodes", [
    {"INT-A": node("INT-A", ["MISSING"])},
    {"INT-A": node("INT-A", ["REQ-A"]), "REQ-A": node("REQ-A", ["INT-A"])},
])
def test_broken_graph_cannot_pass(nodes):
    with pytest.raises(ValueError):
        m.validate_graph(nodes)


def test_diamond_deduplicates_and_new_origin_version_invalidates_review():
    before = snap(node("PH-A"), node("INT-A", ["PH-A"]), node("INT-B", ["PH-A"]),
                  node("REQ-A", ["INT-A", "INT-B"]))
    after = copy.deepcopy(before)
    after["nodes"]["PH-A"]["revision"] = "v2"
    tasks = m.plan(before, after)["tasks"]
    assert len(tasks) == 4
    first = next(t for t in tasks if t["id"] == "REQ-A")
    after["nodes"]["PH-A"]["revision"] = "v3"
    second = next(t for t in m.plan(before, after)["tasks"] if t["id"] == "REQ-A")
    assert first["revision"] != second["revision"]


def test_section_boundary_and_missing_heading_fail_closed():
    text = "# Doc\n## Intent\ngoal\n### Why\nbecause\n## Design\nlayout"
    assert m.section(text, "## Intent") == "## Intent\ngoal\n### Why\nbecause"
    with pytest.raises(ValueError):
        m.section(text, "## Missing")
    with pytest.raises(ValueError):
        m.section(text + "\n## Intent", "## Intent")


@pytest.mark.parametrize("verdict,status", [
    ({"disposition": "no-impact", "rationale": "reason", "evidence_ids": ["INT-A"]}, "proposed"),
    ({"disposition": "approve", "rationale": "reason", "evidence_ids": ["INT-A"]}, "failed"),
    ({"disposition": "satisfied", "rationale": "reason", "evidence_ids": ["FAKE"]}, "failed"),
])
def test_ai_can_never_complete_review(verdict, status):
    before, after = snap(node("INT-A")), snap(node("INT-A", rev="new"))
    report = m.plan(before, after)
    m.reason(report, before, after, {"max_model_calls": 1, "max_context_chars": 5000}, lambda _: verdict)
    assert report["tasks"][0]["review_status"] == "pending"
    assert report["tasks"][0]["reasoning_status"] == status
    assert "rationale" not in json.dumps(report)


def test_budget_and_provider_failure_are_visible():
    before, after = snap(node("INT-A"), node("INT-B")), snap(node("INT-A", rev="new"), node("INT-B", rev="new"))
    report = m.plan(before, after)
    def fail(_):
        raise RuntimeError("provider response might contain sensitive input")
    m.reason(report, before, after, {"max_model_calls": 1, "max_context_chars": 5000}, fail)
    assert [t["reasoning_status"] for t in report["tasks"]] == ["failed", "budget-exhausted"]
    assert "sensitive" not in json.dumps(report)


def test_oversized_context_is_not_silently_truncated():
    before, after = snap(node("INT-A")), snap(node("INT-A", rev="new"))
    report = m.plan(before, after)
    m.reason(report, before, after, {"max_model_calls": 1, "max_context_chars": 1}, lambda _: pytest.fail("called"))
    assert report["tasks"][0]["reasoning_status"] == "context-too-large"


def test_upsert_is_idempotent_preserves_human_text_and_reopens(monkeypatch):
    inventory, calls = [], []
    def api(path, method, payload):
        calls.append((method, payload))
        return {"number": 1, "html_url": "https://github.com/x/y/issues/1", "state": "open", **payload}
    monkeypatch.setattr(m, "gh", api)
    block = m.START + "\n<!-- impact-task:INT-A -->\nreview\n" + m.END
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block)
    inventory[0]["body"] += "\nHuman decision; do not erase."
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block)
    assert len(calls) == 1
    inventory[0]["state"] = "closed"
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block + "\n")
    assert calls[-1][0] == "PATCH"
    assert "Human decision" in calls[-1][1]["body"]


def test_ambiguous_markers_fail_instead_of_overwriting():
    with pytest.raises(ValueError):
        m.managed_body(m.START + m.START + m.END, "new")
    with pytest.raises(ValueError):
        m.find_marker([{"body": "marker"}, {"body": "marker"}], "marker")


def test_issue_listing_prs_are_never_treated_as_tracker_issues():
    assert m.find_marker([{"body": "marker", "pull_request": {"url": "pr"}}], "marker") is None


def test_sync_replay_recovers_partial_writes_without_duplicate_issues(monkeypatch):
    store = {"jayleekr/hypeprooflab": []}
    count = 0
    crash = True
    def api(path, method, payload):
        nonlocal count
        repo = path.split("repos/", 1)[1].split("/issues")[0]
        if method == "POST":
            count += 1
            if crash and count == 3:
                raise RuntimeError("interrupted")
            item = {"number": count, "html_url": f"https://github.com/{repo}/issues/{count}", "state": "open", **payload}
            store[repo].append(item)
            return copy.deepcopy(item)
        item = next(i for i in store[repo] if i["number"] == int(path.rsplit("/", 1)[1]))
        item.update(payload)
        return copy.deepcopy(item)
    monkeypatch.setattr(m, "gh", api)
    monkeypatch.setattr(m, "pages", lambda _: copy.deepcopy(store["jayleekr/hypeprooflab"]))
    report = m.plan(snap(), snap(node("INT-A"), node("INT-B")))
    policy = {"repositories": store}
    with pytest.raises(RuntimeError):
        m.sync(report, policy)
    crash = False
    m.sync(report, policy)
    assert len(store["jayleekr/hypeprooflab"]) == 3  # one epic and two tasks


def test_wrong_actor_stale_revision_bot_and_no_evidence_do_not_resolve():
    task = {"owner": "owner", "revision": "v2", "stage": "validation"}
    policy = {"ownership_triage": ["admin"]}
    def comment(actor, body, type="User"):
        return {"user": {"login": actor, "type": type}, "body": body, "html_url": "https://github.com/x/y/issues/1#c"}
    invalid = [comment("stranger", "/impact-resolve v2 validated https://example.org/evidence"),
               comment("owner", "/impact-resolve v1 validated https://example.org/evidence"),
               comment("owner", "/impact-resolve v2 satisfied " + "x" * 30),
               comment("owner", "/impact-resolve v2 validated " + "x" * 30),
               comment("owner", "/impact-resolve v2 validated https://example.org/evidence", "Bot")]
    assert m.resolution(task, invalid, policy) is None
    assert m.resolution(task, [comment("owner", "/impact-resolve v2 validated https://example.org/evidence")], policy)


def test_cross_repo_issue_body_contains_no_source_or_reasoning_text():
    report = m.plan(snap(), snap(node("INT-A")))
    task = report["tasks"][0]
    task["text"] = "PRIVATE EXCERPT"
    task["rationale"] = "PRIVATE MODEL EXPLANATION"
    body = m.task_body(task, report, "https://github.com/x/y/issues/1")
    assert "PRIVATE" not in body
    assert "UNASSIGNED" in body


def test_unregistered_changed_path_creates_mapping_review_without_path_disclosure():
    class Reader:
        def changed(self, *_):
            return ["web/src/app/new-private-page.tsx", "docs/archive/old.md"]
    before, after = snap(node("INT-A")), snap(node("INT-A"))
    repo = "jayleekr/hypeprooflab"
    after["commits"][repo] = "b" * 40
    report = m.plan(before, after)
    m.coverage(report, before, after, Reader(), {"repositories": {repo: {"watch_prefixes": ["web/"], "manifest": "config/traceability.json"}}})
    assert report["unmapped"][repo]["count"] == 1
    assert report["tasks"][0]["reasoning_status"] == "mapping-required"
    assert "private-page" not in json.dumps(report)


def test_real_git_snapshot_uses_commit_not_dirty_worktree(tmp_path):
    repo = "jayleekr/hypeprooflab"
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args]).decode().strip()
    git("init", "-q")
    (tmp_path / "intent.md").write_text("## Intent\nOriginal")
    (tmp_path / "traceability.json").write_text(json.dumps({"version": 1, "repository": repo,
        "nodes": [{"id": "INT-A", "stage": "intent", "sources": [{"path": "intent.md", "section": "## Intent"}]}]}))
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "seed")
    old = git("rev-parse", "HEAD")
    (tmp_path / "intent.md").write_text("## Intent\nUncommitted malicious change")
    reader = m.Reader({repo: str(tmp_path)})
    policy = {"repositories": {repo: {"manifest": "traceability.json"}}, "members": [], "canon_owner": "jay"}
    result = m.snapshot(reader, policy, {repo: old})
    assert result["nodes"]["INT-A"]["text"] == "## Intent\nOriginal"
    assert "text" not in m.public_snapshot(result)["nodes"]["INT-A"]


def test_design_without_requirement_is_visible_not_assumed_complete():
    graph = snap(node("PH-A", stage="philosophy"), node("DES-A", ["PH-A"], stage="design"))
    assert m.structural_gaps(graph["nodes"]) == ["DES-A"]


def test_resumable_reasoning_uses_exact_revision_cache(monkeypatch):
    before, after = snap(node("INT-A")), snap(node("INT-A", rev="new"))
    report = m.plan(before, after)
    task = report["tasks"][0]
    body = m.task_body({**task, "recommendation": "satisfied", "reasoning_status": "proposed"}, report, "epic")
    monkeypatch.setattr(m, "pages", lambda _: [{"body": body}])
    m.restore_recommendations(report, {"repositories": {task["repo"]: {}}})
    m.reason(report, before, after, {"max_model_calls": 1, "max_context_chars": 5000}, lambda _: pytest.fail("cached review called model"))
    assert task["reasoning_status"] == "proposed"
    task["revision"] = "different"
    task["reasoning_status"] = "not-run"
    m.restore_recommendations(report, {"repositories": {task["repo"]: {}}})
    assert task["reasoning_status"] == "not-run"


def test_checkpoint_is_not_written_after_partial_sync_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "preflight", lambda _: {})
    after = snap(node("INT-A"))
    monkeypatch.setattr(m, "snapshot", lambda *_: after)
    monkeypatch.setattr(m.Reader, "resolve", lambda *_: "a" * 40)
    monkeypatch.setattr(m, "pages", lambda *_: [])
    monkeypatch.setattr(m, "sync", lambda *_: (_ for _ in ()).throw(RuntimeError("partial write")))
    monkeypatch.setattr(m, "upsert", lambda *_: pytest.fail("checkpoint advanced after failure"))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--apply", "--output", str(tmp_path / "report.json")])
    with pytest.raises(RuntimeError):
        m.main()


def test_moving_main_prevents_any_issue_write(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "preflight", lambda _: {})
    after = snap(node("INT-A"))
    monkeypatch.setattr(m, "snapshot", lambda *_: after)
    monkeypatch.setattr(m.Reader, "resolve", lambda *_: "b" * 40)
    monkeypatch.setattr(m, "pages", lambda *_: [])
    monkeypatch.setattr(m, "sync", lambda *_: pytest.fail("published stale source"))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--apply", "--output", str(tmp_path / "report.json")])
    with pytest.raises(ValueError, match="main moved"):
        m.main()


def test_missing_api_key_is_explicit_pending(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(m, "snapshot", lambda *_: snap(node("INT-A")))
    monkeypatch.setattr(m, "pages", lambda *_: [])
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--reason", "--output", str(output)])
    assert m.main() == 0
    task = json.loads(output.read_text())["tasks"][0]
    assert task["reasoning_status"] == "not-configured"
    assert task["review_status"] == "pending"


@pytest.mark.parametrize("mutation", ["delete", "stage", "owner", "source"])
def test_consumer_manifest_cannot_redefine_protected_canon(mutation):
    repo = "jayleekr/hypeprooflab"
    original = {"id": "LAB-PHILOSOPHY", "stage": "philosophy", "owner": "jayleekr",
                "sources": [{"path": "PHILOSOPHY.md"}]}
    edited = copy.deepcopy(original)
    if mutation == "stage":
        edited["stage"] = "intent"
    elif mutation == "owner":
        edited["owner"] = "other-member"
    elif mutation == "source":
        edited["sources"] = [{"path": "unrelated.md"}]
    class Reader:
        def resolve(self, *_):
            return "a" * 40
        def read(self, _repo, _sha, path):
            if path == "config/traceability.json":
                return json.dumps({"version": 1, "repository": repo,
                                   "nodes": [] if mutation == "delete" else [edited]})
            return "source content"
    policy = {"repositories": {repo: {"manifest": "config/traceability.json"}},
              "members": ["jayleekr", "other-member"], "canon_owner": "jayleekr",
              "protected_nodes": {"LAB-PHILOSOPHY": {"repo": repo, "stage": "philosophy",
                                  "owner": "jayleekr", "path": "PHILOSOPHY.md"}}}
    with pytest.raises(ValueError):
        m.snapshot(Reader(), policy, {})


def test_later_unknown_revokes_earlier_acceptance():
    task = {"owner": "owner", "revision": "v2", "stage": "intent"}
    comments = [{"user": {"login": "owner"}, "html_url": "https://github.com/x/y/issues/1#c",
                 "body": "/impact-resolve v2 satisfied " + "sufficient rationale " * 2},
                {"user": {"login": "owner"}, "html_url": "https://github.com/x/y/issues/1#d",
                 "body": "/impact-resolve v2 unknown " + "new contradictory evidence " * 2}]
    assert m.resolution(task, comments, {"ownership_triage": []}) is None


def test_failed_model_does_not_advance_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(m, "preflight", lambda _: {})
    monkeypatch.setattr(m, "snapshot", lambda *_: snap(node("INT-A")))
    monkeypatch.setattr(m.Reader, "resolve", lambda *_: "a" * 40)
    monkeypatch.setattr(m, "pages", lambda _: [])
    monkeypatch.setattr(m, "model_call", lambda _: lambda _: (_ for _ in ()).throw(ValueError("provider outage")))
    published = []
    monkeypatch.setattr(m, "sync", lambda report, _: published.append(report))
    monkeypatch.setattr(m, "upsert", lambda *_: pytest.fail("checkpoint advanced after model failure"))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--reason", "--apply", "--output", str(tmp_path / "out.json")])
    assert m.main() == 2
    assert published[0]["tasks"][0]["reasoning_status"] == "failed"


def test_partial_checkpoint_cannot_skip_repository_history(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "snapshot", lambda *_: snap(node("INT-A")))
    monkeypatch.setattr(m, "pages", lambda _: [{"body": '<!-- impact-checkpoint:v1 -->\n```json\n{"commits":{}}\n```'}])
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--output", str(tmp_path / "out.json")])
    with pytest.raises(ValueError, match="every configured repository"):
        m.main()


def test_preflight_checks_all_repos_before_writes(monkeypatch):
    calls = []
    def api(path, method="GET", payload=None):
        calls.append((path, method))
        if path == "user":
            return {"login": "operator"}
        if path.endswith("private-repo"):
            raise ValueError("no read permission")
        return {} if "?" not in path else []
    monkeypatch.setattr(m, "gh", api)
    with pytest.raises(ValueError):
        m.preflight({"repositories": {"owner/first": {}, "owner/private-repo": {}}})
    assert all(method == "GET" for _, method in calls)


def test_operational_probe_cleans_up_after_partial_api_failure(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "impact", m)
    spec = importlib.util.spec_from_file_location("ops_smoke", ROOT / "scripts/change-impact/ops_smoke.py")
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    monkeypatch.setattr(m, "preflight", lambda _: {})
    monkeypatch.setattr(m, "pages", lambda _: [])
    stored = {}
    def api(path, method="GET", payload=None):
        if path.endswith("/comments"):
            raise ValueError("injected failure after write")
        if method == "POST":
            stored.update(number=1, html_url="https://github.com/owner/repo/issues/1", state="open", **payload)
        if method == "PATCH":
            stored.update(payload)
        return copy.deepcopy(stored)
    monkeypatch.setattr(m, "gh", api)
    with pytest.raises(ValueError, match="after write"):
        ops.run({"repositories": {"owner/repo": {}}})
    assert stored["state"] == "closed"
    assert "impact-task:" not in stored["body"]
    assert "impact-checkpoint:" not in stored["body"]
