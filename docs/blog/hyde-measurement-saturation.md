# 0pp lift 가 가리킨 것 — 측정 surface 안의 진짜 신호

> This post documents the measurement-surface diagnosis that led to [ADR
> 0032](../adr/0032-eval-saturation-routed-subset.md).  Originally
> drafted as a portfolio retrospective; rehomed to engineering repo
> (`docs/blog/`) so that the methodology — 24×0pp saturation detection
> + hashing-backend artifact analysis + cross-validation with
> sentence-transformers backend — stays visible to future engineers
> reading the ADR cluster.  Sibling post:
> [`docs/blog/2026-05-extractive-baseline.md`](./2026-05-extractive-baseline.md).

BidMate-DocAgent 에 HyDE (Hypothetical Document Embeddings, Gao et al. 2022) 를 plug-in 가능한 ablation 으로 추가했다. 측정 결과는 `full` 대비 정확히 **0pp lift**였다. 본 글은 그 0pp 가 무엇을 *진짜로* 가리키고 있었는지에 대한 기술 조사 (technical investigation) 다.

결론부터 적는다 — HyDE 는 폐기되지 않았다. 측정 surface 자체가 변별력을 잃어 그 위에서 HyDE 를 평가할 수 없는 상태였다는 결론이 나왔고, 그래서 *측정 surface* 를 의심하는 별도 ADR (0032) 을 썼다. 이것이 RAG 트렌드 한 줄짜리를 코드에 넣는 데 들인 시간의 80% 였다.

## 왜 HyDE 를 넣고 싶었나

한국 공공 RFP corpus 는 두 가지 특징이 있다.

1. **사용자 query 는 짧고 구어체.** "이 사업 핵심 리스크 뭐야?", "보안 통제 요건은?"
2. **Corpus chunk 는 길고 합니다체.** "본 사업의 정보보안 관리체계는 ISMS-P 인증 기준 통제항목 102개를 준수하며 …"

Dense retrieval 에서 [짧은 구어체 query 임베딩] ↔ [긴 합니다체 chunk 임베딩] 을 비교하면, 같은 의미여도 표현 register 가 달라 코사인 유사도가 systematic 하게 떨어진다. 정확히 이걸 풀라고 HyDE 가 제안된 거다 — LLM 이 query 를 받아 "이 query 에 대한 가상의 정답 passage" 를 합니다체로 만들고, 그 passage 를 임베딩해서 retrieval 에 쓴다. 실패 분석 트레이스에서 top-K miss 케이스 대부분이 이 vocabulary gap 이었다.

도입은 명확히 정당화됐다. 의문은 "HyDE 를 *default 로 켤 것인가*" 였다.

## Promote 조건을 사전에 명시한 이유

[ADR 0023](../adr/0023-hyde-query-expansion-ablation.md) 에 다음 promote 조건을 코드 작성 *전*에 박았다.

> `full_hyde` real backend 가 `full` 대비 **≥ +3pp lift + non-overlapping 95% CI on public synthetic n ≥ 100**

