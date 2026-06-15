# hype-merge monitor

`hype-merge`는 열린 PR을 merge해도 되는지 감시하는 read-only 하네스다.
자동으로 merge하지 않는다. 목적은 승인/체크 상태가 바뀌었을 때 어떤 PR이
ready인지, 어떤 PR이 사람 리뷰를 더 기다려야 하는지, 어떤 PR이 수정 필요인지
한 화면에서 구분하는 것이다.

## 사용법

```bash
python3 scripts/hype-merge/monitor.py
python3 scripts/hype-merge/monitor.py --repo jayleekr/hypeproof-harness
python3 scripts/hype-merge/monitor.py --format json
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
3. deploy/docs PR은 의존 관계가 있으면 사람이 순서를 확인한다.
4. merge 후 production deploy나 release workflow가 있으면 해당 check와 live
   smoke를 끝까지 확인한다.

이 도구의 출력은 merge 후보를 줄이는 보조 신호다. 실제 merge는 GitHub branch
protection, CODEOWNERS, required checks, 그리고 PR의 최신 review state가 최종
권위다.
