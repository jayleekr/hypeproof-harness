#!/usr/bin/env python3
"""AI PR reviewer — the automation arm of the hype-review harness.

hype-review defines *how* a HypeProof PR should be reviewed: eight role lenses,
path-based risk detection (security/deploy/data/governance), and a three-way
verdict (Approve / Comment / Request Changes) where a security/data/deploy
blocker can never be approved away. This script runs that judgement on a PR with
Claude and *submits the review* — the piece a human used to do by hand.

Design contract (fail-safe, never a rubber stamp):
  - The lenses and risk rules are REUSED from scripts/hype-review/review.py, so
    the bot and a human reviewer apply the exact same criteria.
  - APPROVE is only ever submitted when the model returns decision=approve AND
    reports zero blockers. Any blocker → REQUEST_CHANGES. Any error talking to
    the model → COMMENT (never a fake approval, never a silent pass).
  - It refuses to review its own authored PR (a reviewer must differ from the
    author for the approval to count and to mean anything).

Usage:
  review_pr.py --repo owner/name --pr 123            # review + submit
  review_pr.py --repo owner/name --pr 123 --dry-run  # print verdict, submit nothing

Env:
  ANTHROPIC_API_KEY   required to actually review (absent → posts a "not
                      provisioned" comment and exits 0, so the gate degrades
                      loudly-but-safely instead of blocking every PR).
  AI_REVIEW_MODEL     model id, default claude-sonnet-5.
  GH_TOKEN            used by `gh` to fetch the PR and submit the review; give it
                      a NON-author identity (a reviewer bot/App) for the approval
                      to count toward branch protection.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Reuse the single source of truth for lenses + risk rules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hype-review"))
import review as hr  # noqa: E402  (PATH_RISK_RULES, ROLE_LENSES, RISK_LENSES, BASE_QUESTIONS)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("AI_REVIEW_MODEL", "claude-sonnet-5")
MAX_DIFF_CHARS = 60_000  # keep the request bounded; note truncation in the prompt
BLOCKING_LENSES = {"security", "data", "deploy", "governance"}


def gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], text=True, capture_output=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def detect_risks(files: list[str]) -> list[str]:
    """Risk lenses triggered by the changed paths (same rules as hype-review)."""
    hits: list[str] = []
    for pattern, risk in hr.PATH_RISK_RULES:
        if any(re.search(pattern, f, re.IGNORECASE) for f in files) and risk not in hits:
            hits.append(risk)
    return hits


def lens_questions(risks: list[str]) -> list[str]:
    qs = list(hr.BASE_QUESTIONS)
    for risk in risks:
        lens = hr.RISK_LENSES.get(risk) or hr.ROLE_LENSES.get(risk)
        if lens:
            qs.extend(lens.questions)
    # de-dup, preserve order
    seen: set[str] = set()
    return [q for q in qs if not (q in seen or seen.add(q))]


SYSTEM_PROMPT = """\
You are the HypeProof AI PR reviewer. Apply the hype-review criteria exactly.

VERDICT RULES (three-way, same as a human reviewer):
- APPROVE only if ALL hold: the change's stated intent matches the actual diff;
  the author's tests/screenshots directly prove the core risk; any remaining
  opinion is NOT a merge blocker.
- COMMENT if you have a context question or suggestion that an author reply
  could resolve — not a blocker.
- REQUEST_CHANGES if there is a blocker that could break security, data
  isolation, deployment, or a user-facing feature. A security / data / deploy /
  governance blocker can NEVER be approved away, even if everything else is fine.

Be concrete: a blocker cites a file and (if you can) a line, and states the
failure it causes. Do not invent problems to look thorough; a clean, well-tested
change should be approved. You are one reviewer adding lens questions the team
might miss, not the sole gate — required CI checks still run independently.

Return ONLY a JSON object, no prose, no markdown fence:
{
  "decision": "approve" | "comment" | "request_changes",
  "summary": "<=3 sentences: what this PR does and your overall read",
  "blockers": [{"file": "path", "line": <int or null>, "issue": "what breaks and why"}],
  "questions": ["non-blocking questions/suggestions, each one line"]
}
"""


def build_user_prompt(pr: dict, files: list[str], risks: list[str], diff: str) -> str:
    qs = "\n".join(f"- {q}" for q in lens_questions(risks))
    truncated = "\n\n[diff truncated for length]" if len(diff) >= MAX_DIFF_CHARS else ""
    return f"""\
PR: {pr['url']}
Title: {pr['title']}
Author: {pr['author']['login']}
Risk lenses detected from changed paths: {', '.join(risks) or 'none'}

Body:
{(pr.get('body') or '(none)')[:4000]}

Changed files ({len(files)}):
{chr(10).join('- ' + f for f in files[:100])}

Apply these lens questions while reviewing:
{qs}

