# ADR 0071 — real100 retrieval 표면도 MiniLM 기본값 유지 (Phase 2.0); KURE-v1은 default-flip 후보

- **Status**: accepted
- **Date**: 2026-05-23
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline 보존),
  [ADR 0019](./0019-embedding-default-stays-minilm.md) (deferral + condition-3),
  [ADR 0037](./0037-kure-v1-closes-phase-1-5.md) (Phase 1.5 답변-표면 closure),
  [ADR 0057](./0057-bm25s-additive-backend.md) (`full_bm25s` BM25-lib 비교 행),
  [ADR 0058](./0058-phase35-mode-winner.md) (hybrid 기본),
  [ADR 0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md) (소비한 retrieval aggregate 표면),
  [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 2.0, issue #1359

## TL;DR

- 5모델(MiniLM/EmbeddingGemma-300M/bge-m3-korean/KURE-v1/Qwen3-0.6B)을 **real100 비공개 corpus**(26376 kordoc 청크)에서 **retrieval 표면**(ADR 0069 `chunk_recall@k`/`mrr`/`ndcg` + bootstrap CI)으로 측정. Phase 1.x의 public-synthetic answer-quality 표면에서 처음 벗어남.
- `full`(hybrid) recall@10이 baseline MiniLM(0.235) 대비 4후보 전부 양(+): KURE-v1 **+6.3pp**(0.298, mrr +13.3pp 최고), Qwen3 +3.0, EmbeddingGemma +2.7, bge-m3-korean +2.0. **Phase 1.5와 정반대** — 그때 KURE는 `full` answer accuracy를 −1.3pp로 못 움직였다(routing이 dense 우회). ADR 0069 retrieval 표면이 answer 표면이 가렸던 임베딩-품질 신호를 드러냄.
- ADR 0019 condition-3은 ≥+5pp **and** non-overlapping CI 둘 다 요구. KURE +6.3pp는 임계 초과하나 **CI 중첩**(n=114 검정력 한계) → **미트리거 → `DEFAULT_EMBEDDING_MODEL`은 MiniLM 유지**. KURE-v1을 더 큰 n에서 재평가할 가장 유력한 default-flip 후보로 기록.

## Context

[ADR 0019](./0019-embedding-default-stays-minilm.md)가 MiniLM 기본값을 보류 결정하며 condition-3을 명시했다: 후보가 MiniLM 대비 `full` 파이프라인에서 ≥+5pp lift를 **비중첩 95% bootstrap CI**로 보일 때만 default-flip 트리거. [ADR 0037](./0037-kure-v1-closes-phase-1-5.md)(Phase 1.5)이 KURE-v1을 public-synthetic n=100 answer 표면에서 측정 — `full` accuracy −1.3pp로 미트리거. 6개 임베딩 pivot 전부 `0pp-on-full` 패턴.

Phase 1.x의 두 구조적 한계: (1) public-synthetic corpus가 saturate([ADR 0032](./0032-eval-saturation-routed-subset.md) Phase 1.4 falsifier), (2) **answer 표면이 임베딩 차이를 가린다** — metadata-first routing([ADR 0002](./0002-metadata-first-retrieval.md)) + hybrid([ADR 0058](./0058-phase35-mode-winner.md))가 dense 채널을 우회하므로 answer accuracy로는 임베딩 품질을 분리 측정 불가.

[ADR 0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md)가 `eval_summary.json`에 run-level retrieval aggregate(`chunk_recall@{5,10,20}`/`chunk_mrr`/`chunk_ndcg@{10,20}` + bootstrap CI)를 노출했다. 이 ADR(Phase 2.0)이 그 표면의 첫 소비자로, 두 축을 모두 바꿔 측정: corpus를 **real100**(harder, 비공개)로, 표면을 **retrieval**로.

## Decision

**`rag_embedding.py`의 `DEFAULT_EMBEDDING_MODEL` = `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 유지.** ADR 0019는 *accepted* 유지; 이 ADR이 Phase 2.0(real100 × retrieval 표면) 측정을 공식 전달하고 condition-3 비트리거를 확인한다.

### Phase 2.0 측정 결과 (`full`=hybrid, baseline MiniLM, n=114)

| metric | MiniLM | EmbeddingGemma | bge-m3-korean | KURE-v1 | Qwen3-0.6B |
|---|---:|---:|---:|---:|---:|
| chunk_recall@10 | 0.235 [0.174,0.298] | 0.262 | 0.255 | **0.298** [0.233,0.367] | 0.265 |
| Δ vs MiniLM (pp) | — | +2.7 | +2.0 | **+6.3** | +3.0 |
| chunk_mrr Δ (pp) | — | +4.7 | +4.8 | **+13.3** | +6.8 |
| CI vs baseline | — | overlap | overlap | **overlap** | overlap |

순위: KURE-v1 > Qwen3 ≈ EmbeddingGemma > bge-m3-korean > MiniLM. 한국어 특화(KURE)가 범용 multilingual(MiniLM) 대비 우위 — 모델 크기보다 한국어 도메인 정합이 신호(KURE 568M < Qwen3 600M인데 KURE가 더 높음).

### 측정 타당성 (cross-model 분리)

청크 텍스트·청크 ID·BM25 입력이 5개 인덱스 전부 **바이트-동일**(각 26376 청크, MiniLM↔KURE 26376/26376 동일-위치-동일-텍스트 검증). 빌드 사이 유일 변수는 dense 임베딩 → `full` recall의 모델 간 차이는 전적으로 dense 채널에 귀속. `full_bm25s`([ADR 0057](./0057-bm25s-additive-backend.md) BM25-lib 스왑, **순수-BM25 control 아님 — 동일 hybrid라 임베딩-민감**)가 모델별로 `full`과 ≤0.5pp 일치하고 모델 간 변동 폭도 동일 → 변동 원천이 BM25 구현이 아니라 임베딩임을 교차 확인.

### ADR 0019 condition reconciliation

| condition | Phase 2.0 후 status |
|---|---|
| 1. 후보가 `scripts/run_embedding_ablation.py`에 추가 | ✅ 5모델 |
| 2. corpus 완전 실행 | ✅ real100 n=114 retrieval-evaluable (issue #1359) |
| 3. 비중첩 CIs로 `full` lift ≥ +5pp | ❌ 미트리거 (KURE +6.3pp이나 CI 중첩) |
| 4. 결과 문서화 follow-up ADR | ✅ 이 ADR |

## Consequences

- `DEFAULT_EMBEDDING_MODEL`이 MiniLM 유지; `EMBEDDING_BACKEND=hashing`이 CI/smoke 기본값 유지([ADR 0001](./0001-preserve-naive-baseline.md) byte-identity 불변).
- `0pp-on-full`(answer 표면) 서사가 **retrieval 표면에서는 성립하지 않음**을 기록 — real100에서 임베딩이 hybrid recall을 실제로 움직인다. 단 통계적 분리는 n=114 검정력 한계로 미달.
- **re-open 조건**: KURE-v1을 더 큰 n(또는 paired bootstrap)으로 재평가해 `full` recall@10 lift가 ≥+5pp & non-overlapping CI이면 default-flip follow-up ADR(선례 0021/0037). KURE가 가장 유력한 단일 후보.
- real100 인덱스/eval_summary.json/raw_results는 로컬·uncommitted([ADR 0005](./0005-eval-split-public-synthetic-private-local.md) 경계). commit은 aggregate(means+CI)만 — `reports/real100/embedding_ablation_retrieval.aggregate.json`, `.gitignore` + `.githooks/pre-commit` allowlist 동시 갱신.
- 5모델 전부 로컬 HF·무료·네트워크 egress 없음 → [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) 3조건 충족(외부 페이로드 유출 0).
- Env: EmbeddingGemma/Qwen3는 `sentence-transformers≥5.0` 요구(PR #1358). Qwen3-0.6B는 eval query-encode가 MPS+fp16+GQA matmul 비호환(`LLVM: failed to infer result type`, 16 q-heads / 8 kv-heads) → eval만 CPU로 우회(빌드 인덱스 재사용). 다른 4모델은 GQA 미사용이라 MPS fp16 정상.

## Verification

Phase 2.0 aggregate(means + CI)가 commit되어 ADR 0019 condition-3 미트리거 판정의 근거를 기계 판독 가능하게 고정한다. baseline = MiniLM, 후보 KURE-v1의 `full` recall@10 CI가 baseline CI와 중첩함을 aggregate JSON에서 확인 가능.

<!-- verifies-key: reports/real100/embedding_ablation_retrieval.aggregate.json:embedding_ablation_retrieval.aggregate/v1 -->
<!-- verifies-key: reports/real100/embedding_ablation_retrieval.aggregate.json:KURE-v1 -->

## Alternatives

- **Default를 KURE-v1로 flip** — 기각. condition-3의 non-overlapping CI 게이트 미충족(점추정 +6.3pp는 강하나 CI 중첩). ADR 0019의 통계적 엄격성을 깨면 노이즈에 default가 흔들림.
- **ADR 없이 doc만** — Phase 2.0 문서가 발견을 기록하나, 새 표면(real100 retrieval)에서의 closure 결정 + 명시적 re-open 조건은 ADR 0037 선례처럼 결정 provenance로 고정할 가치. 미래 기여자가 "retrieval 표면도 봤나?"를 재실행하지 않게 함.
- **n 확대 후 측정** — 이 ADR이 그 follow-up의 트리거를 명시(re-open 조건). 지금은 현 n=114 결과로 closure.

## See also

- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 2.0 — 전체 결과 + 읽기 가이드 + Qwen3 CPU 우회 재현.
- [`reports/real100/embedding_ablation_retrieval.aggregate.json`](../../reports/real100/embedding_ablation_retrieval.aggregate.json) — 기계 판독 aggregate (means + CI).
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — 원본 deferral + condition-3.
- [ADR 0037](./0037-kure-v1-closes-phase-1-5.md) — Phase 1.5 답변-표면 closure (병행 선례).
- [ADR 0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md) — 소비한 측정 표면.
