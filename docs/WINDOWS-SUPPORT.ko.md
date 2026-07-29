# hypeproof-harness — Windows 지원 현황과 권고안

> 작성 2026-07-28 · 기준 `hypeproof-harness@a15989d` · 대상 Windows 11 x64 · PowerShell 5.1 + Git Bash
>
> **이 문서는 조사 결과와 권고안이다. 이 저장소의 기존 파일은 하나도 수정하지 않았다.**
> 모든 판정은 이 PC 에서 직접 실행해 확인했다. 실측하지 않은 것은 `[미측정]`,
> 실측 사실에서 논리적으로 도출한 것은 `[도출]` 로 표시했다.

<details><summary>English</summary>

Findings + recommendation for running `hypeproof-harness` on Windows. **No existing file in
this repo was modified.** Everything is measured on the machine unless tagged `[미측정]`
(unmeasured) or `[도출]` (derived from measured facts).
</details>

---

## 0. 결론 먼저

| 문제 | 현재 Windows 상태 | 권고 |
|---|---|---|
| `.claude/skills/*` 심링크 6개 | **전부 깨짐** — 24~31바이트 텍스트 파일 | **S3: 심링크 폐기 → 실파일 벤더링.** harness 가 이미 consumer 에게 강제하는 그 계약을 자기 자신에게 적용하는 것 |
| `scripts/sync.sh` 의 `rsync` | **실행 불가** — Git for Windows 에 rsync 없음 | **R3: rsync 를 POSIX `find`+`cmp`+`cp` 로 대체.** 그 로직이 이미 같은 파일 안에 있다 |
| `tests/run.sh` T-V12 | 심링크 문제와 동일 원인으로 실패 | S3 를 적용하면 **코드 변경 없이** 자동 해결 |
| `scripts/register-skills.sh` apply 모드 | Windows 에서 **파괴적** — 수렴하지 않고 트리를 오염시킴 | S3 적용 시 자연 해소. 그 전까지는 **Windows 에서 실행 금지** |

두 권고안 다 **관리자 권한 0회 · UAC 클릭 0회**로 성립한다.

---

## 1. 무슨 일이 일어나는가 — 실측

### 1.1 인덱스에는 심링크가 6개다

```
$ git ls-files -s | grep ^120000
120000 6e69c04… 0  .claude/skills/demo-video-harness
120000 40afd28… 0  .claude/skills/hype-review
120000 a8d6467… 0  .claude/skills/hypeproof-operator
120000 856acb2… 0  .claude/skills/onboard-member
120000 64bebd3… 0  .claude/skills/skill-creator
120000 a7e0988… 0  .claude/skills/weekly-loop
```

`120000` = git 이 정의한 심볼릭 링크 모드다. blob 의 내용이 곧 링크 대상 문자열이다.

### 1.2 Windows 작업 트리에서는 텍스트 파일이다

```
$ ls -la .claude/skills/
-rw-r--r-- 31  demo-video-harness
-rw-r--r-- 24  hype-review
-rw-r--r-- 31  hypeproof-operator
-rw-r--r-- 27  onboard-member
-rw-r--r-- 26  skill-creator
-rw-r--r-- 24  weekly-loop

$ cat .claude/skills/hype-review
../../skills/hype-review
```

디렉토리여야 할 자리에 **경로 문자열이 든 24바이트 일반 파일**이 있다.
Claude Code 는 `.claude/skills/<name>/SKILL.md` 를 찾으므로 **6개 스킬이 전부 로드되지 않는다.**

원인: `core.symlinks=false`. 이 값은 두 곳에 있다 (실측).

```
C:/Program Files/Git/etc/gitconfig   core.symlinks=false     ← 시스템 스코프(관리자 소유)
.git/config                          core.symlinks=false     ← clone 시점에 박힘
```

### 1.3 `core.symlinks=true` 로 고치려 하면 **더 나빠진다**

비관리자 · Developer Mode OFF 상태에서, 120000 엔트리를 가진 저장소를 강제로 심링크
모드로 clone 한 결과(실측):

```
$ git -c core.symlinks=true clone <repo> <dst>
error: unable to create symlink .claude/skills/foo: Permission denied
fatal: unable to checkout working tree
warning: Clone succeeded, but checkout failed.
exit 128
```

