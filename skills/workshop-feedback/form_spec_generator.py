#!/usr/bin/env python3
"""workshop-feedback — reusable pre/post/follow-up form spec generator (harness canonical).

One per-engagement config -> `forms.spec.json` describing THREE forms:
  pre       (D-7, remote)      — baseline
  post      (D0, on-site QR)   — value + re-measure + re-contact opt-in
  follow-up (D+30, opt-in)     — sustained use / business signal

Design contract (why this is a harness skill, not a lab one-off):
  * FIXED CORE lives in THIS file — the org-standard question set, identical for
    every lecture, so confidence/NPS/value stay comparable and pre->post->follow-up
    deltas are measurable. Do NOT fork the core per topic.
  * TOPIC SLOT is the only thing that changes per engagement, supplied by the config.
  * The form is a rentable surface; the schema + the feedback record are the nouns
    we own. This generator is the single source of truth for the schema; a Google
    Apps Script (apps-script/build-forms.gs) is just one renderer of forms.spec.json.
  * PRIVACY: feedback track is anonymous (participant code + phone-last-4 rejoin key).
    The re-contact track is a SEPARATE opt-in block (internal_only) the renderer must
    write to a DIFFERENT sheet — never mixed into the anonymous feedback responses.

Self-contained: stdlib + PyYAML only (no lab common.py dependency — harness owns it).

Usage:
    python3 form_spec_generator.py CONFIG.yaml -o forms.spec.json [--strict]

Config (see templates/feedback.config.example.*.yaml):
    engagement: "치과 AI 레이스 (2시간)"
    retention_months: 6
    topic:
      pre:  { q: "...", type: choice_multi, options: [...] }
      post: { q: "...", type: choice,       options: [...] }

Exit codes: 0 ok · 1 config/validation error · 2 io/parse error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML 필요 (pip install pyyaml)\n")
    raise SystemExit(2)

# §5 헌법 3조 — 과장 금지. Minimal inline scan (harness self-contained).
BANNED = ["최고", "1위", "업계 최고", "보장", "무조건", "100%", "완벽",
          "revolutionary", "guaranteed", "best-in-class"]

SCALE = ["1", "2", "3", "4", "5"]

# ---- FIXED CORE — constant across every lecture. Owned by harness, not config. ----
CORE_PRE = [
    {"id": "PC1", "type": "text",
     "q": '요즘 업무에서 "이거 또 해야 하네" 싶은 반복 불편함 하나만 적어주세요.'},
    {"id": "PC2", "type": "text", "q": "오늘 워크숍에서 얻고 싶은 것 한 가지는?"},
    {"id": "PC3", "type": "scale", "scale": SCALE, "baseline": "confidence",
     "q": '"내 반복 업무를 AI 도구로 바꿀 수 있다"에 얼마나 자신 있나요? (1 전혀~5 매우)'},
]
CORE_POST = [
    {"id": "AC1", "type": "scale", "scale": SCALE,
     "q": "오늘 만든 도구가 실제 업무에 쓸 만한가요? (1 전혀~5 매우)"},
    {"id": "AC2", "type": "scale", "scale": SCALE, "delta_of": "PC3",
     "q": '지금 "내 반복 업무를 AI로 바꿀 수 있다" 자신감은? (1~5)'},
    {"id": "AC3", "type": "text", "q": "실제로 써볼 도구/스킬 하나만 적어주세요."},
    {"id": "AC4", "type": "choice", "options": ["추천", "보통", "아니오"],
     "aggregate": "distribution",
     "q": "동료에게 이 워크숍을 추천하겠어요?"},
    {"id": "AC5", "type": "text",
     "q": '"기능 설명"이 아니라 "내 불편함에서 시작"한 방식은 어땠나요? (한 줄)'},
]
CORE_FOLLOWUP = [
    {"id": "F1", "type": "choice", "options": ["안 씀", "가끔", "자주", "매일"],
     "q": "지난 한 달, 그 도구를 실제로 썼나요?"},
    {"id": "F2", "type": "scale", "scale": SCALE, "delta_of": "PC3",
     "q": "지금 자신감은? (1~5)"},
    {"id": "F3", "type": "text", "q": "실제로 바뀐 업무 하나 / 또는 안 쓰게 된 이유는?"},
    {"id": "F4", "type": "choice", "options": ["예", "아니오"], "internal_only": True,
     "q": "팀·동료에게 공유했나요?"},
    {"id": "F5", "type": "choice", "options": ["매우", "있음", "미정", "없음"],
     "internal_only": True, "q": "이런 걸 계속 도입할 의향이 있나요? (반복 가치 신호)"},
]

IDENTITY = {"id": "Q0", "type": "text", "required": True,
            "q": "참가자 코드 + 휴대폰 뒤 4자리 (예: A-1234)"}
JOBROLE = {"id": "Q0b", "type": "choice", "q": "직군/역할", "options": ["__직군1__", "__직군2__", "기타"]}


def consent_pre(months: int) -> dict:
    return {"id": "CONSENT", "type": "consent", "required": True,
            "q": ("본 설문은 워크숍 개선과 익명 결과 리포트에만 쓰입니다. "
                  "수집: 참가자 코드·역할·응답(실명·연락처 미수집). "
                  f"보유: 워크숍 후 {months}개월 뒤 파기. 제3자 제공 없음. 동의하십니까?")}


RECONTACT = {"id": "RECONTACT", "type": "recontact", "internal_only": True,
             "separate_sheet": True,
             "q": ("한 달 뒤에도 잘 쓰이는지 딱 한 번 더 여쭤봐도 될까요? "
                   "예를 고르면 연락처(이메일/카톡ID/휴대폰 중 1)를 남겨주세요. "
                   "후속 발송 목적에 한해 보관, 언제든 철회 가능.")}

# Generic fallback slot (used if config omits topic — keeps the skill runnable).
GENERIC_TOPIC_PRE = {"id": "DS1", "type": "text",
                     "q": "이 분야에서 반복 검색/확인이 가장 잦은 상황은?"}
GENERIC_TOPIC_POST = {"id": "DSP1", "type": "text",
                      "q": "오늘 만든 도구를 어느 상황에 쓸 것 같나요?"}


def _slot(node: dict | None, fallback: dict, sid: str) -> dict:
    if not node:
        return fallback
    out = {"id": sid, "type": node.get("type", "text"), "q": node.get("q", fallback["q"])}
    if node.get("options"):
        out["options"] = list(node["options"])
    return out


def scan_banned(text: str) -> list[str]:
    return [b for b in BANNED if b.lower() in (text or "").lower()]


def build_spec(cfg: dict) -> dict:
    eng = str(cfg.get("engagement", "워크숍"))
    months = int(cfg.get("retention_months", 6))
    topic = cfg.get("topic", {}) or {}
    roles = cfg.get("roles")
    jobrole = dict(JOBROLE)
    if roles:
        jobrole = {"id": "Q0b", "type": "choice", "q": "직군/역할",
                   "options": list(roles) + (["기타"] if "기타" not in roles else [])}
    tpre = _slot(topic.get("pre"), GENERIC_TOPIC_PRE, "DS1")
    tpost = _slot(topic.get("post"), GENERIC_TOPIC_POST, "DSP1")

    return {
        "meta": {
            "engagement": eng,
            "join_key": "participant_code + phone_last4",
            "fixed_core": ["PC1", "PC2", "PC3", "AC1-5", "F1-5"],
            "note": "Fixed core owned by harness; only topic slot is per-engagement.",
            "retention_months": months,
        },
        "forms": [
            {"key": "pre", "when": "D-7", "channel": "remote",
             "title": f"{eng} — 시작 전 30초",
             "sections": [
                 {"name": "동의", "items": [consent_pre(months)]},
                 {"name": "식별(익명)", "items": [IDENTITY, jobrole]},
                 {"name": "고정 코어", "items": CORE_PRE},
                 {"name": "주제", "items": [tpre]},
             ]},
            {"key": "post", "when": "D0", "channel": "on-site (QR/tablet)",
             "title": f"{eng} — 끝나고 1분",
             "sections": [
                 {"name": "식별", "items": [IDENTITY]},
                 {"name": "고정 코어(사후)", "items": CORE_POST},
                 {"name": "주제", "items": [tpost]},
                 {"name": "재접촉 동의(분리 저장)", "items": [RECONTACT]},
             ]},
            {"key": "followup", "when": "D+30", "channel": "opt-in only",
             "title": f"{eng} — 한 달 뒤", "audience": "recontact_consented_only",
             "sections": [
                 {"name": "식별", "items": [IDENTITY]},
                 {"name": "지속(코어 연장)", "items": CORE_FOLLOWUP},
             ]},
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="§5 금지표현이 주제 슬롯에 있으면 exit 1")
    args = ap.parse_args(argv)

    try:
        cfg = yaml.safe_load(Path(args.config).read_text("utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"ERROR: cannot load config: {e}\n")
        return 2
    if not isinstance(cfg, dict) or not cfg.get("engagement"):
        sys.stderr.write("ERROR: config에 'engagement' 필수\n")
        return 1

    spec = build_spec(cfg)

    topic = cfg.get("topic", {}) or {}
    hits = scan_banned(str(topic.get("pre", {}).get("q", "")) + " "
                       + str(topic.get("post", {}).get("q", "")))
    if hits:
        msg = f"§5 금지표현 (주제 슬롯): {', '.join(hits)}"
        if args.strict:
            sys.stderr.write("ERROR: " + msg + "\n")
            return 1
        sys.stderr.write("WARN: " + msg + "\n")

    try:
        Path(args.out).write_text(json.dumps(spec, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"ERROR: cannot write: {e}\n")
        return 2

    n = sum(len(s["items"]) for f in spec["forms"] for s in f["sections"])
    sys.stderr.write(f"OK: {len(spec['forms'])} forms, {n} items -> {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
