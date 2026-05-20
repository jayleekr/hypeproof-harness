# hypeproof-harness

HypeProof 멤버들이 **같은 방식으로 같이 일하기 위한** 공유 레이어.
`hypeproof-studio` · `sediment` · `hypeprooflab` 세 repo가 공유 스킬과
협업 규약을 여기서 가져간다.

> **배포 모델 (2026-05-20부터)**: 서브모듈이 아니라 **vendored 실파일**.
> 각 repo의 `.claude/skills/skill-creator/`는 이 repo의 같은 경로에서
> 복사된 실파일이고, `HARNESS_VERSION` 파일이 어느 harness SHA에서
> 복사됐는지 기록한다. 배경/근거는 §1, 동기화는 §2, 테스트 합격선은
> [tests/REQUIREMENTS.md](./tests/REQUIREMENTS.md), 롤백은
> [docs/rollback-vendor.md](./docs/rollback-vendor.md).

<details><summary>English</summary>

Shared collaboration layer for HypeProof members. Three repos —
`hypeproof-studio`, `sediment`, `hypeprooflab` — vendor the shared skill
into their own tree as real files; `HARNESS_VERSION` records the
provenance SHA. **Submodule architecture was retired 2026-05-20**
(see §1). Sync: §2. Test contract: `tests/REQUIREMENTS.md`. Rollback:
`docs/rollback-vendor.md`.
</details>

---

## 1. 무엇이 공유되나 / What's shared here

| Path | 목적 |
|---|---|
| `skills/skill-creator/` | 새 스킬을 만들고 고치고 평가하는 generic 툴킷. 결합도 0(검증) |

스킬은 이거 하나다. PR/이슈 스킬(`hype-open-pr`·`report-ui`)은 studio 환경에
구조적으로 결합돼서 studio-local로 둔다. 추가 generic 스킬이 검증되면 여기로.

`.github` 이슈/PR 템플릿이나 `human-needed` 라벨 정책 같은 **non-skill**
협업 규약은 글로 §3–§6에 적힌다 — GitHub이 서브모듈/심링크 템플릿을 안
따라가므로 파일로 공유되지 않는다.

<details><summary>English</summary>

One generic skill (`skill-creator`, zero repo coupling — verified by T6
portability test). PR/issue skills are studio-coupled, kept studio-local.
Non-skill conventions are prose in §3–§6.
</details>

---

## 2. 동기화 / Sync (vendor 운영)

### 멤버 입장 — 그냥 clone하면 끝

```bash
git clone git@github.com:jayleekr/<repo>.git
cd <repo>
# 별도 셋업 필요 없음. .claude/skills/skill-creator/ 가 이미 실파일로 존재.
```

서브모듈 init 같은 거 없다. `git submodule update --init` 결과도 no-op
(서브모듈 자체가 없음). Vercel/CI도 영향 없음.

### 운영자 입장 — skill-creator를 업데이트할 때

1. 이 repo(`hypeproof-harness`)에서 `skills/skill-creator/`를 편집·커밋·push
2. 동기 스크립트 실행:
   ```bash
   bash scripts/sync.sh --check         # 어느 consumer가 drift하는지 보기 (read-only)
   bash scripts/sync.sh                  # apply: rsync 캐노니컬→ 각 consumer
   bash scripts/sync.sh --commit         # apply + 각 consumer의 main에 커밋 (push는 별도)
   ```
3. 각 consumer repo로 가서 `git push` (또는 PR)

소비 repo 경로는 [`tests/consumers.txt`](./tests/consumers.txt)에 있다. 머신마다
다르면 환경변수로 오버라이드: `CONSUMER_hypeproof_studio=/path bash scripts/sync.sh`
(이름의 하이픈은 언더스코어로).

### 가드레일

- `--commit`은 consumer가 `main` 위에 있고 skill-creator 외 staged 변경이
  없을 때만 진행. 우회 = `ALLOW_ANY_BRANCH=1`.
