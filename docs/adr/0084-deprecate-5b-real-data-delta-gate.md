# 0084: §5b real-data delta 게이트 폐지

- Status: accepted
- Date: 2026-05-29
- Related: [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0007](./0007-issue-linked-branch-naming.md), [ADR 0051](./0051-flat-root-module-layout.md), [ADR 0062](./0062-failure-rate-regression-contract.md)
- Issue: #1669

## Context

PR #69 에서 공개 fixture smoke 델타는 녹색이었으나 비공개 100-doc real-eval 에서
의도된 보류(intended abstention) 회귀가 새어 나갔다. 그 사후 대응으로
**§5b real-data delta 게이트**가 도입됐다 — load-bearing 경로
([`scripts/_governance.py`](../../scripts/_governance.py) `LOAD_BEARING_PATHS`)
를 손댄 PR 은 body 에 `### 5b. Real-data delta` 섹션 + `make real-eval-delta`
집계 표 또는 "동작 변화 없음" escape 문장을 담아야 했고,
`scripts/check_branch_and_issue.py --check-5b` 가 CI 에서 그 *존재* 를 hard-gate
했다 (regex `FIVE_B_TABLE_RE` / `FIVE_B_ESCAPE_RE`). pre-push soft-warn,
PreToolUse awareness, auto-ship `render_5b()` cascade, pre-create bash-guard
soft-warn 이 같은 표면을 둘러쌌다.

운영 결과 이 게이트는 reviewer 가 의존하는 *계약* 으로 자리잡지 못했다. CI 가
강제할 수 있는 것은 섹션·표·escape 문장의 **존재** 뿐이고 (issue #1027 이
명시), 표 안 숫자의 정확성·escape claim 의 진위는 자동 검증 불가다. 실측 비용은
지속적이었다: template↔gate 언어 drift (issue #1048), Korean escape over-match
(issue #1236), stacked-PR base filter 우회 (issue #1159), pre-create soft-warn
배선 (issue #1097) 등 게이트 *자체* 를 유지보수하는 follow-up 이 누적됐다.
유지보수자는 §5b 첨부를 더 이상 강제하지 않기로 결정했다 — real-data 영향은
권장 근거로 남되, 누락이 머지를 막지는 않는다.

## Decision

1. **§5b PR-body 게이트를 폐지한다.** `scripts/check_branch_and_issue.py` 의
   `--check-5b` 모드 (`check_5b_mode`, `_five_b_section`, `FIVE_B_*` regex,
   `five_b_escape_satisfied`) 와 `branch-and-issue-check.yml` 의 "Validate PR
   §5b" 스텝을 제거한다. `--branch` / `--pr` / `--check-ceiling-ratchet` 모드는
   유지한다.
2. **pre-push soft-warn #1 (real-eval delta reminder) 을 제거한다.** README
   freshness reminder 와 naive_baseline golden reminder 는 유지한다 (`$changed`
   변수 계산도 후자가 의존하므로 보존).
3. **auto-ship §5b cascade 를 제거한다.** `_ship_pr_body.py` 의 `render_5b()`
   / `validate_5b()` / `check_body_5b()` 및 real-eval cache 헬퍼를 삭제하고, PR
   body 생성에서 `### 5b. Real-data delta` 섹션을 빼낸다. `--real-eval-mode`
   플래그는 `stop-ship.sh` 하위 호환을 위해 accepted-but-ignored no-op 으로
   남긴다.
4. **pre-create bash-guard §5b soft-warn 을 제거한다.** stacked-PR 가드는
   유지한다.
5. **agent_loop.py 의 §5b PRBodyFinding / CIFinding 분기를 제거한다.**
6. **측정 도구와 awareness 는 보존한다.** `scripts/run_real_eval_delta.py`,
   Makefile `real-eval-delta` 타깃, `LOAD_BEARING_PATHS` SSoT, pre-push
   reminders, PreToolUse load-bearing awareness 는 그대로다. real-data aggregate
   첨부는 이제 **권장**(강제 아님)이며 PR 템플릿 §5 Eval 영향 안내로 옮긴다.
7. **PR 템플릿에서 `### 5b. Real-data delta` 섹션을 제거한다.** §1–§7 본체는
   유지한다.

## Consequences

- load-bearing 변경에 real-data 근거가 누락돼도 CI 가 막지 않는다 — reviewer
  판단에 맡긴다. **reviewer checkpoint 는 PR template §5 의 visible blockquote**
  로 노출되어(HTML comment 가 아니라 rendered PR 에서 보이는 텍스트), 작성자가
  load-bearing 변경 시 ① aggregate 첨부 / ② 동작 무변경 사유 / ③ real-eval 미실행
  사유 중 하나를 명시하도록 안내한다. PR #69 회귀 클래스에 대한 방어는 추가로
  ADR 0005 (eval 분리 규율), ADR 0062 (failure-rate ceiling ratchet), pre-push
  test-coverage soft-warn 으로 분산 유지된다.
- `LOAD_BEARING_PATHS` 소비자가 2곳(pre-push reminders + PreToolUse awareness)
  으로 줄어든다. SSoT 자체는 불변이므로 ADR 0051 의 module-layout 계약은 영향
  없다.
- auto-ship 은 더 빨라지고 (full real-eval 실행 경로 제거) body 가 단순해진다.
  `REAL_EVAL` env / `--real-eval-mode` 는 호환용 no-op 으로 남아 기존 호출이
  깨지지 않는다.
- ADR 0007 (branch/issue 강제) + ceiling ratchet 게이트는 `--check-5b` 제거 후
  에도 모든 PR base 에서 그대로 fire 한다
  (`tests/test_pr_gate_workflow_triggers_regression.py` 가 guard).

## Alternatives considered

- **게이트를 advisory(soft-warn)로만 약화.** pre-push/pre-create soft-warn 은
  이미 advisory 였고, hard CI 게이트만 비용을 냈다. 부분 약화는 유지보수 표면을
  남기므로 완전 폐지가 더 단순하다.
- **escape regex 를 더 똑똑하게.** issue #1048/#1236 의 반복 drift 가 보여주듯,
  자연어 attestation 을 regex 로 검증하는 것은 본질적으로 취약하다. 근본
  원인은 "존재 검증 ≠ 내용 검증" 이므로 regex 개선으로는 해결 불가.

## Verification

```bash
# §5b 게이트 잔재가 없음 (측정 도구·문서의 정당한 언급 제외)
! python3 scripts/check_branch_and_issue.py --check-5b 1 2>/dev/null
grep -q -- "--check-5b" .github/workflows/branch-and-issue-check.yml && echo FAIL || echo OK
# 측정 도구 + SSoT + dispatch 보존
python3 -m pytest -q tests/test_governance.py tests/test_ship_pr_body.py \
  tests/test_pr_template_loadbearing_parity.py \
  tests/test_pr_gate_workflow_triggers_regression.py
python3 scripts/check_branch_and_issue.py --branch chore/issue-1669-deprecate-5b-gate
# 측정 도구 보존 확인 (헬프만; private real-eval 실행 아님)
python3 scripts/run_real_eval_delta.py --help >/dev/null
git diff --check
```

<!-- verifies-key: scripts/_governance.py:LOAD_BEARING_PATHS -->
<!-- verifies-key: scripts/run_real_eval_delta.py:extract_aggregate -->
<!-- verifies-key: scripts/check_branch_and_issue.py:check_ceiling_ratchet_mode -->
<!-- verifies-key: Makefile:real-eval-delta -->
