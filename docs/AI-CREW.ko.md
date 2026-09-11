# HypeProof AI Crew

## Intent

인간이 목표·판단·결과를 책임지고 AI가 반복 실행을 맡아 제품과 교육을 발전시킨다. 공용 정본은 harness, How We Work는 lab의 안내 화면이다. Jay가 방향·공용 운영 구조를 소유하며, 개별 결과는 제품별 인간 A가 책임진다.

## 요구사항

- HAR-CREW-01: Scout, Compass, Forge, Lens, Keeper를 별도 발견 가능한 스킬로 제공한다.
- HAR-CREW-02: 각 스킬은 입력·산출물·완료 기준·권한·인계 조건을 명시한다. 제작과 검증을 구분하고 실제 관찰과 가설을 혼동하지 않는다.
- HAR-CREW-03: Keeper는 재확인 기한·상태·명시적 충돌을 읽기 전용으로 검사한다. 손상된 입력을 정상으로 취급하지 않는다. 원문을 삭제하지 않는다.

## 설계

| Persona | 스킬 | 인간 판단 |
|---|---|---|
| Scout | hypeproof-scout | 봉호 및 고객 담당 |
| Compass | hypeproof-compass | 제품별 책임자 |
| Forge | hypeproof-forge | 진용 / 교육 담당 / Jay |
| Lens | hypeproof-lens | 광현 및 제품별 책임자 |
| Keeper | hypeproof-keeper | 광현 및 각 영역 책임자 |

Keeper 시작 점검 → Scout 조사 → Compass 계획 → Forge 제작 → Lens 검증 → 인간 판단·현장 관찰 → Keeper 갱신·인계.

제품 총괄 A: Jay. HypeProof Studio 제품 리드 R: 지웅. 제품명은 Lab의 products/PRODUCT-LINEUP.md를 따른다. 지웅은 창업교육, 제형은 홈페이지 강의의 프로그램 운영·고객 담당이며, 프로그램을 별도 소프트웨어 제품으로 취급하지 않는다. 운영 배정 정본은 각 제품의 ROLES.md와 업무 기록에서 확인한다. 이름은 실행 권한이나 개인의 시간·보상 합의를 대신하지 않는다.

각 SKILL.md는 바로 로드 가능한 절차다. harness 안에서 .claude/skills와 .agents/skills로 발견된다. 다른 저장소에서는 필요한 SKILL.md 절대 경로를 명시해 로드할 수 있다. 이번 변경은 전역 설치·consumer 자동 배포·스케줄 실행을 하지 않는다.

GPT 앱의 기존 리서처는 Jay 설명상 사용 중이다. 기존 설정을 읽거나 이전한 것이 아니며 Scout와 자동으로 같은 상태가 되지 않는다. gstack 코드는 복사하지 않았고, HypeProof의 업무 계약으로 작성했다.

## 검증

스킬 frontmatter 검사, 양쪽 등록 링크 검사, Keeper의 기한·종료 상태·충돌·잘못된 날짜·중복 ID·읽기 전용 동작 테스트를 실행한다. 이 검증은 스킬의 실제 모델 행동이나 사람의 교육 효과를 입증하지 않는다.

## Keeper 사용

`python3 skills/hypeproof-keeper/scripts/check_context.py CONTEXT.json --as-of YYYY-MM-DD`

입력 형식은 같은 폴더의 example-context.json을 참고한다. 예시는 가상 데이터다. due 날짜 당일까지 유효하며 다음 날부터 overdue다. active만 재확인 대상이며 closed/superseded는 활성 컨텍스트에서 분리한다. 자동 사실 검증이나 의미 기반 중복 탐지는 하지 않는다.

매주 기준 통과/검증 건수, 인간 재작업/처리 건수와 이유, 인간 판단 대기 시간을 본다. Keeper는 기한이 지난 활성 기록 수, 명시적 충돌 그룹 수를 제공한다. 담당자 응답 시간은 실제 인계 기록으로 측정한다.

## 법무·IP 연결

조민한(Minhan)은 계약·IP·개인정보·동의·사용 권한 검토를 맡는다. Lens는 근거와 쟁점을 정리하고 민한에게 판단을 넘긴다. Jay의 최종 사업 조건 수락·정산 총괄과 구분한다.

## 기여 기반 실행

Jay가 사업 전체·위험·실행 공백·주요 결정을 맡고, 멤버는 수락한 범위·기간·가능 시간의 결과를 책임진다. 지웅은 Studio 고객 문제·우선순위 제안·합의된 실행 조율·주간 공유를 맡는다. 스킬은 멤버에게 미합의 업무나 상근 의무를 확대하지 않는다. KPI는 합의 산출물·기한·막힘 공유를 중심으로 보며 제품·사업 성과는 별도로 관찰한다.

## 책임 단위와 리드 제안

핵심 제품은 Studio·Chalk·Sediment, Harness·AI Crew는 공통 실행 기반이다. 창업교육·홈페이지 강의는 별도 프로그램이며 결과 정리 파이프라인은 교육 운영 도구다. 제품 리드 지원자는 고객 문제·4주 결과·가능 시간·지원·결정권을 제안하고 Jay와 합의한다. 제품 리드는 합의한 자원 안에서 우선순위와 실행을 결정하며, 다른 멤버의 시간을 임의 배정하지 않는다.

## 스킬 발견 경로의 범위

.claude/skills는 register-skills.sh가 전체 skills/를 관리한다. .agents/skills는 현재 hype-pr과 AI Crew 다섯 스킬만 명시적으로 등록하는 선택 목록이다. 전체 스킬 미러가 아니며, Crew 링크는 tests/test_ai_crew.py에서 검증한다. 다른 스킬의 자동 등록이나 consumer 배포를 보장하지 않는다.
