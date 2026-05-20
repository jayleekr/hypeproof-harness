---
name: onboard-member
description: Interactive HypeProof member onboarding — picks the consumer repo (studio/sediment/lab), clones it (or git-pulls if present), installs git hooks if the repo has .githooks/, and validates .claude/settings.json + MCP server config + vendored skill-creator + docs/MEMBER-GUIDE.ko.md. Use ONCE when joining HypeProof Lab. After onboarding, day-to-day work happens in the consumer repo and this skill is not needed again. Idempotent — safe to re-run.
user_invocable: true
triggers:
  - "onboard"
  - "onboard-member"
  - "join hypeproof"
  - "hypeproof setup"
  - "온보딩"
  - "멤버 셋업"
  - "신규 멤버"
argument_hint: "[studio | sediment | lab] — optional; will ask if omitted"
---

# onboard-member

새 HypeProof 멤버를 위한 **1회성** 셋업. Claude Code가 이 문서를 따라 인터랙티브하게 각 단계를 실행한다. 첫 clone 이후 일상 작업은 그 consumer repo에서 진행하고 이 스킬은 다시 쓸 일이 없다.

이 스킬은 키/토큰을 자동 저장하지 않는다 (안내만). 그건 안전상 사용자 본인이 처리해야 한다.

---

## 흐름 / Flow

### 1. 어느 repo의 멤버인지 확인

`argument_hint`로 받은 값이 있으면(`studio`/`sediment`/`lab`) 그걸 사용하고, 없으면 **AskUserQuestion**으로 물어본다:

| 선택지 | 설명 |
|---|---|
| `studio` → `jayleekr/hypeproof-studio` | VSCodium fork 워크숍 도구 |
| `sediment` → `jayleekr/sediment` | 지식 DB / SaaS 백엔드·프론트 |
| `lab` → `jayleekr/hypeprooflab` | 공개 사이트(hypeproof-ai.xyz) + 콘텐츠/운영 |

회의/Discord에서 배정받은 영역으로 선택. 모르면 Jay에게 물어본 뒤 진행.

### 2. 로컬 경로 확인 + Clone

기본 경로: `~/CodeWorkspace/<repo>` (예: `~/CodeWorkspace/hypeproof-studio`). 사용자가 다른 경로 원하면 AskUserQuestion으로 받음.

**경로에 이미 git 디렉토리가 있으면**:
- `git -C <path> remote get-url origin`을 읽어 기대한 repo와 일치하는지 확인
- 일치하면: `git -C <path> fetch origin && git -C <path> pull --ff-only` (이미 셋업됨, 동기만)
- 불일치하면: 사용자에게 경고 + 별도 경로 묻기

**경로가 없으면**:
- `mkdir -p $(dirname <path>)`
- `git clone --recursive git@github.com:jayleekr/<repo>.git <path>` 실행
  - `--recursive`: studio의 `vscodium-base` 서브모듈 동시 clone, 다른 repo엔 무해
- 실패하면 (SSH 키 없음, 권한 없음 등): 사용자에게 명확한 에러 + 해결 안내
  ```
  - SSH 키 셋업: github.com/settings/keys
  - 권한 요청: @jayleekr 또는 @JeHyeong2 에게 핑
  ```

### 3. Git hooks 설치

```bash
if [ -d "<path>/.githooks" ]; then
  git -C <path> config core.hooksPath .githooks
  ls -1 <path>/.githooks
  # studio: pre-push 가드 (main 직접 push 막음)
fi
```

`.githooks/` 디렉토리가 없으면 skip (lab·sediment는 현재 없음). 설치된 훅 목록을 사용자에게 보고.

### 4. Claude Code 설정 검증

다음 항목을 점검하고 **결과만 보고** — 자동 수정은 안 함:

1. **`.claude/settings.json` 존재 + 유효 JSON**
   - 없으면: 안내 ("claude code가 자동 생성하니 첫 세션 후 다시 확인")
   - 잘못된 JSON: `python3 -m json.tool` 결과로 위치 보고

