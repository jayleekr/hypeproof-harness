#!/usr/bin/env python3
"""Create and operate HypeProof Studio quality dashboard cohorts.

The cohort JSON is the single source of truth. The visible dashboard reads the
same shape, and this CLI turns it into GitHub issues when `--apply` is used.
Dry-run is the default.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COHORT_DIR = ROOT / "quality" / "studio" / "cohorts"
DEFAULT_REPO = "jayleekr/hypeproof-studio"


GATES: list[dict[str, Any]] = [
    {
        "id": "G1",
        "name": "설치 후 Studio 첫 응답까지 간다",
        "owner": "Studio Ops",
        "eta_offset_days": -10,
        "report": "install-session-trace.md",
        "review": "AI 1차, 사람 최종",
        "items": [
            "설치 화면이 단일 준비 페이지에 있고 학생도 접근 가능",
            "토큰 발급과 세션 열기 화면이 단일 준비 페이지에 있음",
            "토큰 발급과 세션 열기가 3분 안에 완료",
            "토큰 끊김, 만료, 권한 오류의 복구 행동이 보임",
            "Mac/Windows 공개계 설치가 각각 10분 안에 완료",
            "강의 필수 라이브러리가 양쪽 OS에 설치됨",
            "Mac/Windows가 fallback 없이 같은 SDK 로직으로 작동",
            "자기 workspace path와 실행 컨텍스트를 정확히 읽음",
        ],
    },
    {
        "id": "G2",
        "name": "커리큘럼을 끝까지 완수한다",
        "owner": "Curriculum Ops",
        "eta_offset_days": -7,
        "report": "participant-runthroughs.md",
        "review": "커리큘럼 owner 승인",
        "items": [
            "커리큘럼이 확정되고 리뷰 완료",
            "모든 참가자가 Studio로 커리큘럼을 직접 완수",
            "참가자별 완주 증거가 G2 이슈에 업로드됨",
            "강의를 방해하는 과도한 보안/승인/안전 장치가 없음",
            "이미지, 프롬프트, 요구사항이 산출물에 실제 반영됨",
            "파일 저장은 실제 write와 존재 확인까지 완료",
            "preview 또는 브라우저에서 결과물을 직접 확인",
            "최종 유저가 파일, URL, 저장소, harness 중 하나를 가져감",
        ],
    },
    {
        "id": "G3",
        "name": "정해진 시간보다 20분 일찍 끝낸다",
        "owner": "Performance Ops",
        "eta_offset_days": -5,
        "report": "timebox-benchmark.md",
        "review": "운영 리허설 승인",
        "items": [
            "에이전트 응답 속도 Cursor 대비 분석 리포트 존재",
            "tool calling 속도 Cursor 대비 분석 리포트 존재",
            "강의 skill과 cohort 시스템 프롬프트가 분리됨",
            "skill Lazy Loading이 trace로 증명됨",
            "강의 skill 최적화 리포트 존재",
            "제한 시간보다 20분 일찍 완주",
            "브라우저/tool 예산이 결과 검증 단계까지 남음",
            "동시 접속, 429, 대기, 복구 흐름이 검증됨",
        ],
    },
]

REPORTS = [
    {
        "id": "G1 REPORT",
        "file": "install-session-trace.md",
        "description": "Mac/Windows 설치 시간, 토큰 발급, 세션 열기, 끊김 복구, 첫 응답 캡처.",
        "accepts_upload": True,
        "uploaded": None,
    },
    {
        "id": "G2 REPORT",
        "file": "participant-runthroughs.md",
        "description": "모든 참가자의 완주 trace, 산출물 URL, 실패/복구 로그, take-home 산출물.",
        "accepts_upload": True,
        "uploaded": None,
    },
    {
        "id": "G3 REPORT",
        "file": "timebox-benchmark.md",
        "description": "Cursor 대비 응답/tool 호출 속도, 제한시간 20분 전 완주 여부, 동시 접속 결과.",
        "accepts_upload": True,
        "uploaded": None,
    },
    {
        "id": "REVIEW",
        "file": "ai-human-approval.md",
        "description": "AI 1차 리뷰, 사람 최종 리뷰, Red/Yellow 항목의 Green 전환 예정일.",
        "accepts_upload": False,
        "uploaded": None,
    },
]


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9가-힣]+", "-", value)
    return value.strip("-") or "cohort"


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def due_date(cohort_date: dt.date, offset_days: int) -> str:
    return (cohort_date + dt.timedelta(days=offset_days)).isoformat()


def status_for_gate(completed: int, total: int) -> str:
    if completed == total:
        return "Green"
    if completed > 0:
        return "Yellow"
    return "Red"


def build_cohort(course: str, date: dt.date, slug: str | None, repo: str) -> dict[str, Any]:
    cohort_slug = slug or f"{slugify(course)}-{date.isoformat()}"
    gates = []
    for gate in GATES:
        items = [{"text": item, "done": False} for item in gate["items"]]
        gates.append({
            "id": gate["id"],
            "name": gate["name"],
            "owner": gate["owner"],
            "due": due_date(date, gate["eta_offset_days"]),
            "report": gate["report"],
            "review": gate["review"],
            "status": "Red",
            "items": items,
        })

    return {
        "title": "hypeproof studio quality dash board",
        "course": course,
        "date": date.isoformat(),
        "slug": cohort_slug,
        "repo": repo,
        "ready_page": f"https://studio.hypeproof.ai/ready/{cohort_slug}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gates": gates,
        "reports": REPORTS,
        "green_plan": [
            {"when": "D-14", "status": "Today", "text": "강의 날짜 확정, 단일 준비 페이지 생성, GitHub 이슈 발행"},
            {"when": "D-10", "status": "Red", "text": "G1 설치/토큰/세션 리포트 업로드 및 리뷰"},
            {"when": "D-7", "status": "Yellow", "text": "G2 참가자 전원 인간 완주 증거 제출"},
            {"when": "D-5", "status": "Yellow", "text": "G3 속도/툴/동시접속/20분 버퍼 검증"},
            {"when": "D-3", "status": "Green", "text": "AI 또는 사람 최종 리뷰 완료, Studio 사용 가능 판정"},
        ],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def recalculate(cohort: dict[str, Any]) -> dict[str, Any]:
    for gate in cohort.get("gates", []):
        items = gate.get("items") or []
        done = sum(1 for item in items if item.get("done"))
        gate["status"] = status_for_gate(done, len(items))
    statuses = [gate.get("status") for gate in cohort.get("gates", [])]
    cohort["verdict"] = "Ready" if statuses and all(status == "Green" for status in statuses) else "Not Ready"
    return cohort


def issue_title(cohort: dict[str, Any], gate: dict[str, Any]) -> str:
    return f"{cohort['course']} - {cohort['date']} - {gate['id']} {gate['name']}"


def issue_body(cohort: dict[str, Any], gate: dict[str, Any]) -> str:
    items = "\n".join(f"- [ ] {item['text']}" for item in gate["items"])
    return "\n".join([
        "## Context",
        f"{cohort['course']} ({cohort['date']}) 강의에서 HypeProof Studio를 사용해도 되는지 판정하는 {gate['id']} 게이트입니다.",
        "",
        f"- 단일 준비 페이지: {cohort['ready_page']}",
        f"- Evidence report: `{gate['report']}`",
        f"- Review: {gate['review']}",
        "",
        "## Tasks",
        items,
        "",
        "## Owner",
        f"담당: {gate['owner']}",
        "",
        "## ETA",
        f"ETA: {gate['due']}",
        "",
        "## Evidence",
        "Evidence: <보고서/PR/코멘트 permalink>",
    ])


def issue_plan(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "repo": cohort["repo"],
            "title": issue_title(cohort, gate),
            "body": issue_body(cohort, gate),
            "labels": [
                "studio-quality",
                f"cohort:{cohort['slug']}",
                gate["id"].lower(),
                f"due:{gate['due']}",
            ],
        }
        for gate in cohort.get("gates", [])
    ]


def run(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, input=input_text, capture_output=True, check=False)


def command_init(args: argparse.Namespace) -> int:
    cohort = recalculate(build_cohort(args.course, args.date, args.slug, args.repo))
    path = args.output or DEFAULT_COHORT_DIR / f"{cohort['slug']}.json"
    write_json(path, cohort)
    print(path)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    cohort = recalculate(load_json(args.cohort))
    plan = issue_plan(cohort)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    for idx, issue in enumerate(plan, start=1):
        print(f"{idx}. {issue['title']}")
        print(f"   repo: {issue['repo']}")
        print(f"   labels: {', '.join(issue['labels'])}")
    return 0


def command_create_issues(args: argparse.Namespace) -> int:
    cohort = recalculate(load_json(args.cohort))
    created = []
    for issue in issue_plan(cohort):
        cmd = [
            "gh", "issue", "create",
            "--repo", issue["repo"],
            "--title", issue["title"],
            "--body", issue["body"],
        ]
        for label in issue["labels"]:
            cmd.extend(["--label", label])
        if not args.apply:
            created.append({"apply": False, "command": cmd})
            continue
        proc = run(cmd)
        if proc.returncode != 0:
            print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
            return proc.returncode
        created.append({"apply": True, "url": proc.stdout.strip()})
    print(json.dumps(created, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a cohort JSON source of truth")
    init.add_argument("--course", required=True)
    init.add_argument("--date", required=True, type=parse_date)
    init.add_argument("--slug")
    init.add_argument("--repo", default=DEFAULT_REPO)
    init.add_argument("--output", type=Path)
    init.set_defaults(func=command_init)

    plan = sub.add_parser("plan-issues", help="print the GitHub issues to create")
    plan.add_argument("cohort", type=Path)
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(func=command_plan)

    create = sub.add_parser("create-issues", help="create GitHub issues with gh")
    create.add_argument("cohort", type=Path)
    create.add_argument("--apply", action="store_true")
    create.set_defaults(func=command_create_issues)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
