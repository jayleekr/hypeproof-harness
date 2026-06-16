# HypeProof Repo Governance

Status: proposed

이 문서는 `hypeproof-harness`를 HypeProof 저장소 운영의 control plane으로
확장하기 위한 구조를 정의한다. 목표는 제품 repo가 public/private 여부와
무관하게 같은 기조로 관리되고, 새 repo와 release repo까지 같은 정책을
재사용하게 만드는 것이다.

## 목표

- `hypeproof-harness`가 repo 생성, 권한, branch protection, Actions 보안,
  secret scanning, 템플릿, release repo 정책의 canonical source가 된다.
- 정책은 선언형 YAML로 두고, GitHub의 실제 상태는 audit/apply 스크립트가
비교한다.
- public repo는 코드가 공개되는 것을 전제로 운영하되, merge/write 권한은
멤버와 승인된 automation으로 제한한다.
- private repo는 멤버만 접근하게 유지하되, GitHub 플랜 한계 때문에 적용할 수
없는 보호 정책은 "미지원 drift"로 명확히 드러낸다.
- 새 repo는 GitHub UI에서 임의로 만들지 않고, harness의 profile을 통해
생성한다.

## 원칙

1. Desired state first
   - GitHub UI 설정은 결과일 뿐이다. 원천은 `policy/` 아래 선언이다.

2. Audit before apply
   - 모든 변경 도구는 dry-run/audit을 먼저 제공한다. apply는 명시적 옵션이나
     manual workflow에서만 수행한다.

3. Secrets are referenced, never stored
   - harness에는 secret 이름, 필요 여부, rotation 책임만 둔다. 값은 GitHub
     Secrets, Fly, Vercel, Cloudflare에만 둔다.

4. Public code, private authority
   - public repo는 외부 PR/comment를 완전히 막을 수 없다는 전제로 설계한다.
     핵심은 main 유입, secret 접근, deploy 권한을 통제하는 것이다.

5. Exceptions expire
   - 임시 예외는 `expires_at`, owner, 이유를 가져야 한다. 만료된 예외는 audit
     실패로 처리한다.

## 디렉터리 구조

```text
policy/
  repos.yaml
  members.yaml
  profiles/
    public-product.yaml
    private-product.yaml
    harness-core.yaml
    release-artifact.yaml
    content-vault.yaml
  templates/
    common/
      CODEOWNERS
      SECURITY.md
      pull_request_template.md
    workflows/
      repo-policy-audit.yml
      secret-diff-scan.yml
scripts/
  repo-governance/
    audit.py
    apply.py
    create.py
    render_templates.py
    github_api.py
docs/
  REPO-GOVERNANCE.ko.md
```

`policy/`는 선언, `scripts/repo-governance/`는 실행 엔진이다. 기존
`scripts/sync.sh`는 shared docs/skills vendoring을 계속 담당하고, repo 설정
관리는 별도 엔진이 맡는다.

## Inventory

`policy/repos.yaml`은 모든 관리 대상 repo의 목록이다.

```yaml
version: 1

repositories:
  - name: hypeproof-studio
    owner: jayleekr
    visibility: public
    profile: public-product
    lifecycle: product
    default_branch: main
    products: [studio]
    required_secrets:
      actions:
        - ANTHROPIC_API_KEY
        - DISCORD_WEBHOOK_HYPEPROOF_STUDIO
    release_repos:
      - jayleekr/hypeproof-studio-releases
    exceptions:
      - id: studio-claude-solver-temporary
        owner: jayleekr
        reason: restrict Claude Solver to collaborators before enforcing workflow allowlist
        expires_at: 2026-07-01

  - name: sediment
    owner: jayleekr
    visibility: public
    profile: public-product
    lifecycle: product
    default_branch: main
    products: [sediment]
    required_secrets:
      actions:
        - FLY_API_TOKEN
        - VERCEL_TOKEN
        - VERCEL_ORG_ID
        - VERCEL_PROJECT_ID
        - DISCORD_WEBHOOK_SEDIMENT

  - name: hypeprooflab
    owner: jayleekr
    visibility: private
    target_visibility: public
    profile: content-vault
    lifecycle: product
    default_branch: main
    products: [lab, vault]
    public_readiness:
      blocked_by:
        - issue: jayleekr/hypeprooflab#96
          reason: exposed Google OAuth credential rotation and history purge verification
        - issue: jayleekr/hypeprooflab#100
          reason: tracked content PII/email sweep
      verifier:
        pr: jayleekr/hypeprooflab#120
        workflow: OAuth purge verification
    required_secrets:
      actions:
        - VERCEL_TOKEN
        - SEDIMENT_INGEST_URL
        - SEDIMENT_WEBHOOK_SECRET

  - name: hypeproof-harness
    owner: jayleekr
    visibility: public
    profile: harness-core
    lifecycle: governance
    default_branch: main

  - name: jayleekr.github.io
    owner: jayleekr
    visibility: public
    profile: public-product
    lifecycle: site
    default_branch: master
    protected_branch: master
```

