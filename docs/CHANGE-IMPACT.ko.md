# 기준 변경의 영향 검토

> 작성일 2026-09-08 · 상태: 활성 · 구현 Epic: #120 · 운영 활성화는 세 저장소 onboarding merge 이후

## Intent

철학, Mission, 제품 역할, Intent, 요구사항, Design, 구현, Test, Validation 중 어느
단계에서든 기준이 바뀌면, 영향을 검토할 책임자와 후속 작업을 놓치지 않는다.
기준의 채택(main merge)과 전체 반영 완료는 별도 상태다. 기능 테스트 PASS는 사람의
판단 성장이나 학습효과를 증명하지 않는다.

## 저장소와 권한

| 저장소 | 소유하는 정본 |
|---|---|
| hypeproof-harness | 엔진, 허용 저장소, 라우팅·예산 정책, 스케줄, 검증 계약 |
| hypeprooflab | PHILOSOPHY.md, MISSION.md, 제품 역할, 웹의 표현과 경험 |
| hypeproof-studio | 제품 Intent, 앱·Service REQ, 경험 설계, 테스트와 실행 기록 |

각 저장소의 `config/traceability.json`은 자신의 파일과 고정 ID, 상위 ID, 담당자만 등록한다.
상위 문서를 복사하거나 하네스에 제품 정본을 옮기지 않는다. 등록 문서는 전체 또는
정확한 Markdown heading 범위로 나눌 수 있다. 세 manifest를 합친 연결망에 중복 ID,
끊긴 연결, 순환, 없는 파일·절이 있으면 검토는 실패한다. PR의 코드나 manifest가
하네스 실행 정책을 바꿀 수 없다.

철학·Mission 책임자는 Jay다. 나머지는 해당 노드의 owner가 판단한다. 미지정은
UNASSIGNED로 표시하고 이슈를 강제 배정하지 않는다. owner 지정은 consumer PR에서
합의하며 구성원 목록은 `policy/members.yaml`을 참조한다. 미지정 영역의 임시 판단은
`policy/change-impact.json`의 ownership_triage가 맡는다. 도메인 책임의 영구 위임은
별도 owner 등록이다. AI는 승인권자가 아니다.

## 요구사항과 검증

| ID | 요구사항 | 실행 테스트 |
|---|---|---|
| CI-01 | Intent 등 임의 단계에서 시작하고 하위 영향·상위 정합성을 연결한다 | intent/diamond/removed edge tests |
| CI-02 | 정본을 immutable SHA에서 읽고 dirty checkout을 읽지 않는다 | real git snapshot test |
| CI-03 | 모델의 영향 없음은 제안이며, 실패·미설정·예산 초과는 pending이다 | AI authority/budget/context tests |
| CI-04 | 반복 실행과 중간 실패에서 중복 이슈를 만들지 않는다 | sync replay test |
| CI-05 | 사람 본문을 보존하며 marker 충돌은 중단한다 | upsert/ambiguous marker tests |
| CI-06 | 비공개 원문·모델 설명을 다른 저장소의 이슈에 복사하지 않는다 | cross-repo disclosure test |
| CI-07 | 오래된 승인·권한 없는 댓글·bot·증거 없는 완료를 수용하지 않는다 | resolution tests |
| CI-08 | 미등록 변경은 mapping review로 드러낸다 | unregistered path test |
| CI-09 | 기준 채택과 전체 반영 완료를 구분한다 | status reports + version-bound resolution |

`python -m pytest tests/change_impact -q`로 실행한다. 완료 증거 URL은 책임자의
attestation이며 엔진이 URL의 사용자·학습효과를 판정하지 않는다. 이슈 close 이벤트는
검증으로 세지 않는다. 배포/실기기/학습효과는 해당 제품의 기존 검증 규칙을 따른다.

## 설계

