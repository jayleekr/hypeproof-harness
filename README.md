<h1 align="center">hypeproof-harness</h1>

<p align="center">
  <b>HypeProof Lab의 AI-네이티브 워크플로 중심.</b><br>
  Claude Code로 일하는 작은 팀이 같은 방식으로 움직이기 위한 공유 OS.
</p>

<p align="center">
  <code>private</code> · <code>Claude Code</code> · <code>macOS · Linux · WSL2</code>
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
도메인을 책임진다. 이 harness는 그 세 repo가 **같은 협업 OS를 공유하도록
보장한다** — vendoring으로 코드는 각자, 워크플로는 하나.

---

## What's in here

| 자산 | 무엇 | Vendored to |
|---|---|---|
| `skills/skill-creator/` | Claude Code 스킬을 만들고 평가하는 generic 툴킷 | 3 consumers `.claude/skills/` |
| `skills/onboard-member/` | 신규 멤버 1회성 셋업 인터랙티브 스킬 | (harness-local) |
| `docs/MEMBER-GUIDE.ko.md` | 한글 멤버 워크플로 가이드 — 5단계 lifecycle | 3 consumers `docs/` |
| `scripts/sync.sh` | 캐노니컬 → consumer 동기 (`--check` · apply · `--commit`) | (maintainer) |
| `tests/run.sh` + `REQUIREMENTS.md` | Vendor 정합성 검증 (T-V1..T-V10) | (maintainer) |
| `docs/rollback-vendor.md` | submodule 모델로 5분 안에 돌아가는 7-step 런북 | (maintainer) |

**Not shared here**: studio-only 규칙(`branding-swap`, `build-pipeline`,
`extension-dev`), `e2e/`, `vscodium-base` 서브모듈, 각 repo의 `.github/` 템플릿
(GitHub은 submodule 심링크 템플릿을 따라가지 않는다).

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

스킬이 다음을 차례로 묻고 자동 셋업한다:

1. **플랫폼 점검** — macOS / Linux / WSL2 / Windows native
2. **소속 consumer repo** — studio · sediment · lab
3. **워크스페이스 경로** — `$HYPEPROOF_WORKSPACE`, `~/code`, `~/dev`,
   `~/CodeWorkspace` 등 자기 컨벤션 그대로
4. **clone + git hooks + Claude Code 설정 검증**
5. 자기 repo의 `docs/MEMBER-GUIDE.ko.md`로 안내

키·토큰은 안내만 — 자동 저장하지 않는다. Idempotent (재실행 안전).

> 자세한 워크플로는 [`docs/MEMBER-GUIDE.ko.md`](docs/MEMBER-GUIDE.ko.md) —
> 모든 consumer repo에 vendoring돼 있어서 거기서도 같은 파일을 볼 수 있다.

### 🛠 메인테이너 — 공유 콘텐츠 업데이트

```bash
# 1. canonical 편집
vim skills/skill-creator/SKILL.md     # 또는 docs/MEMBER-GUIDE.ko.md
git commit && git push origin main

# 2. 모든 consumer로 동기
bash scripts/sync.sh --check          # drift 미리보기 (read-only)
bash scripts/sync.sh --commit         # rsync + 각 consumer main에 커밋

# 3. 각 consumer push (또는 PR — harness 변경은 피어리뷰 권장)
```

**Guardrails**

- `--commit`은 `main` 위 + skill 외 변경 없을 때만 실행 (`ALLOW_ANY_BRANCH=1`로 우회)
- Git 신원은 각 consumer의 ambient config 그대로 — 스크립트가 override하지 않는다
- `rsync --delete`가 consumer-only 파일을 지우려 하면 abort — `--force-delete`로 명시 우회

### 🔁 다른 머신에서 운영 — `CONSUMER_*` env override

```bash
CONSUMER_hypeproof_studio=/abs/path/to/local/clone \
CONSUMER_sediment=/abs/path/to/sediment \
  bash scripts/sync.sh --check
```

Env 변수명에서 dash는 underscore로 정규화된다 (`hypeproof-studio` → `hypeproof_studio`).

---

## How it works

