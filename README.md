# hypeproof-harness

HypeProof 멤버들이 **같은 방식으로 같이 일하기 위한** 공유 레이어.
`hypeproof-studio` · `sediment` · `hypeprooflab` 세 repo가 이걸
서브모듈(`.harness`)로 들여와 같은 스킬과 같은 협업 규약을 쓴다.

이 문서는 **Claude Code로 그대로 실행**할 수 있게 쓰여 있다. 컨트리뷰터는
Claude Code에게 *"harness README §N 따라줘"* 라고 하면 된다. 각 단계가
"알아내기"가 아니라 "이 명령 실행"이다.

<details><summary>English</summary>

The shared collaboration layer for HypeProof members. Three repos —
`hypeproof-studio`, `sediment`, `hypeprooflab` — consume it as a git
submodule (`.harness`) so they use the same skill and the same workflow.

Written to be run by Claude Code. Tell it *"follow harness README §N"*
and each step executes through pre-built harness. Every step is "run
this", not "figure this out".
</details>

---

## 0. 전제 / Prerequisites

- **Claude Code를 쓴다고 가정.** 모든 단계가 Claude Code 실행 기준.
- 세 repo 중 하나 이상에 접근 권한 + `hypeproof-harness` 접근 권한 + GitHub
  계정.
- repo별 스택 셋업(빌드·키·서비스)은 각 repo의 `DEV-GUIDE.md` /
  `CONTRIBUTING.md` 참고. 이 문서는 **그 위에 올라가는 공통 규약**.

<details><summary>English</summary>

- Assumes Claude Code; every step is phrased for it.
- Access to at least one of the three repos + `hypeproof-harness` + a
  GitHub account.
- Per-repo stack setup (build / keys / services) lives in that repo's
  `DEV-GUIDE.md` / `CONTRIBUTING.md`. This doc is the **shared layer on
  top of those**.
</details>

---

## 1. 무엇이 공유되나 / What's shared here

| Path | 목적 / Purpose |
|---|---|
| `skills/skill-creator/` | 새 스킬을 만들고 고치고 평가하는 generic 툴킷. 모든 멤버가 `/skill-creator`로 호출 |

스킬은 이거 하나다 — `hype-open-pr` · `report-ui` 같은 PR/이슈 스킬은 studio
내부 의존이 너무 커서 studio-local로 둔다. 새로 generic 스킬이 검증되면
여기 추가.

`.github` 이슈/PR 템플릿, `human-needed` 라벨 정책 등 **non-skill** 협업 규약은
이 문서(§3–§5)에 글로 적혀 있다 — GitHub이 서브모듈 심링크 템플릿을 안
따라가므로 파일 형태로 공유 안 함.

<details><summary>English</summary>

Just one skill — `hype-open-pr` / `report-ui` are too coupled to studio
to share. As more generic skills prove out, they land here.

Non-skill conventions (`.github` templates, label policy, etc.) live as
**prose in this doc** — GitHub doesn't follow submodule symlinks for
templates, so they aren't shared as files.
</details>

---

## 2. 한 번에 셋업 / One-command setup

소비 repo를 clone할 때:

```bash
git clone --recursive git@github.com:jayleekr/<repo>.git
cd <repo>
# 그 repo의 setup 스크립트가 있다면 실행 (예: studio는 scripts/setup.sh)
```

이미 clone돼 있고 submodule이 비어 있으면:

```bash
git submodule update --init .harness
```

그 다음 그 repo의 `.claude/skills/skill-creator` 심링크가
`.harness/skills/skill-creator`로 풀리고, Claude Code 세션에서 `/skill-creator`로
바로 쓸 수 있다.

<details><summary>English</summary>

When cloning a consumer repo, use `--recursive`. If already cloned and
the submodule is empty: `git submodule update --init .harness`. The
repo's `.claude/skills/skill-creator` symlink resolves into the harness,
and Claude Code picks the skill up automatically.
</details>

---

## 3. 같이 일하는 흐름 / How we work together

회의 2026-05-18 결정한 5단계. **모든 코드 변경이 이 길로만 main에 들어간다.**