- `--commit`은 commit 신원을 **그 repo의 ambient git config로 사용**한다 —
  스크립트가 user.name을 절대 override 안 함.
- rsync `--delete`가 consumer-side에 추가된 파일을 지우려 하면 abort. 강제 =
  `--force-delete` 명시.

### 누가 / 언제

- **누가**: 메인테이너(Jay)가 기본 owner. 다른 멤버가 운영 가능하지만
  변경은 모두 PR/리뷰 후에 sync 실행.
- **언제**: harness `main` push 후 즉시. CI 자동화(harness → consumer
  drift 알림 / 자동 PR 열기)는 향후 작업.

<details><summary>English</summary>

**Members**: just `git clone <repo>`; no setup. The vendored skill is
already a real directory in `.claude/skills/skill-creator/`.

**Operators** (updating skill-creator):
1. edit and push `skills/skill-creator/` in this repo
2. `bash scripts/sync.sh --check` to preview drift, `--commit` to apply
   and create commits in each consumer using **the consumer's own git
   identity** (the script never overrides `user.name`)
3. push each consumer

Consumer paths: `tests/consumers.txt`. Per-machine override:
`CONSUMER_<basename-with-underscores>=/abs/path`.

Guardrails: refuses if not on `main` (override: `ALLOW_ANY_BRANCH=1`),
refuses if there are unrelated staged changes, refuses to `--delete`
files only present in consumer (override: `--force-delete`).
</details>

---

## 3. 같이 일하는 흐름 / How we work together

회의 2026-05-18 결정한 5단계. **모든 코드 변경이 이 길로만 main에 들어간다.**

```
이슈 발행 → 브랜치 → 커밋·테스트 → PR(템플릿) → merge → 이슈 자동 close
```

### 3.1 이슈 먼저
모든 변경은 GitHub 이슈에서 출발. studio UI에서 발견했으면 `/report-ui`로,
다른 repo는 그 repo의 이슈 폼.

> **휴먼 vs AI**: 이슈에 `human-needed` 라벨이 붙으면 사람 처리. 없으면
> AI(Claude Code) 자동 해결 시도 가능. 기준은 **지용 소유 (5/21 마감)**.

### 3.2 브랜치 이름

| 종류 | 이름 |
|---|---|
| 버그 픽스 | `fix/issue-<N>-<slug>` |
| 새 기능 | `feat/issue-<N>-<slug>` |
| 문서 | `docs/issue-<N>-<slug>` |
| chore | `chore/<topic>` |

`main` 직접 push 금지 — 메인테이너 전용. 가드: `.githooks/pre-push` + CI
`main-guard`(소프트 — 우회 가능, 빨간 빌드).

### 3.3 PR

studio면 `/hype-open-pr`. 다른 repo면 `gh pr create --fill --base main`.

**정책: PR 필수, 리뷰 선택.** 자신 있으면 셀프머지 OK. 단 *이 harness repo의
변경은 회의 룰상 **항상 피어리뷰*** (3 repo가 공유하므로).

### 3.4 PR 본문 필수

- `Closes #<N>` — 머지 시 이슈 auto-close
- What & why — 한 단락
- Tested — §4의 무엇이 통과했는지

### 3.5 머지 후

- 브랜치 삭제 (`gh pr merge --delete-branch`)
- 이슈는 auto-close

<details><summary>English</summary>

5-step lifecycle agreed 2026-05-18. **The only path to main.**

```
file issue → branch → commit & test → PR (template) → merge → auto-close
```

`human-needed` label = human required. Absent = AI may try. Criteria
owned by 지용 (due 5/21). Branch naming: `fix/issue-<N>-<slug>`,
`feat/...`, `docs/...`, `chore/<topic>`. **PR-first, review optional**;
exception: changes to this harness repo are always peer-reviewed.
PR body essentials: `Closes #<N>`, what & why, Tested. After merge:
delete the branch.
</details>

---

## 4. 테스트 게이트 / Test gate

repo별 스택에 묶여 있다 — 각자 자기 repo의 테스트 규약을 따른다:

