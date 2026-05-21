# Cross-encoder reranker ablation

issue #163(Phase 1.3)를 추적한다. 기존 60/25/15 dense + lexical + metadata 블렌드 위에 additive ablation 으로 cross-encoder 재순위(reranker)를 추가한다.

## 범위(scope)

현재 [`rag_core.retrieve`](../../rag_core.py) 의 `agentic_full` 재순위는 하드코딩된 점수 블렌드(`metadata_first=True` 일 때 0.60 dense + 0.25 lexical + 0.15 metadata)다. cross-encoder 재순위는 현대 검색 스택의 다음 표준 레이어다 — 하나를 ablation 으로 추가하여 블렌드가 정밀도(precision)를 놓치고 있는지 검증한다.

이 페이지는 통합(integration)을 문서화한다. 측정은 로컬 실행 단계다(아래 *Reproduction* 참조).

## 설계(design)

* **Dispatch point**: 기존 60/25/15 블렌드의 `scored.sort()` 이후, `top_k` 컷 + comparison balance **이전**. cross-encoder 는 블렌드 점수가 가장 높은 top-N 후보(N = `min(30, top_k × 3)`)를 재채점하고, sigmoid 로 logit 을 `[0,1]` 로 스쿼시한 뒤 재정렬한다. 블렌드는 recall 깔때기를 공급하고, cross-encoder 는 precision-at-k 를 더한다.
* **Module**: [`rag_rerank.py`](../../rag_rerank.py) — `rag_synthesis.py` 의 lazy-import + stub-default + env-var-gated 패턴을 그대로 따른다.
* **Preset flag**: `rerank_cross_encoder: bool`, 기존 3개 preset(`naive_baseline`, `agentic_full`, `agentic_full_llm`) 모두에서 기본 `False`. [`eval/config.yaml`](../../eval/config.yaml) 의 새 ablation 행 `full_reranker` 가 이를 `true` 로 뒤집는다.
* **Postcondition guard**: 재정렬된 모든 `chunk_id` 는 입력의 부분집합이어야 한다. 위반 시 `meta["fallback_reason"] = "chunk_id_postcondition_violation"` 와 함께 입력 순서로 fallback 한다.
* **Score normalization**: cross-encoder logit 은 `[0,1]` 범위가 아니다. `rag_core.py` ~L2254 의 검증기 점수 하한선(임계값 0.18)은 정규화된 블렌드에 맞춰 튜닝되었는데, sigmoid 스쿼시가 backend 별 분기 없이 이를 계속 동작하게 한다. Cohere 의 `relevance_score` 는 이미 정규화되어 있으므로 Cohere 분기는 sigmoid 를 건너뛰고 대신 clamp 한다.

## Backends

`BIDMATE_RERANK_BACKEND` 로 선택(기본 `stub`):

| backend | model default | env vars | cost | notes |
|---|---|---|---|---|
| `stub` | (none) | — | free | Identity pass-through. **CI 기본.** stub 에서 `full_reranker` 행은 `full` 과 byte 동일. |
| `bge` | `BAAI/bge-reranker-v2-m3` | `BIDMATE_RERANK_MODEL` | free | ~1.1GB 로컬 다운로드. CPU 에서 query 당 ~80–200ms. |
| `bge_ko` | `dragonkue/bge-reranker-v2-m3-ko` | `BIDMATE_RERANK_MODEL` | free | 한국어 파인튜닝. `bge` 와 동일한 FlagEmbedding 코드 경로. |
| `cohere` | `rerank-3.5-multilingual` | `BIDMATE_COHERE_API_KEY` 또는 `COHERE_API_KEY`, `BIDMATE_RERANK_MODEL` | ~$2 / 1k searches (n=42 시 ~$0.084) | 네트워크 호출. 점수가 이미 [0,1] (sigmoid 없음). |

## Reproduction

