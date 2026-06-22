# HypeProof 공통 에이전트 가이드

> **출처(provenance)**: `jayleekr/hypeproof-harness:docs/AGENT-GUIDE.ko.md`
> 의 vendored 사본. 직접 수정하지 말 것 — 변경은 harness에서 PR로.

이 문서는 Claude Code, Codex, OpenClaw 등 코딩 에이전트가 공통으로 따라야
하는 팀 규약이다. 에이전트별 루트 파일(`CLAUDE.md`, `AGENTS.md`,
`OPENCLAW.md`)은 이 문서를 첫 진입점으로 삼고, repo별 세부 규칙만 각 repo
문서에 둔다.

---

## 1. 우선순위

1. 사용자의 최신 지시
2. 현재 repo의 에이전트별 루트 파일 (`CLAUDE.md`, `AGENTS.md`, `OPENCLAW.md`)
3. 이 공통 가이드
4. repo의 `README.md`, `DEV-GUIDE.md`, `docs/` 문서
5. 코드와 테스트가 보여주는 실제 동작

충돌하면 더 구체적이고 더 최근의 지시를 따른다. 단, 시크릿 노출, 무단
destructive 명령, 사용자 변경 되돌리기는 하지 않는다.

## 2. 작업 흐름

모든 코드 변경은 다음 흐름을 기본으로 한다.

```text
이슈 발행 -> 브랜치 생성 -> 수정 -> 테스트 -> PR -> merge
```

- 이슈가 없으면 먼저 만든다.
- 브랜치는 `fix/`, `feat/`, `docs/`, `chore/` 중 하나로 시작한다.
- PR 본문에는 `Closes #<issue-number>` 또는 동등한 자동 close 문구를 넣는다.
- `main` 직접 push는 메인테이너가 명시한 경우에만 한다.
- harness 변경은 세 consumer repo에 영향을 줄 수 있으므로 더 좁고 검증 가능한
  변경으로 유지한다.

## 3. 리뷰와 배포 권한

리뷰 요청과 배포 권한은 repo마다 다르게 해석하지 않는다.

- PR은 작성자를 제외한 활성 멤버 전원을 reviewer로 요청한다. 현재 활성 멤버는
  `@jayleekr`, `@JeHyeong2`, `@ico1036`, `@xoqhdgh1002`, `@JinyongShin`,
  `@TJ-kr`이다.
- GitHub가 작성자 본인이나 권한 없는 계정을 reviewer로 받을 수 없으면 PR 본문이나
  코멘트에 예외 사유를 남긴다.
- production 배포 권한은 repo 정책에 명시된 trusted workflow가 가진다. 기본값은
  `main` merge 후 GitHub Actions가 배포하는 방식이다.
- Vercel, Fly, Cloudflare 같은 provider의 Git 자동 배포는 repo 정책과 repo-local
  설정 파일에 명시되어야 한다. 개인/private scope에서 contributor commit을 자동
  preview/deploy하게 두지 않는다.
- 수동 CLI 배포는 기본 경로가 아니다. 사고 복구나 긴급 hotfix일 때만 maintainer가
  승인하고, 이슈/PR에 실행자, 이유, 대상 URL, 결과를 기록한다.
- repo visibility, provider project scope, deploy secret, deploy trigger를 바꾸는 PR은
  같은 PR에서 `policy/`와 해당 repo의 root agent 문서를 함께 갱신한다.

## 4. Vendored 파일

다음 파일/디렉토리는 harness에서 consumer repo로 복사되는 공유 자산이다.

- `.claude/skills/skill-creator/`
- `scripts/notify/`
- `docs/MEMBER-GUIDE.ko.md`
- `docs/AGENT-GUIDE.ko.md`
- `CLAUDE.md` (없으면 seed, 있으면 보존 + 이 문서 참조)
- `AGENTS.md` (없으면 seed, 있으면 보존 + 이 문서 참조)
- `OPENCLAW.md` (없으면 seed, 있으면 보존 + 이 문서 참조)

consumer repo 안에서 vendored 디렉토리와 문서는 직접 고치지 않는다. 루트
에이전트 파일은 repo별 규칙을 담을 수 있으므로 기존 내용을 보존하되, 반드시
이 공통 가이드를 참조하게 한다. 공통 규칙을 고쳐야 하면 `hypeproof-harness`에서
PR을 만들고, 메인테이너가 `scripts/sync.sh`로 consumer에 반영한다.

## 5. 에이전트별 역할

### Claude Code

- Claude Code 스킬은 `.claude/skills/`에서 발견된다.
- 공통 스킬인 `skill-creator`는 harness에서 vendoring된다.
- repo별 Claude 전용 규칙이 필요하면 `CLAUDE.md`에 짧게 두고, 공통 규칙은 이
  문서로 링크한다.

### Codex

- Codex는 repo 루트의 `AGENTS.md`를 우선 진입점으로 사용한다.
- `AGENTS.md`는 공통 규칙을 복사하지 말고 이 문서를 참조한다.
- 구현 전에는 파일 구조와 기존 테스트를 먼저 읽고, 수정은 최소 범위로 둔다.

### OpenClaw

- OpenClaw용 루트 진입점은 `OPENCLAW.md`로 둔다.
- OpenClaw가 다른 파일명을 요구하면 해당 repo에서 얇은 alias 파일만 추가하고,
  본문은 이 문서를 참조하게 한다.

## 6. 안전 규칙

- 시크릿, 토큰, `.env`, 운영 키는 커밋하지 않는다.
- 사용자나 다른 에이전트가 만든 변경을 되돌리지 않는다.
- `git reset --hard`, 대량 삭제, 강제 push는 사용자가 명시한 경우에만 한다.
- 테스트나 sync가 실제 consumer repo를 수정할 수 있으면 명령의 범위를 먼저
  확인한다.
- 불확실한 외부 사실이나 최신 정책은 확인한 뒤 쓴다.
- 배포 설정을 바꿀 때는 provider dashboard의 숨은 상태만 믿지 말고 repo 파일,
  GitHub Actions, policy 선언이 같은 말을 하는지 확인한다.

## 7. 검증

harness 변경 시 기본 검증은 다음이다.

```bash
bash -n scripts/sync.sh
bash -n tests/run.sh
bash tests/run.sh
```

consumer가 로컬에 없거나 아직 새 vendored 파일을 받지 않은 경우에는 CI와 같은
mock consumer 워크스페이스로 검증한다.

```bash
mkdir -p /tmp/ws/hypeproof-studio /tmp/ws/sediment /tmp/ws/hypeprooflab
for d in /tmp/ws/*; do
  git -C "$d" init -q -b main
  git -C "$d" -c user.email=ci@example.com -c user.name=CI commit --allow-empty -q -m init
done
HYPEPROOF_WORKSPACE=/tmp/ws bash scripts/sync.sh
HYPEPROOF_WORKSPACE=/tmp/ws bash tests/run.sh
```