`policy/members.yaml`은 사람과 역할을 분리한다.

```yaml
version: 1

members:
  admins:
    - jayleekr
    - JeHyeong2
  writers:
    - ico1036
    - xoqhdgh1002
    - JinyongShin
    - TJ-kr

roles:
  maintainer:
    github_permission: admin
  contributor:
    github_permission: push
```

나중에 GitHub Organization으로 옮기면 `members.yaml`은 team slug 기반으로
바뀌고, repo inventory는 그대로 유지한다.

## Profiles

Profile은 repo 유형별 기본 정책이다. 각 repo는 하나의 profile을 선택하고,
정말 필요한 경우에만 repo-level override를 둔다.

| Profile | 대상 | 핵심 정책 |
| --- | --- | --- |
| `harness-core` | `hypeproof-harness` | 가장 엄격. 2 approvals, CODEOWNERS required, admins enforced, direct push 금지 |
| `public-product` | `hypeproof-studio`, `sediment`, public tool/site repo | public 유지, 외부 PR 허용, main은 PR/CI/review로만 유입, Actions read-only |
| `private-product` | private 제품 repo | 멤버만 접근, main PR 강제, 가능한 경우 branch protection 적용 |
| `content-vault` | `hypeprooflab` | public 전환 전까지 임시 private, 콘텐츠 ingest secret 보호, vault 변경 workflow 제한 |
| `release-artifact` | release mirror/artifact repo | 사람 개발 금지, admin만 직접 collaborator, CI bot만 release/tag 생성, issues/wiki/projects off |

예시:

```yaml
# policy/profiles/public-product.yaml
version: 1
profile: public-product

repository:
  allow_forking: true
  delete_branch_on_merge: true
  allow_auto_merge: false
  merge_methods:
    squash: true
    merge_commit: false
    rebase: false

collaborators:
  manage: members

security:
  dependabot_security_updates: enabled
  secret_scanning: enabled
  secret_scanning_push_protection: enabled
  secret_scanning_non_provider_patterns: enabled

actions:
  enabled: true
  default_workflow_permissions: read
  can_approve_pull_request_reviews: false
  fork_pr_approval: all_external_contributors
  allow_pull_request_target: false
  require_pinned_actions: warn

branch_protection:
  branch: main
  enforce_admins: true
  allow_force_pushes: false
  allow_deletions: false
  required_pull_request_reviews:
    required_approving_review_count: 1
    dismiss_stale_reviews: true
    require_code_owner_reviews: true
    require_last_push_approval: true
  required_status_checks:
    strict: true
    checks: []
```

`checks`는 profile 기본값을 비워두고 repo별로 선언한다. check 이름은 workflow
변경에 민감하므로 inventory에서 명시해야 drift가 보인다.

## Policy Modules

Audit/apply 엔진은 작은 module로 나뉜다.

| Module | Audit | Apply |
| --- | --- | --- |
| `repo_settings` | visibility, merge method, fork, delete branch on merge | 가능 |
| `collaborators` | direct collaborator, pending invitation, 권한 | 가능 |
| `branch_protection` | main 보호, review, status checks | 가능, 플랜 미지원은 unsupported |
| `rulesets` | org/repo ruleset | 가능, 플랜 미지원은 unsupported |
| `actions` | token permission, fork approval, allowed actions | 가능 |
| `security` | secret scanning, push protection, Dependabot | 가능, repo visibility/plan 의존 |
| `templates` | CODEOWNERS, SECURITY, PR template | PR 생성 또는 patch |
| `workflows` | required workflow 존재와 위험 패턴 | PR 생성 또는 warning |
| `secrets` | required secret 이름 존재 여부 | audit only |
| `environments` | production deploy environment와 reviewer | 가능 |
| `labels` | 표준 labels | 가능 |

## Public Readiness Holds

운영 기조는 public repo + member-only contribution이다. 다만 이미 노출된 secret,
PII, 법무/계약 문서처럼 public 전환 자체가 위험을 키우는 경우에는 `visibility`를
현재 안전 상태로 두고 `target_visibility`에 최종 상태를 적는다.

