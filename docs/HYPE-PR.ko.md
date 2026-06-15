# hype-pr

> 이 문서는 `hypeproof-harness:docs/HYPE-PR.ko.md`가 원천이다.
> 제품 repo에 vendoring된 사본은 직접 고치지 말고 harness에서 PR로 바꾼다.

---

## 목적

`hype-pr`는 PR 생성 시 팀 운영 규칙을 사람 기억에 맡기지 않기 위한 하네스다.

- PR 작성자를 제외한 active 멤버 전원을 reviewer로 요청한다.
- auto-merge는 켜도 되는 PR인지 먼저 판정한다.
- 보안, 배포, 데이터, dependency, governance 변경은 auto-merge 대상에서 제외한다.
- 실제 merge는 여전히 branch protection, CODEOWNERS, required checks가 통과해야 한다.

즉, auto-merge는 "리뷰 없이 merge"가 아니라 "필수 보호 조건이 모두 통과하면 GitHub가
순서대로 merge하게 예약"하는 기능이다.

---

## 기본 사용법

먼저 dry-run으로 reviewer와 auto-merge eligibility를 확인한다.

```bash
python3 scripts/hype-pr/pr.py plan \
  --repo jayleekr/hypeproof-studio \
  --author JinyongShin \
  --path docs/dev/cohort.md \
  --auto-merge
```

기존 PR에 reviewer를 다시 요청한다.

```bash
python3 scripts/hype-pr/pr.py request-reviewers \
  --repo jayleekr/sediment \
  --pr 87

# 실제 GitHub mutation
python3 scripts/hype-pr/pr.py request-reviewers \
  --repo jayleekr/sediment \
  --pr 87 \
  --apply
```

새 PR을 만들 때도 기본은 dry-run이다.

```bash
python3 scripts/hype-pr/pr.py create \
  --repo jayleekr/hypeproof-harness \
  --head feat/hype-pr-workflow-harness \
  --title "Add hype-pr workflow harness" \
  --body-file /tmp/pr-body.md \
  --author jayleekr \
  --path scripts/hype-pr/pr.py \
  --path docs/HYPE-PR.ko.md
```

`--apply`를 붙이면 `gh pr create`를 실행한다. `--auto-merge`를 같이 붙였고
eligibility가 통과하면 생성 직후 `gh pr merge --auto --squash --delete-branch`도
실행한다.

reviewer 요청은 PR 생성 후 1명씩 시도한다. 특정 repo에서 아직 write 권한이 없거나
초대를 수락하지 않은 멤버가 있으면 PR 생성 자체를 막지 않고, 해당 reviewer 요청
실패를 JSON 결과에 남긴다.

---

## Auto-Merge 판정

auto-merge는 다음 조건을 모두 만족해야 eligible이다.

- CLI에서 `--auto-merge`를 명시했다.
- PR이 draft가 아니다.
- repo profile의 `repository.allow_auto_merge`가 true다.
- repo inventory에 required status checks가 선언돼 있다.
- 변경 파일에서 high-risk category가 감지되지 않았다.
- PR label에 `human-needed`, `security`, `deploy`, `data`, `incident`,
  `breaking-change`, `do-not-merge`가 없다.

현재 active development profile은 auto-merge를 허용한다.

| Profile | GitHub auto-merge setting | 이유 |
|---|---:|---|
| `harness-core` | true | required review/check가 가장 엄격하므로 조건 통과 후 예약 merge 허용 |
| `public-product` | true | public code/private authority 모델에서 보호 조건 통과 후 예약 merge 허용 |
| `private-product` | true | private 예외 repo도 branch protection 통과 후 예약 merge 허용 |
| `content-vault` | false | vault/secret 성격 변경은 수동 merge 유지 |
| `release-artifact` | false | release repo는 source workflow가 artifact를 발행하고 사람 개발 PR은 예외 |

high-risk path는 auto-merge를 막는다.

| Risk | 예시 |
|---|---|
| `security` | `auth`, `admin`, `oauth`, `secret`, `token`, `credential`, `SECURITY.md` |
| `deploy` | `.github/workflows/`, `vercel`, `fly.toml`, `wrangler`, `deploy`, `release` |
| `data` | `migration`, `schema`, `tenant`, `rls`, `database`, `.sql` |
| `dependency` | lockfile, `pyproject.toml`, requirements, `Cargo.lock` |
| `governance` | `policy/`, `CODEOWNERS`, branch protection, repo-governance |

docs/UI 변경은 high-risk가 아니지만, reviewer가 `human-needed`를 붙이면 auto-merge가
막힌다.

---

## PR 작성자 기준

PR 작성자는 다음을 기억한다.

1. PR 생성 전 `hype-pr plan`으로 reviewer와 auto-merge 판정을 확인한다.
2. high-risk 변경이면 `--auto-merge`를 붙이지 않는다.
3. low-risk 반복 작업이면 `--auto-merge`를 붙일 수 있다.
4. reviewer는 모두 요청하되, 모든 사람의 승인을 기다리는 정책은 아니다.
5. merge는 branch protection quorum과 required checks가 결정한다.

`hype-review`는 리뷰어가 자기 lens로 질문하게 만드는 도구이고, `hype-pr`는 작성자가
PR을 만들 때 팀 운영 정책을 자동으로 적용하게 만드는 도구다.