```
                    ┌──────────────────────────────────┐
                    │      hypeproof-harness           │
                    │      ─────────────────           │
                    │   canonical shared content       │
                    │   + onboarding skill             │
                    │   + sync / test tooling          │
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

세 consumer는 같은 `skill-creator` · 같은 `MEMBER-GUIDE` · 같은 이슈/PR
컨벤션을 공유한다. **차이는 각자의 도메인 코드뿐.** 멤버는 자기 consumer
repo만 신경 쓰면 된다 — 이 harness는 메인테이너가 갱신한다.

Submodule이 아니라 vendor를 고른 이유는 [vendor migration report][migration]에.

[migration]: https://github.com/jayleekr/hypeprooflab/blob/main/jay/reports/2026-05-20-vendor-migration.html

---

## Platform support

| OS | 멤버 온보딩 | Studio 로컬 빌드 | Sediment / Lab |
|---|:---:|:---:|:---:|
| **macOS** arm64 | ✅ Primary | ✅ Only supported | ✅ |
| **Linux** | ✅ Works | ❌ studio policy | ✅ |
| **Windows** native | ⚠ unsupported | ❌ | ⚠ unsupported |
| **Windows** + WSL2 | ✅ Recommended | ❌ | ✅ |

워크스페이스 경로(`$WS`)는 자기 컨벤션 그대로 — `~/CodeWorkspace`, `~/code`,
`~/dev`, `~/projects` 등 무엇이든. `/onboard-member`가 묻는다.

---

## Hard rules

5단계 lifecycle(이슈 → 브랜치 → 커밋·테스트 → PR → merge)은
[`docs/MEMBER-GUIDE.ko.md §4`](docs/MEMBER-GUIDE.ko.md)에서 본다. 워크플로
디테일과 무관하게 모든 repo가 따르는 5가지:

- **PR-first, review optional** — `main` 직접 push 금지 (메인테이너 제외)
- **`human-needed` 라벨**로 AI 자동처리 vs 사람 필요를 명시 (policy owner: 지용)
- **스킬은 `/skill-creator`로만** 만들고 고친다 — SKILL.md를 손으로 쓰지 않는다
- **이 repo 변경은 항상 피어리뷰** — 3 consumer가 공유한다
- **시크릿 절대 커밋 금지** — 새면 즉시 Jay에게 알리고 로테이션

---

## Team & access

| | GitHub | Role | Note |
|---|---|---|---|
| Jay Lee | [`@jayleekr`](https://github.com/jayleekr) | `admin` | Maintainer |
| Jehyeong Shin | [`@JeHyeong2`](https://github.com/JeHyeong2) | `admin` | Co-maintainer |
| Bongho Tae | [`@xoqhdgh1002`](https://github.com/xoqhdgh1002) | `write` | Onboarding + 기여 |
| Jinyong Shin | [`@JinyongShin`](https://github.com/JinyongShin) | `write` | Onboarding + 기여 |
| TJ Kang | [`@TJ-kr`](https://github.com/TJ-kr) | `write` | Onboarding + 기여 |
| Jkim | [`@ico1036`](https://github.com/ico1036) | `write` | Onboarding + 기여 |

멤버는 **1회 온보딩**에 한해 이 repo를 clone한다. 일상 작업은 자기 consumer
repo에서. shared 콘텐츠를 함께 개선하고 싶으면 PR로 — 피어리뷰 후 머지.

---

## Documentation

- 📘 **한글 멤버 가이드** — [`docs/MEMBER-GUIDE.ko.md`](docs/MEMBER-GUIDE.ko.md)
- 🧪 Vendor 테스트 합격선 — [`tests/REQUIREMENTS.md`](tests/REQUIREMENTS.md)
- 🔄 롤백 런북 (vendor → submodule) — [`docs/rollback-vendor.md`](docs/rollback-vendor.md)
- 📊 Vendor 마이그레이션 보고서 — `hypeprooflab:jay/reports/2026-05-20-vendor-migration.html`
- 🗺 토폴로지 · 시퀀스 — `hypeprooflab:jay/reports/2026-05-19-repo-structure-diagram.html`
- 🏗 Studio 페이즈/게이트 — `hypeproof-studio:METAPLAN.md`
- 🎯 16 Essences (제품 철학) — `hypeproof-studio:docs/essence-v0.1.md`

---

<p align="center"><sub>
Maintained by <a href="https://github.com/jayleekr">@jayleekr</a> · HypeProof Lab · Internal use only
</sub></p>
