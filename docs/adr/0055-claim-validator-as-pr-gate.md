# ADR 0055 — `claim_validator` as PR gate (improvement-claim statistical honesty)

- Status: Proposed
- Date: 2026-05-18
- Authors: Hyunsoo Kim
- Related: ADR 0050 (ALLOW_REGRESSION pattern), ADR 0053 (distinguishing-power gauge), ADR 0054 (conditional-on-substantive-answer scorer semantics — paired pairs filter)
- Augments: Phase 4 audit (`docs/audits/eval-framework-phase4-audit.md`, PR #963) item 3 supply
- Issue: #964

## Context

Phase 4 audit (PR #963 / `e65f792`) 의 item 3 진단 — **`claim_validator.py` 부재 (✗ absent)**. `find . -name 'claim_validator*'` 0건, `grep claim_validator|validate_claim` 0건. PR body 의 "+X.Xpp SIG/NS" 표기 convention (e.g. PR #956 body 의 "**−0.046 SIG** (−0.084, −0.011)" 형식) 은 작성자 손으로 paired-CI 부호 확인 + SIG 라벨 부여 — 자동 게이트 부재.

최근 main PR 빈도 (~25 PR / 1주, #939~#963 기준) 를 고려하면 도입 지연 1주 = 25 PR 의 improvement claim 통계 정직성이 사람 spot check 에만 의존.

ADR 0050 (corpus 확장) / ADR 0054 (scorer semantics 변경) 가 의도적 regression 의 `[ALLOW_REGRESSION]` escape 를 도입한 것과 **대칭의 반대 방향** — improvement claim (positive shift) 의 자동 검증. ALLOW_OVERCLAIM 대칭 escape 는 의도적 미도입 (§Consequences).

## Decision

1. **PR body convention 도입** — improvement claim 은 다음 한 줄 (multi-line 지원, 각 metric 별 1줄):
   ```
   Claim: <metric>=<+X.Xpp>     # 예: Claim: accuracy=+4.0pp, Claim: groundedness=-2.5pp
   ```
   regex (`scripts/validate_claim.py:CLAIM_PATTERN`):
   ```python
   r"^Claim:\s+(?P<metric>\w+)\s*=\s*(?P<sign>[+-])(?P<value>[\d.]+)pp\s*$"
   ```
   Code fence 안의 라인은 skip (예시/문서 illustration 보호).

2. **자동 검증 4 조건** (`scripts/validate_claim.py:validate_one_claim`) — 4 개 모두 통과해야 PASS:
   - (a) CI 가 0을 가로지르지 않음 (`ci_lo` 와 `ci_hi` 부호 동일)
   - (b) effective sample size (post-None-skip, ADR 0054 substantive-only) ≥ `--min-sample` (default 200)
   - (c) `sign(claim) == sign(mean_diff)` (방향 일치)
   - (d) `|claim| ≤ |optimistic CI edge|` (over-claim 차단; positive claim 은 `ci_hi`, negative claim 은 `ci_lo`)

3. **`pr-eval.yml` step 추가** — 신규 step "Validate improvement claims", `if: contains(github.event.pull_request.body, 'Claim:')` 조건부 실행. `Claim:` 라인 0건이면 skip → 기존 PR 패턴 0 영향.

4. **재사용 — 신규 helper 작성 금지** — `eval/bootstrap.py:78-104` `paired_bootstrap_ci(values_a, values_b, *, num_resamples=1000, alpha=0.05, seed=17)` 그대로 사용. 단 argument 순서: `(candidate, baseline)` (mean_diff = candidate − baseline → positive = improvement, Claim: 부호와 일치).

5. **ADR 0054 None-pair 처리** — `case_id` 페어링 후 *어느 한 쪽이라도 None* 인 페어 drop. effective_n = 살아남은 페어 수. ADR 0054 의 substantive-answer-only 의미 유지.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| convention 강제 X (opt-in) | 기존 PR body 의 `Claim:` regex 매칭 0건 (`gh pr list --state merged --limit 100` 검증) → backward-compatible. convention 강제는 별 ADR 후보 (e.g. PR template 의 `Claim:` placeholder 도입). |
| `--min-sample 200` default | ADR 0044 / 0052 trajectory 의 n=221 에 fit. real n 보다 더 큰 sample 요구는 false negative. |
| `ALLOW_OVERCLAIM` 미도입 | ALLOW_REGRESSION 은 *의도적* trade-off (corpus 확장, scorer 변경) 의 acknowledged 비용 → escape 정당. OVERCLAIM 은 *통계적 정직성* 의 escape → 정당화 어려움. ADR 0055 가 차단함으로써 portfolio claim 의 외부 검증 가능성 유지. |
| code fence skip | 본 ADR 자체가 ADR 본문에 `Claim: accuracy=+4.0pp` 예시 포함 — 검증 대상 안 됨. 모든 docs PR 도 동일 보호. |
| `pp` (percentage point) 단위 강제 | `%` 와 `pp` 혼동 위험. SIG/NS 표기 convention 도 `pp` 사용. |

## Consequences

### Positive

- **모든 future improvement claim 의 통계 검증 자동화** — PR 당 SIG/NS 수동 확인 → 자동 게이트. 시간 적분 ROI 큼 (25 PR/주 × 평균 2 claim/PR ≈ 50 claim/주 자동 검증).
- **Portfolio narrative 강화** — recruiter / reviewer 가 PR body 의 "+X.Xpp" claim 을 CI badge 와 함께 검증 가능. "이 PR 의 +4.0pp 가 통계적으로 의미있나?" 가 *fast verifiable*.
- **5-step closure narrative (시퀀스 A)** 의 step 5 (= claim_validator 도입) 가 본 ADR 으로 land. portfolio blog 1편 작성 시 "audit → 발견 → fix → 측정 표면 audit → 자동 게이트 도입" 5-step 완성.
- **ADR 0054 와의 시너지** — None-pair drop 이 substantive-answer-only 의미를 PR-gate layer 까지 전파. ADR 0054 의 scorer fix 가 PR-gate 자동화의 *prerequisite* 였음이 가시화.

### Negative

- **`Claim:` 미명시 PR 은 검증 skip** — 작성자가 잊으면 보호 미작동. convention 강제 (PR template `Claim:` placeholder) 는 별 ADR 후보.
- **opt-in convention 의 학습 비용** — 신규 contributor 가 convention 모름 시 누락. ADR 0055 본 문서 + README 의 contributing 섹션 (별 PR) 에 명시.
- **CI walltime ~5-10초 추가** — `Claim:` 있는 PR 만. paired_bootstrap_ci num_resamples=1000 기준 metric 당 ~2초.

### Invariance check

- **ADR 0001 (naive_baseline byte-identical)**: 유지. validate_claim 은 read-only — production code path 0 영향.
- **ADR 0003 (answer contract schema_version=2)**: 유지. prediction dict / case_results schema 변경 없음.
- **ADR 0005 (eval split public/private)**: 유지. validate_claim 은 CI 의 `pr/reports/eval_summary.json` (ADR 0005 의 ephemeral artifact) 를 read — aggregate boundary 무영향.
- **ADR 0050 (ALLOW_REGRESSION)**: 직교. ALLOW_REGRESSION 은 regression escape, ADR 0055 는 improvement claim 게이트. 둘은 반대 방향의 서로 다른 surface.
- **ADR 0054 (conditional-on-substantive-answer)**: **활용** — None-pair drop 으로 substantive-answer-only 의미 전파.

## Out of scope (별 PR / 별 ADR)

- **PR template 의 `Claim:` placeholder 추가** — convention 강제. ADR 0056 후보.
- **`ALLOW_OVERCLAIM` escape 도입** — 의도적 미도입 (위 §Why).
- **claim 의 `pp` 외 단위 (%, ratio, raw)** — `pp` 한정. 확장 시 별 ADR.
- **per-PR 자동 claim suggester** ("이 PR 의 측정 결과로 자동 Claim: 행 생성") — 별 PR scope, validate_claim 와 별개.
- **시퀀스 A 의 다음 step (3c trace v2, 3b rationality judge, blog, Phase 5 audit)** — 본 ADR 의 scope 외.

## Verification

<!-- verifies-key: scripts/validate_claim.py:validate_one_claim -->
<!-- verifies-key: scripts/validate_claim.py:CLAIM_PATTERN -->
<!-- verifies-key: scripts/validate_claim.py:paired_metric_arrays -->
<!-- verifies-key: tests/test_validate_claim.py:TestHappyPath -->
<!-- verifies-key: tests/test_validate_claim.py:TestCICrossesZero -->
<!-- verifies-key: tests/test_validate_claim.py:TestADR0054NoneSemanticsHandled -->
<!-- verifies-key: .github/workflows/pr-eval.yml:Validate improvement claims -->

## References

- Phase 4 audit (`docs/audits/eval-framework-phase4-audit.md`, PR #963) — 본 ADR 의 motivation.
- ADR 0054 (`docs/adr/0054-conditional-on-answer-scorer-semantics.md`) — None-pair drop 의미의 source.
- ADR 0050 / 0054 의 ALLOW_REGRESSION pattern — 본 ADR 의 대칭 반대 방향.
- `eval/bootstrap.py:78-104` `paired_bootstrap_ci` — 재사용 entrypoint.
- PR #956 body — 사람 손으로 작성된 SIG/NS 표기의 대표 사례 ("**−0.046 SIG** (−0.084, −0.011)").
