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


def test_intent_change_reviews_direct_children_and_upward_consistency_not_siblings():
    before = snap(node("MISSION"), node("INT-A", ["MISSION"]), node("INT-B", ["MISSION"]),
                  node("REQ-A", ["INT-A"]), node("TEST-A", ["REQ-A"], stage="test"))
    after = copy.deepcopy(before)
    after["nodes"]["INT-A"]["revision"] = "new"
    tasks = m.plan(before, after)["tasks"]
    # TEST-A is a grandchild: it joins a round only when REQ-A itself changes.
    assert {t["id"] for t in tasks} == {"INT-A", "REQ-A"}
    assert next(t for t in tasks if t["id"] == "INT-A")["parents"] == ["MISSION"]
    after["nodes"]["REQ-A"]["revision"] = "new"
    tasks = m.plan(before, after)["tasks"]
    assert {t["id"] for t in tasks} == {"INT-A", "REQ-A", "TEST-A"}
    assert next(t for t in tasks if t["id"] == "TEST-A")["causes"] == ["REQ-A"]


def test_one_upstream_edit_does_not_fan_out_to_the_whole_graph():
    # Issue #255: one table edit in a strategy node re-opened 239 reviews.
    chain = [node("LAB-ROLES", stage="strategy")]
    for depth in range(1, 6):
        parent = chain[depth - 1]["id"] if depth == 1 else f"N{depth - 1}-0"
        chain += [node(f"N{depth}-{i}", [parent]) for i in range(3)]
    before = snap(*chain)
    after = copy.deepcopy(before)
    after["nodes"]["LAB-ROLES"]["revision"] = "new"
    tasks = m.plan(before, after)["tasks"]
    assert sorted(t["id"] for t in tasks) == ["LAB-ROLES", "N1-0", "N1-1", "N1-2"]
    assert all(t["causes"] == ["LAB-ROLES"] for t in tasks)


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
    assert {t["id"] for t in tasks} == {"PH-A", "INT-A", "INT-B"}
    first = next(t for t in tasks if t["id"] == "INT-A")
    after["nodes"]["PH-A"]["revision"] = "v3"
    second = next(t for t in m.plan(before, after)["tasks"] if t["id"] == "INT-A")
    assert first["revision"] != second["revision"]
    # Both parents of the diamond change: REQ-A is reviewed once, for both causes.
    after["nodes"]["INT-A"]["revision"] = after["nodes"]["INT-B"]["revision"] = "v2"
    tasks = m.plan(before, after)["tasks"]
    assert len(tasks) == 4
    assert next(t for t in tasks if t["id"] == "REQ-A")["causes"] == ["INT-A", "INT-B"]


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


def test_upsert_is_idempotent_preserves_human_text_and_never_reopens(monkeypatch):
    inventory, calls = [], []
    def api(path, method, payload):
        calls.append((path, method, payload))
        result = {"number": 1, "html_url": "https://github.com/x/y/issues/1", "state": "open", **payload}
        result["assignees"] = [{"login": a} for a in payload.get("assignees", [])]
        return result
    monkeypatch.setattr(m, "gh", api)
    block = m.START + "\n<!-- impact-task:INT-A -->\nreview\n" + m.END
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block, "owner")
    inventory[0]["body"] += "\nHuman decision; do not erase."
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block, "owner")
    assert len(calls) == 1
    inventory[0]["state"] = "closed"
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block + "\n", "owner",
             "new revision notice")
    (_, patch, payload), (path, post, comment) = calls[-2:]
    assert patch == "PATCH" and "Human decision" in payload["body"]
    assert "state" not in payload and "assignees" not in payload  # closed stays closed, unassigned
    assert (path, post, comment) == ("repos/x/y/issues/1/comments", "POST", {"body": "new revision notice"})
    # An open issue still gets the owner assigned, and no notice comment.
    inventory[0]["state"] = "open"
    m.upsert("x/y", inventory, "<!-- impact-task:INT-A -->", "Review", block + "\n\n", "owner", "unused")
    assert calls[-1][1] == "PATCH" and calls[-1][2]["assignees"] == ["owner"]
    assert "state" not in calls[-1][2]