```bash
# CI-default stub (no-op identity — full_reranker row byte-equals full)
bash scripts/test.sh
python3 eval/run_eval.py --config eval/config.yaml --output_dir reports/stub_rerank

# BGE-reranker-v2-m3 local (FlagEmbedding required)
pip install FlagEmbedding
export BIDMATE_RERANK_BACKEND=bge
python3 eval/run_eval.py --config eval/config.yaml --index_dir data/index --output_dir reports/bge_rerank

# Korean-finetuned variant
export BIDMATE_RERANK_BACKEND=bge_ko
python3 eval/run_eval.py --config eval/config.yaml --index_dir data/index --output_dir reports/bge_ko_rerank

# Cohere rerank-3.5-multilingual (paid)
pip install cohere
export BIDMATE_RERANK_BACKEND=cohere BIDMATE_COHERE_API_KEY=...
python3 eval/run_eval.py --config eval/config.yaml --index_dir data/index --output_dir reports/cohere_rerank
```

## 핵심 수치(headline numbers)

### 파이프라인 버그 수정 (issue #448)

이 수정 이전에는 `eval/config.yaml` 의 `full_reranker` 행에 있는 `rerank_cross_encoder: true` 가
조용히 버려졌다 — 플래그는 `eval/run_eval.py` 에서 읽혔으나
`run_rag_query → _build_run_context → _RunContext → make_plan → plan dict` 로 전파되지 않았다. 그 결과
`full_reranker` 는 `BIDMATE_RERANK_BACKEND` 와 무관하게 `full` 과 byte 동일했다.

같은 PR 에서 `rerank_cross_encoder` 를 다음을 통해 연결하여 수정:
- `rag_query.py:make_plan` (파라미터 + plan dict 키 추가)
- `rag_core.py:_build_run_context` / `_RunContext` / `_phase_retrieve_loop`
- `eval/run_eval.py` 의 `run_rag_query` 호출

### 측정: bge_ko backend (2026-05-13, n=100 synthetic, hashing embeddings)

```
EMBEDDING_BACKEND=hashing BIDMATE_RERANK_BACKEND=bge_ko
eval config: /tmp/eval_reranker_only.yaml (naive_baseline + full + full_reranker)
index:       data/index (hashing embeddings, ADR 0001 public synthetic)
```

**전체 지표 (95% bootstrap CI, n=100):**

| run | accuracy | Δ vs full | citation_precision | Δ vs full | n |
|---|---|---|---|---|---|
| naive_baseline | 0.782 [0.679–0.872] | — | 0.525 [0.450–0.610] | — | 100 |
| full | 0.718 [0.615–0.821] | — | 0.705 [0.625–0.780] | — | 100 |
| full_reranker (bge_ko) | 0.590 [0.487–0.692] | **−12.8pp** | 0.705 [0.620–0.785] | 0pp | 100 |

**query-type 별 accuracy (full vs full_reranker):**

| query_type | full | full_reranker | Δ |
|---|---|---|---|
| single_doc (n=34) | 0.882 | 0.735 | −14.7pp |
| comparison (n=24) | 0.500 | 0.292 | −20.8pp |
| follow_up (n=21) | 0.700 | 0.700 | 0pp |
| abstention (n=21) | 0.000 | 0.000 | 0pp |

**보류(abstention) 분해 (correct_refusal / incorrect_answer / boundary_partial):**

| run | correct_refusal | incorrect_answer | boundary_partial |
|---|---|---|---|
| naive_baseline | 6 | 16 | 0 |
| full | 18 | 4 | 0 |
| full_reranker (bge_ko) | **22** | **0** | 0 |

**Latency (query 당 ms, warm):**

| run | p50 | p95 | mean |
|---|---|---|---|
| naive_baseline | 1.7 ms | 3.1 ms | 1.9 ms |
| full | 2.6 ms | 4.6 ms | 2.6 ms |
| full_reranker (bge_ko) | 2822 ms | 9435 ms | 3559 ms |

### ADR 0026 재개(re-open) 판정 (issue #448)

**조건** (ADR 0026 re-open 임계값): `full` 대비 비중첩(non-overlapping) 95% CI 와 함께
accuracy **또는** citation_precision 이 ≥+3pp 상승.

**결과**: accuracy −12.8pp, citation_precision 0pp. CI 가 중첩됨 (full: [0.615–0.821],
full_reranker: [0.487–0.692]; 중첩 구간 [0.615–0.692]).