**작업 트리 전체 체크아웃이 실패한다.** "텍스트 파일이라도 남는" 현재 상태보다 나쁘다.
→ **Windows 에서 `core.symlinks=true` 를 권하지 마라.**

### 1.4 Git Bash 의 `ln -s` 는 **조용히 복사한다**

`register-skills.sh` L59 가 쓰는 바로 그 명령이다.

```
$ ln -s target link1 ; echo "exit=$?"
exit=0
$ [ -L link1 ] && echo SYMLINK || echo "NOT A SYMLINK"
NOT A SYMLINK
$ ls -la link1
-rw-r--r-- 6 f.txt        ← target/ 의 내용이 복사됨. 링크가 아니라 사본이다.

$ MSYS=winsymlinks:nativestrict ln -s target link2
ln: failed to create symbolic link 'link2': Operation not permitted
```

즉 기본 모드는 **exit 0 으로 성공을 보고하면서 잘못된 결과를 만든다.**
`nativestrict` 로 정직하게 실패시키면 비관리자에서는 권한 거부다.

### 1.5 그래서 `register-skills.sh` 는 Windows 에서 파괴적이다 `[도출]`

위 1.2 + 1.4 를 `register-skills.sh` L40–62 에 대입하면:

| 단계 | 코드 | Windows 에서의 결과 |
|---|---|---|
| 판정 | L45 `[ -L "$link" ] && …` | 텍스트 파일이므로 **거짓** → `drift=1` |
| `--check` | L51–55 | `DRIFT  not a symlink: .claude/skills/hype-review` × 6 → **exit 1** |
| `apply` | L58 `rm -rf "$link"` | 24바이트 텍스트 파일 삭제 |
| `apply` | L59 `ln -s "$want" "$link"` | **`skills/hype-review/` 전체를 `.claude/skills/hype-review/` 로 복사** (1.4) |
| 재실행 | L45 | 여전히 `[ -L ]` 거짓 → **영원히 수렴하지 않음** |
| git 상태 | — | 120000 blob 6개 삭제 + 신규 파일 다수. 실수로 커밋하면 `skills/` 가 통째로 두 번 들어간다 |

`.githooks/pre-commit` 이 `register-skills.sh --check` 를 그대로 부르므로,
`git config core.hooksPath .githooks` 를 켠 Windows 사용자는 **모든 커밋이 차단된다.**

> ⚠ 이 절은 `[도출]` 이다. 이 저장소를 수정하지 않기 위해 `register-skills.sh` 를
> harness 에 대해 실제로 실행하지 않았다. 근거는 1.2(트리 상태 실측)와
> 1.4(`ln -s` 동작 실측) 두 개다. 재현은 **사본 저장소에서** 하라.

### 1.6 T-V12 는 같은 원인의 파생

`tests/run.sh` L337 은 `bash scripts/register-skills.sh --check` 에 위임한다.
따라서 T-V12 는 Windows 에서 **항상 FAIL** 이고, 그 실패는 T-V12 자신의 문제가 아니라
등록 방식(심링크)의 문제다. `tests/REQUIREMENTS.md:52` 가 "5 harness PASSes always"
로 세는 5개 중 하나가 무조건 빠지므로 `run.sh` 전체가 exit 1 이 된다.

> **`verification.md` 규율 적용**: FAIL 이 뜨면 순서가 정해져 있다 —
> ① 계측기가 틀렸나 ② 대상이 틀렸나. 여기서는 **둘 다 아니다.**
> 계측기(T-V12)도 대상(skills/)도 정상이고, **둘을 잇는 등록 메커니즘**이
> 플랫폼 가정을 하고 있다. T-V12 에 Windows 스킵 조건을 다는 것은
> 계측기를 무디게 만드는 잘못된 수리다.

---

## 2. 심링크 — 3안 비교

### S1. 현상 유지 + "Developer Mode 를 켜라"로 문서화

Windows 사용자에게: Developer Mode ON → `git config --global core.symlinks=true` → 재클론.

