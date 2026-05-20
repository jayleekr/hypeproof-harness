<h1 align="center">hypeproof-harness</h1>

<p align="center">
  <b>HypeProof Lab의 AI-네이티브 워크플로 중심.</b><br>
  Claude Code로 일하는 작은 팀이 같은 방식으로 움직이기 위한 공유 OS.
</p>

<p align="center">
  <code>private</code> · <code>Claude Code</code> · <code>macOS · Linux · WSL2</code> · <code>2026-05</code>
</p>

---

## Why this exists

> HypeProof는 AI-네이티브 회사다. Claude Code가 우리의 IDE이고,
> 회의록·이슈·PR은 소스 코드만큼 중요한 자산이다. 4개 repo로 일하는
> 작은 팀이 **같은 방식으로** 움직이려면 — 같은 스킬, 같은 이슈 흐름,
> 같은 라벨 정책, 같은 온보딩 — 한 곳에 박혀 있어야 한다.
>
> **여기가 그 한 곳이다.**

3개의 product repo(`hypeproof-studio`, `sediment`, `hypeprooflab`)는 각자의
도메인을 책임진다. 이 harness는 그 세 repo가 **동일한 협업 OS를 공유하도록
보장한다** — vendoring 메커니즘으로 코드는 각자, 워크플로는 하나.

---

## What's in here

| 자산 | 무엇 | 어디로 vendored |
|---|---|---|
| `skills/skill-creator/` | Claude Code 스킬을 만들고 평가하는 generic 툴킷 | → 3 consumers `.claude/skills/` |
| `skills/onboard-member/` | 신규 멤버 1회성 셋업 인터랙티브 스킬 | (harness-local) |
| `docs/MEMBER-GUIDE.ko.md` | 한글 멤버 워크플로 가이드 (5단계 lifecycle) | → 3 consumers `docs/` |
| `scripts/sync.sh` | 캐노니컬 → consumer 동기 (`--check` / apply / `--commit`) | (maintainer) |
| `tests/REQUIREMENTS.md` + `tests/run.sh` | T-V1..T-V10 vendor 정합성 검증 | (maintainer) |
| `docs/rollback-vendor.md` | 5분 안에 submodule 모델로 돌아가는 7-step 런북 | (maintainer) |

명시적으로 **공유 안 하는 것**: studio-local 규칙(`branding-swap`, `build-pipeline`,
`extension-dev`), `e2e/` 흐름, `vscodium-base` 서브모듈, 각 repo의 `.github/`
템플릿(GitHub가 submodule 심링크 템플릿을 안 따라가므로 vendor 불가).

---

## Quick start

### 👥 신규 멤버 — 1회성 온보딩

```bash
git clone git@github.com:jayleekr/hypeproof-harness.git
cd hypeproof-harness && claude
```

Claude Code 세션에서:

```
/onboard-member
```

스킬이 인터랙티브하게 진행한다:
1. **플랫폼 점검** — macOS / Linux / WSL2 / Windows native 판정
2. **어느 consumer repo의 멤버인지** — studio · sediment · lab 중 선택
3. **워크스페이스 경로** — `$HYPEPROOF_WORKSPACE` env, `~/code`, `~/dev`,
   `~/CodeWorkspace` 등 자기 컨벤션 그대로 (강제 X)
4. **clone + git hooks + Claude Code 설정 검증**
5. 자기 repo의 `docs/MEMBER-GUIDE.ko.md`로 안내

키/토큰은 자동 저장 X (안내만). 재실행 안전(idempotent).

> 자세한 워크플로 가이드는 [`docs/MEMBER-GUIDE.ko.md`](docs/MEMBER-GUIDE.ko.md) —
> 멤버에게 vendoring되므로 자기 consumer repo에서도 같은 파일을 볼 수 있다.

### 🛠 메인테이너 — 공유 콘텐츠 업데이트

```bash
# 1. canonical 편집
vim skills/skill-creator/SKILL.md     # 또는 docs/MEMBER-GUIDE.ko.md
git commit && git push origin main

# 2. 모든 consumer로 동기
bash scripts/sync.sh --check          # drift 미리보기 (read-only)
bash scripts/sync.sh --commit         # rsync + 각 consumer main에 커밋
                                       # (git 신원: consumer의 ambient config)

# 3. 각 consumer push (또는 PR — harness 변경은 피어리뷰 권장)
```

**가드레일** (CR 시리즈 비판 반영):
- `--commit`은 main 위 + skill 외 변경 없을 때만 (`ALLOW_ANY_BRANCH=1` 우회)
- 신원은 consumer의 ambient git config 사용 — 스크립트가 override 안 함
- `rsync --delete`가 consumer-only 파일 노릴 때 abort (`--force-delete` 강제)

### 🔁 다른 머신에서 운영 (CONSUMER_* env override)

```bash
CONSUMER_hypeproof_studio=/abs/path/to/local/clone \
CONSUMER_sediment=/abs/path/to/sediment \
  bash scripts/sync.sh --check
```