def test_sync_comments_on_a_closed_review_once_per_revision_instead_of_reopening(monkeypatch):
    repo = "jayleekr/hypeprooflab"
    store, calls = [], []
    def api(path, method, payload):
        calls.append((path, method, payload))
        if path.endswith("/comments"):
            return {"html_url": "https://github.com/c"}
        if method == "POST":
            item = {"number": len(store) + 1, "state": "open", **payload,
                    "html_url": f"https://github.com/{repo}/issues/{len(store) + 1}"}
            store.append(item)
            return copy.deepcopy(item)
        item = next(i for i in store if i["number"] == int(path.rsplit("/", 1)[1]))
        item.update(payload)
        return copy.deepcopy(item)
    monkeypatch.setattr(m, "gh", api)
    monkeypatch.setattr(m, "pages", lambda _: copy.deepcopy(store))
    policy = {"repositories": {repo: {}}}
    before = snap(node("INT-A"))
    m.sync(m.plan({"commits": {}, "nodes": {}}, before), policy)
    task_issue = next(i for i in store if "impact-task:INT-A" in i["body"])
    task_issue["state"] = "closed"  # a person closed it
    after = copy.deepcopy(before)
    after["nodes"]["INT-A"]["revision"] = "new"
    report = m.plan(before, after)
    calls.clear()
    m.sync(report, policy)
    assert task_issue["state"] == "closed"
    assert all(p.get("state") != "open" for _, _, p in calls)
    notices = [p["body"] for path, _, p in calls if path == f"repos/{repo}/issues/{task_issue['number']}/comments"]
    assert len(notices) == 1 and report["tasks"][0]["revision"] in notices[0]
    assert "source evidence" not in notices[0]
    # Same review revision, different source head: body refresh, no second notice.
    report["head"] = {repo: "b" * 40}
    calls.clear()
    m.sync(report, policy)
    assert not [p for path, _, p in calls if path.endswith(f"/{task_issue['number']}/comments")]


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


def test_unadopted_source_prevents_any_issue_write(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "preflight", lambda _: {})
    after = snap(node("INT-A"))
    monkeypatch.setattr(m, "snapshot", lambda *_: after)
    monkeypatch.setattr(m.Reader, "adopted", lambda *_: False)
    monkeypatch.setattr(m, "pages", lambda *_: [])
    monkeypatch.setattr(m, "sync", lambda *_: pytest.fail("published stale source"))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--apply", "--output", str(tmp_path / "report.json")])
    with pytest.raises(ValueError, match="not adopted"):
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


def checkpoint_json(block):
    import re
    return json.loads(re.search(r"```json\n(.*?)\n```", block, re.S)[1])