| | |
|---|---|
| 코드 변경 | 없음 |
| 권한 | **🔒 관리자 1회 + UAC 클릭** |
| 검증 | Developer Mode ON 상태에서 심링크 clone 이 실제로 성공하는지 **`[미측정]`** |
| 위험 | `ln -s` 는 Developer Mode 만으로는 안 된다 — `MSYS=winsymlinks:nativestrict` 를 같이 설정해야 하고(1.4), 안 하면 apply 가 여전히 조용히 복사한다 |
| 기존 클론 | `.git/config` 에 `core.symlinks=false` 가 박혀 있어 **재클론 필요**(1.2) |
| 판정 | 문서 1줄로 끝나 보이지만 실제로는 관리자 승격 + 전역 설정 + 재클론 + MSYS 변수 4단 조합. 그리고 그중 어느 것도 실측되지 않았다 |

### S2. Windows 에서 junction 으로 대체

`register-skills.sh` 에 플랫폼 분기를 넣어 `mklink /J` (또는 PowerShell
`New-Item -ItemType Junction`)를 쓴다. 정션은 `SeCreateSymbolicLinkPrivilege` 를
요구하지 않으므로 **비관리자로 만들어진다** (같은 PC 에서 `fnm` 이 실제로
`%LOCALAPPDATA%\fnm_multishells` 아래 `LinkType=Junction` 을 만드는 것으로 확인됨).

| | |
|---|---|
| 권한 | ✅ 비관리자 |
| 치명적 문제 | **git 이 정션을 심링크로 보지 않는다.** 정션은 디렉토리로 보이고, git 은 그 아래 실파일을 추적 대상으로 인식한다. 결과: 인덱스의 120000 엔트리는 "삭제됨", 정션 내부 파일은 "신규"로 뜬다 |
| 결과 | `git status` 가 매번 오염됨. `git add -A` 한 번이면 `skills/` 전체가 중복 커밋됨 |
| 추가 문제 | `register-skills.sh` 는 `readlink` 로 대상을 비교한다(L45, L69). 정션에는 안 통한다 → `--check` 로직 전면 재작성 필요 |
| 판정 | 권한 문제는 풀지만 **git 과 싸운다.** S3 와 코드 변경량이 비슷한데 위험만 크다 |

### S3. 심링크 폐기 → `.claude/skills/` 에 실파일 벤더링 ★ **권고**

`register-skills.sh` 를 "심링크 생성기"에서 "복사 동기화기"로 바꾼다.
`--check` 는 `[ -L ]`/`readlink` 대신 **파일 단위 `cmp` 대조**로 바꾼다.

| | |
|---|---|
| 권한 | ✅ 비관리자 · UAC 0회 |
| 플랫폼 | macOS · Linux · Windows 전부 동일 동작 |
| T-V12 | **코드 변경 불필요** — `register-skills.sh --check` 에 위임하는 구조가 그대로 유지된다 |
| pre-commit | 그대로 동작 |
| 저장소 비용 | 작업 트리 `skills/` 2.3MB(35 파일) → `.claude/skills/` 사본으로 +2.3MB. **git 이력 비용은 사실상 0** |
| 새 발명인가 | **아니다** — 아래 참조 |

**이력 비용이 0 인 이유 (실측)**: git 은 내용 주소 저장소다. 동일한 내용의 파일은
동일한 blob 해시를 가지므로 **하나만 저장된다.** 200,000바이트 파일을 커밋한 뒤
바이트 동일한 사본을 추가로 커밋한 실험:

```
git dir before duplicate: 269KB   after identical copy committed: 271KB
distinct blobs: 1        ← 2개가 아니라 1개
```

즉 트리 엔트리만 늘고 blob 은 재사용된다.

**이것이 새 발명이 아닌 이유 (실측)**: harness 는 이미 consumer 에게 정확히 이 계약을
강제하고 있다. `sync.sh` L182 는 `rsync -a --delete` 로 `skills/<name>/` 을
`consumer/.claude/skills/<name>/` 에 **실파일로 복사**하고 `HARNESS_VERSION` 을 남긴다.
같은 PC 의 `hypeproof-studio` 를 실측하면:

```
$ git ls-files -s .claude/skills/ | awk '{print $1}' | sort | uniq -c
     27 100644
     10 100755        ← 120000 이 0개. 전부 실파일
$ ls .claude/skills/skill-creator/HARNESS_VERSION
.claude/skills/skill-creator/HARNESS_VERSION      ← sync.sh 가 남긴 벤더링 표식
```