`visibility`와 `target_visibility`가 다르면 repo에는 반드시 다음이 있어야 한다.

- `public_readiness.blocked_by`: public 전환을 막는 issue와 이유
- 만료일이 있는 임시 exception
- 가능하면 public 전환을 증명할 verifier PR/workflow

예: `hypeprooflab`은 최종 목표가 `public`이지만, #96의 OAuth credential
rotation/history purge와 #100의 PII sweep이 끝나기 전까지는 private로 유지한다.
이 상태는 policy drift가 아니라 명시적인 security hold이며, exception 만료 전
재검토해야 한다.

## Collaborator Policy

`policy/members.yaml`의 admins/writers가 contributor 권한의 원천이다.
profile은 이 목록을 어떻게 repo에 적용할지 정한다.

- `collaborators.manage: members`: admins는 `admin`, writers는 `write`
- `collaborators.manage: admins`: admins만 `admin`; release-artifact repo에 사용

live audit은 실제 collaborator와 pending invitation을 분리해서 표시한다.
초대가 pending인 사용자는 아직 공식 reviewer request 대상이 될 수 없으므로
`collaborators` module에서 high finding으로 남긴다. pending invitation의 권한이
policy보다 낮으면 apply로 다시 초대/권한 보정을 시도할 수 있다. 권한이 맞는
pending invitation은 API로 강제로 해소할 수 없고, 사용자가 GitHub 초대를
수락해야 사라진다.

## Scripts

### `audit.py`

실제 GitHub 상태와 desired state를 비교한다.

```bash
python scripts/repo-governance/audit.py --all
python scripts/repo-governance/audit.py --repo jayleekr/sediment --json
```

Exit code:

- `0`: drift 없음
- `2`: drift 있음
- `3`: GitHub 플랜/권한 때문에 적용 불가한 unsupported drift 있음
- `4`: policy 파일 자체가 invalid

### `apply.py`

API로 가능한 설정을 반영한다. 기본은 dry-run이다.

```bash
python scripts/repo-governance/apply.py --repo jayleekr/sediment --dry-run
python scripts/repo-governance/apply.py --repo jayleekr/sediment --apply
```

권한/초대 drift만 줄일 때는 다른 설정을 건드리지 않도록 module을 좁힌다.

```bash
python scripts/repo-governance/apply.py --repo jayleekr/sediment --module collaborators --dry-run
python scripts/repo-governance/apply.py --repo jayleekr/sediment --module collaborators --apply
```

파일 변경이 필요한 항목, 예를 들어 CODEOWNERS나 workflow template은 대상 repo에
직접 push하지 않는다. `--create-pr` 모드에서 PR branch를 만들고 PR을 연다.

### `create.py`

새 repo 생성은 inventory PR이 merge된 뒤 실행한다.

```bash
python scripts/repo-governance/create.py --repo jayleekr/new-product --profile public-product
```

생성 순서:

1. GitHub repo 생성
2. default branch 초기화
3. common templates 적용
4. collaborators/team 권한 적용
5. Actions/security 설정 적용
6. branch protection 적용
7. required secrets checklist issue 생성
8. first audit report 생성

### `render_templates.py`

템플릿은 repo별 변수를 받아 렌더링한다.

```bash
python scripts/repo-governance/render_templates.py --repo jayleekr/hypeproof-studio
```

## Workflows

Harness 자체에는 두 가지 workflow를 둔다.

1. Policy audit
   - `pull_request`: policy 변경 PR에서 affected repo만 audit
   - `schedule`: 매일 전체 repo drift audit
   - `workflow_dispatch`: 수동 전체 점검

2. Policy apply
   - `workflow_dispatch` 전용
   - `environment: repo-governance`
   - maintainer approval 필요
   - dry-run artifact를 먼저 업로드하고, 같은 run에서 승인 후 apply

제품 repo에는 최소한 다음 workflow/template을 배포한다.

- `secret-diff-scan.yml`
- repo별 unit/build/test workflow
- `repo-policy-audit.yml`는 선택 사항. canonical audit는 harness에서 돈다.

## Public Repo 보안 기준

Public repo는 다음을 전제로 한다.

- 외부인은 코드를 읽고 fork/PR/comment할 수 있다.
- 외부인은 직접 push/merge/deploy할 수 없어야 한다.
- 외부 PR workflow는 secret에 접근하지 못해야 한다.
- comment-triggered automation은 collaborator만 실행할 수 있어야 한다.