def test_failed_model_advances_checkpoint_but_stays_visible(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(m, "preflight", lambda _: {})
    monkeypatch.setattr(m, "snapshot", lambda *_: snap(node("INT-A")))
    monkeypatch.setattr(m.Reader, "resolve", lambda *_: "a" * 40)
    monkeypatch.setattr(m, "pages", lambda _: [])
    monkeypatch.setattr(m, "model_call", lambda _: lambda _: (_ for _ in ()).throw(ValueError("provider outage")))
    published, saved = [], []
    monkeypatch.setattr(m, "sync", lambda report, _: published.append(report))
    monkeypatch.setattr(m, "upsert", lambda *args: saved.append(args[4]))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--reason", "--apply", "--output", str(tmp_path / "out.json")])
    assert m.main() == 2  # provider fault is still a red run...
    assert published[0]["tasks"][0]["reasoning_status"] == "failed"
    # ...but progress is saved: the next run does not re-plan the same round.
    assert checkpoint_json(saved[0]) == {"commits": snap(node("INT-A"))["commits"],
                                         "reasoning_gaps": {"failed": 1}}


def test_budget_exhaustion_advances_checkpoint_and_records_the_gap(monkeypatch, tmp_path):
    # Issue #255: 8 model calls against 200+ tasks held the checkpoint for days.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(m, "preflight", lambda _: {})
    after = snap(*(node(f"INT-{i}") for i in range(5)))
    monkeypatch.setattr(m, "snapshot", lambda *_: after)
    monkeypatch.setattr(m.Reader, "adopted", lambda *_: True)
    monkeypatch.setattr(m, "pages", lambda _: [])
    monkeypatch.setattr(m, "restore_recommendations", lambda *_: None)
    verdict = {"disposition": "no-impact", "rationale": "reason", "evidence_ids": ["INT-0"]}
    monkeypatch.setattr(m, "model_call", lambda _: lambda prompt: {**verdict, "evidence_ids": [
        next(iter(json.loads(prompt)["nodes"]))]})
    monkeypatch.setattr(m, "sync", lambda *_: None)
    saved = []
    monkeypatch.setattr(m, "upsert", lambda *args: saved.append(args[4]))
    policy = json.loads((ROOT / "policy/change-impact.json").read_text())
    policy["max_model_calls"] = 2
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--reason", "--apply", "--policy", str(policy_path),
                                     "--output", str(tmp_path / "out.json")])
    assert m.main() == 0
    assert checkpoint_json(saved[0])["reasoning_gaps"] == {"budget-exhausted": 3}
    assert "INT-" not in saved[0]  # counts only, never node IDs, in the public checkpoint


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
        if path.endswith("/commits/main"):
            return {"sha": "a" * 40}
        if "/contents/" in path:
            return {"encoding": "base64", "content": "e30="}
        if path.endswith("private-repo"):
            raise ValueError("no read permission")
        return {} if "?" not in path else []
    monkeypatch.setattr(m, "gh", api)
    with pytest.raises(ValueError):
        m.preflight({"repositories": {"owner/first": {"manifest": "config/traceability.json"}, "owner/private-repo": {"manifest": "config/traceability.json"}}})
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


@pytest.mark.parametrize("path,method,expected", [
    ("repos/jayleekr/hypeprooflab/commits/main", "GET", "source-reader"),
    ("repos/jayleekr/hypeprooflab/contents/PHILOSOPHY.md?ref=abc", "GET", "source-reader"),
    ("repos/jayleekr/hypeprooflab/compare/a...b", "GET", "source-reader"),
    ("repos/jayleekr/hypeprooflab/issues", "POST", "issue-writer"),
    ("repos/jayleekr/hypeprooflab/issues", "GET", "issue-writer"),
    ("repos/jayleekr/hypeprooflab/contents/file", "PUT", "issue-writer"),
    ("repos/jayleekr/hypeproof-harness/contents/file", "GET", "issue-writer"),
])
def test_private_source_token_never_authorizes_writes_or_other_repos(monkeypatch, path, method, expected):
    monkeypatch.setenv("GH_TOKEN", "issue-writer")
    monkeypatch.setenv("CHANGE_IMPACT_SOURCE_REPO", "jayleekr/hypeprooflab")
    monkeypatch.setenv("CHANGE_IMPACT_SOURCE_TOKEN", "source-reader")
    def run(args, **kwargs):
        assert kwargs["env"]["GH_TOKEN"] == expected
        return subprocess.CompletedProcess(args, 0, "{}", "")
    monkeypatch.setattr(m.subprocess, "run", run)
    m.gh(path, method)


def test_access_diagnostic_does_not_echo_source_or_credentials(monkeypatch):
    def run(args, **_):
        raise subprocess.CalledProcessError(1, args, output="PRIVATE RESPONSE", stderr="private detail (HTTP 403)")
    monkeypatch.setattr(m.subprocess, "run", run)
    with pytest.raises(m.GitHubAccessError) as error:
        m.gh("repos/jayleekr/hypeprooflab/contents/private-filename?ref=abc")
    assert str(error.value) == "GET repos/jayleekr/hypeprooflab/contents: HTTP 403"


@pytest.mark.parametrize("status,expected", [("ahead", True), ("behind", False), ("diverged", False)])
def test_adopted_ancestor_allows_progress_but_unmerged_ref_is_rejected(monkeypatch, status, expected):
    reader = m.Reader()
    monkeypatch.setattr(reader, "resolve", lambda *_: "b" * 40)
    monkeypatch.setattr(m, "gh", lambda path: {"status": status})
    assert reader.adopted("owner/repo", "a" * 40) is expected