**그래서 이 PC 에서 studio 스킬 7개는 정상 로드되고 harness 스킬 6개는 깨져 있다.**
harness 만 자기 자신에게 다른 규칙(심링크)을 쓰고 있어서 생긴 차이다.

**T-V14(목록/로직을 두 곳에 두지 않는다)를 위반하지 않는 이유**:
단일 소스는 여전히 `skills/` 하나다. `.claude/skills/` 는 **생성물**이고,
그 생성물이 원본과 일치한다는 것을 `--check` 가 게이트한다. sync.sh 가
consumer 쪽에서 하는 것과 **정확히 같은 계약**이며, 드리프트는 CI(`test.yml` L53)와
T-V12 가 이미 막고 있다.

#### S3 의 구체적 변경 범위 (제안 — 이 문서는 코드를 바꾸지 않는다)

| 파일 | 변경 |
|---|---|
| `scripts/register-skills.sh` | L45 판정 `[ -L ] && readlink == want && -e` → **`find`+`cmp` 로 디렉토리 대조**. L58–59 `rm -rf` + `ln -s` → **`rm -rf` + `cp -a "$SKILLS_DIR/$name/." "$link/"`**. L66–81 고아 처리는 "PREFIX 를 가리키는 심링크" → "`skills/` 에 대응이 없는 `.claude/skills/<name>/` 디렉토리"로 |
| `tests/run.sh` | **변경 없음** (위임 구조 유지) |
| `.githooks/pre-commit` | **변경 없음** |
| `scripts/sync.sh` | **변경 없음** (consumer 쪽은 이미 복사 방식) |
| 마이그레이션 | 1회성: 6개 120000 엔트리를 지우고 `register-skills.sh` 를 macOS/Linux 에서 한 번 돌려 실파일을 커밋 |

#### S3 의 정직한 단점

- **작업 트리가 2.3MB 커진다.** 특히 `skills/demo-video-harness/` 가 2.0MB 로 대부분을 차지한다.
  이 스킬이 커지면 사본도 같이 커진다.
- **`skills/` 를 고치고 `register-skills.sh` 를 안 돌리면 드리프트가 난다.**
  심링크는 구조적으로 드리프트가 불가능했다. 대신 `--check` 가 CI·T-V12·pre-commit
  3중으로 걸려 있어 조용히 지나가지는 않는다.
- 리뷰 diff 가 2배로 보인다. `.gitattributes` 에 `-diff` 나 `linguist-generated`
  표시를 주는 것을 같이 검토할 만하다 `[미측정]`.

### 권고: **S3**

이유 세 가지, 우선순위 순:

1. **권한 요구가 사라진다.** S1 은 관리자 승격(UAC 클릭)을 요구하고 그 효과조차 미측정이다.
   S3 는 비관리자로 완결되고, 이미 이 PC 에서 studio 쪽으로 **동작이 증명돼 있다.**
2. **harness 가 자기 계약을 자기에게 적용하게 된다.** consumer 3곳에는 실파일 복사를
   강제하면서 자기 자신만 심링크를 쓰는 비대칭이 이 문제의 근원이다. S3 는 그
   비대칭을 없앤다. S2 는 세 번째 메커니즘을 추가해 비대칭을 늘린다.
3. **계측기를 무디게 하지 않는다.** T-V12 에 Windows 스킵을 다는 흔한 대응은
   "계측기가 안 보이게 만들기"다(`verification.md` 규칙 6 — 먼저 계측기를 의심하되,
   계측기를 끄는 것으로 해결하지 않는다). S3 는 T-V12 를 손대지 않고 **통과하게** 만든다.

---

## 3. rsync — 3안 비교

### 문제 확인 (실측)

```
$ command -v rsync
(없음)
$ ls "C:/Program Files/Git/usr/bin/" | grep -E '^(rsync|tar|sed|awk|cmp|find|ln|readlink|ssh)'
awk.exe  cmp.exe  find.exe  ln.exe  readlink.exe  sed.exe  ssh.exe  tar.exe
                                          ← rsync.exe 없음
```

`sync.sh` 는 rsync 를 **정확히 두 곳**에서 쓴다:

- L182 `rsync -a --delete --exclude='HARNESS_VERSION' "$SRC/" "$DST/"` (스킬)
- L260 `rsync -a --delete --exclude='HARNESS_VERSION' "$SCSRC/" "$SCDST/"` (스크립트 트리)

