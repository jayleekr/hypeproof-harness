#!/usr/bin/env python3
"""Control-group proof that the escalation validator actually bites.

Builds throwaway queue files and asserts the validator's EXIT CODE, so the
distinction is demonstrated rather than asserted:
  * a well-formed queue whose pending cases all have owners  -> 0
  * a pending case missing its human_owner                   -> 1  (the block)
  * a vacuous / malformed queue                              -> 2  (fail-closed)
Also exercises add/resolve round-trips (including the refusals).

Run: python3 tests/escalation/test_escalation.py   (exit 0 = all controls held)
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
CLI_PY = HERE.parents[2] / "scripts" / "escalation" / "escalation.py"

spec = importlib.util.spec_from_file_location("escalation", CLI_PY)
esc = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(esc)

RESULTS: list[tuple[str, bool]] = []


def check(name: str, got: int, want: int) -> None:
    ok = got == want
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: exit {got} (want {want})")


def write(tmp: Path, text: str) -> Path:
    q = tmp / "queue.yaml"
    q.write_text(text, encoding="utf-8")
    return q


GOOD = """schema_version: 1
cases:
  - case_id: ESC-0001
    reason: an ambiguous thing
    human_owner: jay
    status: pending
    created: "2026-07-22T00:00:00Z"
    resolution: ""
"""


def run():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)

        q = write(tmp, GOOD)
        check("well-formed pending case (owner present) passes", esc.main(["--queue", str(q)]), 0)

        # pending case missing human_owner -> content violation (exit 1)
        q = write(tmp, GOOD.replace("    human_owner: jay\n", ""))
        check("pending case missing human_owner is rejected", esc.main(["--queue", str(q)]), 1)

        # pending missing reason -> exit 1
        q = write(tmp, GOOD.replace("    reason: an ambiguous thing\n", ""))
        check("pending case missing reason is rejected", esc.main(["--queue", str(q)]), 1)

        # resolved case with empty resolution -> exit 1
        q = write(tmp, GOOD.replace("status: pending", "status: resolved"))
        check("resolved case with empty resolution is rejected", esc.main(["--queue", str(q)]), 1)

        # empty queue -> fail-closed exit 2
        q = write(tmp, "schema_version: 1\ncases: []\n")
        check("empty queue fails closed", esc.main(["--queue", str(q)]), 2)

        # missing queue file -> exit 2
        check("missing queue file fails closed",
              esc.main(["--queue", str(tmp / "nope.yaml")]), 2)

        # duplicate case_id -> exit 2
        q = write(tmp, GOOD + GOOD.split("cases:\n", 1)[1])
        check("duplicate case_id fails closed", esc.main(["--queue", str(q)]), 2)

        # bad status -> exit 2
        q = write(tmp, GOOD.replace("status: pending", "status: maybe"))
        check("out-of-enum status fails closed", esc.main(["--queue", str(q)]), 2)

        # add: refuses empty owner
        q = write(tmp, GOOD)
        check("add refuses empty --human-owner",
              esc.main(["--queue", str(q), "add", "--reason", "x", "--human-owner", ""]), 1)

        # add: happy path, then the new case validates and is pending-owned
        q = write(tmp, GOOD)
        rc = esc.main(["--queue", str(q), "add", "--reason", "new ambiguous case",
                       "--human-owner", "legal-review", "--evidence", "e1"])
        check("add appends a pending case", rc, 0)
        check("queue still validates after add", esc.main(["--queue", str(q)]), 0)
        txt = q.read_text(encoding="utf-8")
        RESULTS.append(("added case got ESC-0002 id", "ESC-0002" in txt))
        print(f"[{'PASS' if 'ESC-0002' in txt else 'FAIL'}] added case got ESC-0002 id")

        # resolve: refuses empty resolution
        check("resolve refuses empty --resolution",
              esc.main(["--queue", str(q), "resolve", "ESC-0001", "--resolution", ""]), 1)

        # resolve: happy path, then it must carry the resolution
        check("resolve closes a case",
              esc.main(["--queue", str(q), "resolve", "ESC-0001", "--resolution", "decided X"]), 0)
        check("queue still validates after resolve", esc.main(["--queue", str(q)]), 0)


def main() -> int:
    run()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} controls held.")
    if failed:
        print("FAILED CONTROLS:\n  " + "\n  ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