따라서 `public-product`는 다음을 강제한다.

- `main` branch protection 필수
- `GITHUB_TOKEN` default permission은 read
- fork PR approval은 `all_external_contributors`
- `pull_request_target` 금지
- `contents: write` workflow는 push/tag/manual만 허용
- issue/comment trigger workflow가 secret 또는 write permission을 쓰면
  collaborator permission check 필수
- deploy secret은 protected environment에 묶고, main push 또는 manual approval만 허용

`hypeproof-studio`의 Claude Solver 같은 workflow는 다음 패턴만 허용한다.

```yaml
if: |
  github.event.sender.type != 'Bot' &&
  steps.permission.outputs.allowed == 'true' &&
  contains(github.event.comment.body, '@claude')
```

`steps.permission`은 GitHub API로 sender가 해당 repo에 `write`, `maintain`,
`admin` 중 하나인지 확인해야 한다.

## Private Repo 기준

Private repo는 접근 자체가 멤버에게만 허용된다. 그래도 main 보호 원칙은 같다.

문제는 personal account private repo에서 branch protection이 플랜에 따라 막힐 수
있다는 점이다. 이 경우 audit은 실패를 숨기지 않고 다음처럼 보고한다.

```text
unsupported: branch_protection requires GitHub Pro/Team for private repo
```

운영 선택지는 둘 중 하나다.

- GitHub Pro/Team 또는 Organization으로 이전해서 정책을 실제 적용한다.
- 그 전까지 `main-guard` workflow와 멤버 운영 규칙으로만 soft enforce한다.

## Release Artifact Repo 기준

Release repo는 개발 repo가 아니다.

- visibility는 artifact 공개 여부에 따라 public/private를 선택한다.
- collaborators는 maintainer와 release bot만 둔다.
- issues, projects, wiki는 끈다.
- branch protection은 main direct push 금지.
- release/tag 생성은 source repo의 release workflow 또는 bot token만 허용한다.
- release asset은 immutable로 취급한다. 교체가 필요하면 새 tag를 만든다.

## Drift Report 형식

Audit 결과는 사람이 읽는 표와 machine-readable JSON을 모두 낸다.

```json
{
  "repo": "jayleekr/sediment",
  "profile": "public-product",
  "status": "drift",
  "items": [
    {
      "module": "branch_protection",
      "severity": "high",
      "field": "required_status_checks",
      "expected": ["cli-tests / Backend + shim + rate-limit UT"],
      "actual": null,
      "apply_supported": true
    }
  ]
}
```

Severity 기준:

- `critical`: secret/deploy/write 권한이 외부 트리거와 결합됨
- `high`: main 보호, required checks, collaborator 권한 문제
- `medium`: secret scanning, Actions permission, template 누락
- `low`: labels, docs, branch cleanup 같은 운영 품질 drift

## 도입 순서

1. `policy/repos.yaml`, `policy/members.yaml`, profile 파일을 추가한다.
2. `audit.py`를 read-only로 구현한다.
3. 매일 audit workflow를 추가하고, drift를 issue/comment로 남긴다.
4. `hypeproof-studio`, `sediment`, `hypeproof-harness`의 public profile drift를
   먼저 줄인다.
5. `apply.py`를 manual workflow로만 연결한다.
6. release repo들을 inventory에 편입한다.
7. `create.py`를 붙여 새 repo는 harness profile로만 만들게 한다.
8. GitHub Organization 이전 여부를 결정한다. 이전하면 team/ruleset module을
   켜고 direct collaborator 관리를 team 관리로 대체한다.

## 현재 repo에 대한 profile 매핑

| Repo | Visibility | Profile | 우선 조치 |
| --- | --- | --- | --- |
| `jayleekr/hypeproof-harness` | public | `harness-core` | secret scanning/push protection on, admins enforce |
| `jayleekr/hypeproof-studio` | public | `public-product` | main protection 추가, Claude Solver collaborator-only |
| `jayleekr/sediment` | public | `public-product` | required checks와 review count 적용 |
| `jayleekr/hypeprooflab` | private -> public target | `content-vault` | #96 OAuth purge, #100 PII sweep 완료 전까지 security hold |
| `jayleekr/jayleekr.github.io` | public | `public-product` | collaborator-only contribution, PR CI 추가 |

이 구조를 쓰면 repo가 늘어나도 새 정책을 복사하지 않는다. repo는 inventory에
추가되고, profile은 재사용되며, 예외만 명시적으로 기록된다.