그 외 전부 POSIX coreutils (`find` `cmp` `cp -p` `mkdir` `rm`) 이고 Git Bash 에 다 있다.

### R1. MSYS2 를 별도 설치해 `pacman -S rsync`

| | |
|---|---|
| 권한 | 사용자 디렉토리 설치는 가능 `[미측정]` |
| 문제 | **새 런타임 하나를 통째로 들인다.** Git Bash(MSYS2 기반)와 별개의 MSYS2 설치가 되어 DLL·PATH 충돌 여지가 생긴다 |
| 문제 | "아무것도 없는 PC" 전제와 충돌 — 부트스트랩 부담이 커진다 |
| 판정 | 두 줄 때문에 런타임 하나를 추가하는 것은 비율이 안 맞는다 |

### R2. `robocopy` 로 포팅

`C:\Windows\System32\Robocopy.exe` 는 항상 존재한다(실측). `robocopy SRC DST /MIR /XF HARNESS_VERSION`.

| | |
|---|---|
| 권한 | ✅ 비관리자 |
| 문제 | **종료코드 규약이 정반대다.** robocopy 는 0~7 이 성공(1=파일 복사됨, 2=추가 파일, 3=둘 다…), 8 이상이 실패다. `sync.sh` 는 `set -euo pipefail` 이라 **정상 복사(exit 1)에서 스크립트가 죽는다.** 호출부마다 `|| [ $? -lt 8 ]` 래핑이 필요 |
| 문제 | Git Bash 경로(`/c/...`)를 Windows 경로로 변환해야 한다(`cygpath -w`). `$SRC/` 트레일링 슬래시 의미도 다르다 |
| 문제 | 플랫폼 분기가 생긴다 — macOS/Linux 는 rsync, Windows 는 robocopy. **같은 동작의 구현이 둘**이 되어 T-V14 가 경계하는 그 형태 |
| 판정 | 동작은 하지만 스크립트를 플랫폼별로 갈라놓는다 |

### R3. rsync 를 POSIX `find`+`cmp`+`cp` 로 대체 ★ **권고**

`sync.sh` 는 **이미 그 로직을 갖고 있다.**

- `--check` 모드 L127–140 / L209–222: `find -print0` 로 순회하며 `cmp -s` 로 파일 대조,
  `DRIFT`(원본에만 있음/다름)와 `EXTRA`(사본에만 있음)를 산출한다.
  이것이 `rsync --delete` 가 하는 판단 그 자체다.
- apply 모드 L146–163 / L228–243: 삭제 예정 파일 목록을 `will_delete` 배열로
  **이미 계산해 놓고** 사용자에게 보여준 뒤 `--force-delete` 를 요구한다.

즉 rsync 는 apply 실행부 한 줄에만 남아 있고, 그 한 줄이 필요로 하는 정보는
그 위에서 전부 계산돼 있다. 대체는 다음 형태로 충분하다:

```bash
# L182 자리 (개념 예시 — 이 문서는 코드를 바꾸지 않는다)
mkdir -p "$DST"
for rel in "${will_delete[@]}"; do rm -f "$DST/$rel"; done
( cd "$SRC" && find . -type d -exec mkdir -p "$DST/{}" \; )
( cd "$SRC" && find . -type f -print0 ) | while IFS= read -r -d '' rel; do
  cmp -s "$SRC/$rel" "$DST/$rel" || cp -p "$SRC/$rel" "$DST/$rel"
done
```

| | |
|---|---|
| 권한 | ✅ 비관리자 |
| 새 의존성 | **없음.** `find` `cmp` `cp` `mkdir` `rm` 전부 Git Bash 에 존재(실측) |
| 플랫폼 분기 | **없음.** 한 구현이 3 OS 에서 동일하게 돈다 |
| 부수 효과 | `--check` 와 `apply` 가 **같은 비교 함수**를 쓰게 되어 둘이 어긋날 수 없다. 지금은 `--check` 는 `cmp`, `apply` 는 rsync 라 서로 다른 판정기다 |
| 단점 | 대용량에서 rsync 보다 느리다. 대상은 스킬 2.3MB · 35파일 · 스크립트 6트리 — **무시 가능** |
| 단점 | 퍼미션/타임스탬프 보존이 `cp -p` 수준으로 제한 (rsync `-a` 대비 xattr 등 미보존). 대상이 텍스트 스킬·스크립트라 실질 영향 없음 `[미측정]` |