`-`은 env 변수명에서 `_`로 정규화됨 (`hypeproof-studio` → `hypeproof_studio`).

---

## How it works

```
                    ┌──────────────────────────────────┐
                    │      hypeproof-harness           │
                    │      ─────────────────           │
                    │   canonical shared content       │
                    │   + onboarding skill             │
                    │   + sync/test tooling            │
                    └──────────────┬───────────────────┘
                                   │  scripts/sync.sh
                                   │  (rsync + git commit, vendored real files)
                                   ▼
              ┌────────────────┬───┴────────────┬──────────────────┐
              │                │                │                  │
              ▼                ▼                ▼                  
       hypeproof-studio    sediment        hypeprooflab        
       VSCodium fork ·     knowledge DB    공개 사이트 +       
       워크숍 도구          / SaaS          콘텐츠/운영         
```

세 consumer는 같은 `skill-creator`·같은 `MEMBER-GUIDE`·같은 이슈/PR 컨벤션을
공유한다. **차이는 각자의 도메인 코드뿐.** 멤버는 자기 consumer repo만
신경 쓰면 된다 (이 harness는 메인테이너가 갱신).

설계 결정의 근거 (왜 submodule 대신 vendor):
[`jay/reports/2026-05-20-vendor-migration.html`](https://github.com/jayleekr/hypeprooflab/blob/main/jay/reports/2026-05-20-vendor-migration.html)

---

## Platform support

| OS | 멤버 온보딩 | Studio 로컬 빌드 | Sediment / Lab |
|---|:---:|:---:|:---:|
| **macOS** arm64 | ✅ Primary | ✅ Only supported | ✅ |
| **Linux** | ✅ Works | ❌ METAPLAN §0 | ✅ |
| **Windows** native | ⚠ unsupported | ❌ | ⚠ unsupported |
| **Windows** + WSL2 | ✅ Recommended | ❌ | ✅ |

워크스페이스 경로(`$WS`)는 자기 컨벤션 그대로 — `~/CodeWorkspace`,
`~/code`, `~/dev`, `~/projects` 등 무엇이든. `/onboard-member`가 묻는다.

---

## Conventions

> 자세한 5단계 lifecycle (이슈 → 브랜치 → 커밋·테스트 → PR → merge):
> [`docs/MEMBER-GUIDE.ko.md §4`](docs/MEMBER-GUIDE.ko.md).

핵심 규칙 — 어기지 않음:

- **PR-first, review optional** · `main` 직접 push 금지 (메인테이너 제외)
- **`human-needed` 라벨**로 AI 자동처리 vs 사람 필요 구분 (policy owner: 지용)
- **스킬은 `/skill-creator`로만** 만들고 고친다 · SKILL.md 직접 손쓰지 말 것
- **이 repo 변경은 항상 피어리뷰** — 3 consumer가 공유하므로
- **시크릿 절대 커밋 금지** — 새면 Jay에게 알려 즉시 로테이션

---

## Team & access

| | GitHub | role | note |
|---|---|---|---|
| Jay Lee | [`@jayleekr`](https://github.com/jayleekr) | `admin` | maintainer |
| Jehyeong Shin | [`@JeHyeong2`](https://github.com/JeHyeong2) | `admin` | co-maintainer |
| Bongho Tae | [`@xoqhdgh1002`](https://github.com/xoqhdgh1002) | `write` | onboarding + 기여 |
| Jinyong Shin | [`@JinyongShin`](https://github.com/JinyongShin) | `write` | onboarding + 기여 |
| TJ Kang | [`@TJ-kr`](https://github.com/TJ-kr) | `write` | onboarding + 기여 |
| Jkim | [`@ico1036`](https://github.com/ico1036) | `write` | onboarding + 기여 |

멤버는 **1회 온보딩**에 한해 이 repo를 clone한다. 일상 작업은 자기 consumer
repo에서. shared 콘텐츠를 함께 개선하고 싶으면 PR로 — 피어리뷰 후 머지.

---

## Reference

- 📘 **한글 멤버 가이드** — [`docs/MEMBER-GUIDE.ko.md`](docs/MEMBER-GUIDE.ko.md)
- 🧪 Vendor 테스트 합격선 — [`tests/REQUIREMENTS.md`](tests/REQUIREMENTS.md)
- 🔄 롤백 런북 (vendor → submodule) — [`docs/rollback-vendor.md`](docs/rollback-vendor.md)
- 📊 Vendor 마이그레이션 보고서 — `hypeprooflab:jay/reports/2026-05-20-vendor-migration.html`
- 🗺 토폴로지·시퀀스 — `hypeprooflab:jay/reports/2026-05-19-repo-structure-diagram.html`
- 🏗 Studio 페이즈/게이트 — `hypeproof-studio:METAPLAN.md`
- 🎯 16 Essences (제품 철학) — `hypeproof-studio:docs/essence-v0.1.md`

---

<p align="center"><sub>
maintained by <a href="https://github.com/jayleekr">@jayleekr</a> · last updated 2026-05-20 ·
HypeProof Lab · 내부 사용
</sub></p>
