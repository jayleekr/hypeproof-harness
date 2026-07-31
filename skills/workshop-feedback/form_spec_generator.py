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
     "q": '업무에서 "매번 똑같이 반복한다" 싶은 일이 있으시면 한 가지만 적어 주세요.'},
    {"id": "PC2", "type": "text", "q": "이번 강의에서 가장 얻어 가고 싶으신 것은 무엇인가요?"},
    {"id": "PC3", "type": "scale", "scale": SCALE, "baseline": "confidence",
     "q": '지금으로선 "AI를 내 업무에 활용할 수 있겠다"는 생각이 어느 정도 드시나요? (1 거의 안 듦~5 매우 그렇다)'},
]
CORE_POST = [
    {"id": "AC1", "type": "scale", "scale": SCALE,
     "q": "오늘 다뤄 본 내용 중 실제 업무에 써볼 만한 것이 있으셨나요? (1 없었다~5 많았다)"},
    {"id": "AC2", "type": "scale", "scale": SCALE, "delta_of": "PC3",
     "q": '이제 "AI를 내 업무에 활용할 수 있겠다"는 생각이 어느 정도 드시나요? (1~5)'},
    {"id": "AC3", "type": "text", "q": "돌아가서 실제로 한 번 써보실 것이 있다면 한 가지만 적어 주세요."},
    {"id": "AC4", "type": "choice", "options": ["권한다", "보통이다", "권하지 않는다"],
     "aggregate": "distribution",
     "q": "가까운 동료분께 이 강의를 권하시겠어요?"},
    {"id": "AC5", "type": "text",
     "q": '기능을 나열하기보다 "실제로 불편하신 일"에서 시작한 오늘 방식은 어떠셨나요? (한 말씀)'},
]
# ---- PRODUCT INTEREST (post) — 계속 쓸 의향 + 그 조건. -------------------------
# 왜 코어인가: "강의는 좋았다"와 "이 도구를 계속 쓰겠다"는 다른 신호이고, 후자는
# 로드맵 입력이다. 매 강의 같은 문항이어야 강의 간 비교가 된다.
# 금지: 가격·출시·플랜을 암시하는 문구. 확인되지 않은 약속이 된다 (헌법 3조).
# 그래서 "구독" 대신 "계속 써보고 싶다", 기능 문항은 전부 가정법으로 둔다.
PRODUCT_FEATURES = [
    "우리 조직 자료를 계속 기억하기",
    "직원·동료와 함께 쓰기",
    "만든 결과물이 자동으로 저장·정리되기",
    "휴대폰에서도 보기",
    "오늘 다룬 것 외의 업무(문서·이미지 등)",
    "막힐 때 사람에게 물어보기",
    "오늘 배운 것을 복습할 자료",
]


def product_interest(cfg: dict) -> list[dict]:
    """계속 쓸 의향(분포) + 그러려면 필요한 것(복수) + 자유서술.

    제품명은 config의 product.name (없으면 '오늘 쓰신 도구'). 기능 보기는 코어이며,
    config product.extra_features 로 덧붙일 수만 있다 — 코어를 갈아끼우지 않는다.
    """
    p = (cfg.get("product") or {}) if isinstance(cfg.get("product"), dict) else {}
    name = str(p.get("name") or "오늘 쓰신 도구")
    feats = list(PRODUCT_FEATURES) + [str(x) for x in (p.get("extra_features") or [])]
    return [
        {"id": "AC6", "type": "choice", "aggregate": "distribution",
         "options": ["예, 계속 써보고 싶다", "아직 모르겠다", "아니오"],
         "q": f"{name}를 강의 이후에도 계속 써 보고 싶으신가요?"},
        {"id": "AC7", "type": "choice_multi", "options": feats + ["기타"],
         "depends_on": {"id": "AC6", "not": "아니오"},
         "q": "만약 계속 쓰신다면, 어떤 점이 갖춰져 있어야 실제로 쓰실 것 같으세요? (여러 개 선택 가능)"},
        {"id": "AC8", "type": "text",
         "q": "그 밖에 “이런 게 되면 쓰겠다” 싶은 것이 있으시면 한 가지만 적어 주세요."},
    ]