### R4 (대안). "sync.sh 는 macOS/Linux 전용" 으로 문서에 명시

메인테이너가 아무도 Windows 에서 벤더링하지 않는다면 이것도 정당한 답이다.
**단, 그 경우에도 R3 를 하는 편이 낫다** — 코드가 줄고, 판정기가 하나로 합쳐지고,
플랫폼 제약이 사라진다. 즉 R3 는 Windows 지원이 아니라 **단순화**로도 정당화된다.

### 권고: **R3**

이유 세 가지:

1. **새 의존성이 0 이다.** R1 은 런타임을 추가하고 R2 는 Windows 전용 코드 경로를 추가한다.
   R3 는 둘 다 없다.
2. **판정기가 하나로 합쳐진다.** 지금 `--check`(cmp)와 `apply`(rsync)는 서로 다른
   구현으로 같은 질문에 답하고 있다. 이것은 harness 자신이 T-V14 로 금지하는 형태다.
   R3 는 그 중복을 제거한다.
3. **대체 코드가 이미 파일 안에 있다.** 새로 설계하는 게 아니라 `--check` 의
   순회를 apply 에서 재사용하는 것이다. 리뷰 부담이 가장 작다.

---

## 4. 그 밖의 Windows 이슈

| 항목 | 상태 | 비고 |
|---|---|---|
| `tests/run.sh` 전체 | T-V12 실패로 exit 1 | S3 적용 시 해소. 나머지 T-V 항목의 Windows 동작은 **`[미측정]`** — consumer 3곳 클론이 없어 이 PC 에서 전수 실행 불가 |
| `scripts/security/check-secrets.sh` | `core.quotePath` 이슈로 브랜치가 이미 떠 있음 (`fix/check-secrets-quotepath-hermetic`) | 이 문서 범위 밖. 별건으로 진행 중 |
| CI 게이트 위치 | `.github/workflows/test.yml` L53 이 `register-skills.sh --check` 를 **`ubuntu-latest`** 에서 실행 | 즉 **CI 는 Windows 문제를 잡지 못한다.** Windows 사용자가 드리프트를 커밋하면 CI 는 그때서야(리눅스 기준으로) 잡는다 |
| `sync.sh` consumer 경로 | `${HYPEPROOF_WORKSPACE}` 기본값 = 이 저장소의 부모 | Windows 경로에서도 동작할 것으로 보이나 **`[미측정]`** |
| Claude Code 스킬 로드 | 현재 harness 저장소에서 6개 전부 미로드 | 같은 PC 의 studio 스킬 7개는 정상 로드(실파일) |

---

## 5. 지금 당장 하지 말아야 할 것

1. **`git config --global core.symlinks=true` 를 켜지 마라.** §1.3 실측 — clone 이 exit 128 로 실패한다.
2. **Windows 에서 `scripts/register-skills.sh` (apply 모드)를 실행하지 마라.** §1.5 — 수렴하지 않고 트리를 오염시킨다. `--check` 는 안전하다(읽기 전용).
3. **`.claude/skills/` 의 24바이트 파일을 손으로 고치지 마라.** 인덱스 모드는 120000 이므로 내용을 바꿔도 심링크 대상 문자열이 바뀔 뿐이다.
4. **T-V12 에 Windows 스킵 조건을 달지 마라.** 계측기를 끄는 수리다. 원인은 등록 메커니즘에 있다.
5. **Developer Mode 를 "그냥 켜면 되지" 로 처리하지 마라.** UAC 클릭 1회는 자동화 요구사항(클릭 0회) 위반이고, 켜도 `ln -s` 는 `MSYS=winsymlinks:nativestrict` 없이는 여전히 복사한다(§1.4).

---

## 6. 실측 로그

2026-07-28 · `C:\Users\sonatus\Downloads\hypeproof-harness` (HEAD `a15989d`) ·
비관리자 PowerShell 5.1 / Git Bash 2.54.0.windows.1 · Developer Mode OFF ·
`HKLM\...\LongPathsEnabled=0` · `IsInRole(Administrator)=False`.