Unified diff:
```diff
{diff[:MAX_DIFF_CHARS]}{truncated}
```
"""


def call_claude(system: str, user: str, model: str, api_key: str) -> dict:
    payload = json.dumps({
        "model": model,
        "max_tokens": 2000,
        # Verdict is a bounded structured task; extended thinking (default-on for
        # some Claude 5 models) would otherwise spend the whole token budget and
        # return no text. Disable it so the JSON answer is produced.
        "thinking": {"type": "disabled"},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    text = "".join(
        part.get("text", "") for part in data.get("content", []) if part.get("type") == "text"
    )
    return parse_verdict(text)


def parse_verdict(text: str) -> dict:
    """Extract the JSON verdict, tolerating stray prose or a ```json fence."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON object in model output: {text[:200]}")
    obj = json.loads(text[start : end + 1])
    obj.setdefault("blockers", [])
    obj.setdefault("questions", [])
    obj.setdefault("summary", "")
    if obj.get("decision") not in {"approve", "comment", "request_changes"}:
        raise ValueError(f"bad decision: {obj.get('decision')!r}")
    return obj


def enforce_safety(verdict: dict) -> dict:
    """A verdict with blockers can never be an approval (fail-safe)."""
    if verdict["blockers"] and verdict["decision"] == "approve":
        verdict["decision"] = "request_changes"
        verdict.setdefault("_downgraded", True)
    return verdict


def render_body(verdict: dict, risks: list[str]) -> str:
    lines = ["## 🤖 AI 리뷰 (hype-review lens)", ""]
    if risks:
        lines.append(f"감지된 위험 관점: {', '.join('`' + r + '`' for r in risks)}")
        lines.append("")
    lines.append(verdict["summary"])
    if verdict.get("_downgraded"):
        lines += ["", "> ⚠️ blocker가 있어 approve → request_changes로 강등됨."]
    if verdict["blockers"]:
        lines += ["", "### ❌ Blocker (머지 전 해결 필요)"]
        for b in verdict["blockers"]:
            loc = b.get("file", "")
            if b.get("line"):
                loc += f":{b['line']}"
            lines.append(f"- **{loc}** — {b.get('issue', '')}")
    if verdict["questions"]:
        lines += ["", "### 💬 확인/제안 (blocker 아님)"]
        lines += [f"- {q}" for q in verdict["questions"]]
    lines += ["", "---", "*hype-review 기준 자동 적용 · required CI 체크는 별도로 강제됩니다.*"]
    return "\n".join(lines)


GH_EVENT = {"approve": "APPROVE", "request_changes": "REQUEST_CHANGES", "comment": "COMMENT"}


def _post_review(repo: str, pr_number: int, event: str, body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", "api", "--method", "POST",
         f"repos/{repo}/pulls/{pr_number}/reviews",
         "-f", f"event={event}", "-f", f"body={body}"],
        text=True, capture_output=True,
    )


def submit_review(repo: str, pr_number: int, verdict: dict, body: str) -> None:
    event = GH_EVENT[verdict["decision"]]
    res = _post_review(repo, pr_number, event, body)
    if res.returncode == 0:
        return
    # GitHub forbids the GITHUB_TOKEN (github-actions[bot]) from submitting an
    # APPROVE — only a real reviewer identity (HYPEPROOF_REVIEWER_TOKEN) can.
    # Rather than fail the run, post the same verdict as a COMMENT with a note,
    # so the review is still visible and the identity gap is explicit.
    if event == "APPROVE":
        note = (body + "\n\n> ℹ️ AI 판정은 **승인**이나, 공식 approval은 리뷰어 신원이 있어야 "
                "제출됩니다 (`HYPEPROOF_REVIEWER_TOKEN` 미설정 — github-actions[bot]은 approve 불가). "
                "COMMENT로 남깁니다.")
        fb = _post_review(repo, pr_number, "COMMENT", note)
        if fb.returncode == 0:
            print("APPROVE not permitted for this identity — posted as COMMENT")
            return
        res = fb
    raise RuntimeError(f"could not submit review ({event}): {res.stderr.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--dry-run", action="store_true", help="print verdict, submit nothing")
    args = ap.parse_args()

    pr = gh_json(["pr", "view", str(args.pr), "--repo", args.repo,
                  "--json", "url,title,body,author,isDraft"])
    if pr.get("isDraft"):
        print("draft PR — skipping AI review")
        return 0

    files = _changed_files(args.repo, args.pr)
    diff = subprocess.run(["gh", "pr", "diff", str(args.pr), "--repo", args.repo],
                          text=True, capture_output=True, check=True).stdout
    risks = detect_risks(files)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        msg = ("## 🤖 AI 리뷰\n\nAI 리뷰어가 아직 프로비저닝되지 않았습니다 "
               "(`ANTHROPIC_API_KEY` 시크릿 없음). 리뷰를 건너뜁니다 — required CI 체크는 정상 강제됩니다.")
        print(msg)
        if not args.dry_run:
            subprocess.run(["gh", "pr", "comment", str(args.pr), "--repo", args.repo, "--body", msg],
                           check=False)
        return 0

    reviewer = _current_login()
    if reviewer and reviewer.lower() == pr["author"]["login"].lower():
        print(f"reviewer identity ({reviewer}) is the PR author — cannot self-approve; skipping")
        return 0

    user_prompt = build_user_prompt(pr, files, risks, diff)
    try:
        verdict = enforce_safety(call_claude(SYSTEM_PROMPT, user_prompt, DEFAULT_MODEL, api_key))
    except (urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as e:
        # Never fake-approve on an error — fall back to a COMMENT that flags it.
        verdict = {"decision": "comment", "summary": f"AI 리뷰 호출 실패로 자동 승인하지 않음: {e}",
                   "blockers": [], "questions": []}

    body = render_body(verdict, risks)
    print(f"decision={verdict['decision']} blockers={len(verdict['blockers'])}")
    print(body)
    if args.dry_run:
        return 0
    submit_review(args.repo, args.pr, verdict, body)
    return 0


def _changed_files(repo: str, pr_number: int) -> list[str]:
    data = gh_json(["pr", "view", str(pr_number), "--repo", repo, "--json", "files"])
    return [f["path"] for f in (data.get("files") or [])]


def _current_login() -> str:
    try:
        return subprocess.run(["gh", "api", "user", "--jq", ".login"],
                              text=True, capture_output=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