def test_main_advancing_keeps_pinned_checkpoint_for_next_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "preflight", lambda _: {})
    after = snap(node("INT-A"))
    monkeypatch.setattr(m, "snapshot", lambda *_: after)
    monkeypatch.setattr(m.Reader, "adopted", lambda *_: True)
    monkeypatch.setattr(m, "pages", lambda *_: [])
    monkeypatch.setattr(m, "sync", lambda *_: None)
    saved = []
    monkeypatch.setattr(m, "upsert", lambda *args: saved.append(args[-1]))
    monkeypatch.setattr("sys.argv", ["impact", "scan", "--apply", "--output", str(tmp_path / "report.json")])
    assert m.main() == 0
    assert checkpoint_json(saved[0])["commits"] == after["commits"]


def test_pr_preview_issue_transport_updates_same_issue_and_preserves_human_text(monkeypatch):
    inventory, calls = [], []
    def api(path, method, payload):
        assert path in {"repos/x/y/issues", "repos/x/y/issues/9"}
        calls.append((path, method, payload))
        return {"number": 9, "html_url": "https://github.com/x/y/issues/9", **payload}
    monkeypatch.setattr(m, "gh", api)
    pr = {"number": 7, "html_url": "https://github.com/x/y/pull/7"}
    first = m.publish_pr_report("x/y", pr, "Head a", "issue", inventory)
    inventory[0]["body"] += "\nReviewer note survives."
    assert m.publish_pr_report("x/y", pr, "Head a", "issue", inventory)["number"] == first["number"]
    assert len(calls) == 1
    updated = m.publish_pr_report("x/y", pr, "Head b", "issue", inventory)
    assert updated["number"] == first["number"]
    assert "Reviewer note survives." in updated["body"]
    assert pr["html_url"] in updated["body"] and "Head b" in updated["body"]
    assert "impact-task:" not in updated["body"]


def test_pr_publication_errors_do_not_silently_switch_transports(monkeypatch):
    calls = []
    def fail(path, method, payload):
        calls.append(path)
        raise m.GitHubAccessError("denied")
    monkeypatch.setattr(m, "gh", fail)
    with pytest.raises(m.GitHubAccessError):
        m.publish_pr_report("x/y", {"number": 7, "html_url": "url"}, "report", "issue", [])
    assert calls == ["repos/x/y/issues"]
    with pytest.raises(ValueError, match="transport"):
        m.publish_pr_report("x/y", {}, "report", "invalid", [])


def test_capped_comparison_splits_and_preserves_rename_and_reverted_paths(monkeypatch):
    a, b, c = "a" * 40, "b" * 40, "c" * 40
    responses = {
        f"{a}...{c}": {"status": "ahead", "files": [{"filename": "partial"}] * 300,
                        "commits": [{"sha": b}, {"sha": c}]},
        f"{a}...{b}": {"status": "ahead", "files": [
            {"filename": "new", "previous_filename": "old"}, {"filename": "reverted"}]},
        f"{b}...{c}": {"status": "ahead", "files": [
            {"filename": "late"}, {"filename": "reverted"}]},
    }
    calls = []
    def api(path):
        calls.append(path)
        return responses[path.split("/compare/")[1]]
    monkeypatch.setattr(m, "gh", api)
    assert m.Reader().changed("x/y", a, c) == ["late", "new", "old", "reverted"]
    assert len(calls) == 3


@pytest.mark.parametrize("response", [
    {"status": "ahead", "files": [{"filename": "partial"}] * 300,
     "commits": [{"sha": "b" * 40}]},
    {"status": "diverged", "files": []},
    {"status": "ahead"},
])
def test_incomplete_or_unsplittable_comparison_still_fails(monkeypatch, response):
    monkeypatch.setattr(m, "gh", lambda _: response)
    with pytest.raises(ValueError):
        m.Reader().changed("x/y", "a" * 40, "b" * 40)


def test_divergent_split_never_returns_partial_paths(monkeypatch):
    a, b, c = "a" * 40, "b" * 40, "c" * 40
    def api(path):
        if path.endswith(f"{a}...{c}"):
            return {"status": "ahead", "files": [{}] * 300, "commits": [{"sha": b}]}
        return {"status": "diverged", "files": [{"filename": "not-complete"}]}
    monkeypatch.setattr(m, "gh", api)
    with pytest.raises(ValueError, match="diverged"):
        m.Reader().changed("x/y", a, c)


