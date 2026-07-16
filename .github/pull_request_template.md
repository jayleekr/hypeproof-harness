<!--
MEMBER-GUIDE §4.4 — PR 본문 필수: What & why · Tested · Closes #
브랜치 네이밍: fix/issue-N-* · feat/issue-N-* · docs/issue-N-* · chore/<주제>
AGENT-GUIDE §3 — 작성자를 제외한 활성 멤버 전원을 reviewer로 요청
-->

## What & why

<!-- 한 단락. 무엇을 왜 바꿨는지. -->

## Tested

<!-- 어떤 게이트/명령을 통과했는지. 예시:
- `bash -n scripts/sync.sh tests/run.sh`
- `bash tests/run.sh` — Gate: ✓ PASS
- 멤버 온보딩 dry-run on macOS arm64
-->

## Notes (optional)

<!-- 리뷰어가 알아야 할 가정/제약/후속 이슈 링크. -->

## Security / governance

- [ ] No secrets or credentials in the diff
- [ ] All active HypeProof members were requested as reviewers, excluding the PR author where GitHub disallows it
- [ ] Governance policy changes include audit/test coverage
- [ ] Repo apply/create tooling remains dry-run or manually approved
- [ ] Production deploy authority remains declared in policy; no hidden provider auto-deploy path was added
- [ ] Branch protection / required checks remain compatible with this change

Closes #