1. 모든 repo main SHA를 먼저 고정하고 manifest와 source를 읽는다.
2. 등록 정의와 내용의 hash를 비교한다. 담당자·연결 변경도 재검토 대상이다.
3. 삭제 전·후 연결을 합쳐 영향 범위를 구한다. 삭제로 후속 작업을 숨길 수 없다.
4. 변경 노드에는 상위 정합성 질문, 하위 노드에는 단계별 영향 질문을 배정한다.
5. AI는 변경 전후와 연결된 문서만 읽고 bounded JSON 제안을 반환한다. 전체 원문이
   예산에 맞지 않으면 조용히 자르지 않고 context-too-large로 남긴다.
6. 채택된 변경은 repo별 adoption Epic과 노드별 검토 이슈로 upsert한다. 작업용 이슈는
   제품 담당자가 검토 이슈에 연결한다. 엔진은 불확실한 설계를 곧바로 개발 지시로 바꾸지 않는다.
7. 모든 이슈 발행 성공 후에만 checkpoint를 갱신한다. 중간 실패는 같은 source SHA로
   다시 실행할 수 있다. workflow concurrency는 하나의 writer만 허용한다.
8. `status`가 미해결 검토와 아직 발행하지 않은 변경을 확인한다. 자동 close/merge는 없다.

공유 checkpoint에는 repo SHA만 둔다. 보고서와 public 이슈에는 ID·단계·hash·고정
질문만 둔다. 자세한 원문과 AI explanation은 출력하지 않는다. 다른 접근 경계를 가진
저장소 사이의 내용을 한 public Epic에 복제하지 않고 repo별 Epic으로 연결한다.

## 운영

필요한 도구: Python 3.11+, PyYAML, gh. 기존 AI PR reviewer의 provider adapter를
재사용한다. 모델명과 호출 예산은 하네스 정책이 소유한다.

```bash
# main의 새 변경을 확인하고 로컬 보고서만 작성
python scripts/change-impact/impact.py scan --reason --output impact-report.json

# 채택된 main 변경의 이슈 동기화. SHA가 움직였으면 중단하고 다시 스캔한다.
python scripts/change-impact/impact.py scan --reason --apply

# 진행 중인 PR의 영향 미리보기. PR 코드는 실행하지 않는다.
python scripts/change-impact/impact.py prs --publish-reports --output impact-prs.json

# 미해결 검토가 있으면 exit 1; 기능·학습효과를 자동 승인하지 않는다.
python scripts/change-impact/impact.py status --output impact-status.json

# 특정 PR의 읽기 전용 비교. 나머지 repo는 main을 고정한다.
python scripts/change-impact/impact.py report \
  --base jayleekr/hypeprooflab=BASE_SHA --ref jayleekr/hypeprooflab=HEAD_SHA
```

로컬 git을 쓰려면 `--root owner/repo=/path/to/checkout`을 지정한다. 파일은 항상
git commit object에서 읽는다. manifest 도입 전 커밋과의 report 비교는 지원하지 않으므로
첫 onboarding은 scan의 bootstrap으로 전체 등록 항목을 미검토 상태로 올린다.

리뷰 책임자는 이슈에 다음 형식으로 결정과 충분한 이유를 남긴다.

```text
/impact-resolve <이슈의 revision> no-impact <영향 없는 이유>
/impact-resolve <이슈의 revision> satisfied <기존 상태가 충족하는 근거>
/impact-resolve <이슈의 revision> validated <검증 결과와 https://증거-URL>
```

구현·test·validation의 satisfied만으로는 통과하지 않는다. 새 버전은 기존 결정을
무효화한다. AI가 작성한 권고는 이 댓글을 대신하지 않는다. 필요한 변경이 남아 있으면
관련 PR/검증 이슈를 연결하고 검토 이슈는 pending으로 둔다.

## 자동 실행과 롤아웃