```
이슈 발행 → 브랜치 → 커밋·테스트 → PR(템플릿) → merge → 이슈 자동 close
```

### 3.1 이슈 먼저 (Issue first)
모든 변경은 GitHub 이슈에서 출발. UI에서 발견한 거면 studio의 `/report-ui`로
(스크린샷·환경 자동 첨부). 그 외는 각 repo의 이슈 폼.

> **휴먼 vs AI**: 이슈에 `human-needed` 라벨이 붙으면 사람이 처리해야 함.
> 라벨 안 붙어 있으면 AI(Claude Code)가 자동 해결 시도 가능. 어떤 이슈에
> `human-needed`가 붙어야 하는지의 기준은 **지용 소유 (5/21 마감)**.

### 3.2 브랜치 이름 (Branch naming)

| 종류 | 이름 |
|---|---|
| 버그 픽스 | `fix/issue-<N>-<slug>` |
| 새 기능 | `feat/issue-<N>-<slug>` |
| 문서 | `docs/issue-<N>-<slug>` |

`main`에 직접 푸시 금지 — 메인테이너 전용. 로컬 `pre-push` 가드와 CI
`main-guard`로 막혀 있다 (소프트 가드 — 우회 가능하지만 빨간 빌드).

### 3.3 PR 만들기 (Open the PR)

studio면 `/hype-open-pr` 스킬 (스크립트 + 본문 대화형 채움). 다른 repo면
직접 `gh pr create --fill --base main` 또는 그 repo의 PR 스크립트.

**정책: PR 필수, 리뷰 선택.** 모든 변경은 PR로 들어간다. 리뷰는 의무
아님 — 자신 있으면 머지 가능. *단 하나 예외*: 이 harness repo의 변경은
회의 룰상 **항상 피어리뷰** (3 repo가 공유하니까).

### 3.4 PR 본문 필수 항목 (PR body essentials)

- **`Closes #<N>`** — 머지 시 이슈 자동 close
- **What & why** — 한 단락
- **Tested** — §4(테스트)에서 무엇이 통과했는지

### 3.5 머지 후 (After merge)

- 브랜치 삭제 (`gh pr merge --delete-branch` 또는 GitHub UI)
- 이슈는 자동 close됨

<details><summary>English</summary>

The 5-step lifecycle agreed 2026-05-18. **All code changes reach main
only via this path.**

```
file issue → branch → commit & test → PR (template) → merge → issue auto-closes
```

1. **Issue first.** Studio UI finds use `/report-ui`; others use the
   repo's issue forms.
   - `human-needed` label = a human must handle; absent = AI may try.
     Criteria owned by 지용 (due 5/21).
2. **Branch naming**: `fix/issue-<N>-<slug>` · `feat/issue-<N>-<slug>` ·
   `docs/issue-<N>-<slug>`. No direct main push (maintainer-only;
   `pre-push` + `main-guard` CI are the soft guards).
3. **Open the PR.** Studio: `/hype-open-pr`. Others: `gh pr create
   --fill --base main` or per-repo script. **Policy: PR-first, review
   optional.** Exception: changes to this harness repo are
   **always peer-reviewed** (three repos consume it).
4. **PR body essentials**: `Closes #<N>` · what & why · what tested.
5. **After merge**: delete the branch; issue auto-closes.
</details>

---

## 4. 테스트 게이트 / Test gate

테스트는 repo별 스택에 묶여 있다. **각자 자기 repo의 테스트 규약**을 따른다:

| repo | 어디 | 머지 게이트 |
|---|---|---|
| `hypeproof-studio` | `e2e/` (Playwright + Electron) | `main-guard.yml` |
| `sediment` | `services/sediment/validator/` | rubric 점수 |
| `hypeprooflab` | `qa`/`qa-only` 스킬 · `healthcheck` | `ci.yml` |

공유 룰은 단 하나: **자기 변경 영역에 해당하는 테스트가 통과 안 되면
머지 안 한다.** PR 본문 `Tested:` 칸에 무엇을 돌렸는지 적는다.

<details><summary>English</summary>

