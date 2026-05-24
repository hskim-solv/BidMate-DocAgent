# 0067: Tree-SHA provenance for squash-merge-invariant baseline reachability

- Status: proposed
- Date: 2026-05-22
- Deciders: Hyunsoo Kim
- Related: ADR 0005 (eval-split aggregate-only), 게이트 출처 issue #160 / #413, baseline staleness 검토 #1095, this fix #1222

## Context

`baseline-provenance` CI 게이트(`scripts/check_baseline_provenance.py`,
[`pr-eval.yml`](../../.github/workflows/pr-eval.yml))는 커밋된
`reports/real100/baseline.aggregate.json` 의 `provenance.git_commit` 이
`origin/main` 의 ancestor 인지 `git merge-base --is-ancestor` 로 검증한다.
SHA 가 main 에서 사라지면 `make real-eval-delta` 가 phantom 코드 상태와
diff 하기 때문이다. 그런데 이 게이트는 **baseline regen PR 머지 직후마다
깨졌다** — 방금도 한 인스턴스를 수동 정정(`a7fd711d0573` → `de69c5c2d456`)했다.

근본 원인은 squash-merge 다. `scripts/_utils.py` `build_provenance()` 는
`make real-eval-baseline-update` 시점의 `git rev-parse HEAD`(PR 브랜치 tip)를
기록한다. 이 repo 는 squash-merge 라 그 정확한 SHA 는 main 에 절대 안 올라가고,
main 은 **동일 tree·다른 SHA** 의 새 커밋을 얻는다. 따라서 기록된 `git_commit` 은
baseline-bump PR 머지 즉시 dangling "squash twin" 이 되어, 이후 모든 PR 에서
ancestry 검사가 실패한다.

두 제약이 스크립트 레벨의 단순 우회를 막는다: (1) squash SHA 는 regen 시점에
**알 수 없다**(GitHub 가 머지 때 생성). (2) CI 의 sparse + `fetch-depth:0`
(origin/main 만) 체크아웃에선 dangling twin 커밋 객체가 대개 **부재** —
"twin 의 tree 를 읽어 매칭" 하는 fallback 은 twin 객체가 없어 불가능하다.

## Decision

`provenance` 에 **tree SHA** 를 squash-invariant 도달성 키로 추가하고, 게이트를
2-tier 로 만든다.

1. `build_provenance()` 가 `git rev-parse HEAD^{tree}` 의 12-char SHA 를
   `provenance.git_tree` 로 기록한다. squash-merge 는 동일 tree 를 main 에
   올리므로 `git_commit` 은 dangle 해도 `git_tree` 는 도달 가능하게 남는다.
   writer(`scripts/write_real_eval_baseline.py`)와 future aggregate writers가
   `build_provenance()` 를 호출하면 같은 키를 자동 상속한다.

2. `check_baseline_provenance.py` 의 도달성 검사를 2-tier 로:
   - **Tier 1 (commit, backward-compatible)**: `git_commit` 이 object DB 에
     존재하고 `--ref`(또는 `--allow-equal-to`)의 ancestor 면 통과. 기존
     의미·`--allow-equal-to` escape hatch 그대로 보존.
   - **Tier 2 (tree, squash-invariant)**: tier 1 이 실패하고 `git_tree` 가
     기록돼 있으면 `git log <ref> --format=%T` 에 그 tree(12-char prefix
     매칭)가 있는지 확인. main history 만 걸으므로 dangling twin 객체가
     부재한 CI 환경에서도 동작한다.

   `git_tree` 가 없는(pre-0067) baseline 은 tier 1 만 적용 — `git_commit`
   부재 + `git_tree` 부재면 기존 object-DB 에러(exit 1) 그대로. `"unknown"`
   sentinel 은 부재로 취급해 degenerate snapshot 이 실제 tree 와 매칭되지
   않도록 한다.

production 코드 경로(`rag_*.py`, `api/`, `eval/config.yaml`) 미터치. 커밋된
baseline 의 metric 값은 안 건드린다(§5b 무관). private 데이터는 CI 에 들어오지
않는다 — tree 검사는 main history 만 읽는다.

## Consequences

- **게이트가 squash-merge 와 호환**: baseline regen PR 머지 후 다음 PR 들이
  더 이상 squash-twin dangle 로 빨갛게 되지 않는다 — 매 regen 마다의 수동
  provenance 정정 toil 제거.
- **계약 고정**: `provenance.git_tree` 는 게이트가 의존하는 새 측정-표면
  필드다. 향후 writer/소비자가 이 키를 보존해야 한다 (ADR 임계값의
  "새 측정 표면" 사유로 본 ADR 작성).
- **더 정확한 의미**: tree 매칭은 "baseline metric 이 main 에 존재하는 코드
  상태(tree)에 대응한다" 는 의도를 commit 매칭보다 직접 표현한다.
- 비용: 동일 tree 가 main 에 있으면(예: 무의미 커밋으로 tree 가 반복) commit
  이 dangle 이어도 통과 — 그러나 그것이 정확히 의도한 squash 의미이고, tree
  도달성은 코드 상태가 main 에 있음을 보장한다.
- ADR 0001(naive_baseline byte-identical) / 0005(eval-split aggregate-only)
  불변식 보존.

## Alternatives considered

- **머지 후 provenance.git_commit 을 on-main squash SHA 로 재작성
  (skill-driven)** — 기각: 수동·skill 의존이라 깨지기 쉽고, 매 regen 마다
  추가 단계. tree 키는 schema 한 번 바꿔 영구 해결.
- **twin 커밋의 tree 를 읽어 매칭** — 기각: CI sparse + fetch-depth:0 에서
  twin 객체가 부재해 tree 를 읽을 수 없다. `git log <ref> --format=%T` 는
  main history 만 필요해 CI-feasible.
- **게이트를 commit→tree 로 완전 교체** — 기각: tier 1 commit ancestry 를
  유지하면 in-flight PR 의 `--allow-equal-to` escape hatch 와 정밀 의미가
  보존되고 기존 계약 회귀가 없다. tree 는 fallback 으로 충분.

## Verification

<!-- verifies-key: scripts/_utils.py:git_tree -->
<!-- verifies-key: scripts/check_baseline_provenance.py:def _tree_reachable -->
<!-- verifies-key: scripts/check_baseline_provenance.py:def _extract_provenance_tree -->
<!-- verifies-key: tests/test_check_baseline_provenance.py:CheckBaselineProvenanceSquashTwin -->