`.github/workflows/change-impact.yml`은 trusted main 엔진으로 1시간마다 PR 미리보기와
main 영향 검토를 실행하고, 수동 실행도 제공한다. source repo checkout의 코드는 실행하지
않는다. `HYPEPROOF_GOVERNANCE_TOKEN`에 세 저장소 Contents read, Issues write,
Pull requests read와 PR comment 권한이 필요하다. ANTHROPIC_API_KEY 미설정은 명시적
not-configured이며 검토를 완료 처리하지 않는다. 키·권한 설정을 이번 코드가 바꾸지는 않는다.

1. Harness #121과 Lab #756, Studio #763을 리뷰한다.
2. consumer manifest 두 개를 먼저 merge한다. 이는 앱 동작이나 배포 설정을 바꾸지 않는다.
3. Harness PR을 사람이 merge한다. policy/workflow 변경의 기존 control-plane gate를 따른다.
4. 최초 scan은 등록 항목 전체의 검토 이슈를 만든다. 이것은 기존 철학 개정의 실제 검토 backlog다.
5. 담당자 지정과 실제 리뷰 후 status를 확인한다. 이 엔진의 CI PASS가 adoption 완료는 아니다.

초기 범위는 철학/Mission, Lab 핵심 페이지, Studio native trial이다. 다른 제품의 전체
커버리지를 주장하지 않는다. watch_prefixes 내 미등록 변경은 repo당 mapping review 하나로
묶는다. 그 밖의 경로는 정책 확대가 필요하다. 필수 상위 단계가 빠진 구조는 structural_gaps로 표시하고 전체 완료 판정을 막는다.
초기 매핑에서 빠진 Intent/REQ는 새로
지어내지 않고 onboarding 검토에서 작성·연결한다.

## 운영 시험과 장애 처리

`test.yml`의 수동 입력 `operational_smoke=true`는 실제 운영 token으로 세 저장소의
읽기·이슈 생성·갱신·재실행·관리 영역 밖 본문 보존·댓글 작성을 시험한다. PR 이벤트에서는
실행되지 않는다. 시험 이슈는 별도 marker를 쓰고 finally에서 닫으며 실제 review/checkpoint로
세지 않는다. 2026-09-08 실행 34250669924에서 세 저장소 모두 통과했다.

스케줄은 채택 변경 처리를 PR 미리보기보다 먼저 실행한다. 모델 장애·키 미설정이면
미검토 이슈는 남기고 checkpoint를 전진시키지 않아 다음 실행에서 재시도한다. 예산 소진도
checkpoint를 보존하되 이미 제안한 revision을 재사용한다. 소스/정책/권한 오류는 실패다.
GitHub API와 git 호출은 60초 제한을 둔다.

매 실행의 step summary와 `impact-status.json`은 pending review URL, 빠진 검토 기록,
구조적 누락을 표시한다. 미해결 사람 검토(exit 1)는 정상적인 backlog이며 시스템 오류
(exit 2)와 구분한다. 담당자는 링크된 검토 이슈를 처리한다. Discord/email 전송은 없다.
`/impact-resolve <revision> unknown <reason>` 또는 `change-required`를 나중에 남기면
이전 수용 결정을 철회한다. 운영상 이슈 close만으로 완료되지 않는다.

현재 한계: PR 미리보기는 graph 기반이며 main에서 semantic review한다. 의미 검토는
예산 내 첫 항목부터 실행하고 나머지는 명시적 pending이다. 예산이 소진되면 checkpoint를
유지하고 다음 실행에서 같은 revision의 제안을 재사용하여 나머지 항목을 이어서 검토한다. 기준 변경 시 이미 열린
노드 이슈를 최신 version으로 갱신하며 GitHub 본문 이력과 사람의 댓글은 보존한다.
독립 변경 wave의 Epic은 자동으로 닫지 않는다. URL 진위·배포 성공·실사용 효과는 기존
검증과 책임자가 확인한다. 브랜치 보호의 필수 check 추가는 별도 정책 결정이다.
