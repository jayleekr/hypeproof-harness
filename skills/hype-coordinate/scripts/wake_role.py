#!/usr/bin/env python3
"""Safely dispatch a GitHub work packet to an idle HypeProof cmux role tab."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass


WORKSPACE_TITLE = "studio-testing"
ROLE_CONFIG = {
    "b": ("claude-2-impl", "/hype-studio"),
    "c": ("claude-3-impl", "/hype-chalk"),
    "x1": ("codex-testing", "$hype-intent"),
    "x2": ("codex-2", "$hype-verify"),
}
WORK_URL = re.compile(
    r"https://github\.com/jayleekr/"
    r"(?:hypeproof-harness|hypeproof-studio|hypeprooflab)/"
    r"(?:issues|pull)/[0-9]+\Z"
)
PACKET = re.compile(r"[A-Za-z0-9._-]+\Z")
WORKSPACE_LINE = re.compile(
    r"workspace (workspace:[0-9]+) ([0-9A-F-]+) \"([^\"]+)\""
)
SURFACE_LINE = re.compile(
    r"surface (surface:[0-9]+) ([0-9A-F-]+).* \"([^\"]+)\""
)
PROMPT_LINE = re.compile(r"^\s*[❯›]\s*(.*)$")


@dataclass(frozen=True)
class Surface:
    workspace_ref: str
    workspace_id: str
    surface_ref: str
    surface_id: str
    title: str


def cmux(*args: str) -> str:
    proc = subprocess.run(
        ["cmux", *args], text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "cmux failed")
    return proc.stdout


def find_surface(title: str) -> Surface:
    current: tuple[str, str, str] | None = None
    for line in cmux("tree", "--all", "--id-format", "both").splitlines():
        workspace = WORKSPACE_LINE.search(line)
        if workspace:
            current = workspace.groups()
            continue
        surface = SURFACE_LINE.search(line)
        if current and current[2] == WORKSPACE_TITLE and surface:
            surface_ref, surface_id, surface_title = surface.groups()
            if surface_title == title:
                return Surface(current[0], current[1], surface_ref, surface_id, title)
    raise RuntimeError(f"cmux surface {title!r} not found in {WORKSPACE_TITLE!r}")


def read_screen(surface: Surface, lines: int = 30) -> str:
    return cmux(
        "read-screen",
        "--workspace", surface.workspace_id,
        "--surface", surface.surface_id,
        "--scrollback",
        "--lines", str(lines),
    )


def assert_idle(screen: str) -> None:
    tail = screen.splitlines()[-12:]
    if any("esc to interrupt" in line.lower() for line in tail):
        raise RuntimeError("target role is running")
    prompts = [
        (index, match.group(1).replace("\u00a0", " ").strip())
        for index, line in enumerate(tail)
        if (match := PROMPT_LINE.match(line))
    ]
    if not prompts:
        raise RuntimeError("target idle prompt was not observed")
    index, prompt = prompts[-1]
    if "Ask Codex to do anything" in prompt:
        prompt = ""
    if any("done " in line for line in tail[index + 1:]):
        prompt = ""
    if prompt and any(previous.startswith(prompt) for _, previous in prompts[:-1]):
        # Claude can render a dim history suggestion in an empty prompt. cmux's
        # plain-text screen does not preserve the dim styling, so recognize the
        # suggestion by its exact prefix of a completed earlier prompt.
        prompt = ""
    if prompt:
        raise RuntimeError("target prompt contains unsent text")


def send(surface: Surface, message: str) -> None:
    # Codex treats a newline embedded in `cmux send` as multiline prompt text.
    # Send the complete text first, then a targeted Enter key event. Both calls
    # are synchronous and target the same freshly discovered surface.
    target = ("--workspace", surface.workspace_id, "--surface", surface.surface_id)
    cmux("send", *target, "--", message)
    cmux("send-key", *target, "enter")


def running_observed(screen: str) -> bool:
    return any(
        "esc to interrupt" in line.lower()
        for line in screen.splitlines()[-12:]
    )


def wait_for_start(surface: Surface, timeout: float) -> None:
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        if running_observed(read_screen(surface, lines=20)):
            return
        time.sleep(0.2)
    raise RuntimeError("dispatch was typed but target work did not start")


def ack_observed(screen: str, ack: str) -> bool:
    answer = re.compile(rf"^\s*[^A-Za-z0-9_]*{re.escape(ack)}\s*$")
    return any(
        not PROMPT_LINE.match(line) and bool(answer.fullmatch(line))
        for line in screen.splitlines()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(ROLE_CONFIG), required=True)
    parser.add_argument("--packet")
    parser.add_argument("--work-url")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--ack-timeout", type=int, default=30)
    parser.add_argument("--start-timeout", type=float, default=5.0)
    args = parser.parse_args()

    try:
        title, invocation = ROLE_CONFIG[args.role]
        surface = find_surface(title)
        assert_idle(read_screen(surface))

        ack = None
        if args.test:
            ack = f"WAKE_ACK_{args.role.upper()}_{int(time.time())}"
            message = (
                "WAKE TEST from the deterministic coordinator dispatcher. "
                "Do not read repositories or modify files. "
                f"Reply exactly {ack} and return to idle."
            )
        else:
            if not args.packet or not PACKET.fullmatch(args.packet):
                raise RuntimeError("--packet must use letters, numbers, dot, dash, or underscore")
            if not args.work_url or not WORK_URL.fullmatch(args.work_url):
                raise RuntimeError("--work-url must be an allowed HypeProof GitHub issue or PR")
            message = (
                f"{invocation} Coordinator dispatch packet {args.packet}. "
                f"Read and execute {args.work_url}. Acknowledge the real session "
                "and branch in the GitHub record, work through tests and handoff, "
                "use English for engineering work, and report to the user in Korean."
            )

        result = {
            "status": "ready" if not args.apply else "submitted",
            "role": args.role,
            "workspace": surface.workspace_id,
            "surface": surface.surface_id,
            "title": surface.title,
        }
        if not args.apply:
            print(json.dumps(result, separators=(",", ":")))
            return 0

        send(surface, message)
        if ack:
            deadline = time.monotonic() + max(1, args.ack_timeout)
            while time.monotonic() < deadline:
                screen = read_screen(surface, lines=20)
                if ack_observed(screen, ack):
                    try:
                        assert_idle(screen)
                    except RuntimeError:
                        pass
                    else:
                        result["status"] = "acknowledged"
                        result["ack"] = ack
                        print(json.dumps(result, separators=(",", ":")))
                        return 0
                time.sleep(1)
            raise RuntimeError(f"dispatch sent but {ack} was not observed")

        wait_for_start(surface, args.start_timeout)
        result["status"] = "started"
        result["accepted"] = False
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
