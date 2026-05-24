# Embedding LoRA 미세조정(fine-tune) — 한국어 RFP 쌍 위 KURE-v1

> **Status.** 골격은 #435 에서 커밋; 측정 수치 + 모델 카드(model-card)
> 근거는 어댑터(adapter)를 Colab 에서 학습한 뒤 #179 에서 채움.
> `TODO(user)` 로 표시된 섹션은 *인지적 소유권(cognitive-ownership)* 표면이다 —
> 에이전트(agent)가 초안을 작성하게 두지 말고 본인의 프레이밍으로 직접 작성하라.

- **Related**: issue [#179](https://github.com/hskim-solv/BidMate-DocAgent/issues/179), [ADR 0027](../adr/0027-lora-finetuned-embedding-additive.md), [ADR 0019](../adr/0019-embedding-default-stays-minilm.md), [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md).
- **Notebook**: [`notebooks/embedding_finetune.ipynb`](../notebooks/embedding_finetune.ipynb) — Colab T4 에서 end-to-end 실행 가능.
- **Adapter**: Hugging Face Hub 의 `bidmate/embedding-lora-kure-rfp-ko-v1` *(#179 에서 업로드; SHA 는 [`eval/config.yaml`](../../eval/config.yaml) 에 고정)*.

## TL;DR

<!-- TODO(user): one-paragraph honest framing. Suggested skeleton:

  - Phase 1.2 (ADR 0019) measured 4 off-the-shelf embeddings → bit-identical
    `full` metrics → metadata-first design absorbs embedding variance.
  - This work adds the *trained* artifact (LoRA on KURE-v1) — the embedding-
    fine-tune cycle Phases 1.2/1.3 deliberately left out.
  - Headline measurement is `naive_baseline_finetuned` vs `naive_baseline`
    (dense-only surface where embedding actually matters); the `full` row
    is published as a deliberate null delta, not hidden.

  Write this in your own words — interview answers come out of this paragraph. -->

## 학습 데이터(Training data)

| Statistic | Value |
|---|---|
| Source corpus | `eval/fixtures/smoke_rfp/raw/` — 7 public fixture smoke RFP JSON files (~10.7 KB) |
| Sub-chunks (at `max_chars=240`) | 25 |
| Queries per chunk | 200 (Anthropic backend, Claude Sonnet 4-6) |
| Total generated queries | <!-- TODO(user): paste stats.queries_generated from script output --> |
| Contamination-rejected | <!-- TODO(user): stats.queries_rejected --> |
| Rejection rate | <!-- TODO(user): stats.rejection_rate (must be < 5%) --> |
| Hard negatives per positive | 3 (BM25 rank window [3, 15]) |
| Train / val split | 90 / 10 deterministic by `sha1(query) % 10` |

**Schema reference**: [`data/training/sample.jsonl`](../../data/training/sample.jsonl) — 25행 대표 샘플 (커밋됨; 전체 5k JSONL 은 `.gitignore` 처리).

**오염 가드(Contamination guard)**: 스크립트는 생성된 쿼리(query) 중
`eval/dev_queries_v1.jsonl`, `eval/multiturn_scenarios_v1.jsonl`, 또는
`eval/config.yaml` cases + `prior_turns` 에 있는 항목과 일치하는(소문자화·조사 제거·3-gram Jaccard ≥ 0.70) 것을 모두 거부한다.
거부율(rejection rate)이 5% 를 넘으면 loud-fail 한다.

## 하이퍼파라미터(Hyper-parameters)

| | Value |
|---|---|
| Base model | `nlpai-lab/KURE-v1` |
| LoRA `r` | 16 |
| LoRA `alpha` | 32 |
| LoRA `dropout` | 0.05 |
| `target_modules` | `query`, `key`, `value`, `dense` |
| `task_type` | `FEATURE_EXTRACTION` |
| Loss | `MultipleNegativesRankingLoss` |
| Epochs | 1 |
| Batch | 32 |
| LR | 2e-5 |
| Scheduler | cosine, 10 % warmup |
| AMP | on |
| Seed | 17 |

## 학습 곡선(Training curve)

<!-- TODO(user): export `notebooks/_artifacts/training_curve.png` from the
     notebook and embed below. The image is gitignored — commit it to the
     HF Hub repo's model card README instead, or convert to a small inline
     ASCII summary. -->

## Eval 델타

### A. Dense-only 표면 (헤드라인)

public n=42 fixture smoke eval 위 `naive_baseline_finetuned` vs `naive_baseline` (KURE-v1 base).
**여기가 임베딩(embedding)이 실제로 중요한 지점이다** — metadata-first (ADR 0002) 가 여기서는 dense 를 우회하지 않는다.

| Metric | KURE-v1 base | KURE-v1 + LoRA | Δ | 95 % bootstrap CI |
|---|---|---|---|---|
| accuracy | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| groundedness | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| citation_precision | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

### B. Chunk 단위 검색(retrieval) (gold-annotated 부분집합)

`gold_chunk_ids` 가 있는 `eval/config.yaml` 의 13 cases — 임베딩을 격리하는 표면으로,
metadata-first 라우팅(routing)의 영향을 받지 않는다.

| Metric | KURE-v1 base | KURE-v1 + LoRA | Δ |
|---|---|---|---|
| chunk_recall@5 | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| chunk_MRR | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

### C. `full` 파이프라인 — 공개되는 null 델타

`agentic_full_finetuned` vs `full` (KURE-v1 base). Phase 1.2 (ADR 0019) 에 따르면
metadata-first 파이프라인이 임베딩 분산(variance)을 흡수한다; CI 가 겹치는 ~0 pp ± 2 pp 를 예상한다.
**그래도 공개하라** — 숨기면 LoRA 가 도움이 되는 지점과 그렇지 않은 지점을 잘못 표현하게 된다.

| Metric | KURE-v1 base | KURE-v1 + LoRA | Δ | 95 % bootstrap CI |
|---|---|---|---|---|
| accuracy | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| groundedness | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| citation_precision | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

## 모델 카드(Model card)

<!-- TODO(user): own this section. Suggested headings:

  - Base model + license inheritance
    (KURE-v1 → MIT; adapter inherits MIT)
  - Intended use
    (Korean RFP retrieval; do NOT use as a general-purpose Korean encoder
    — domain-narrow training data)
  - Training data description
    (synthetic queries from 7 public RFP samples; no real bidder data)
  - Known limitations
    (small training corpus, single-domain, query quality bounded by
    Claude's Korean fluency, no asymmetric query/passage split)
  - Ethical considerations
    (extractive grounding contract preserved by ADR 0003; the LoRA only
    changes vector content, not the answer-citation contract)

  These are the parts an external reader uses to judge the work — author
  in your own voice. -->

## 재현성(Reproducibility)

쌍(pair) 재생성 (`seed=17` 으로 결정론적, byte-stable):

```bash
python scripts/generate_finetune_pairs.py \
    --queries_per_chunk 200 \
    --neg_per_pos 3 \
    --seed 17 \
    --output data/training/embedding_pairs.jsonl
# Anthropic backend (paid): BIDMATE_PAIRGEN_BACKEND=anthropic + API key env vars
```

학습 (Colab T4, ~30 min):

```
# Open notebooks/embedding_finetune.ipynb in Colab.
# Runtime → Change runtime type → T4 GPU.
# Run All. Adapter saves to lora_adapter/ and pushes to HF Hub.
```

Eval (operator 측, 어댑터가 HF Hub 에 올라간 뒤). `scripts/run_embedding_ablation.py`
는 `BIDMATE_EMBEDDING_LORA_ADAPTER` 가 설정되면 출력 slug 에 `__lora_<adapter>` 접미사를 붙이므로,
아래 두 run 은 *별도* 디렉터리에 기록된다 — run 간 수동 `mv` 불필요.

```bash
# Run A — baseline KURE-v1 (no adapter)
python scripts/run_embedding_ablation.py --models nlpai-lab/KURE-v1
# → reports/embedding-ablation/nlpai_lab_KURE_v1/eval_summary.json

# Run B — LoRA-adapted KURE-v1
export BIDMATE_EMBEDDING_LORA_ADAPTER=bidmate/embedding-lora-kure-rfp-ko-v1
python scripts/run_embedding_ablation.py --models nlpai-lab/KURE-v1
# → reports/embedding-ablation/nlpai_lab_KURE_v1__lora_bidmate_embedding_lora_kure_rfp_ko_v1/eval_summary.json
unset BIDMATE_EMBEDDING_LORA_ADAPTER

# Diff the relevant ablation rows on the dense-only surface:
diff <(jq '.ablation.runs[] | select(.name=="naive_baseline")'           reports/embedding-ablation/nlpai_lab_KURE_v1/eval_summary.json) \
     <(jq '.ablation.runs[] | select(.name=="naive_baseline_finetuned")' reports/embedding-ablation/nlpai_lab_KURE_v1__lora_bidmate_embedding_lora_kure_rfp_ko_v1/eval_summary.json)
```

`BIDMATE_EMBEDDING_LORA_ADAPTER` 가 설정되지 않으면 `rag_core.embed_texts` 는
#434 이전 동작과 bit-identical 하다 — additive-ablation 불변식
(ADR 0001 / 0025) 은 다음에 의해 고정된다:
[`tests/test_finetuned_ablation_baseline_invariant.py`](../../tests/test_finetuned_ablation_baseline_invariant.py).