사후가 아니라 사전에 박은 이유는 명확하다. 측정 후에 임계값을 정하면 무의식적으로 결과에 맞춰 임계값을 조정하게 된다 (Goodhart's law 의 self-applied 버전). 사전에 박아두면 측정 결과가 조건 미달일 때 "그래도 좋아 보이는데" 로 도망갈 수 없다.

이 패턴은 이미 두 번의 선례가 있었다.

- [ADR 0019](../adr/0019-embedding-default-stays-minilm.md): 임베딩 default 를 MiniLM-L12-v2 로 lock. Re-open 조건: "BGE-M3 / e5-large-instruct 가 `full` 파이프라인에서 ≥ +5pp lift + non-overlapping CI."
- [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md): BGE-M3 측정 완료, 조건 미달, default 유지.

ADR 0023 의 promote 조건도 같은 패턴이다. "이 기능이 켜질 자격이 무엇인가" 를 코드 작성 시점에 답한다.

## 측정 결과: 0pp

`eval/config.yaml` 에 `full_hyde` ablation row 를 추가하고 측정을 돌렸다. [`reports/cost_frontier.md`](../../reports/cost_frontier.md) 에 commit 된 결과:

| Run | Accuracy | 95% CI |
|---|---:|---|
| `full` (baseline) | 0.695 | [0.598–0.793] |
| `full_hyde` | **0.695** | **[0.598–0.793]** |

정확히 동일. 어떤 형태로도 promote 조건 ≥ +3pp lift + non-overlapping CI 를 충족하지 못한다. ADR 0023 은 `proposed` status 로 머무르고 `BIDMATE_QUERY_EXPANSION_BACKEND` 환경변수의 default 는 `identity` (즉 HyDE 끄기) 로 유지된다.

여기서 끝낼 수 있었다. "HyDE 측정해봤더니 lift 없어서 default 안 켰음" — 1줄 보고. 끝.

하지만 같은 표를 한 번 더 봤다.

## 같은 표를 한 번 더 보면

| Run | Accuracy | 95% CI |
|---|---:|---|
| `no_verifier_retry` | 0.805 | [0.720–0.890] |
| `retrieval_only` | 0.805 | [0.720–0.890] |
| `naive_baseline` | 0.744 | [0.646–0.829] |
| `full` | 0.695 | [0.598–0.793] |
| `full_hyde` | 0.695 | [0.598–0.793] |
| `full_reranker` | 0.695 | [0.598–0.793] |
| `full_kiwi` | 0.695 | [0.598–0.793] |
| `full_mecab` | 0.695 | [0.598–0.793] |
| `hybrid_bm25` | 0.695 | [0.598–0.793] |
| `hybrid_bm25_k30` | 0.695 | [0.598–0.793] |
| `hwp_native` | 0.695 | [0.598–0.793] |
| `agentic_full_finetuned` | 0.695 | [0.598–0.793] |

`full` 을 기반으로 한 *모든* ablation 이 정확히 같은 숫자다. HyDE 만 0pp 가 아니라 reranker 도, BM25 morphology tokenizer 도, finetune 도, hybrid 도 다 0pp. 95% CI 도 단 하나의 소수점 자리까지 동일.

여기서 "saturation" 으로 결론짓고 싶지만, 첫 번째 정직한 진단은 더 무미건조하다. **CI public synthetic 은 deterministic `hashing` embedding backend 로 측정한다** (`eval/config.yaml` 에 주석으로 박혀있다):

> "the public synthetic surface, which runs the deterministic `hashing` embedding backend in CI"

이유는 [ADR 0001](../adr/0001-preserve-naive-baseline.md) 의 골든 byte-identical 보존 — sentence-transformers 는 환경/버전에 따라 미세한 float drift 를 만들 수 있어 CI 에서 deterministic byte-identical 골든을 깰 위험이 있다. 그래서 `hashing` backend 는 placeholder embedding (query / chunk 텍스트를 hash 함수로 deterministic 벡터로 매핑) 을 쓴다. 이 backend 는 *임베딩 차이를 본질적으로 표현할 수 없다* — HyDE expanded text 든 원본 query 든 hash 함수를 거치면 임의의 deterministic 벡터로 매핑될 뿐이다.

즉 24개 ablation × 0.695 는 saturation 신호가 아니라 **hashing-backend artifact** 다. 이걸 saturation 으로 잘못 진단했다면 corpus 를 키우거나 verifier 를 완화하는 방향으로 잘못된 노력을 했을 거다.

이게 끝이 아니다. Hashing-backend artifact 라는 *1차 진단* 이 끝이라면 "그러면 sentence-transformers backend 로 측정하면 변별력이 보이느냐?" 가 다음 질문이 된다.

## ADR 0032: sentence-transformers 측정으로 진짜 신호 확인

[ADR 0032](../adr/0032-eval-saturation-routed-subset.md) 은 *real* embedding backend (sentence-transformers, hashing 아님) 로 측정 surface 자체를 falsify 한다. CI byte-identical 골든은 그대로 유지하면서, 로컬에서 sentence-transformers backend 로 별도 측정해 publish 하는 패턴이다 ([ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md) public/private split 의 변형).

핵심은 `agentic_full_routed` 라는 새 ablation preset 이다. 기존 `agentic_full` 에서 `metadata_first: false` 를 강제로 켠다 — metadata-first 우회를 비활성화하고 dense + lexical + BM25 로만 retrieval 하게 만든다. 동시에 `eval/synthetic/routed_subset.jsonl` (n=11) 을 따로 작성했다 — multi-turn follow-up + 다문서 비교 ambiguity + metadata-implicit 추론 query 중심으로, metadata-first 라우팅이 *우회되는* 케이스만 모았다.

이 위에서 5개 임베딩 (MiniLM / e5-large-instruct / KoSimCSE / KURE-v1; BGE-M3 는 torch 2.6 blocker 로 skip) 을 sentence-transformers backend 로 측정했다.

| Model | `full` (metadata_first=true) | `routed` (metadata_first=false) |
|---|---:|---:|
| MiniLM-L12-v2 (default) | 0.500 | 0.400 |
| multilingual-e5-large-instruct | 0.500 | 0.400 |
| KoSimCSE-roberta-multitask | 0.500 | 0.400 |
| KURE-v1 (Korean-specialized) | 0.500 | 0.400 |

Spread (top-vs-bottom): **0.0pp**. Threshold 가 +3pp 였으니, "임베딩 차이로 lift 가 있다" 는 가설은 **falsified** — sentence-transformers backend 에서도, metadata-first 우회 surface 에서도 변별력이 없다.

이건 hashing-backend artifact 가 *아니다*. 두 가설이 남는다.

- **Corpus 규모 saturation.** Public synthetic 은 7 문서 / 9 chunk. 9개 중 top-k=3 회수는 어떤 임베딩으로도 trivial.
- **Verifier ceiling.** [ADR 0004](../adr/0004-evaluation-loop-strict-contract.md) 의 strict exact-term match 정책이 retrieval 품질 이전에 ceiling 을 만든다 — `agentic_full_routed` 도 0.500 이 cap.

ADR 0032 는 `accepted` 상태로 닫혔다 — verdict 는 `saturation_cross_validated`. 결론: **현 측정 surface 로는 어떤 retrieval 기법도 lift 를 측정할 수 없다.** Hashing backend 에서는 backend 자체가 변별력을 차단하고, real backend 에서는 corpus + verifier 가 차단한다.

## 그래서 HyDE 는?

`full_hyde 0.695` 라는 숫자가 가리키던 진짜 의미는 다음과 같다.

- "HyDE 가 나쁘다" → 잘못된 결론
- "HyDE 가 좋다" → 데이터 없음
- "현 측정 surface 로는 HyDE 를 평가할 수 없다" → 맞는 결론

ADR 0023 은 `proposed` 상태로 머무른다. Promote 조건은 변하지 않았다. 새 promote 조건은 추가적으로 측정 surface 재설계 (corpus 확장 또는 verifier 완화) 를 요구할 가능성이 있다. ADR 0023 의 측정-gated 게이트는 이제 단순히 "+3pp lift on n≥100" 이 아니라 "+3pp lift on n≥100 *on a surface that can discriminate retrieval lifts*" 로 정밀화된다.

## 변심의 비용은 거의 0

이 모든 과정에서 default 가 바뀌지 않았다는 사실이 중요하다.

- `IdentityExpander` 는 query 를 그대로 반환한다 ([`rag_query_expansion.py`](../../rag_query_expansion.py)) — `naive_baseline` 골든 `tests/data/naive_baseline_top_k.json` 은 비트 단위 동일.
- `HyDEExpander` 는 leaf module 로 격리되어 환경변수 1개 (`BIDMATE_QUERY_EXPANSION_BACKEND=hyde`) 로만 켜진다.
- Default 경로의 LOC, 의존성, 테스트 surface 변화 = 0.

즉 HyDE 를 "도입하고도 켜지 않은" 결정의 비용은 거의 0이다. 만약 6개월 뒤 측정 surface 가 변별력을 회복하면 환경변수 한 개 켜고 측정만 다시 돌리면 된다. 만약 HyDE 가 영구적으로 무의미하다고 판명되면 leaf module 한 개 + ablation row 한 개 + 환경변수 family 하나를 지우면 된다. ADR 0023 에 그 경로도 명시되어 있다.

이게 ADR 0001 의 "preserve naive baseline" 원칙과 [ADR 0020](../adr/0020-protocol-based-pluggability.md) 의 "Protocol-based pluggability" 원칙이 합쳐졌을 때 생기는 실제 properties 다 — 기능 추가가 default 변경과 분리되어, 추가의 비용이 거의 0이 된다.

## 더 큰 패턴: 측정-gated lockout

본 글에서 가장 일반화할 만한 게 있다면 이거다.

> **기능 추가 ≠ default flip.** 이 두 결정은 분리되어야 하며, default flip 은 사전에 명시된 측정 조건을 통과해야 한다.

이 패턴은 ADR 0023 뿐 아니라 같은 repo 의 여러 ADR 에서 반복된다.

- [ADR 0019](../adr/0019-embedding-default-stays-minilm.md) — 임베딩 6개 측정 후 default lock 유지
- [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md) — BGE-M3 0pp lift 측정 후 default 유지
- [ADR 0026](../adr/0026-cross-encoder-reranker-deferral.md) — Cross-encoder reranker, default stub 유지
- [ADR 0032](../adr/0032-eval-saturation-routed-subset.md) — 측정 surface 자체를 falsify
- [ADR 0037](../adr/0037-kure-v1-closes-phase-1-5.md) — KURE-v1 측정 후 default 유지

외부 적대적 리뷰가 "왜 X 안 했어요?" 라고 물을 때 답할 수 있다 — "도입했고, promote 조건 사전에 박았고, 측정 결과 미달이라 default off. 그게 ADR 00xx 에 있다."

이게 "vibe-driven engineering" 이 "measurement-driven engineering" 으로 바뀔 때 생기는 실질적 차이다. 트렌드 기능을 코드에 넣는 결정은 쉽지만, 그 기능을 default 로 켤지 결정하는 데에는 측정이 필요하고, 그 측정이 신뢰할 만한지 결정하는 데에는 측정 surface 에 대한 측정이 필요하다. 한 차수 위로 올라가는 일이다.

## 결론

가장 강한 엔지니어링 결정은 default 를 안 바꾸는 결정이다. 가장 강한 결정은 측정 surface 자체를 의심하는 결정이다.

HyDE 는 폐기되지 않았다. 다만 측정 surface 가 HyDE 를 평가할 자격이 없었다는 사실이 측정으로 증명됐다. 그 증명에 든 비용은 ADR 한 페이지 + n=11 짜리 routed_subset.jsonl + leaf module 두 개였다. 그리고 default 는 변하지 않았다.

다음 cycle 에서 측정 surface 를 재설계할 때, HyDE 는 거기 그대로 기다리고 있을 것이다.

---

**관련 코드·데이터**

- [ADR 0023 — HyDE additive ablation](../adr/0023-hyde-query-expansion-ablation.md)
- [ADR 0032 — Eval-set saturation routed-subset measurement](../adr/0032-eval-saturation-routed-subset.md)
- [`rag_query_expansion.py`](../../rag_query_expansion.py) — `QueryExpander` Protocol + `IdentityExpander` (default) + `HyDEExpander` (opt-in)
- [`reports/cost_frontier.md`](../../reports/cost_frontier.md) — 25개 ablation × accuracy + 95% CI
- [`reports/embedding_routed.json`](../../reports/embedding_routed.json) — 5 임베딩 × routed_subset measurement

**관련 ADR family (측정-gated lockout 패턴)**

- [ADR 0001](../adr/0001-preserve-naive-baseline.md) — Preserve naive baseline
- ADR 0019 / 0021 / 0037 — Embedding default lock (6개 임베딩 cross-validated)
- ADR 0026 — Cross-encoder reranker, default stub
- ADR 0032 — Measurement surface falsifier