CORE_FOLLOWUP = [
    {"id": "F1", "type": "choice", "options": ["거의 안 씀", "가끔", "자주", "거의 매일"],
     "q": "지난 한 달, 강의에서 배운 방법을 실제로 써 보셨나요?"},
    {"id": "F2", "type": "scale", "scale": SCALE, "delta_of": "PC3",
     "q": '지금은 "AI를 내 업무에 활용할 수 있다"는 생각이 어느 정도 드시나요? (1~5)'},
    {"id": "F3", "type": "text",
     "q": "실제로 달라진 일이 있으시면, 또는 안 쓰게 되셨다면 그 이유를 알려 주세요."},
    {"id": "F4", "type": "choice", "options": ["예", "아니요"], "internal_only": True,
     "q": "직원분들이나 동료와도 함께 써 보셨나요?"},
    {"id": "F5", "type": "choice", "options": ["매우 그렇다", "그렇다", "미정", "아니다"],
     "internal_only": True, "q": "앞으로도 이런 도움을 계속 받아 보실 생각이 있으신가요?"},
]

IDENTITY = {"id": "Q0", "type": "text", "required": True,
            "q": "참가자 코드와 휴대폰 뒤 4자리를 적어 주세요 (예: 가나-1234)"}
JOBROLE = {"id": "Q0b", "type": "choice", "q": "현재 맡고 계신 역할은?",
           "options": ["__역할1__", "__역할2__", "기타"]}


def consent_pre(months: int) -> dict:
    return {"id": "CONSENT", "type": "consent", "required": True,
            "q": ("본 설문은 강의 준비와 강의 후 익명 요약 자료에만 사용됩니다. "
                  "수집 항목: 참가자 코드·역할·응답(성함·연락처는 받지 않습니다). "
                  f"보관: 강의 후 {months}개월 이내 파기하며 외부에 제공하지 않습니다. 동의하십니까?")}


RECONTACT = {"id": "RECONTACT", "type": "recontact", "internal_only": True,
             "separate_sheet": True,
             "q": ("한 달쯤 뒤에, 실제로 도움이 되었는지 딱 한 번만 더 여쭤봐도 될까요? "
                   '"예"를 고르시면 이어지는 짧은 폼에 연락 받으실 방법(이메일/카카오톡/휴대폰 중 하나)을 남겨 주세요. '
                   "후속 안내 외의 목적으로 쓰지 않으며 언제든 철회하실 수 있습니다.")}

# Generic fallback slot (used if config omits topic — keeps the skill runnable).
GENERIC_TOPIC_PRE = {"id": "DS1", "type": "text",
                     "q": "평소 반복해서 찾아보거나 확인하시는 일은 어떤 것인가요?"}
GENERIC_TOPIC_POST = {"id": "DSP1", "type": "text",
                      "q": "오늘 배운 것을 어느 업무에 먼저 적용해 보고 싶으신가요?"}


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
            "fixed_core": ["PC1", "PC2", "PC3", "AC1-5", "AC6-8", "F1-5"],
            "note": "Fixed core owned by harness; only topic slot is per-engagement.",
            "retention_months": months,
            # build-forms.gs auto-shares each response sheet with this reader SA at
            # creation time, so fetch_responses.py can read it with no manual sharing.
            "service_account_email": cfg.get("service_account_email"),
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
                 {"name": "앞으로 (선택)", "items": product_interest(cfg)},
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
    prod = cfg.get("product") or {}
    hits = scan_banned(str(topic.get("pre", {}).get("q", "")) + " "
                       + str(topic.get("post", {}).get("q", "")) + " "
                       + " ".join(str(x) for x in (prod.get("extra_features") or []))
                       + " " + str(prod.get("name", "")))
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