2. **MCP 서버 설정**
   - `.claude/settings.json`의 `mcpServers` 키를 확인
   - 또는 `~/.claude.json`에 정의된 user-level MCP
   - repo별 기대 서버:
     - studio: `playwright`(테스트), 옵션으로 `sediment-connect`(검색)
     - sediment: `sediment-connect` (자기 dogfood)
     - lab: `playwright`(qa-only 스킬용)
   - 누락된 critical server는 *안내만* — 자동 설치 X

3. **Vendored 콘텐츠 존재 확인**
   - `<path>/.claude/skills/skill-creator/SKILL.md` 존재 + `<path>/.claude/skills/skill-creator/HARNESS_VERSION` 존재
   - `<path>/docs/MEMBER-GUIDE.ko.md` 존재
   - 없으면: 누군가 vendoring 실패했다는 뜻 — Jay에게 보고

4. **`.claude/settings.local.json` 안내**
   - 있으면 "로컬 override 존재" 보고 (정상)
   - 없으면 "신규 멤버는 곧 생길 것" 안내 (정상)

### 5. 다음 단계 안내

```
✓ 셋업 완료 — <repo>

다음:
  1. cat <path>/docs/MEMBER-GUIDE.ko.md
     (한글 워크플로 가이드 — Claude Code에 "이 문서 따라줘"라고 하면 단계 실행)

  2. <path>/DEV-GUIDE.md (있다면 — studio엔 있음)
     스택·빌드·키 등 stack-specific 내용

  3. 첫 이슈 발행:
     - studio: cd <path> && claude → /report-ui
     - 그 외: gh issue create --repo jayleekr/<repo>

  4. 모르는 거 있으면 Discord 또는 @jayleekr 핑

이 스킬(onboard-member)은 1회성. 일상 작업은 cd <path>로 가서 새 Claude Code 세션 시작.
```

종료 시 사용자에게 "다른 consumer repo도 추가 셋업할래?" 물음 — 여러 repo 멤버는 반복 실행.

---

## Guardrails

- **재실행 안전 (idempotent)**: 이미 셋업된 환경엔 `git pull --ff-only`만 (mutating 변경 없음); git hooks도 이미 설정돼 있으면 no-op.
- **키 자동 저장 절대 X**: API 키·토큰은 사용자에게 안내·문서 링크만 제공. 환경변수·시크릿 파일은 사용자 본인이 처리.
- **harness 추가 clone 안내 안 함**: 이 스킬을 실행 중이라면 harness는 이미 clone돼 있음 (그 안에서 호출되므로). 일상 작업은 consumer에서.
- **자동 PR/이슈 생성 안 함**: 셋업은 read-only/local만. 첫 이슈는 멤버 본인이 발행 (워크플로 학습 목적).
- **언어**: 진행은 사용자 모국어(보통 한글). 출력 JSON/명령은 영문(repo 컨벤션).

---

## 실패 모드 / Failure modes

| 상황 | 대응 |
|---|---|
| SSH/HTTPS 권한 없음 | 사용자에게 안내 + Jay/JeHyeong 핑 권고. clone 단계에서 abort. |
| `--recursive` 실패 (vscodium-base, studio) | 부분 clone 수용 + "디스크 공간/속도 이슈인지 확인" 안내. 빌드는 별도 진행. |
| `git pull --ff-only` 실패 (consumer main 로컬 ahead) | 사용자에게 보고만, 자동 rebase/merge X. 본인이 처리. |
| Claude Code 설정 누락 | 보고만, 자동 생성 X. 첫 Claude Code 세션이 만들어주거나 별도 셋업. |
| 한 번도 본 적 없는 새 consumer repo | 매핑 외 입력은 거부, AskUserQuestion 재시도. |

---

## 참고 / References

- 한글 워크플로 가이드: 자기 consumer repo의 `docs/MEMBER-GUIDE.ko.md` (이 harness에서 vendoring됨)
- 토폴로지·시퀀스: `hypeprooflab:jay/reports/2026-05-19-repo-structure-diagram.html`
- Vendor 마이그레이션 보고서: `hypeprooflab:jay/reports/2026-05-20-vendor-migration.html`
