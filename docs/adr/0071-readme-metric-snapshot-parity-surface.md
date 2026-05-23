# ADR 0071 — Committed README metric snapshot as parity source of truth

- Status: accepted
- Date: 2026-05-23
- Authors: Hyunsoo Kim
- Related: ADR 0005 (eval split public-synthetic/private-local), ADR 0001 (naive baseline 보존), CLAUDE.md "PR 설명" §5b, PR #1116 (docs 한국어화)
- Issue: #792
- Supersedes-attempt: PR #739 / PR #751 (revert `58b9835`) — CI README-metric sync 게이트의 source-mismatch 실패

## Context

README 의 핵심 성능표 (`<!-- METRICS_TABLE:START -->` … `END`) 는 공개 합성 eval 산출물이다. 그 수치를 CI 에서 강제하려던 첫 시도 (PR #739/#751, `pr-eval.yml` 에 `update_readme_metrics.py --check` step 추가) 는 **source mismatch** 로 항상 실패해 revert 됐다:

- CI eval-delta job 은 `eval/config.ci.yaml` + `embedding-backend: hashing` 로 `reports/eval_summary.json` 을 생성한다.
- README 표는 풀 `eval/config.yaml` 로 로컬 생성된다 (`make smoke` = full config + hashing backend, REPORT_DIR=reports → write+check).
- `reports/eval_summary.json` 은 `.gitignore` (`reports/*`) 로 ignored → **committed source of truth 부재**.
- 따라서 CI 의 `--check` step 은 *PR 시점에 재측정한* divergent eval 을 README 와 비교 → 구조적으로 불일치.
- 자동 fix (CI 에서 README regen) 는 production 수치 손실 (citation precision +18pp → +0pp).

두 번째 (이전엔 표면화 안 된) 원인: README metric 블록은 더 이상 순수 기계 생성물이 아니다. PR #1116 (한국어화) 이 `<details><summary>` 와 하단 caption 을 한국어 prose (ADR 링크 · `<strong>` 통계 포함) 로 손수 편집했으나 `update_readme_metrics.py` 는 여전히 옛 영어 문자열을 emit 한다. 즉 `render(eval_summary) ≠ 현재 README 블록` — snapshot 을 아무리 정확히 만들어도 "render == README" 전체 비교 게이트는 통과 불가.

## Decision

1. **`reports/eval_summary.snapshot.json` 을 committed source of truth 로 한다.** `.gitignore` 에 `!reports/eval_summary.snapshot.json` 예외 1줄. 공개 합성 eval 산출물이므로 ADR 0005 비공개 경계 밖 (`reports/real*/` 미해당, `EVAL_PRIVACY_ARTIFACT_GLOBS` 미해당).

2. **CI 게이트는 재측정하지 않는다.** `pr-eval.yml` 의 step 은 `update_readme_metrics.py --report reports/eval_summary.snapshot.json --readme README.md --check` 만 수행 — README 의 metric 행이 committed snapshot 과 일치하는지 검증. eval 재실행 없음 → #739/#751 의 source mismatch 제거.

3. **게이트 범위는 metric 행 (숫자) 한정.** `--check` 와 write 경로 모두 marker 블록 안의 `|`-delimited 행만 비교/치환하고 (`splice_table_rows`), `<details>`/`<summary>` + caption 의 손수 큐레이션 prose 는 in-place 보존한다. table header/separator 행은 renderer 와 README 가 byte-identical 이라 round-trip clean. prose 의 i18n drift 는 #1116 의 별개 관심사로 decouple.

4. **갱신 절차는 `make snapshot-update`.** operator 가 `make smoke` (full `eval/config.yaml`, hashing backend) 로 `reports/eval_summary.json` 재생성 후 `make snapshot-update` 실행 → snapshot 갱신 + README metric 행 in-place sync (prose 보존). `reports/eval_summary.snapshot.json` + `README.md` 동반 commit.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| committed snapshot (옵션 A) vs 별 workflow (B) / CI 자동 push (C) | A 는 Makefile 1 target + gitignore 1줄 + CI 1 step. B 는 eval 시간을 PR CI 에 부담, C 는 CI push 보안 우려. issue #792 §권고 A. |
| 재측정 안 함 | 재측정이 #739/#751 실패의 직접 원인. snapshot 비교는 backend/config 무관하게 결정론적. |
| 숫자 행만 비교 (rows-only) | render 가 prose 를 소유하지 않으므로 (PR #1116 이후) 전체-블록 비교는 영구 false-fail. 게이트의 본래 목적은 README 숫자 ↔ snapshot 정합 강제이며, prose 큐레이션은 그와 직교. |
| `make smoke` 가 SSoT 생성 경로 | 이미 full `eval/config.yaml` + hashing 으로 README 를 write/check 하는 기존 경로. 신규 측정 표면 도입 아님 — 기존 산출물을 committed 화. |

## Consequences

- **Positive**: CI 가 README 숫자 drift 를 머지 전 차단 (regression test `test_repo_readme_rows_match_snapshot` 가 항상-on sentinel). snapshot 이 reviewer 가 의존할 측정-provenance 계약 고정. `make governance-check` 의 `check` 가 committed snapshot 대상으로 동작 (이전엔 gitignored `reports/eval_summary.json` 부재 시 exit 2).
- **Negative**: snapshot 갱신은 수동 (`make snapshot-update`) — 측정 numbers 가 움직였는데 snapshot 미갱신 시 CI red. 이는 의도 (drift fast-fail).
- **불변 보존**: ADR 0001 (naive baseline) ranking 무변경 (코드 경로 미수정, 측정 산출물만 commit). ADR 0005 경계 (공개 합성 한정). ADR 0003 답변 계약 무관.

## Verification

<!-- verifies-key: scripts/update_readme_metrics.py:splice_table_rows -->
<!-- verifies-key: tests/test_governance_readme_metric_snapshot.py:test_repo_readme_rows_match_snapshot -->
<!-- verifies-key: Makefile:snapshot-update -->
<!-- verifies-key: .gitignore:eval_summary.snapshot.json -->
<!-- verifies-key: .github/workflows/pr-eval.yml:eval_summary.snapshot.json -->

자기-검증 (본문이 약속한 parity 강제가 실제로 작동하는지):
- `python3 scripts/update_readme_metrics.py --report reports/eval_summary.snapshot.json --readme README.md --check` 가 `[OK]` 이면 README ↔ snapshot 정합.
- snapshot 의 한 metric 을 임의 변경하면 `--check` 와 `test_repo_readme_rows_match_snapshot` 이 fail 해야 한다 (게이트가 살아있다는 증거).
