#!/usr/bin/env python3
"""Plan creation of a new HypeProof repo from a governance profile.

Actual repo creation is deliberately not implemented yet; new repos should go
through a policy PR first so the inventory remains canonical.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import load_policy, validate_policy  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args(argv)

    policy = load_policy()
    findings = validate_policy(policy)
    if findings:
        print(json.dumps({"status": "policy-invalid", "findings": [f.as_dict() for f in findings]}, indent=2))
        return 4
    if args.profile not in policy["profiles"]:
        print(f"unknown profile: {args.profile}", file=sys.stderr)
        return 4

    owner, _, name = args.repo.partition("/")
    if not owner or not name:
        print("--repo must be owner/name", file=sys.stderr)
        return 4

    print(json.dumps({
        "status": "planned",
        "repo": args.repo,
        "profile": args.profile,
        "steps": [
            "create GitHub repo",
            "seed default branch",
            "render common templates",
            "apply collaborators",
            "apply security/actions settings",
            "apply branch protection",
            "open required-secrets checklist issue",
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