**판정: REJECTED.** "0pp-on-full 패턴이 유지됨" — bge_ko reranker 는 hashing embeddings 에서
re-open 임계값을 충족하지 못한다.

**근본 원인**: hashing embeddings 는 비의미적(non-semantic)이다(bag-of-character n-grams). reranker 는
의미적 관련성을 재채점하지만, top-k 입력 후보는 이미 비의미적 블렌드로 정렬되어 있다.
reranker 의 의미적 선호가 hashing 블렌드의 정렬과 어긋나, 답변 가능한 쿼리에 대해 더 나쁜
recall 을 낳는다. 비교(comparison) query 타입이 가장 크게 타격받는데(−20.8pp), 비교는
reranker 가 무너뜨리는 multi-source 다양성을 필요로 하기 때문이다.

**보류 개선은 실재하나 불충분**: bge_ko 는 모든 incorrect_answer 보류를 correct_refusal 로
밀어낸다(incorrect 4→0, correct 18→22). 이는 답변 불가 케이스에서의 정밀도 이득이지만,
답변 가능 케이스에서의 accuracy 가 지배적이다.

**Follow-up 게이트**: CI 에 real-embedding 인덱스가 마련되면 의미적 embeddings(예: `BAAI/bge-m3`)로
재평가한다. 의미적으로 순위 매겨진 후보 리스트에서는 reranker 의 precision-at-k 이득이
드러날 공정한 기회를 갖는다. ADR 0026 의 blocked follow-up 으로 추적한다.

## ADR 이 없는 이유

이는 [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) 하의 stub-default additive ablation 이다: env var 뒤에 게이팅된 opt-in backend 파이프라인이며, CI 는 계속 stub identity 경로를 실행한다. load-bearing 결정은 교체되지 않는다 — 60/25/15 블렌드가 recall 깔때기로 남고, cross-encoder 는 그 위의 *precision-at-k* 정제(refinement)다. 향후 PR 이 블렌드를 cross-encoder 로 교체(또는 제거)한다면, CLAUDE.md 의 "ADR threshold" 에 따라 새 ADR 이 필요하다.

## 위험(risks)

* **점수 하한선 회귀** — 검증기 `min_evidence_score` 는 정규화된 점수에 맞춰 튜닝되어 있다. sigmoid 스쿼시 + Cohere `[0,1]`-clamp 둘 다 점수가 범위 안에 머물도록 보장한다. `tests/test_cross_encoder_rerank.py::RerankSigmoidSquashTest` 가 이를 assert 한다.
* **검증기 재시도 상호작용** — 검증기가 `retrieve()` 를 재호출할 수 있다. `plan["rerank_cross_encoder"]` 는 `rerank` 같은 plan dict 키이므로 재시도를 통해 전파된다. end-to-end normalize_run_config 테스트로 검증됨.
* **stub 결정론** — stub 은 순수 identity 여야 한다(재정렬 없음, 점수 변경 없음). 그렇지 않으면 stub backend 에서 `full` vs `full_reranker` 가 어긋나고 CI 의 hashing-backend 불변식이 깨진다. `RerankStubBackendTest::test_stub_backend_is_identity` 가 고정한다.
* **Latency** — CPU 에서 BGE-reranker 는 query 당 ~80–200ms × 42 queries ≈ eval 시간 5–10s 추가. 100 docs 에 대한 real-data eval 은 선형으로 확장된다. 기본값 전환 시 PR 설명에 latency 비용을 문서화할 것.

## 참고

- [`rag_rerank.py`](../../rag_rerank.py) — backend dispatch
- [`rag_synthesis.py`](../../rag_synthesis.py) — 이 모듈이 따르는 패턴
- [`tests/test_cross_encoder_rerank.py`](../../tests/test_cross_encoder_rerank.py) — 계약 테스트
- [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) — additive-ablation 패턴
- [ADR 0001](../adr/0001-preserve-naive-baseline.md) — naive_baseline 불변식 (cross-encoder 는 naive_baseline 에서 절대 발동하지 않음)
- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) — Phase 1.2 자매 사이클 (#161)
