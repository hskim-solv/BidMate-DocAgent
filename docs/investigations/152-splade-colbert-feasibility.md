# 152: SPLADE / ColBERT late-interaction feasibility

- **Status**: investigation (not accepted; precedes a possible ADR 0025)
- **Date**: 2026-05-12
- **Deciders**: retrieval owner, eval owner
- **Related**: [#152](https://github.com/hskim-solv/BidMate-DocAgent/issues/152) (this), [#119](https://github.com/hskim-solv/BidMate-DocAgent/issues/119) (hybrid BM25 parent), [#149](https://github.com/hskim-solv/BidMate-DocAgent/issues/149) (RRF k sweep), [#150](https://github.com/hskim-solv/BidMate-DocAgent/issues/150) (Korean STOPWORDS), [#151](https://github.com/hskim-solv/BidMate-DocAgent/issues/151) (BGE-M3, open), [ADR 0010](../adr/0010-hybrid-bm25-dense-retrieval-rrf.md), [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md)

## TL;DR

ADR 0010 채택 시 SPLADE / ColBERT 는 "hybrid_bm25 가 측정 가능한 real-data gap 을 남기면" 재검토하는 조건으로 명시 deferral 됐다. PR #159 / #119 5b 의 private 21-case smoke 가 그 gap 을 이미 보였다 (groundedness −0.095 / citation_precision −0.143 / intended-abstention −0.500). 이 노트는 (a) #149+#150 의 새 knob 으로 그 gap 이 실제로 닫히는지 정량화하고, (b) ColBERT 저장 비용을 산정하고, (c) SPLADE 와 BGE-M3 sparse 채널의 mechanically equivalence 를 desk-check 해 SPLADE 별도 도입의 의미를 평가하고, (d) 4분면 결정 matrix 로 #151 BGE-M3 결과 이후의 go/no-go 경로를 미리 명시한다.

**잠정 결론** (4분면 matrix § 6 참조, 실측 값은 §3 TBD):
- SPLADE 는 BGE-M3 sparse 와 redundant — #151 이 landing 하면 SPLADE 분기는 자동 close 한다.
- ColBERT 는 PLAID quantized 경로 (~1.9× dense) 만 tractable; naive multi-vector 1024-dim 경로 (~240× dense) 는 non-starter.
- #149+#150 knob 만으로 gap 이 닫히면 (§3 decision rule 통과) ADR 0025 없이 #152 를 no-go 로 close.

## 1. Context

[ADR 0010](../adr/0010-hybrid-bm25-dense-retrieval-rrf.md) "Alternatives considered" 의 마지막 항목:

> **SPLADE / ColBERT late interaction** — out of scope; revisit if hybrid_bm25 still leaves a measurable real-data gap.

[#119 PR #159 의 item 5b](https://github.com/hskim-solv/BidMate-DocAgent/issues/119) 는 private 21-case smoke 에서 base(dense) → head(hybrid_bm25) 의 다음 delta 를 보고했다:

| Metric | Base (dense) | Head (hybrid_bm25) | Δ |
|---|---|---|---|
| Groundedness | 0.524 | 0.429 | **−0.095** ⚠️ |
| Citation precision | 0.429 | 0.286 | **−0.143** ⚠️ |
| Intended-abstention | 1.000 | 0.500 | **−0.500** ⚠️ |
| Latency p95 (ms) | 374.170 | 97.980 | −276.19 ✅ |
| Retry rate | 0.667 | 0.429 | −0.238 ✅ |

`Δ groundedness = −0.095` 는 #152 의 "≥ 0.05 groundedness" gate 를 넘어선다 — 즉 gap 이 정량적으로 측정됐다. 단, 그 사이 #149 (`RRF_K` 를 plan-time knob 으로 노출) 와 #150 (`bm25_stopword_profile = bm25_extra`) 이 merge 됐고 real-data 재측정은 아직 commit 되지 않았다. 우선 그 재측정으로 "knob 만으로 닫히는지" 를 확인한 뒤 SPLADE/ColBERT 결정으로 넘어가는 것이 본 노트의 순서다.

## 2. Why investigation-only

세 가지 이유:

1. **#151 BGE-M3 가 아직 open** — 이슈는 #149 / #150 / #151 결과를 모두 본 뒤 의사결정하라고 명시함 ("그 전에는 **investigation only**"). #151 은 PR 도 branch 도 없는 상태이므로 본 노트는 ADR 0025 까지 가지 않고 의사결정 frame 만 잡는다.
2. **ADR threshold** ([CLAUDE.md](../../CLAUDE.md)) — "Removing or replacing a load-bearing decision" 만 ADR 자격. 본 노트는 ADR 0010 의 deferral 조건을 확인하는 작업이지 새 load-bearing decision 이 아니다.
3. **n=21 noise floor** — 단일 case flip = 1/21 ≈ 0.048 으로 gate (0.05) 와 거의 같다. 작은 sweep 결과를 단일 metric 으로 해석하지 않는 규약 (§3 decision rule) 이 필요하다.

## 3. Gap quantification

### 3.1 Sweep design (2×2 minimum, four cells)

기존 knob 만으로 측정 가능. 모든 cell 은 `eval/config.yaml` 의 기존 row 또는 본 PR 에서 추가하는 단일 row 로 표현된다.

| Cell | retrieval_backend | rrf_k | bm25_stopword_profile | Source preset |
|---|---|---|---|---|
| C1 dense control | dense | — | — | `full` |
| C2 hybrid default | hybrid | 60 | shared | `hybrid_bm25` |
| C3 hybrid tuned | hybrid | **30** | **bm25_extra** | **NEW**: `hybrid_bm25_k30_extra` |
| C4 hybrid k best | hybrid | best ∈ {10, 30, 100} | shared | `hybrid_bm25_k{10,30,100}` |

C3 가 두 knob 을 동시에 켜는 유일한 cell 이다. k=30 을 single pick 으로 둔 이유: 공개 synthetic 의 k-sweep 이 평탄했고 (`docs/ablation-results.md` 의 `hybrid_bm25_k{10,30,60,100}` 동일 metric), 작은 k 는 top-rank 비중을 키워 BM25 noise hit 의 영향을 줄일 가능성이 큼. 4-cell 풀스윕 (`k × profile`) 은 eval cost 두 배이므로 1-axis-collapsed 가 최소 비용 선택.

### 3.2 Procedure ([ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md) boundary)

private 100-doc / 21-case real-data 에서만 실행. raw 결과는 `artifacts/benchmarks/private100_*/` 에 로컬로만 둔다.

```bash
# Each cell — pipeline 이름만 바꿔서 4번 실행
make real-eval PIPELINE=full                       # C1 baseline
make real-eval PIPELINE=hybrid_bm25                # C2
make real-eval PIPELINE=hybrid_bm25_k30_extra      # C3 (NEW row)
make real-eval PIPELINE=hybrid_bm25_k30            # C4 (best-of 후보)
make real-eval-delta BASE=full HEAD=hybrid_bm25_k30_extra
```

본 노트 §3.3 표에는 **aggregate Δ 만** 옮겨 적는다. per-case predictions / chunk IDs / 원문은 절대 commit 하지 않는다 ([docs/private-100-doc-experiments.md](../real-data/private-100-doc-experiments.md) 의 commit boundary).

### 3.3 Results (private 21-case)

> TBD — 측정 후 본 PR 의 review round 에서 채운다. 실측치를 채울 때까지 §6 decision matrix 의 "BGE-M3 leaves gap" row 는 잠정 상태.

| Cell | Δ groundedness | Δ citation_precision | Δ intended-abstention | p95 latency (ms) | retry_rate |
|---|---|---|---|---|---|
| C2 hybrid default vs C1 | (#119 reference: −0.095) | (−0.143) | (−0.500) | (−276.19) | (−0.238) |
| C3 hybrid tuned vs C1 | TBD | TBD | TBD | TBD | TBD |
| C4 hybrid k best vs C1 | TBD | TBD | TBD | TBD | TBD |

### 3.4 Decision rule (noise-aware)

- **Sign rule**: 단일 metric 만으로 판단하지 않는다. `{groundedness, citation_precision, intended-abstention}` 중 **2개 이상**이 동일 방향 (improvement) 일 때만 "knob 이 회귀를 메꿨다" 로 본다.
- **Magnitude rule**: hybrid 셋의 best 가 (i) `Δ groundedness ≥ −0.019` (i.e., #119 의 −0.095 gap 의 ≥ 80% 회복) AND (ii) `Δ citation_precision ≥ −0.02` (within dense control 의 작은 envelope) AND (iii) `intended-abstention ≥ 0.75` 면 **#152 를 no-go 로 close** — SPLADE/ColBERT 불필요.
- **Otherwise**: gap 잔존. §6 matrix 의 BGE-M3-dependent row 로 넘어간다.

## 4. ColBERT storage cost

### 4.1 Anchors from the existing index

[data/index/index.json](../../data/index/index.json) + [data/index/embeddings.npy](../../data/index/embeddings.npy) 의 공개 sample 에서 직접 추출:

| Field | Value | Source |
|---|---|---|
| N_chunks | 9 | `len(idx["chunks"])` |
| avg_tokens / chunk | 90.2 | `mean(len(c["tokens"]))` |
| max_tokens / chunk | 143 | `max(...)` |
| min_tokens / chunk | 57 | `min(...)` |
| embedding dim | 384 | `idx["embedding"]["dimension"]` |
| embeddings.npy size | 13,952 B | `os.path.getsize(...)` |
| dtype | float32 | `np.load(...).dtype` |
| backend | local-hashing-bow | `idx["embedding"]["model"]` |

Private real100 의 N 은 gitignored — `docs/real-data-failure-taxonomy.md` 의 100 docs × 30–50 chunks/doc 추정으로 **3,000–5,000 chunks 범위** 로 둔다. 정확한 수는 본 노트에 commit 하지 않는다.

### 4.2 Per-chunk storage formula

토크나이저는 [rag_core.py:138](../../rag_core.py:138) `TOKEN_RE = r"[A-Za-z0-9]+|[가-힣]+"`. chunk 상한은 [rag_core.py:103](../../rag_core.py:103) `DEFAULT_CHUNK_MAX_CHARS = 520`. 두 값 모두 본 산정 그대로 적용.

| Variant | Per-chunk bytes | vs dense baseline | At N=10,000 chunks |
|---|---|---|---|
| Dense (current MiniLM 384-dim) | 384 × 4 = **1,536** | 1.0× | 15 MB |
| Dense (BGE-M3 1024-dim, ADR 0021) | 1024 × 4 = **4,096** | 2.67× | 41 MB |
| BGE-M3 multi-vector (1024-dim per token) | 90 × 1024 × 4 ≈ **368,640** | **240×** | **3.7 GB** ❌ |
| ColBERTv2 + PLAID (32-dim, 2-bit residuals) | 90 × 32 × 1 ≈ **2,880** | **1.88×** | 29 MB ✅ |

### 4.3 Verdict

- BGE-M3 식 raw multi-vector 1024-dim 경로는 disk + RAM 양쪽에서 dense 대비 240× 이상으로 비합리적. `embeddings.npy` sidecar schema ([rag_vector_store.py:38](../../rag_vector_store.py:38)) 가 ragged shape 를 가정하지 않는 것까지 고려하면 schema break 까지 동반.
- ColBERTv2 + PLAID quantized 경로는 dense 의 1.9× 수준에서 tractable; 단 PLAID indexer 의존성 추가 (cost 별도 평가 필요).
- **사전 결론**: ColBERT 도입을 고려할 경우 quantized 경로만 검토. naive 경로는 본 노트로 영구 배제.

## 5. SPLADE vs BGE-M3 sparse head equivalence (desk research)

| Axis | SPLADE-v2 (`naver/splade-cocondenser-ensembledistil`) | BGE-M3 sparse head |
|---|---|---|
| Vocab | BERT WordPiece ~30k (English-centric base) | XLM-R SentencePiece ~250k (multilingual) |
| Token activation | `log(1 + ReLU(MLM logits))`, FLOPS reg | `ReLU(MLP(hidden))` + learned token-importance |
| Scoring | sparse dot product (inverted index) | sparse dot product (inverted index) |
| Training objective | distillation from cross-encoder, FLOPS reg | joint self-distillation across dense/sparse/multi-vector heads |
| Korean RFP coverage | English base; Korean fine-tune 필요 | multilingual pretraining 으로 Korean native |
| Forward pass | dedicated model | shared model with dense + multi-vector |
| Index format | inverted index over BERT vocab | inverted index over XLM-R vocab |

### 5.1 Verdict

**SPLADE 는 BGE-M3 sparse head 와 redundant** — 본 프로젝트의 Korean RFP 사용 사례에서:

- 두 방식 모두 vocab-sized sparse term weight + dot-product scoring 으로 mechanically equivalent.
- BGE-M3 는 multilingual pretraining 으로 Korean native 인 반면 SPLADE 는 Korean fine-tune 의 추가 비용이 필요하다.
- BGE-M3 는 single forward pass 로 dense + sparse + multi-vector 세 채널을 동시에 산출하므로 SPLADE 별도 모델 운영은 net cost 증가.

→ **#151 BGE-M3 가 ship 되면 #152 의 SPLADE 분기는 자동으로 close**. 본 노트는 SPLADE 단독 ADR 을 권장하지 않는다.

## 6. Decision matrix

`{#149+#150 knob 으로 gap 해소}` × `{#151 BGE-M3 ship + gap closure}` × `{ColBERT cost 수용 가능}` 의 단순화 2-stage 결정 트리:

### Stage 1 — 본 PR 의 §3 sweep 결과로 분기

| Outcome | Action |
|---|---|
| §3.4 decision rule 통과 (knob 만으로 gap 닫힘) | **Close #152 as no-go.** ADR 0010 의 deferral 조건이 무효화됨. SPLADE/ColBERT 모두 불필요. |
| §3.4 decision rule 미통과 | Stage 2 로 이동 |

### Stage 2 — #151 BGE-M3 PR ship 후 분기

| | ColBERT cost 수용 가능 (PLAID 경로) | ColBERT cost 비수용 |
|---|---|---|
| **BGE-M3 가 gap 닫음** (§7 hand-off 기준 충족) | Close #152 no-go. ADR 0021 + #151 PR 으로 커버. | Close #152. #151 단독 ship. |
| **BGE-M3 가 gap 못 닫음** | **Open ADR 0025** scope: ColBERTv2 + PLAID late interaction only. SPLADE 분기는 §5 verdict 로 영구 배제. | Document residual gap; defer; re-evaluate 시 cheaper late-interaction 기법 (e.g., COIL, ALIGNER) 등장 시 재검토. |

각 cell 은 verb-first action — close / open / document / defer — 으로 명시.

## 7. Hand-off criteria to #151

#151 PR 이 close 됐을 때 본 #152 의 후속 action 을 결정짓는 numeric signal:

- **#152 closes when #151 PR 의 5b 가 보고:** `Δ groundedness ≥ +0.05 vs hybrid_bm25` on 21-case real-data smoke **AND** citation_precision 이 dense control 의 ±0.02 envelope 내로 복귀.
- **#152 escalates to ADR 0025 draft when #151 의 5b 가 보고:** `Δ groundedness < +0.05`, OR intended-abstention 이 0.75 미만 (즉 #119 의 −0.500 abstention collapse 가 잔존). 이 경우 §6 Stage 2 의 BGE-M3-leaves-gap row 가 활성화되며 ColBERTv2/PLAID cell 이 유일한 후속 후보가 된다.

#151 PR 본문 5b 에 위 두 metric 이 명시되지 않으면 #152 owner 가 review 단에서 보강을 요청한다.

## 8. Out of scope

본 노트는 다음을 **수행하지 않는다**:

- SPLADE / ColBERT 모델 import 또는 weight 다운로드.
- `index.json` 또는 `embeddings.npy` schema 변경 (token-level multi-vector sidecar 도입 없음).
- `rag_core.py` 의 retrieval 경로 수정 (`retrieve_candidates`, `apply_fusion_and_reranking`, score_parts 변경 없음).
- `eval/config.yaml` 에 `retrieval_backend = "splade"` 또는 `"colbert"` row 추가.
- [rag_pipeline_presets.py:167](../../rag_pipeline_presets.py:167) `VALID_RETRIEVAL_BACKENDS` 수정.

본 PR 의 유일한 코드/설정 변화는 [eval/config.yaml](../../eval/config.yaml) 에 §3.1 의 `hybrid_bm25_k30_extra` row 1개 추가 — 두 knob 모두 [rag_pipeline_presets.py](../../rag_pipeline_presets.py) `VALID_RRF_K_RANGE` / `VALID_BM25_STOPWORD_PROFILES` 안의 기존 값이므로 validator 변경 없음.

## 9. Risks

- **n=21 noise floor** — single case flip = 0.048, gate (0.05) 와 인접. §3.4 sign rule 로 mitigate.
- **`bm25_extra` 의 양면성** — Korean particle (까지/부터) 제거가 abstention 은 회복시키되 정확도 (groundedness ↑ but citation_precision ↓) 의 mixed 결과를 낼 수 있음. §3.3 표는 세 metric 모두 보고.
- **BGE-M3 환경 의존성** — [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md) 와 [docs/embedding-ablation.md](../eval/embedding-ablation.md) 가 `torch < 2.6` 제약을 명시. #151 이 환경 이슈로 ship 되지 않으면 §6 Stage 2 의 BGE-M3 row 자체가 측정 불가 — 이 경우 #152 는 무기한 deferred.
- **load-bearing config 변경** — `eval/config.yaml` 은 [scripts/_governance.py](../../scripts/_governance.py) `LOAD_BEARING_PATHS` 에 포함되므로 본 PR 은 PR template item 5b 를 채워야 한다.
- **PLAID 의존성** — ColBERTv2 quantized 경로는 RAGatouille / Stanford PLAID 등 별도 stack 의존; ADR 0025 가 열릴 경우 그 비용을 cost 표에 추가해야 한다.

## 10. References

- [docs/adr/0010-hybrid-bm25-dense-retrieval-rrf.md:84](../adr/0010-hybrid-bm25-dense-retrieval-rrf.md) — deferral anchor.
- [docs/adr/0021-bge-m3-completes-phase-1-3.md](../adr/0021-bge-m3-completes-phase-1-3.md) — BGE-M3 status.
- [docs/ablation-results.md](../eval/ablation-results.md) — 공개 synthetic ablation rows (hybrid_bm25 k-sweep, bm25_extra).
- [docs/private-100-doc-experiments.md](../real-data/private-100-doc-experiments.md) — ADR 0005 commit boundary.
- [docs/embedding-ablation.md](../eval/embedding-ablation.md) — 모델 size / latency anchor.
- [eval/config.yaml:89](../../eval/config.yaml:89) — `hybrid_bm25` 및 k-sweep / bm25_extra row 위치.
- [rag_core.py:103](../../rag_core.py:103) — `DEFAULT_CHUNK_MAX_CHARS = 520`.
- [rag_core.py:138](../../rag_core.py:138) — `TOKEN_RE`.
- [rag_pipeline_presets.py:40](../../rag_pipeline_presets.py:40) — `RRF_K = 60` default.
- [rag_pipeline_presets.py:168](../../rag_pipeline_presets.py:168) — `VALID_BM25_STOPWORD_PROFILES`.
- [rag_vector_store.py:38](../../rag_vector_store.py:38) — `EMBEDDINGS_FILENAME` sidecar.
