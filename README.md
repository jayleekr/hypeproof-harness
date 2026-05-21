<h1 align="center">hypeproof-harness</h1>

<p align="center">
  HypeProof 팀의 공유 스킬·온보딩·워크플로 규약.
</p>

<p align="center">
  <code>macOS · Linux · WSL2</code>
</p>

---

3개 product repo — `hypeproof-studio` · `sediment` · `hypeprooflab` — 가
여기서 공유 스킬과 가이드를 vendor로 가져간다. 도메인 코드는 각자,
공통 규약은 한 군데.

현재 콘텐츠는 Claude Code 스킬 위주지만 Codex · OpenClaw 등 다른 AI 에이전트용
자원도 같은 vendoring 메커니즘으로 여기 추가할 수 있다.

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

### 🔁 다른 머신에서 운영 — 워크스페이스 경로 해석

`tests/consumers.txt`는 머신 의존 절대경로를 담지 않는다. consumer 경로는
세 단계로 해석된다(우선순위 순):

1. **`CONSUMER_<repo>` env** — 특정 repo를 임의 경로로 지정(최우선 override).
   ```bash
   CONSUMER_hypeproof_studio=/abs/path/to/clone bash scripts/sync.sh --check
   ```
   변수명에서 dash는 underscore로 정규화된다 (`hypeproof-studio` → `hypeproof_studio`).
2. **`${HYPEPROOF_WORKSPACE}`** — `consumers.txt`의 `${HYPEPROOF_WORKSPACE}/<repo>`
   기준 베이스. `export HYPEPROOF_WORKSPACE=/abs/path/to/workspace`로 머신별 지정.
3. **기본값(zero-config)** — `HYPEPROOF_WORKSPACE` 미설정 시 **이 repo의 부모
   디렉토리**로 자동 설정된다. consumer를 hypeproof-harness의 형제로 clone하면
   (`<ws>/hypeproof-harness`, `<ws>/hypeproof-studio`, …) 추가 설정 없이 동작한다.

매칭된 consumer가 하나도 없으면 `sync.sh`/`tests/run.sh`는 조용히 통과하지 않고
위 세 방법을 안내하는 힌트를 출력한다.

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

3개 repo가 같은 스킬과 가이드를 쓰고, 도메인 코드만 각자 다르다. 멤버는
자기 consumer repo만 보면 된다 — 갱신은 메인테이너가 한다.

Vendor를 고른 이유는 [migration report][migration]에.

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
[`MEMBER-GUIDE §4`](docs/MEMBER-GUIDE.ko.md). 모든 repo가 지키는 5가지:

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

멤버는 온보딩 때 한 번 clone한다. 일상은 자기 consumer repo에서. shared
콘텐츠 개선은 PR로.

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
Maintained by <a href="https://github.com/jayleekr">@jayleekr</a> · HypeProof Lab
</sub></p>
