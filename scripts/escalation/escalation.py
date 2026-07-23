#!/usr/bin/env python3
"""Human escalation queue — CLI and fail-closed validator.

WHAT THIS IS
------------
An executable workflow over policy/escalation/queue.yaml, so an ambiguous case
becomes a first-class, owned work item instead of vanishing into an UNKNOWN
bucket. It answers one question as a gate:

    "Does every pending escalation case have a human owner, a creation time,
     and a reason — i.e. is it actually routed to a person?"

The most common way an escalation path fails is by existing on paper while no
one ever looks at it. `validate` makes "is this routed to a human" measurable
(it prints the pending count and rejects any pending case missing its owner),
rather than trusting that someone read a paragraph.

COMMANDS
--------
  validate  (default)  Fail closed unless every pending case has human_owner,
                       created, reason (and resolved cases have a resolution).
                       Prints the examined + pending counts. Exit 0/1/2.
  list [--status S]    Print cases (optionally filtered by status).
  show CASE_ID         Print one case.
  add ...              Append a new case (auto case_id + created); requires
                       --reason and --human-owner, else it refuses.
  resolve CASE_ID --resolution TEXT
                       Mark a case resolved; refuses an empty resolution.

FAIL-CLOSED CONTRACT (validate, exit 2 = could not evaluate; never silent pass)
-------------------------------------------------------------------------------
  * queue file missing, unreadable, or not valid YAML
  * queue declares no cases (a queue that holds nothing is not "all clear")
  * a case is missing case_id or carries a duplicate case_id
  * a case has a status outside {pending, resolved}
validate exits 1 (not 2) when the queue is well-formed but a case is
incomplete: a pending case missing human_owner/created/reason, or a resolved
case with an empty resolution. Those are content violations a human must fix,
distinct from "could not evaluate".

No personal data is stored or printed — human_owner is a role, cases carry
references/counts/paths only.

Usage:
    escalation.py                        # validate the default queue
    escalation.py --queue path/to.yaml validate
    escalation.py list --status pending
    escalation.py show ESC-0003
    escalation.py add --reason "..." --human-owner jay [--evidence x --evidence y]
    escalation.py resolve ESC-0002 --resolution "confirmed fabricated brand"
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: pyyaml required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_ERROR = 2

CHECK_NAME = "human escalation queue"
VALID_STATUS = {"pending", "resolved"}
# Fields a PENDING case must have filled for the routing to be real.
PENDING_REQUIRED = ("human_owner", "created", "reason")

DEFAULT_QUEUE = Path(__file__).resolve().parents[2] / "policy" / "escalation" / "queue.yaml"


class QueueError(Exception):
    """Raised when the queue cannot be evaluated at all (fail-closed → exit 2)."""


def load_queue(path: Path) -> dict:
    if not path.is_file():
        raise QueueError(f"queue not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise QueueError(f"queue is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise QueueError("queue top level is not a mapping")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise QueueError("queue declares no cases (an empty queue is not 'all "
                         "clear' — it means nothing was recorded)")
    return data


def index_cases(cases: list) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            raise QueueError(f"case #{i} is not a mapping")
        cid = str(c.get("case_id", "")).strip()
        if not cid:
            raise QueueError(f"case #{i} is missing case_id")
        if cid in by_id:
            raise QueueError(f"duplicate case_id: {cid}")
        status = str(c.get("status", "")).strip()
        if status not in VALID_STATUS:
            raise QueueError(f"case {cid}: status '{status}' not in "
                             f"{sorted(VALID_STATUS)}")
        by_id[cid] = c
    return by_id


def cmd_validate(path: Path) -> int:
    try:
        data = load_queue(path)
        by_id = index_cases(data["cases"])
    except QueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Failing closed: the escalation queue could not be evaluated, so "
              "it must not report all-clear.", file=sys.stderr)
        return EXIT_ERROR

    pending = [c for c in by_id.values() if c["status"] == "pending"]
    resolved = [c for c in by_id.values() if c["status"] == "resolved"]
    violations: list[str] = []

    for cid, c in sorted(by_id.items()):
        if c["status"] == "pending":
            for field in PENDING_REQUIRED:
                if not str(c.get(field, "")).strip():
                    violations.append(
                        f"{cid}: pending case missing '{field}' — it is not "
                        "routed to a human")
        elif c["status"] == "resolved":
            if not str(c.get("resolution", "")).strip():
                violations.append(
                    f"{cid}: resolved case has an empty resolution — a case is "
                    "not closed without recording how")

    print(f"check: {CHECK_NAME}")
    print(f"cases examined: {len(by_id)}")
    print(f"pending: {len(pending)}   resolved: {len(resolved)}")

    if violations:
        print(f"\nFAIL: {len(violations)} case(s) are incomplete.",
              file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return EXIT_VIOLATION

    print(f"\nPASS: all {len(by_id)} case(s) well-formed; "
          f"{len(pending)} pending case(s) each have an owner.")
    return EXIT_OK


def cmd_list(path: Path, status: "str | None") -> int:
    try:
        data = load_queue(path)
        by_id = index_cases(data["cases"])
    except QueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    shown = 0
    for cid, c in sorted(by_id.items()):
        if status and c["status"] != status:
            continue
        shown += 1
        reason = " ".join(str(c.get("reason", "")).split())
        if len(reason) > 100:
            reason = reason[:97] + "..."
        print(f"{cid}  [{c['status']}]  owner={c.get('human_owner', '-')}")
        print(f"    {reason}")
    print(f"\n{shown} case(s)" + (f" with status={status}" if status else ""))
    return EXIT_OK


def cmd_show(path: Path, case_id: str) -> int:
    try:
        data = load_queue(path)
        by_id = index_cases(data["cases"])
    except QueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    c = by_id.get(case_id)
    if not c:
        print(f"ERROR: no such case_id: {case_id}", file=sys.stderr)
        return EXIT_VIOLATION
    print(yaml.safe_dump(c, allow_unicode=True, sort_keys=False))
    return EXIT_OK


def _next_case_id(by_id: dict[str, dict]) -> str:
    nums = []
    for cid in by_id:
        if cid.startswith("ESC-"):
            try:
                nums.append(int(cid.split("-", 1)[1]))
            except ValueError:
                pass
    return f"ESC-{(max(nums) + 1 if nums else 1):04d}"


def _dump_queue(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")


def cmd_add(path: Path, args: argparse.Namespace) -> int:
    if not args.reason.strip():
        print("ERROR: --reason must not be empty", file=sys.stderr)
        return EXIT_VIOLATION
    if not args.human_owner.strip():
        print("ERROR: --human-owner must not be empty (a case with no owner is "
              "exactly what this queue exists to prevent)", file=sys.stderr)
        return EXIT_VIOLATION
    try:
        data = load_queue(path)
        by_id = index_cases(data["cases"])
    except QueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    cid = _next_case_id(by_id)
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    case = {
        "case_id": cid,
        "reason": args.reason.strip(),
        "evidence": list(args.evidence or []),
        "classification_candidates": list(args.candidate or []),
        "risk_if_false_negative": args.risk_fn or "",
        "risk_if_false_positive": args.risk_fp or "",
        "recommended_action": args.recommended or "",
        "human_owner": args.human_owner.strip(),
        "status": "pending",
        "created": now,
        "resolution": "",
    }
    data["cases"].append(case)
    _dump_queue(path, data)
    print(f"added {cid} (owner={case['human_owner']}, created={now})")
    return EXIT_OK


def cmd_resolve(path: Path, case_id: str, resolution: str) -> int:
    if not resolution.strip():
        print("ERROR: --resolution must not be empty (a case is not closed "
              "without recording how it was resolved)", file=sys.stderr)
        return EXIT_VIOLATION
    try:
        data = load_queue(path)
        by_id = index_cases(data["cases"])
    except QueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    c = by_id.get(case_id)
    if not c:
        print(f"ERROR: no such case_id: {case_id}", file=sys.stderr)
        return EXIT_VIOLATION
    c["status"] = "resolved"
    c["resolution"] = resolution.strip()
    _dump_queue(path, data)
    print(f"resolved {case_id}")
    return EXIT_OK


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=CHECK_NAME)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE,
                        help="path to the escalation queue YAML")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("validate", help="fail closed on incomplete cases (default)")

    p_list = sub.add_parser("list", help="list cases")
    p_list.add_argument("--status", choices=sorted(VALID_STATUS))

    p_show = sub.add_parser("show", help="show one case")
    p_show.add_argument("case_id")

    p_add = sub.add_parser("add", help="append a new pending case")
    p_add.add_argument("--reason", required=True)
    p_add.add_argument("--human-owner", required=True)
    p_add.add_argument("--evidence", action="append")
    p_add.add_argument("--candidate", action="append",
                       help="a classification candidate (repeatable)")
    p_add.add_argument("--risk-fn", help="risk if false negative")
    p_add.add_argument("--risk-fp", help="risk if false positive")
    p_add.add_argument("--recommended", help="recommended action")

    p_res = sub.add_parser("resolve", help="mark a case resolved")
    p_res.add_argument("case_id")
    p_res.add_argument("--resolution", required=True)

    args = parser.parse_args(argv)
    queue = args.queue

    if args.command in (None, "validate"):
        return cmd_validate(queue)
    if args.command == "list":
        return cmd_list(queue, args.status)
    if args.command == "show":
        return cmd_show(queue, args.case_id)
    if args.command == "add":
        return cmd_add(queue, args)
    if args.command == "resolve":
        return cmd_resolve(queue, args.case_id, args.resolution)
    parser.error(f"unknown command: {args.command}")
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