| # | 명령 | 결과 |
|---|---|---|
| 1 | `git ls-files -s \| grep ^120000` | 6건 (`.claude/skills/*`) |
| 2 | `ls -la .claude/skills/` | 6개 전부 일반 파일, 24~31바이트 |
| 3 | `cat .claude/skills/hype-review` | `../../skills/hype-review` |
| 4 | `git config --list --show-origin` | `C:/Program Files/Git/etc/gitconfig` → `core.symlinks=false`; `.git/config` → `core.symlinks=false` |
| 5 | `git -c core.symlinks=true clone <120000 포함 repo>` | `unable to create symlink … Permission denied` / `fatal: unable to checkout working tree` / **exit 128** |
| 6 | `ln -s target link1` (Git Bash 기본) | exit 0 · `[ -L link1 ]` **거짓** · `link1/f.txt` 존재 = 디렉토리 사본 |
| 7 | `MSYS=winsymlinks:nativestrict ln -s target link2` | `Operation not permitted` (exit 1) |
| 8 | `command -v rsync` | 없음 |
| 9 | `ls "C:/Program Files/Git/usr/bin/"` | `awk cmp find ln readlink sed ssh tar` 존재 · **`rsync` 없음** |
| 10 | `where.exe robocopy` | `C:\Windows\System32\Robocopy.exe` |
| 11 | `du -sh skills/` · `find skills -type f \| wc -l` | 2.3MB · 35 파일 (`demo-video-harness` 단독 2.0MB) |
| 12 | `du -sh .git` | 1.2MB |
| 13 | 동일 내용 200KB 파일을 별도 경로에 추가 커밋 | `.git` 269KB → **271KB**, `blob` 객체 **1개** (2개 아님) → 사본의 이력 비용 ≈ 0 |
| 14 | studio `git ls-files -s .claude/skills/` 모드 분포 | `100644` 27 · `100755` 10 · **`120000` 0** |
| 15 | studio `.claude/skills/skill-creator/HARNESS_VERSION` | 존재 → sync.sh 벤더링 산출물 |
| 16 | `.github/workflows/test.yml` L53 | `bash scripts/register-skills.sh --check` · `runs-on: ubuntu-latest` |
| 17 | `.githooks/pre-commit` | `register-skills.sh --check` 실패 시 커밋 차단 |

미실행(의도적): `scripts/register-skills.sh` (apply/check 둘 다) · `scripts/sync.sh` ·
`tests/run.sh`. 이 저장소를 수정하지 않기 위해서다. §1.5 는 #2 와 #6 에서 도출한 것이며,
재현은 **사본 저장소**에서 하라.

<details><summary>English</summary>

**Bottom line.** The 6 `.claude/skills/*` entries are git mode `120000` symlinks; on
Windows with `core.symlinks=false` (set in the admin-owned system gitconfig *and* baked
into `.git/config` at clone time) they check out as 24–31 byte text files, so none of the
6 skills load. Forcing `core.symlinks=true` is worse, not better — measured: the clone's
checkout fails outright with exit 128 on a non-admin, Developer-Mode-off session. Git
Bash's `ln -s` silently *copies* instead of linking (exit 0, `[ -L ]` false), which makes
`register-skills.sh` apply-mode non-convergent and destructive on Windows.

**Recommendation — symlinks: option S3**, replace symlinks with vendored real files.
It needs no admin, works identically on all three OSes, leaves `tests/run.sh` and
`.githooks/pre-commit` untouched, and costs essentially nothing in git history (measured:
committing a byte-identical copy of a 200 KB file grew `.git` by 2 KB and produced *one*
blob, not two). Most importantly it is not a new invention: `sync.sh` already vendors
these same skills into consumer repos as real files, and on this very machine the studio
repo's 7 vendored skills load fine while the harness's 6 symlinked ones do not. The
harness is the only repo applying a different rule to itself.

**Recommendation — rsync: option R3**, replace the two `rsync -a --delete` calls with the
POSIX `find`/`cmp`/`cp` traversal that `sync.sh` already implements for `--check`. Zero
new dependencies, no platform branch, and it collapses two different implementations of
the same comparison into one — which is what the repo's own T-V14 principle asks for.