def test_comparison_split_budget_is_bounded(monkeypatch):
    calls = []
    def api(path):
        calls.append(path)
        return {"status": "ahead", "files": [{}] * 300,
                "commits": [{"sha": f"{len(calls):040x}"}]}
    monkeypatch.setattr(m, "gh", api)
    with pytest.raises(ValueError, match="limit"):
        m.Reader().changed("x/y", "a" * 40, "b" * 40)
    assert len(calls) == 63


def test_binary_git_github_parity_and_revision_sensitivity(tmp_path, monkeypatch):
    import base64
    import hashlib
    repo = "example/binary"
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args]).decode().strip()
    git("init", "-q")
    manifest = {"version": 1, "repository": repo, "nodes": [
        {"id": "INT-PDF", "stage": "intent", "sources": [{"path": "protocol.pdf"}]}]}
    (tmp_path / "traceability.json").write_text(json.dumps(manifest))
    first = b"%PDF-1.7\n\xff\x00binary-a\n"
    (tmp_path / "protocol.pdf").write_bytes(first)
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "first")
    before = git("rev-parse", "HEAD")
    (tmp_path / "protocol.pdf").write_bytes(first.replace(b"binary-a", b"binary-b"))
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "changed")
    after = git("rev-parse", "HEAD")
    # Working-copy bytes must not replace either pinned source.
    (tmp_path / "protocol.pdf").write_bytes(b"uncommitted")
    def github(path):
        if "/commits/" in path:
            return {"sha": path.rsplit("/", 1)[1]}
        resource, sha = path.split("?ref=")
        file = resource.split("/contents/")[1]
        raw = subprocess.check_output(["git", "-C", str(tmp_path), "show", f"{sha}:{file}"])
        return {"encoding": "base64", "content": base64.b64encode(raw).decode()}
    monkeypatch.setattr(m, "gh", github)
    local, remote = m.Reader({repo: str(tmp_path)}), m.Reader()
    policy = {"repositories": {repo: {"manifest": "traceability.json"}}, "members": [], "canon_owner": "jay"}
    snapshots = []
    for sha in [before, after]:
        assert local.read(repo, sha, "protocol.pdf") == remote.read(repo, sha, "protocol.pdf")
        assert isinstance(remote.read(repo, sha, "protocol.pdf"), m.BinarySource)
        local_snap = m.snapshot(local, policy, {repo: sha})
        assert local_snap == m.snapshot(remote, policy, {repo: sha})
        snapshots.append(local_snap)
    assert json.loads(local.read(repo, before, "protocol.pdf"))["sha256"] == hashlib.sha256(first).hexdigest()
    assert snapshots[0]["nodes"]["INT-PDF"]["revision"] != snapshots[1]["nodes"]["INT-PDF"]["revision"]
    assert m.plan(*snapshots)["tasks"][0]["id"] == "INT-PDF"
    with pytest.raises(ValueError, match="binary source does not support section"):
        m.section(local.read(repo, before, "protocol.pdf"), "## Intent")


@pytest.mark.parametrize("transport", ["git", "github"])
def test_unknown_or_malformed_text_still_fails_utf8(transport, monkeypatch):
    import base64
    raw = b"# Intent\n\xffinvalid-text"
    monkeypatch.setattr(m.Reader, "git", lambda *_: raw)
    monkeypatch.setattr(m, "gh", lambda _: {"encoding": "base64", "content": base64.b64encode(raw).decode()})
    reader = m.Reader({"x/y": "/unused"} if transport == "git" else {})
    for path in ["intent.md", "implementation.py", "unknown.bin"]:
        with pytest.raises(UnicodeDecodeError):
            reader.read("x/y", "a" * 40, path)
    assert isinstance(reader.read("x/y", "a" * 40, "protocol.PDF"), m.BinarySource)


