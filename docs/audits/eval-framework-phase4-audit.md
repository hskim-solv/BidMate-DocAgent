# eval-framework-progressive-audit — Phase 4 (statistical rigor)

| field | value |
|---|---|
| Skill | [`.claude/skills/eval-framework-progressive-audit/SKILL.md`](../../.claude/skills/eval-framework-progressive-audit/SKILL.md) (PR #889) |
| Phase | **4 — Statistical rigor audit** (skill line 151-164) |
| Date | 2026-05-18 |
| Author | Hyunsoo Kim |
| Issue | #962 |
| Predecessor | Phase 3 audit (#960 / PR #961, merged `914489c`) — STOP gate 영수증 |
| Successor | Phase 5 (Closed error loop audit) — 별 plan turn (skill STOP gate, 사용자 승인 영수증 필요) |
| Strict-forbid | **실제 validator 구현 / seed 스윕 추가 0건** (skill body line 163-164) |

## Executive summary

| # | item | 상태 | 핵심 evidence |
|---|---|:---:|---|
| 1 | Multi-seed 운영 (각 variant 3 seed 이상 mean ± std) | ◐ partial | **Ablation surface ✓** — `scripts/phase2_chunking_ablation.py:711` `--seeds default="17,23,29"` (3-seed) + `scripts/_ablation_common.py:52-69` `_seed_averaged_paired_ci` 가 CI 평균. **Main eval surface ✗** — `eval/run_eval.py` 의 system variant 비교는 `DEFAULT_SEED = 17` 단일 seed (`eval/bootstrap.py:28`). `eval/korean_public/run.py:204` KorQuAD public 도 단일 seed 17. |
| 2 | Paired bootstrap CI 운영 (variant 비교) | ✓ present | `eval/bootstrap.py:78-104` `paired_bootstrap_ci(values_a, values_b, *, num_resamples, alpha, seed)` 완전 impl (paired-delta resampling: 동일 case index 를 두 array 에 동시 적용). `scripts/_ablation_common.py:58` 1개 consumer (PR #950 의 #952/#956 ablation runner). `reports/real100/eval_summary.json` 의 `ci:` block 은 12 metric per-metric CI 보유 (`{accuracy, groundedness, citation_precision, ...}`) — 그러나 단일 metric 의 unpaired CI (variant-비교가 아닌 absolute 분포). |
| 3 | `claim_validator.py` 부재 (개선 주장 → Δ + CI + sample + p-value 검증기) | ✗ absent | `find . -name 'claim_validator*'` → 0건. `grep claim_validator\|validate_claim --include='*.py'` → 0건. 사람 손으로 PR body 에 "+X.Xpp SIG/NS" 표기 (e.g. PR #956 body 의 "**−0.046 SIG** (−0.084, −0.011)" 형식) 가 convention 화돼 있으나 자동 검증기 없음. |

**판정**: present 1 + partial 1 + absent 1. 가장 큰 갭 = **item 3 (claim_validator 0건)** — Phase 4 의 "improvement claim 이 통계적으로 검증 가능한가?" 질문에 현재 답이 "수동 inspection 만".

## 상세 진단

### Item 1 — Multi-seed 운영

**스킬 요구 (line 153-154)**: 각 system variant 가 3 seed 이상으로 실행되어 mean ± std 가 보고되는지 — `eval/run_eval.py` / `eval/config.yaml` 의 seed 처리 grep.

**현재 wiring**:

- **Ablation surface ✓**:
  - `scripts/phase2_chunking_ablation.py:711` — `parser.add_argument("--seeds", default="17,23,29")` (3-seed default)
  - `scripts/_ablation_common.py:52-69` — `_seed_averaged_paired_ci(a, b, seeds)` — `[paired_bootstrap_ci(a, b, seed=seed) for seed in seeds]` 의 `mean_diff/ci_lo/ci_hi` 산술 평균. 산출 dict 에 `seeds` 필드 보존.
  - 즉 **PR #952 (chunking) + #956 (retrieval mode) ablation 은 3-seed averaging 채택**.
- **Main eval surface ✗**:
  - `eval/bootstrap.py:28` `DEFAULT_SEED = 17` — single seed default.
  - `eval/run_eval.py` 본체에 `--seeds` flag 부재 (grep 결과 `--seed` 단수형도 무). 즉 `make real-eval` / `make eval-public` 은 single-seed 실행.
  - `eval/korean_public/run.py:204` — KorQuAD bootstrap_ci 도 단일 `seed=DEFAULT_SEED`.
- **Hashing artifact surface ✓ (단, 다른 의미)**: `scripts/generate_finetune_pairs.py:475`, `scripts/generate_real_cases.py:420` 의 `--seed` 는 stub backend determinism 용 (재현성), variant 비교용 아님.

**Gap**:
- 본 eval pipeline 의 variant 비교 (e.g. `naive_baseline` vs `agentic_full` accuracy delta) 는 single seed 산출. variant 의 randomness 가 LLM judge stochasticity / retrieval scoring tie-break / bootstrap resampling 에 잠재. seed 1개 산출의 CI 가 seed 별로 얼마나 흔들리는지 측정 안 됨.

**Supply 제안** (별 PR):
- `eval/run_eval.py` 에 `--seeds 17,23,29` flag 추가; 각 seed 별 `evaluate_run()` 실행 → 결과를 `_seed_averaged_paired_ci` (이미 존재) 와 동일 패턴으로 metric 별 mean ± std 산출.
- aggregate JSON 의 `ci:` block 을 `{accuracy: {mean, std, ci_lo, ci_hi, seeds}}` 로 schema 확장 (schema version bump 검토 필요 — 기존 consumer 호환성).
- 추정 ~150 LOC + 1 test (3-seed 결정성 + schema round-trip).
- ADR 미발행 또는 별 ADR 후보 (eval pipeline contract 변경).

### Item 2 — Paired bootstrap CI 운영

**스킬 요구 (line 155-157)**: Variant 비교 시 동일 eval 예제에 대한 paired bootstrap CI 가 산출되는지 — `eval/bootstrap.py` 의 현재 능력 측정.

**현재 wiring**:

- **Library ✓** — `eval/bootstrap.py:78-104` `paired_bootstrap_ci`:
  ```python
  def paired_bootstrap_ci(
      values_a: list[float],
      values_b: list[float],
      *,
      num_resamples: int = DEFAULT_NUM_RESAMPLES,
      alpha: float = DEFAULT_ALPHA,
      seed: int = DEFAULT_SEED,
  ) -> dict[str, float | int] | None:
      """Paired-delta CI by resampling case indices once and applying to both arrays."""
  ```
  → length-equal 가드, paired index resampling (`idx = rng.integers(low=0, high=n, size=(num_resamples, n))`, `diffs = (arr_a[idx] - arr_b[idx]).mean(axis=1)`), {mean_diff, ci_lo, ci_hi, n, num_resamples, alpha} 반환.
- **Consumer ✓** — `scripts/_ablation_common.py:21,58` (PR #950→#952→#956), seed averaging wrapper 포함.
- **Main eval pipeline ◐** — `reports/real100/eval_summary.json` 의 top-level `ci:` block 12 metric 보유하나 이는 **unpaired bootstrap_ci** (각 metric 분포의 absolute CI). variant 비교 paired CI 는 ablation runner 가 별도 산출.

**Gap**:
- 본 eval 의 `naive_baseline` vs `agentic_full` 같은 default-vs-baseline pair 의 paired CI 가 `eval_summary.json` 에 미surface (현재는 단일 run aggregate). `make real-eval-delta` 결과의 paired CI 가 명시적 metric output 으로 노출되는지 추가 grep 필요.

**Supply 제안** (별 PR — small):
- `eval/run_eval.py` 의 `compare_runs` 또는 동등 함수에서 `naive_baseline` vs `agentic_full` paired CI 를 metric 별 계산 → aggregate `ci_paired_vs_baseline:` block 추가.
- 추정 ~50 LOC + 1 test.

### Item 3 — `claim_validator.py` 부재

**스킬 요구 (line 158-160)**: 개선 주장 (e.g. "verifier 가 accuracy 를 4% 개선") 입력받아 측정된 Δ, CI, sample size, p-value 출력 + CI 가 0을 가로지르는 주장을 거부할 validator.

**현재 wiring**: **부재 (✗)**.

**Evidence**:
- `find . -name "claim_validator*"` → 0건.
- `grep -rE "claim_validator|validate_claim" --include="*.py"` → 0건.
- Convention 으로 PR body 에 SIG/NS 표기는 존재 — e.g. PR #956 "**−0.046 SIG** (−0.084, −0.011)" 패턴 — 그러나 작성자 손으로 짝지어진 ci_lo/ci_hi 부호 확인 + SIG 라벨 부여. 자동 게이트 부재.

**Gap**: improvement claim 의 통계적 정직성이 reviewer (사람) 의 spot check 에만 의존. PR description 에 "improved X by Y" 라고 적어도 CI 가 0을 가로지르면 (NS) 그 자체를 차단할 자동화 0.

**Supply 제안** (별 PR — **ADR-worthy**):
- 신규 `scripts/validate_claim.py`:
  ```bash
  python3 scripts/validate_claim.py \
    --metric accuracy \
    --baseline reports/real100/baseline.aggregate.json \
    --candidate reports/real100/eval_summary.json \
    --claim "+4.0pp" \
    --min-sample 200
  # exits non-zero if CI crosses 0 OR sample < min-sample OR claim sign mismatches CI
  ```
- `eval/bootstrap.py` 의 `paired_bootstrap_ci` 재사용 + p-value 계산 (one-sided permutation test 또는 bootstrap-based).
- CI integration: `pr-eval.yml` 에 신규 step "claim sanity check" — PR body 에서 `Claim: <metric>=<+Δpp>` 라인 grep 해 위 validator 호출.
- 별 ADR 발행 필요 (PR title/body convention 강화 = governance contract). **ADR 0055/0056 후보** (가칭, 본 audit 시점 미예약).
- 추정 ~200 LOC + 1 ADR + 1 test + pr-eval.yml 변경 ~20 LOC.

## Acceptance checklist 매핑

스킬 본문 line 162-164 의 Phase 4 acceptance:

> multi-seed / paired bootstrap / claim validator 3-item present/partial/absent 표 산출; 각 누락 항목 supply 제안 명시. **실제 validator 구현 / seed 스윕 추가 0건.**

| 요구사항 | 본 audit |
|---|:---:|
| 3-item present/partial/absent 표 산출 | ✓ (Executive summary) |
| 각 partial/absent 항목 supply 제안 명시 | ✓ (상세 진단 §item 1/3 — item 2 는 present 지만 main pipeline 갭으로 부분 supply 제안 추가) |
| 실제 validator 구현 / seed 스윕 0건 | ✓ (code path 0 — docs only) |

→ **Phase 4 acceptance 통과**. 사용자 머지 행위 자체가 STOP gate 영수증 (skill 본문 line 116: "사용자 승인 전 다음 phase 진입 금지" 동일 패턴).

## Out of scope (별 PR / 별 plan turn)

- **위 3 supply 의 실제 구현** — 스킬 본문 strictly forbid.
- **Skill Phase 5 (Closed error loop)** audit — 별 plan turn. 본 audit 머지 후 사용자 승인 영수증 받고 진행.
- **Phase 3 의 미머지 supply** (rationality judge ADR 0055 후보, trace schema_version 2) — 별 PR (Phase 3 audit 가 이미 surface, 본 phase 와 직교).
- **Retrieval-eval skill Phase 4 (Metadata / filtering ablation)** — 별 surface (skill 다름).
- **`answer_format_compliance −0.64pp` 잔여 false-negative** — 별 축, ADR 0054 wrap-up surface.
- **Portfolio repo blog narrative 갱신** — D층 surface, 본 audit 와 독립.

## References

- 본 audit 의 mother skill: [`.claude/skills/eval-framework-progressive-audit/SKILL.md`](../../.claude/skills/eval-framework-progressive-audit/SKILL.md) (PR #889)
- Predecessor: [Phase 3 audit](./eval-framework-phase3-audit.md) (#960 / PR #961, merged `914489c`)
- Item 1 코드 근거 (multi-seed):
  - [`eval/bootstrap.py:28`](../../eval/bootstrap.py) (DEFAULT_SEED=17, single)
  - [`scripts/phase2_chunking_ablation.py:711`](../../scripts/phase2_chunking_ablation.py) (`--seeds 17,23,29` ablation default)
  - [`scripts/_ablation_common.py:52-69`](../../scripts/_ablation_common.py) (`_seed_averaged_paired_ci`)
  - [`eval/korean_public/run.py:204`](../../eval/korean_public/run.py) (KorQuAD single-seed)
- Item 2 코드 근거 (paired bootstrap):
  - [`eval/bootstrap.py:78-104`](../../eval/bootstrap.py) (`paired_bootstrap_ci`)
  - [`scripts/_ablation_common.py:21,58`](../../scripts/_ablation_common.py) (1 consumer + seed averaging)
  - PR #950 (paired CI helper introduction), PR #952 (chunking), PR #956 (retrieval mode)
- Item 3: `find/grep` 0건 — 부재의 evidence.
- Sibling skill (다른 surface): [`.claude/skills/retrieval-eval/SKILL.md`](../../.claude/skills/retrieval-eval/SKILL.md)
- Convention 으로 PR body SIG/NS 표기 사례: PR #956 body 의 "**−0.046 SIG** (−0.084, −0.011)" 표.
