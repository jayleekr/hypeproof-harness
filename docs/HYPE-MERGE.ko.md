# hype-merge monitor

## Intent

사람은 정책이 요구하는 판단과 승인을 맡고, 에이전트는 승인 뒤의 기계적인
병합·검증·다음 브랜치 갱신을 맡는다. 사람의 승인과 merge 버튼 누르기를 같은
일로 취급해 전달을 멈추지 않는다.

## 요구사항

`hype-merge`는 열린 PR을 merge해도 되는지 판정한다. 목적은 승인/체크 상태가 바뀌었을 때 어떤 PR이
ready인지, 어떤 PR이 사람 리뷰를 더 기다려야 하는지, 어떤 PR이 수정 필요인지
한 화면에서 구분하는 것이다.

- 정본 policy나 PyYAML을 읽지 못하면 실패한다. approval 수를 0으로 완화하지 않는다.
- `ready`는 사람이 merge해야 한다는 뜻이 아니다. 의존 순서와 최신 독립 검증을
  확인한 조정 에이전트가 정확한 head를 병합할 수 있다.
- 사람은 정본 policy가 요구하는 비작성자 approval과 명시적인 제품·사업·배포
  결정을 제공한다. 그 승인이 보이면 조정 에이전트가 병합을 마친다.
- GitHub branch protection이 정본보다 약하면 승인 전 auto-merge를 예약하지 않는다.

## 설계

`monitor.py`가 정본 정책과 현재 GitHub 상태를 합쳐 `ready`/`waiting`/`blocked`를
판정한다. `automerge.py`는 review gate가 GitHub에도 걸린 `waiting` PR에는
auto-merge를 예약하고, 운영자가 하나의 `ready` PR을 지정하면 exact-head direct
merge를 실행한다.

## 사용법

```bash
python3 scripts/hype-merge/monitor.py
python3 scripts/hype-merge/monitor.py --repo jayleekr/hypeproof-harness
python3 scripts/hype-merge/monitor.py --format json
python3 scripts/hype-merge/automerge.py
python3 scripts/hype-merge/automerge.py --apply
python3 scripts/hype-merge/automerge.py \
  --repo jayleekr/hypeproof-studio --pr 123 --merge-ready
python3 scripts/hype-merge/automerge.py \
  --repo jayleekr/hypeproof-studio --pr 123 --merge-ready --apply
```

기본 repo 목록은 `policy/repos.yaml`의 release가 아닌 모든 관리 대상 repo를
따른다. release repo는 사람이 직접 개발 PR을 merge하는 공간이 아니므로
제외한다.

## 판정 기준

- `ready`: checks가 green이고, 변경 요청이 없고, mergeable이며, repo profile이
  요구하는 작성자 외 approval 수를 만족한다.
- `waiting`: checks는 문제 없지만 branch protection, `human-needed`, 또는 repo
  profile의 required approval 때문에 리뷰를 더 기다리는 상태다.
- `blocked`: draft, failed/pending checks, changes requested, `do-not-merge`류
  라벨, merge conflict처럼 작성자 조치가 필요한 상태다.

중요한 점은 GitHub branch protection이 없는 repo에서도 profile이 review를
요구하면 작성자가 아닌 사람의 approval 없이는 `ready`로 보지 않는다는 것이다.
이는 public code/private authority 운영 기조와 self-merge 금지 원칙을 맞추기
위한 보수적 기준이다. `human-needed` 라벨은 같은 기준을 PR 단위로 명시하는
보조 신호다.

## Merge 운영

1. `hype-merge monitor`로 ready queue를 확인한다.
2. ready PR만 squash merge 대상으로 본다.
3. 조정 에이전트가 의존 관계, 현재 X2 판정, 최신 head를 확인한다.
4. `--merge-ready --repo <repo> --pr <n> --apply`로 exact-head squash merge한다.
5. merge SHA, main CI, 배포를 확인하고 다음 의존 브랜치를 갱신한다.

이 도구의 출력은 merge 후보를 줄이는 보조 신호다. 실제 merge는 GitHub branch
protection, CODEOWNERS, required checks, 그리고 PR의 최신 review state가 최종
권위다.

## Auto-Merge 예약

`automerge.py`는 기본 dry-run이다. `--apply`를 붙였을 때만 GitHub에
`gh pr merge --auto --squash --delete-branch --match-head-commit <sha>`를 보낸다.

대상은 다음 조건을 모두 만족해야 한다.

- `monitor.py` 기준 `waiting`
- checks green
- GitHub `reviewDecision`이 `REVIEW_REQUIRED`
- blocker가 리뷰 대기 항목뿐임
- 최신 head SHA가 확인됨

따라서 failed check, conflict, changes requested, `do-not-merge`/`blocked`/`hold`
라벨이 있는 PR은 auto-merge 예약 대상이 아니다. `ready` PR은 `--merge-ready`와
단일 `--repo`/`--pr`로만 직접 병합한다. 이 제한은 여러 저장소의 ready PR을
의존 순서 확인 없이 한 번에 병합하지 못하게 한다.