class FakeIssues:
    """In-memory Issues API: POST/PATCH issues and comments, list via `pages`."""

    def __init__(self, repo):
        self.repo, self.issues, self.comments, self.calls = repo, [], {}, []

    def gh(self, path, method="GET", payload=None):
        self.calls.append((path, method, payload))
        if path.endswith("/comments"):
            number = int(path.split("/")[-2])
            if method == "POST":
                self.comments.setdefault(number, []).append(payload["body"])
                return {"html_url": f"https://github.com/{self.repo}/issues/{number}#c"}
            return []
        if method == "POST":
            number = len(self.issues) + 1
            item = {"number": number, "state": "open", "comments": 0, **payload,
                    "html_url": f"https://github.com/{self.repo}/issues/{number}"}
            self.issues.append(item)
            return copy.deepcopy(item)
        item = self.issue(int(path.rsplit("/", 1)[1]))
        item.update(payload)
        return copy.deepcopy(item)

    def pages(self, _path):
        return copy.deepcopy(self.issues)

    def issue(self, number):
        return next(i for i in self.issues if i["number"] == number)


def test_one_adoption_epic_per_repo_is_updated_in_place_and_supersedes_wave_epics(monkeypatch):
    repo = "jayleekr/hypeprooflab"
    api = FakeIssues(repo)
    # A per-wave Epic left by the previous engine version (65 of these were open).
    api.gh(f"repos/{repo}/issues", "POST", {"title": "change-impact: adoption abc",
           "body": m.START + "\n<!-- impact-wave:abc -->\n## Change adoption\n" + m.END})
    monkeypatch.setattr(m, "gh", api.gh)
    monkeypatch.setattr(m, "pages", api.pages)
    policy = {"repositories": {repo: {}}}
    first = snap(node("INT-A"), node("INT-B"))
    m.sync(m.plan({"commits": {}, "nodes": {}}, first), policy)
    second = copy.deepcopy(first)
    second["nodes"]["INT-A"]["revision"] = "new"
    m.sync(m.plan(first, second), policy)
    third = copy.deepcopy(second)
    third["nodes"]["INT-B"]["revision"] = "new"
    m.sync(m.plan(second, third), policy)
    epics = [i for i in api.issues if m.EPIC_MARKER in i["body"]]
    assert len(epics) == 1 and epics[0]["state"] == "open"
    assert epics[0]["title"] == "change-impact: adoption"
    assert "INT-B" in epics[0]["body"] and "INT-A" not in epics[0]["body"]  # latest round
    legacy = api.issue(1)
    assert legacy["state"] == "closed" and legacy["state_reason"] == "not_planned"
    assert len(api.comments[1]) == 1 and epics[0]["html_url"] in api.comments[1][0]
    tasks = [i for i in api.issues if "impact-task:" in i["body"]]
    assert len(tasks) == 2
    assert all(epics[0]["html_url"] in i["body"] for i in tasks)  # one stable Epic URL


def test_finished_pr_previews_close_and_open_ones_stay(monkeypatch):
    repo = "jayleekr/hypeprooflab"
    api = FakeIssues(repo)
    for number in (5, 6, 7):
        api.gh(f"repos/{repo}/issues", "POST", {"title": f"change-impact: PR #{number} preview",
               "body": m.START + f"\n<!-- impact-pr-preview:{number} -->\n" + m.END})
    api.issue(3)["state"] = "closed"  # a person already closed #7's preview
    monkeypatch.setattr(m, "gh", api.gh)
    # PR 6 is open but beyond max_prs_per_repo: its preview must survive the slice.
    assert m.close_finished_previews(repo, api.issues, {6, 8}) == [1]
    assert api.issue(1)["state"] == "closed" and "PR #5" in api.comments[1][0]
    assert api.issue(2)["state"] == "open" and 2 not in api.comments
    assert 3 not in api.comments  # already closed: no noise


def test_pr_reports_close_previews_only_when_publishing(monkeypatch):
    repo = "jayleekr/hypeprooflab"
    preview = {"number": 1, "state": "open", "body": "<!-- impact-pr-preview:5 -->"}
    seen = []
    def pages(path):
        if "/pulls" in path:
            return [{"number": 6, "base": {"ref": "dev"}, "head": {"repo": {"full_name": repo}}}]
        return [preview]
    monkeypatch.setattr(m, "pages", pages)
    monkeypatch.setattr(m, "close_finished_previews", lambda *args: seen.append(args[1:]))
    policy = {"repositories": {repo: {}}, "max_prs_per_repo": 0, "pr_report_transport": "issue"}
    m.pr_reports(None, policy, None, False, True)
    assert seen == [([preview], {6})]  # the full open list, not the max_prs slice
    seen.clear()
    m.pr_reports(None, policy, None, False, False)  # a dry run never closes anything
    assert seen == []


