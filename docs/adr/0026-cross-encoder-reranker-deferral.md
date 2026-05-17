# 0026: Cross-encoder reranker default는 stub-identity 유지; real-backend 측정 보류

- **Status**: Superseded
- **Superseded by**: [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) § "Cross-encoder reranker deferral"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (기준선 보존), [ADR 0002](./0002-metadata-first-retrieval.md) (rerank step를 가리는 메타데이터 우선 라우팅), [ADR 0019](./0019-embedding-default-stays-minilm.md) (mirror — measurement-gated default-stays), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (deferred-then-closed 선례), [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) (sibling 보류 패턴, 2026-05-12 accepted), [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md), [`docs/eval/ablation-results.md`](../eval/ablation-results.md), [`rag_reranker.py`](../../rag_reranker.py) (`Reranker` Protocol + `CrossEncoderReranker` default), issues [#163](https://github.com/hskim-solv/BidMate-DocAgent/issues/163), [#345](https://github.com/hskim-solv/BidMate-DocAgent/issues/345), [#412](https://github.com/hskim-solv/BidMate-DocAgent/issues/412), PR [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358)

## TL;DR

- 공공 합성(n=42)에서 `rerank: true` blend가 0pp(`full` ≡ `no_rerank` byte-identical) + stub-identity 하 `full_reranker ≡ full` by construction + real backend(`bge`/`bge_ko`/`cohere`) 미측정.
- `Reranker` Protocol seam + `BIDMATE_RERANK_BACKEND=stub` default 유지 — 0pp 합성 delta에도 HyDE-reranker / LLM-as-reranker 후속용 plug point.
- 3 재개 조건(real backend 1 완주 + ≥ +3pp lift + 후속 ADR) 충족 시 default flip.

## 배경

reranking과 상호작용하는 검색-side 표면 3개, 각각 다른 측정 상태:

1. **`rerank: true` blend**([`rag_core.retrieve`](../../rag_core.py)의 60/25/15 dense + lexical + metadata blend) — `full` 분석 변형 프리셋에 present.
2. **`Reranker` Protocol + `CrossEncoderReranker` default**([`rag_reranker.py`](../../rag_reranker.py), 이슈 [#345](https://github.com/hskim-solv/BidMate-DocAgent/issues/345) / PR [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358)) — `plan["rerank_cross_encoder"]` set 시에만 [`rag_retrieval.apply_fusion_and_reranking`](../../rag_retrieval.py)(PR-H1a, 이슈 #459로 `rag_core.py`에서 추출) 소비. [`eval/config.yaml`](../../eval/config.yaml) `line 143-149`(`rerank: true` + `rerank_cross_encoder: true`)에 `full_reranker` 프리셋으로 노출.
3. **Cross-encoder backend**(`bge`, `bge_ko`, `cohere`) `BIDMATE_RERANK_BACKEND` 선택. CI default `stub` — [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)가 dispatch 기술하며 *"`full_reranker` row byte-equals `full` under stub"*(line 25) 명시. Stub은 순수 identity pass-through; `tests/test_cross_encoder_rerank.py::RerankStubBackendTest::test_stub_backend_is_identity`가 invariant lock.

현 분석 변형 표([`docs/eval/ablation-results.md`](../eval/ablation-results.md)) — 공공 합성 표면(n=42)에서 **첫 번째** 표면이 이미 0pp:

| Run | Accuracy | Groundedness | Citation precision | Abstention |
|---|---:|---:|---:|---:|
| `full` (rerank on, blend only) | 0.906 | 0.929 | 0.905 | 1.000 |
| `no_rerank` (rerank off entirely) | 0.906 | 0.929 | 0.905 | 1.000 |

3 관찰:

- **`rerank: true` blend는 이 표면에서 `no_rerank` 대비 zero quality lift.** 가설([ADR 0002](./0002-metadata-first-retrieval.md) + [ADR 0019](./0019-embedding-default-stays-minilm.md) `0pp-on-full` 패턴 일관): 대부분 쿼리에서 메타데이터 우선 필터링이 dense 검색을 우회 → post-retrieval reorder가 개선할 여지 미미.
- **stub 하 `full_reranker`는 by construction `full`과 byte-identical**(empirical accident 아님). 거기서 0 delta는 architectural invariant, 측정 finding 아님.
- **이 repo eval 표면에 real cross-encoder backend 측정 없음.** [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md) §Results는 *"Measurement pending — append below after running the reproduction commands."*로 마감. `bge` / `bge_ko` / `cohere` 명령은 ship되었으나 user-environment setup(모델 다운로드 / API key) 필요, 미수행.

따라서 본 ADR이 close하는 질문: *(a) blend가 이미 0 lift, (b) stub 하 cross-encoder는 by design identity, (c) real backend 미측정인 상태에서 `Reranker` Protocol 표면 + `CrossEncoderReranker` default를 코드베이스에 유지할지?* measurement-gated 보류 패턴([ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md)) + sibling [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md)가 자연스럽게 적용: 결정을 지금 lock, real backend로 default flip할 재개 조건 문서화.

[ADR 0023](./0023-hyde-query-expansion-ablation.md)(proposed)은 이미 [ADR 0020](./0020-protocol-based-pluggability.md)(proposed, skeleton-only)을 Protocol convention 출처로 cross-reference; 본 ADR은 두 ADR의 downstream — convention 자체가 아니라 convention 내 **기본 동작** 결정.

## 결정

`Reranker` Protocol 표면 + `CrossEncoderReranker` default를 [`rag_reranker.py`](../../rag_reranker.py)에 유지; `BIDMATE_RERANK_BACKEND=stub`(identity)를 CI default 유지 → `full_reranker ≡ full` by construction. 0pp 합성 delta에도 rerank seam 제거 **금지** — real backend 미측정 + Protocol이 HyDE-reranker / LLM-as-reranker 후속 seam.

본 결정 lock knob:

- [`eval/config.yaml`](../../eval/config.yaml) 프리셋 row 유지: `full`(`rerank: true`), `no_rerank`(`rerank: false`), `full_reranker`(`rerank: true` + `rerank_cross_encoder: true`).
- `BIDMATE_RERANK_BACKEND` env-var dispatch `stub`(CI default) | `bge` | `bge_ko` | `cohere`. 재개 조건 발화 전까지 default `stub`.
- [`rag_reranker.py`](../../rag_reranker.py) `default_reranker()` factory가 단일 dispatch hook 유지 — 향후 LLM-as-reranker / HyDE-reranker 구현은 adapter swap, seam 변경 없음.

경계 명확화: 본 ADR은 [ADR 0020](./0020-protocol-based-pluggability.md)이 도입한 Protocol convention 내 **기본 동작** 결정. Protocol 자체 존재 재결정이 *아님* — 그것은 ADR 0020 영역.

## 재개 조건

[ADR 0019](./0019-embedding-default-stays-minilm.md) + sibling [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md)의 gate 패턴 따라, 본 ADR은 다음 **셋 모두** 충족 시 재개(+ `stub` default flip):

1. maintainer가 `bge` / `bge_ko` / `cohere` 중 ≥ 1을 공공 합성 eval(n=42)에 완주 + [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md) §Results에 결과 표 추가.
2. 위 backend **≥ 1**이 공공 합성 표면에서 `full` 대비 `accuracy` 또는 `citation_precision`에 `full_reranker` lift **≥ +3pp**, bootstrap 95% CI 비중첩. X = 3은 의도적: [ADR 0019](./0019-embedding-default-stays-minilm.md) "≥ +5pp on full" gate보다 완화 — precision-targeted post-retrieval reorder는 embedding swap보다 작은 절대 lift에서도 portfolio signal 가능.
3. 후속 ADR(`002x` 이상) 생성 — `BIDMATE_RERANK_BACKEND` default를 `stub` → 승자 backend로 flip, latency / cost trade-off(`bge` ~80-200ms / query CPU, `cohere` ~$2 / 1k searches per [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)) 문서화.

조건 1 충족했으나 2 미충족(real backend도 0pp 패턴 유지) 시 본 ADR `accepted` 유지 + [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md) §Results에 측정 부록만 추가(ADR replace 없음) — [ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md)과 동일 loop shape.

## 결과

**Wins**

- 향후 LLM-as-reranker / HyDE-reranker가 seam 재논의 없이 동일 Protocol plug — [`rag_reranker.py`](../../rag_reranker.py)가 단일 swap point 유지.
- [`eval/config.yaml`](../../eval/config.yaml)의 `full` / `no_rerank` / `full_reranker` 분석 변형 row 정합 유지; senior-positioning narrative가 [ADR 0001](./0001-preserve-naive-baseline.md) 확장 "additive ablation" 구체 예시 보유.
- stub-identity invariant이 CI 결정성 보존 — real backend 채택은 environment opt-in, CI-default flip이 아님. byte-equality 테스트 `tests/test_cross_encoder_rerank.py::RerankStubBackendTest::test_stub_backend_is_identity`가 lock.
- reviewer-facing 정직: "0 delta on synthetic" framing이 ADR-backed(fabricated lift 없음) + 미측정 real backend는 숨은 todo 아닌 재개 trigger로 표면화.

**Costs**

- 미사용 real-backend 코드 경로([`rag_rerank.py`](../../rag_rerank.py) 내 BGE / Cohere dispatch) 유지 비용. never-raise fallback 계약으로 완화 — `stub`이 always-safe 경로 + 미지/실패 backend는 silently identity degrade.
- "cross-encoder reranker 있는데 아무것도 안 하나?"라는 reviewer 질문에 단일 문장 아닌 미묘 답변("CI default 하 identity, real backend 미측정") 필요. 위 Context 섹션이 근거 운반.
- 결정이 "*이 corpus, stub 하* 미중요"가 아니라 "rerankers don't matter"로 오독 가능. 완화: 재개 조건이 corpus(공공 합성, n=42) + backend(`bge` / `bge_ko` / `cohere`) 명시.

## 검토한 대안

1. **`Reranker` Protocol 전체 제거(PR [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358) rollback).** Protocol은 향후 LLM-as-reranker / HyDE 작업이 plug하는 seam. 제거는 [ADR 0020](./0020-protocol-based-pluggability.md) convention에 codified된 검색-side pluggability를 재단편화 — 이 표면에서 측정 이득 없음. Net loss.
2. **`BIDMATE_RERANK_BACKEND` default를 `bge_ko`로 무조건 flip.** 측정 아직 없음; real backend default는 모든 CI run에 ~1.1 GB 다운로드 + ~80-200ms / query 강제, empirical 정당화 전무. [ADR 0019](./0019-embedding-default-stays-minilm.md) "≥ +Xpp 증거 없이 default flip 금지" 규칙이 동일 적용.
3. **identity reranker 기본(= `full_reranker`에서 `rerank_cross_encoder` 제거).** `full_reranker` 프리셋은 cross-encoder 경로 *실행을 위해* 존재. flag 제거는 `full_reranker`를 `full`로 collapse + 분석 변형 표면 소거 — additive-ablation 체제([ADR 0001](./0001-preserve-naive-baseline.md) 확장) 목적의 정반대.
4. **다른 cross-encoder 모델로 전환(`BAAI/bge-reranker-large`, `mixedbread-ai/mxbai-rerank-large-v1`).** 범위 외. 본 ADR은 표면 유지 여부 결정, default 모델 결정 아님. real-backend 측정 도착(재개 조건 1) 시 후속 ADR이 seam 재논의 없이 모델 선택 다룸.
5. **real-backend 측정 지금 실행(이슈 [#163](https://github.com/hskim-solv/BidMate-DocAgent/issues/163)을 본 ADR에서 full close).** 측정은 ~1.1 GB 모델 다운로드(`bge`) 또는 Cohere API key(`cohere`) 필요, 둘 다 docs-PR critical path 외. 보류 먼저 문서화 + 측정은 나중이 [ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md)과 동일 loop shape.

## See also

- [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md) — 설계 + 재현 명령; 본 ADR이 *결정* lock하는 doc.
- [`docs/eval/ablation-results.md`](../eval/ablation-results.md) — 위 인용 `full` vs `no_rerank` 수치.
- [`rag_reranker.py`](../../rag_reranker.py) — `Reranker` Protocol 표면 + `CrossEncoderReranker` default.
- [`tests/test_cross_encoder_rerank.py`](../../tests/test_cross_encoder_rerank.py) — stub-identity invariant 테스트.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — 본 ADR이 따르는 measurement-gated 보류 패턴.
- [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) — sibling 보류 ADR(동일 일자, 동일 패턴).
