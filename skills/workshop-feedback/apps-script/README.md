# build-forms.gs — 구글 렌더러 (forms.spec.json → Google Forms)

`form_spec_generator.py`가 만든 `forms.spec.json`을 구글폼 3종(+연락처 1)으로 렌더.
**스키마는 생성기가 소유, 구글은 렌더러일 뿐.**

## 실행 (구글에서만 — ⚠️ repo/CI에서 실행 불가)
1. `script.google.com` → 새 프로젝트 → `build-forms.gs` 붙여넣기
2. `forms.spec.json` 내용을 `var SPEC =` 에 붙여넣기
3. `buildAll()` 1회 실행 → 권한 승인 → 생성된 폼·연결 시트 확인

## 프라이버시 (강제)
- 피드백 폼: `setCollectEmail(false)` (익명). 조인키 = 참가자 코드 + 뒤4자리.
- `type: recontact` = **별도 폼·별도 시트(INTERNAL)** 자동 분리 → 익명 트랙 오염 방지.
- `internal_only`(F4·F5·recontact)는 sales 산출물 미유입.

## 지원 문항 타입
`consent` · `text` · `scale`(1~N) · `choice` · `choice_multi` · `recontact`(분리 처리)

## 상태
🟡 레퍼런스 구현 — 구글 환경 검증 필요. API: `FormApp`, `SpreadsheetApp`.