def status_issue(number, nid, rev, target, comments):
    return {"number": number, "comments": comments, "state": "open",
            "html_url": f"https://github.com/x/y/issues/{number}",
            "body": f"<!-- impact-task:{nid} -->\nStage: `intent` · revision: `{rev}`\n"
                    f"Target revision: `{target}`\n"}


def test_status_fetches_comments_only_for_resolvable_issues(monkeypatch):
    rev, target, stale = "1" * 64, "2" * 64, "3" * 64
    after = {"nodes": {f"INT-{c}": {"owner": "owner", "stage": "intent", "revision": target} for c in "ABCD"}}
    issues = [status_issue(1, "INT-A", rev, target, 0),   # no comment: cannot resolve
              status_issue(2, "INT-B", rev, stale, 3),    # stale body: cannot resolve
              status_issue(3, "INT-C", rev, target, 2),   # resolved
              status_issue(4, "INT-D", rev, target, 1)]   # commented, not resolved
    fetched = []
    good = {"user": {"login": "owner"}, "html_url": "c", "body": f"/impact-resolve {rev} no-impact " + "x" * 30}
    def pages(path):
        if path.endswith("/comments"):
            fetched.append(path)
            return [good] if "/3/" in path else []
        return issues
    monkeypatch.setattr(m, "pages", pages)
    pending, tracked = m.adoption_status({"repositories": {"x/y": {}}, "ownership_triage": []}, after)
    assert sorted(fetched) == ["repos/x/y/issues/3/comments", "repos/x/y/issues/4/comments"]
    assert sorted(pending) == [f"https://github.com/x/y/issues/{n}" for n in (1, 2, 4)]
    assert tracked == {"INT-A", "INT-B", "INT-C", "INT-D"}


def test_status_and_idle_scan_skip_the_second_snapshot_when_nothing_moved(monkeypatch, tmp_path):
    commits = {"jayleekr/hypeprooflab": "a" * 40, "jayleekr/hypeproof-studio": "b" * 40,
               "jayleekr/hypeproof-harness": "c" * 40}
    after = {**snap(node("PH-A", stage="philosophy")), "commits": commits}
    calls = []
    def snapshot(_reader, _policy, refs):
        calls.append(refs)
        return after
    monkeypatch.setattr(m, "snapshot", snapshot)
    checkpoint = {"body": "<!-- impact-checkpoint:v1 -->\n```json\n" + json.dumps({"commits": commits}) + "\n```"}
    monkeypatch.setattr(m, "pages", lambda path: [checkpoint] if "hypeproof-harness/issues" in path else [])
    monkeypatch.setattr(m, "adoption_status", lambda *_: ([], {"PH-A"}))
    output = tmp_path / "status.json"
    monkeypatch.setattr("sys.argv", ["impact", "status", "--output", str(output)])
    assert m.main() == 0
    assert len(calls) == 1
    assert json.loads(output.read_text())["complete"] is True


def test_content_root_flag_feeds_blob_reads_only_and_stays_in_scope(monkeypatch):
    seen = []
    def snapshot(reader, *_):
        seen.append((reader.roots, reader.content_roots))
        raise ValueError("stop after wiring")
    monkeypatch.setattr(m, "snapshot", snapshot)
    monkeypatch.setattr("sys.argv", ["impact", "report", "--base", "jayleekr/hypeprooflab=main",
                                     "--content-root", "jayleekr/hypeprooflab=/src/lab"])
    with pytest.raises(ValueError, match="stop"):
        m.main()
    assert seen == [({}, {"jayleekr/hypeprooflab": "/src/lab"})]
    monkeypatch.setattr("sys.argv", ["impact", "report", "--base", "jayleekr/hypeprooflab=main",
                                     "--content-root", "someone/else=/src/other"])
    with pytest.raises(ValueError, match="outside change-impact scope"):
        m.main()
