#!/usr/bin/env python3
"""Explicit operational probe: one reusable test issue per approved repository.

No production impact-task/checkpoint markers or source excerpts are written. All
probe issues are closed in finally. Run only on an explicitly dispatched operator
workflow or authorized local session, never on PR events.
"""
import argparse
import json
from pathlib import Path
import time

import impact


def run(policy):
    proof = impact.preflight(policy)
    results, cleanup = [], []
    marker = "<!-- impact-operational-probe:v1 -->"
    run_id = str(time.time_ns())
    try:
        for repo in policy["repositories"]:
            inventory = impact.pages(f"repos/{repo}/issues?state=all")
            block = f"{impact.START}\n{marker}\nOperational test only. Run `{run_id}`.\n{impact.END}"
            issue = impact.upsert(repo, inventory, marker, "change-impact: operational API probe", block)
            cleanup.append((repo, issue["number"]))
            note = "\n\nPreservation fixture: operator text outside the managed region."
            current = impact.gh(f"repos/{repo}/issues/{issue['number']}")
            if note not in current["body"]:
                current = impact.gh(f"repos/{repo}/issues/{issue['number']}", "PATCH", {"body": current["body"] + note})
            refreshed = [current]
            changed = block.replace("Operational test only.", "Operational update verified; not adoption evidence.")
            impact.upsert(repo, refreshed, marker, "unused", changed)
            # Retry after a completed write must not duplicate/rewrite or erase operator text.
            retried = impact.upsert(repo, refreshed, marker, "unused", changed)
            check = impact.gh(f"repos/{repo}/issues/{issue['number']}")
            assert retried["number"] == issue["number"] and note in check["body"]
            assert changed in check["body"]
            comment = impact.gh(f"repos/{repo}/issues/{issue['number']}/comments", "POST",
                                {"body": f"Operational probe `{run_id}`: create/read/update/retry/preservation passed. This is synthetic API evidence, not a product review approval."})
            results.append({"repo": repo, "issue": issue["html_url"], "comment": comment["html_url"],
                            "create_update_retry": "pass", "human_text_preserved": True})
    finally:
        errors = []
        for repo, number in cleanup:
            try:
                impact.gh(f"repos/{repo}/issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
            except Exception:
                errors.append(f"{repo}#{number}")
        if errors:
            raise RuntimeError("probe cleanup required: " + ", ".join(errors))
    return {"preflight": proof, "probes": results, "all_closed": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="impact-operational-proof.json")
    args = parser.parse_args()
    policy = json.loads((impact.ROOT / "policy/change-impact.json").read_text())
    proof = run(policy)
    Path(args.output).write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"probes": len(proof["probes"]), "all_closed": proof["all_closed"]}))