Tests are stack-bound and per-repo. One shared rule: **don't merge with
tests red in the area you touched.** Record what you ran in `Tested:`.
</details>

---

## 5. 병행 작업 / Parallel work

이슈 여러 개 동시에 굴릴 땐 **Claude Code 네이티브 worktree**:

```bash
claude -w issue-12         # 이슈 #12용 새 worktree + 세션
claude -w issue-15 --tmux  # 또 다른 이슈를 별도 worktree(+tmux 패널)
```

흐름은 §3과 동일. worktree 디렉토리는 `.claude/worktrees/`에 두면 깔끔
(gitignored).

> 함정: 각 repo가 자기 스택의 함정이 있다 (studio는 port 8787, sediment는
> Fly proxy, 등). 자기 repo의 DEV-GUIDE worktree 섹션 참고.

<details><summary>English</summary>

Run several issues in parallel with Claude Code's native worktree
(`claude -w issue-N`). Same flow as §3. Per-repo stack gotchas live in
that repo's DEV-GUIDE.
</details>

---

## 6. 가드레일 / Guardrails

전 repo 공통, 어겨선 안 됨:

- **시크릿 절대 커밋 금지.** 키·토큰·`.dev.vars`·`/tmp` 경로 dump 금지.
  `/report-ui`·`/collect-studio-env`는 설계상 시크릿 비포함. 새면 즉시
  Jay에게 알려 로테이션.
- **main 직접 푸시 금지** (메인테이너 제외). PR로만.
- **AI가 처리할 수 있는 이슈와 사람만 할 수 있는 이슈를 라벨로 구분**한다
  (`human-needed`). 라벨 기준은 5/21 지용이 확정.
- **하네스 스킬은 `/skill-creator`로만** 만들고 고친다. 직접 SKILL.md를
  손으로 쓰지 않음.
- **이 repo(`hypeproof-harness`) 변경은 항상 피어리뷰.** 3 repo가 공유.

<details><summary>English</summary>

- **Never commit secrets.** `/report-ui` / env collectors are designed
  to be secret-free; if a key leaks, tell Jay to rotate.
- **No direct main push** (maintainer only). PRs only.
- **Label issues `human-needed` vs auto-resolvable** (policy due 5/21).
- **Skills are created/edited only via `/skill-creator`.**
- **Harness changes are always peer-reviewed** — three repos consume it.
</details>

---

## 7. 멤버 / Team

현재 컨트리뷰터 — 자세한 롤은 각 repo의 `CONTRIBUTORS.md` 참고:

| Name | GitHub | Note |
|---|---|---|
| Jae Won (Jay) Lee | [@jayleekr](https://github.com/jayleekr) | Maintainer |
| Shin Jehyeong | [@JeHyeong2](https://github.com/JeHyeong2) | Co-maintainer (sediment·lab) |
| Bongho Tae | [@xoqhdgh1002](https://github.com/xoqhdgh1002) | Curriculum |
| Jinyong Shin | [@JinyongShin](https://github.com/JinyongShin) | Engineering |
| Taejin Kang (TJ) | [@TJ-kr](https://github.com/TJ-kr) | GTM |
| Jkim | [@ico1036](https://github.com/ico1036) | Contributor |

(Ryan/Kiwon/JUNGWOO는 아직 어떤 repo에도 컬래보레이터로 추가되지 않음 —
GitHub 아이디 매핑 미완.)

<details><summary>English</summary>

Current collaborators (full roles in each repo's `CONTRIBUTORS.md`).
Ryan/Kiwon/JUNGWOO are not yet GitHub-mapped on any repo.
</details>

---

## 8. 어디서 무엇을 찾나 / Pointers

- 각 repo의 스택·빌드·키: 그 repo의 `DEV-GUIDE.md` / `CONTRIBUTING.md`
- studio의 페이즈/게이트: `METAPLAN.md`
- 16 Essences (제품 철학): studio `docs/essence-v0.1.md`
- 토폴로지 / 시퀀스 / 마일스톤 플랜:
  `hypeprooflab:jay/reports/2026-05-19-repo-structure-diagram.html`
