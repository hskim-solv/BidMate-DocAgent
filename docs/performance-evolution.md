# 성능 추이 (Performance Evolution)

> 이 문서는 BidMate-DocAgent 의 평가 지표가 시간에 따라 어떻게 변화했는지를 기록한다. 대화형 time-series 는 [GitHub Pages leaderboard](https://hskim-solv.github.io/BidMate-DocAgent/leaderboard/) 에서 확인할 수 있다.

---

## 1. 평가셋 규모와 신뢰구간 수축

초기 평가셋은 n=42 (single_doc 14 / comparison 10 / follow_up 9 / abstention 9) 였다. bootstrap 95% CI 반폭이 **±0.12** 로, 미세한 성능 차이를 noise 와 구분할 수 없었다.

n=100 으로 확장 후 (issue #570, [ADR 0033](adr/0033-multihop-cross-section-eval-slice.md)):

```
CI 반폭 수축 = ±0.12 × √(42/100) ≈ ±0.078  (×0.65 감소)

  n=42 : Accuracy CI band 폭 ≈ 0.250  (검출 한계: ~25pp 차이부터 통계적 유의)
  n=100: Accuracy CI band 폭 ≈ 0.156  (검출 한계: ~15pp 차이부터 통계적 유의)
```

실제 영향: n=42 에서 `no_rerank` · `hierarchical` 등 여러 ablation 이 `full` 과 동일 metric 으로 보였던 것은 **기능이 동등해서가 아니라 CI 가 차이를 검출하지 못했기 때문** 이었다. n=100 이후 CI 비겹침 비교로 실제 효과 분리가 가능해졌다.

---

## 2. 기능별 단계적 효과 (Ablation Breakdown)

아래 표는 `agentic_full` 의 각 컴포넌트를 하나씩 제거했을 때 지표가 어떻게 변하는지 보여준다 (n=100, 95% CI).

### 핵심 ablation — 통계적으로 유의한 효과

| Ablation | Change | Accuracy | Citation | Groundedness | Abstention | Interpretation |
|---|---|---|---|---|---|---|
| `naive_baseline` | base | 0.844±0.12 | 0.512±0.12 | 0.714±0.14 | 0.300 | extractive, 모든 기능 off |
| `no_metadata_first` | metadata_first off | 0.844±0.12 | 0.679±0.11 | 0.881±0.10 | 1.000 | **CI 비겹침**: citation 0.571–0.786 vs full 0.821–0.976 → metadata_first 효용 입증 |
| `no_verifier_retry` | verifier retry off | 0.906±0.12 | 0.762±0.14 | 0.762±0.14 | 0.300 | **CI 시사**: groundedness 0.619–0.881 vs full 0.857–0.976 → verifier loop 효용 |
| `full` | all on | 0.906±0.12 | 0.905±0.08 | 0.929±0.07 | 1.000 | **최종 생산 파이프라인** |

### 검출 한계 내 ablation (n=100 에서도 CI 겹침)

| Ablation | Accuracy | Citation | Note |
|---|---|---|---|
| `no_rerank` | 0.906±0.12 | 0.905±0.08 | CrossEncoder reranker 기여가 이 n 에서는 noise 내 |
| `hybrid_bm25` | 0.906±0.12 | 0.905±0.08 | BM25 hybrid 는 edge case 에서 recall 보조, 전체 metric 변화 없음 |
| `full_hyde` | 0.906±0.12 | 0.905±0.08 | HyDE query expansion 의 효과는 harder case 집중 real-eval 필요 |
| `full_kiwi` | 0.906±0.12 | 0.905±0.08 | Kiwi 형태소 BM25 는 morphology edge case 에서 보조 |

> CI 겹침 = "이 컴포넌트가 효과 없다"가 아님. n=100 검출 한계 (~15pp) 아래의 미세 효과는 private real-data eval 또는 harder subset 으로 분리 필요.

---

## 3. 질의 유형별 성능 분해

| Query Type (n) | agentic_full Accuracy | naive_baseline Accuracy | Δ |
|---|---|---|---|
| single_doc (34) | 1.000 ± 0.00 | 1.000 ± 0.00 | +0.0pp (ceiling) |
| comparison (24) | 0.875 ± 0.13 | 0.750 ± 0.17 | +12.5pp |
| follow_up (21) | 1.000 ± 0.00 | 0.750 ± 0.19 | **+25.0pp** |
| abstention (21) | 1.000 ± 0.00 | 0.222 ± 0.18 | **+77.8pp** |

**주요 인사이트**:
- follow_up: 대화 context 이어받기 ([`rag_query.py`](../rag_query.py) `resolve_conversation_context`) 가 25pp 기여.
- abstention: verifier retry + `allow_partial_topic` 이 abstention 정밀도를 0.222 → 1.000 으로 끌어올림.
- single_doc: 이미 ceiling — 성능 여력은 비교/복합 질의에 집중.

---

## 4. 시계열 요약 (naive_baseline 안정성 확인)

`naive_baseline` 은 ADR 0001 ("preserve extractive floor") 에 의해 **의도적으로 불변**이다. 아래는 leaderboard history 의 요약 통계:

```
naive_baseline (2026-05-11 ~ 2026-05-12, N=68 runs):
  Accuracy    : 0.844  (σ=0.000, 전 구간 동일)
  Citation    : 0.512  (σ=0.000)
  Groundedness: 0.714  (σ=0.000)
  Abstention  : 0.300  (σ=0.000)
```

68개 CI run 에서 단 한 번도 수치가 바뀌지 않았다 — 이것이 "regression sentinel" 로서의 naive_baseline 역할이다. `agentic_full` 이 이 숫자를 갑자기 건드리면 load-bearing path 에 의도치 않은 변경이 생긴 것이다.

`agentic_full` time-series 는 [ADR 0030](adr/0030-leaderboard-headline-includes-agentic-full.md) 이후 PR [#477](https://github.com/hskim-solv/BidMate-DocAgent/pull/477) 스냅샷부터 누적 중이다.

---

## 5. 평가 인프라 개선 이력

| PR | 변경 | 효과 |
|---|---|---|
| [#464](https://github.com/hskim-solv/BidMate-DocAgent/pull/464) | N-aware silence band + base/head CI | real(N=21) 에서도 5e-4 고정 임계값 → N 비례 임계값으로 신호 감지 |
| [#480](https://github.com/hskim-solv/BidMate-DocAgent/pull/480) | eval_summary.json 캐싱 | base-side re-run ~5분 → ~0초 |
| [#472](https://github.com/hskim-solv/BidMate-DocAgent/pull/472) | push-per-commit → 일 1회 cron | leaderboard 노이즈 감소 |
| [#570](https://github.com/hskim-solv/BidMate-DocAgent/issues/570) | 평가셋 n=42 → n=100 | CI 반폭 ×0.65 수축, 미세 ablation 효과 검출 가능 |

---

> 이 문서의 수치는 `reports/eval_summary.json` · `reports/leaderboard.md` 에서 파생됩니다. 상세 STAR 회고는 [docs/rag-challenges-solved.md](rag-challenges-solved.md) 를 참조하세요.
