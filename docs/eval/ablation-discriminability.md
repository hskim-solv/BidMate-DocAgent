# Ablation Discriminability — Null-result as Hero Asset

> 19개 ablation 측정에서 통계적으로 baseline을 이기는 변경 **0건**.
> [ADR 0001 `naive_baseline`](../adr/0001-preserve-naive-baseline.md) 결정성의
> mechanical proof.

이 문서는 portfolio reviewer가 30초 안에 다음 세 가지를 읽도록 설계되었다:

1. **baseline이 강하다** — 19개 변경 시도 중 statistically significant winner 0건.
2. **측정 framework가 honest하다** — CI 겹침이 hide되지 않고 explicit하게 노출된다.
3. **Null result를 결과로 공개한다** — 시니어 엔지니어가 부정적 발견을
   suppress하지 않고 정량 형태로 commit하는 portfolio engineering 시그널.

## Decision rule

ablation A가 baseline B를 *통계적으로* 이긴다고 선언하려면 둘 다 충족해야 한다:

- `mean(A) − mean(B) ≥ +5pp` on 동일 split, 동일 n
- `CI_lo(A) > CI_hi(B)` — 95% bootstrap CI(`n=1000` resamples, seed=17) **비겹침**

CI 겹침은 "동등" 의 증거가 아니라 *현재 n*에서 두 분포를 구별할 수 없다는
[detection limit](https://en.wikipedia.org/wiki/Detection_limit)일 뿐이다.
실제로는 효과가 존재할 수 있고 더 큰 n이 분리할 수도 있다 — 단지 *지금
가진 데이터*로는 baseline 대비 ablation 의 우위를 *주장할 수 없다*.

이 결정 규칙은 다음 문헌의 RAG 평가 관행과 일치한다:

- [RAGAS — Faithfulness/Answer Relevancy CI](https://docs.ragas.io/en/latest/concepts/metrics/) —
  단일 mean이 아니라 분포 비교.
- [LangChain Evals — Bootstrap CI on aggregated runs](https://docs.smith.langchain.com/evaluation/concepts) —
  표본 변동성을 명시.

## Current measurement (n=42, public synthetic, hashing backend)

[README ablation table](../../README.md#ablation-comparison) snapshot에서 4 surfaced
+ 15 detection-blind = **19개 ablation** 를 `naive_baseline` 대비 평가했다.
[(README 원본 line 121–150)](../../README.md#ablation-comparison)

| 결과 카테고리 | 건수 | 비고 |
|---|---:|---|
| `mean ≥ +5pp` AND `CI 비겹침` (= statistically significant winner) | **0 / 19** | hero finding |
| `mean ≥ +5pp` BUT `CI 겹침` (= 시사적이지만 underpowered) | 1 / 19 | `no_verifier_retry` accuracy +6pp, CI [0.731, 0.911] vs `naive_baseline` [0.682, 0.882] — 겹침 |
| `mean ≤ −5pp` AND `CI 비겹침` (= 통계적 regression) | 0 / 19 | — |
| CI 겹침 (= detection-blind) | 18 / 19 | n=42의 half-width ≈ ±0.12 한계 |

n=42 에서 두 Bernoulli 비율 사이의 minimum detectable difference 는 80% power 기준
**~13pp** 이므로, `naive_baseline` (0.782) vs `full` (0.718) 의 −6.4pp 차이는
설계상 검출 불가능하다 — 이것은 `full` 의 결함이 아니라 **n=42 가 통계적
한계**라는 사실의 노출이다.

## Why this is the hero asset

전형적인 ML portfolio는 baseline에서 +X% 개선을 자랑하며 결과를 *positive
selection*한다. 이 저장소는 반대로 한다:

- ADR 0001 결정 — `naive_baseline` 은 fixed-size chunking + dense top-k 만 사용하는
  의도적으로 단순한 floor. **교체되지 않는다** (다른 모든 ablation은 *추가적*).
- 19개 변경 (metadata-first, rerank, verifier+retry, hybrid BM25, hierarchical
  chunking, HyDE, LLM synthesis, LoRA finetune, …) 중 **0건** 이 통계적으로
  baseline을 이김 — [README `<details>` 영역의 "Detection-blind"
  cohort](../../README.md#ablation-comparison) 가 그 사실을 *숨기지 않고*
  surface한다.
- 시니어 reviewer 시그널: "이 후보자는 (a) baseline을 weaponize 했고,
  (b) 자기 ablation이 통계적으로 의미 없다는 사실을 *결과로 게시*했다."

이 두 사실은 별도 README chunk가 아니라 **같은 표** 안에 공존한다 —
[ADR 0001 의 commit boundary](../adr/0001-preserve-naive-baseline.md)
규약을 그대로 따른다.

## n=100 expansion (issue #570 완료)

[Issue #570](https://github.com/hskim-solv/BidMate-DocAgent/issues/570) 로
public synthetic 데이터셋이 n=42 → n=100 으로 확장됐다. Bootstrap CI 폭의 이론적
축소율은 `√(42/100) ≈ 0.65` 이므로 half-width 가 ±0.12 → ±0.078 로 좁아진다.
n=100 에서의 detection limit 는 minimum detectable difference ≈ ~8.5pp.

**Re-measurement 는 real-eval 기준으로 진행되며**, 이 문서는 새 측정이
landing 한 시점에 갱신된다. n=100 결과가 일부 ablation을 detection-blind 에서
분리해낼 수 있다 — 분리되면 그 자체가 새 ADR / amendment 의 evidence; 분리되지
않으면 null 결과가 더 큰 n 에서도 robust 하다는 hardened claim.

## Replication

이 문서의 표는 다음 source 에서 재현 가능:

- `eval/config.yaml` — ablation 정의 (preset name → toggle 조합 매핑)
- [`docs/eval/ablation-results.md`](./ablation-results.md) — 최신 `make benchmark`
  manifest 기반 committed snapshot
- [`README.md` Ablation comparison](../../README.md#ablation-comparison) —
  bootstrap CI 와 detection-blind cohort 가 함께 노출된 portfolio surface

CI bootstrap parameter (n_resamples=1000, alpha=0.05, seed=17) 는
[`eval/run_eval.py`](../../eval/run_eval.py) 의 `bootstrap_ci` helper 에서 pin.

## See also

- [ADR 0001 — Preserve naive_baseline](../adr/0001-preserve-naive-baseline.md) —
  "왜 baseline은 교체되지 않는가" 의 commit-level 결정.
- [ADR 0011 — LLM synthesis as additive ablation](../adr/0011-llm-synthesis-as-additive-ablation.md) —
  `full_llm` / `full_llm_metadata` 가 *추가* surface 이지 replacement 가 아닌 이유.
- [ADR 0030 — Real-eval leaderboard schema](../adr/0030-real-eval-leaderboard-schema.md) —
  n 확장 후 leaderboard 표현 형식.
- [Issue #570](https://github.com/hskim-solv/BidMate-DocAgent/issues/570) —
  n=42 → n=100 expansion (re-measurement pending).
- [Issue #782](https://github.com/hskim-solv/BidMate-DocAgent/issues/782) —
  이 문서를 spawn한 backlog 항목.