| repo | 어디 | 머지 게이트 |
|---|---|---|
| `hypeproof-studio` | `e2e/` (Playwright + Electron) | `main-guard.yml` |
| `sediment` | `services/sediment/validator/` | rubric 점수 |
| `hypeprooflab` | `qa`/`qa-only` 스킬 · `healthcheck` | `ci.yml` |

공유 룰: **자기 변경 영역에 해당하는 테스트가 통과 안 되면 머지 안 한다.**

추가로 vendor 동기화 자체의 합격선은 [`tests/REQUIREMENTS.md`](./tests/REQUIREMENTS.md)
의 T-V1..T-V10. 운영자가 sync 후 또는 의심될 때 `bash tests/run.sh` 실행.

<details><summary>English</summary>

Stack-bound, per-repo. Shared rule: don't merge with red tests in the
area you touched. Additionally, vendor-sync correctness is covered by
T-V1..T-V10 in `tests/REQUIREMENTS.md`; operators run `bash tests/run.sh`
after sync or whenever in doubt.
</details>

---

## 5. 병행 작업 / Parallel work

```bash
claude -w issue-12         # 이슈 #12용 새 worktree + 세션
claude -w issue-15 --tmux  # 또 다른 worktree
```

흐름은 §3과 동일. worktree는 `.claude/worktrees/`(gitignored)에 두면 깔끔.
repo별 함정은 각자 DEV-GUIDE의 worktree 섹션 참고.

<details><summary>English</summary>

`claude -w issue-N`. Same flow as §3. Per-repo gotchas in each repo's
DEV-GUIDE.
</details>

---

## 6. 가드레일 / Guardrails

- **시크릿 절대 커밋 금지**. 새면 Jay에게 알려 로테이션 — 드라마 X.
- **main 직접 push 금지** (메인테이너 제외). PR로만.
- **`human-needed` 라벨로 AI/사람 처리 구분.** 기준 = 지용 5/21.
- **하네스 스킬은 `/skill-creator`로만** 만들고 고친다 (직접 SKILL.md 쓰지 말 것).
- **이 repo 변경은 항상 피어리뷰.**

<details><summary>English</summary>

No secrets · no direct main push · `human-needed` label · skills via
`/skill-creator` only · harness changes always peer-reviewed.
</details>

---

## 7. 멤버 / Team

| Name | GitHub | Note |
|---|---|---|
| Jae Won (Jay) Lee | [@jayleekr](https://github.com/jayleekr) | Maintainer |
| Shin Jehyeong | [@JeHyeong2](https://github.com/JeHyeong2) | Co-maintainer |
| Bongho Tae | [@xoqhdgh1002](https://github.com/xoqhdgh1002) | Curriculum |
| Jinyong Shin | [@JinyongShin](https://github.com/JinyongShin) | Engineering |
| Taejin Kang (TJ) | [@TJ-kr](https://github.com/TJ-kr) | GTM |
| Jkim | [@ico1036](https://github.com/ico1036) | Contributor |

Ryan/Kiwon/JUNGWOO는 GitHub 아이디 매핑 미완.

<details><summary>English</summary>

Current collaborators. Ryan/Kiwon/JUNGWOO not yet GitHub-mapped.
</details>

---

## 8. 어디서 무엇을 찾나 / Pointers

- 각 repo 스택·빌드·키: 그 repo의 `DEV-GUIDE.md` / `CONTRIBUTING.md`
- studio 페이즈/게이트: `METAPLAN.md` · 16 Essences: `docs/essence-v0.1.md`
- 토폴로지/시퀀스/마일스톤 플랜:
  `hypeprooflab:jay/reports/2026-05-19-repo-structure-diagram.html`
- **Vendor 마이그레이션 보고서**:
  `hypeprooflab:jay/reports/2026-05-20-vendor-migration.html`
- Vendor 테스트 합격선: [tests/REQUIREMENTS.md](./tests/REQUIREMENTS.md)
- Vendor 롤백 절차: [docs/rollback-vendor.md](./docs/rollback-vendor.md)
