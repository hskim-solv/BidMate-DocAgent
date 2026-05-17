# 0037: KURE-v1이 ADR 0019 issue #447 re-open 조건 close; 기본값은 MiniLM 유지

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline 보존),
  [ADR 0002](./0002-metadata-first-retrieval.md) (메타데이터 우선 dominance),
  [ADR 0019](./0019-embedding-default-stays-minilm.md) (deferral),
  [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 보완),
  [ADR 0032](./0032-eval-saturation-routed-subset.md) (Phase 1.4 routed falsifier),
  [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.5, issue #447

## TL;DR

- KURE-v1(한국어 특화 임베딩) n=100 공개 합성 측정 결과: accuracy −1.3pp / groundedness +0.0pp vs MiniLM, 6번째 임베딩에서도 `0pp-on-full` 패턴 성립.
- ADR 0019 re-open 조건 3(`full` lift ≥ +5pp)이 트리거되지 않음 → `DEFAULT_EMBEDDING_MODEL`은 MiniLM 유지.
- 환경 blocker(`torch≥2.6`, `torchvision≥0.21`) 해소 + `requires_torch_min_version` 게이트 추가로 미래 contributor가 skip log를 보게 함.

## 배경

[Issue #447](https://github.com/hskim-solv/BidMate-DocAgent/issues/447)이 ADR 0019 / 0021 re-open 윈도우를 명시 3 조건과 함께 열었다 (모두 충족해야 기본값 변경 트리거):

1. 이전 5개 측정 임베딩(MiniLM, e5-base, e5-large-instruct, KoSimCSE, BGE-M3)에 **포함되지 않은** 신규 후보가 `scripts/run_embedding_ablation.py`에 추가.
2. 후보가 **공개 합성 corpus** (n=100; 원래 n=42, issue #570로 확장)에 대해 완전 실행.
3. 후보가 MiniLM 대비 **`full` 파이프라인** accuracy 또는 groundedness **≥ +5pp** lift, bootstrap 95% CI 비중첩. `naive_baseline` lift는 **불인정** (ADR 0001 불변식).

`nlpai-lab/KURE-v1`이 이슈 primary 후보로 listed — 한국어 NLP 태스크 fine-tuned 한국어 특화 임베딩 (~1.1 GB, 768-dim). [ADR 0032](./0032-eval-saturation-routed-subset.md) (Phase 1.4) n=11 routed subset에서 부분 측정 — routed accuracy 0.400, spread 0.0pp vs MiniLM. 이 ADR이 조건 2 요구 n=100 full corpus 실행 공식 전달.

### Env blocker 및 fix (issue #447 prerequisite)

개발 머신에서 `scripts/run_embedding_ablation.py` 실행에 복합 Python env 이슈 해소 필요:

| Symptom | Cause | Fix |
|---|---|---|
| eval에서 `torch.load` crash | `torch 2.2.2` 설치; `sentence-transformers 2.7.0`이 `torch >= 2.6` 요구 (CVE-2025-32434) | `pip install "torch>=2.6,<2.7"` → `torch 2.6.0` |
| `BertModel` import 오류 | `torchvision 0.17.2` (`torch==2.2.2` 요구) 업그레이드 후 broken | `pip install "torchvision>=0.21,<0.22"` → `torchvision 0.21.0` |
| `m3_full`이 skip 대신 crash | `FlagEmbedding` 설치 → `requires_module` 게이트 통과; torch 검사 여전히 실패 | `eval/config.yaml` `m3_full` 행에 `requires_torch_min_version: "2.6"` + `eval/run_eval.ablation_runs()`에 대응 게이트 추가 |

`requirements.txt`가 이미 `torch>=2.6` 선언; 개발 환경이 drift. `requires_torch_min_version` 게이트는 미래 contributor가 under-spec 머신에서 runtime crash 대신 깨끗한 `[skip]`을 볼 수 있게 하는 방어 인프라.

## 결정

**문서화된 기본 임베딩으로 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 유지.** ADR 0019는 *accepted* 유지; 이 ADR이 issue #447을 close하면서 Phase 1.5 공식 측정 전달 + 조건 3 비트리거 확인.

### Phase 1.5 측정 결과

재현 (torch 2.6.0, sentence_transformers 2.7.0, torchvision 0.21.0):

```
/opt/homebrew/opt/python@3.11/bin/python3.11 scripts/run_embedding_ablation.py \
    --models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
             nlpai-lab/KURE-v1
```

**`full` agentic 파이프라인** (n=100, KURE-v1 vs MiniLM):

| metric | MiniLM | KURE-v1 | Δ |
|---|---:|---:|---:|
| accuracy | 0.731 | 0.718 | **−1.3** |
| groundedness | 0.750 | 0.750 | **+0.0** |
| citation_precision | 0.715 | 0.700 | **−1.5** |
| abstention | 0.818 | 0.818 | **+0.0** |
| format compliance | 0.620 | 0.620 | **+0.0** |

KURE-v1은 accuracy(−1.3pp)와 citation(−1.5pp)에서 marginally 더 나쁨; groundedness, abstention, format 동일. +5pp 임계값 미도달뿐만 아니라 net-negative. 6번째 임베딩 pivot에서 `0pp-on-full` 패턴 성립.

**`naive_baseline`** (ADR 0001 보존 분석 변형; 조건 3에 **불인정**):

| metric | MiniLM | KURE-v1 | Δ |
|---|---:|---:|---:|
| accuracy | 0.590 | 0.782 | **+19.2** |
| groundedness | 0.550 | 0.690 | **+14.0** |
| citation_precision | 0.440 | 0.530 | +9.0 |
| format compliance | 0.520 | 0.640 | +12.0 |

한국어 특화가 dense-only 검색을 상당히 lift — 원본 n=42 corpus에서 e5-base (+18.8pp), e5-large-instruct, BGE-M3와 같은 형태. agentic 파이프라인이 메타데이터 우선 라우팅(ADR 0002)을 통해 lift 흡수.

> **Corpus 크기 주의**: eval config가 원래 n=42 → n=100으로 issue #570 (stratified: +20 single_doc, +14 comparison, +12 follow_up, +12 abstention) 확장. ADR 0021 `full` 수치(accuracy 0.906, groundedness 0.929)는 n=42 corpus 반영, 여기 n=100 수치와 직접 비교 **불가**. 이 ADR 내 비교(KURE-v1 vs MiniLM, 둘 다 n=100)는 내부적으로 일관. `0pp-on-full` 주장은 여전히 유효: 어느 모델도 binding metric에서 다른 모델 dominance 못 함.

### ADR 0019 조건 reconciliation

| condition | Phase 1.5 후 status |
|---|---|
| 1. 후보가 `scripts/run_embedding_ablation.py`에 추가 | ✅ KURE-v1이 이미 docstring 예제(line 23)에 있음 |
| 2. n=100 공개 합성 corpus 완전 실행 | ✅ 이 ADR |
| 3. 비중첩 CIs로 `full` lift ≥ +5pp | ❌ 미트리거 (Δ = −1.3pp accuracy, +0.0pp groundedness) |
| 4. 결과 문서화 follow-up ADR | ✅ 이 ADR |

## 결과

- `rag_core.py`의 `DEFAULT_EMBEDDING_MODEL`이 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 유지.
- `EMBEDDING_BACKEND=hashing`이 CI / smoke-test 기본값 유지 (ADR 0001).
- `0pp-on-full` 패턴이 이제 **6개 측정 임베딩 pivot** cover: MiniLM (2019), e5-base (2023), e5-large-instruct (2024 SoTA), KoSimCSE (Korean), BGE-M3 (multi-functional), KURE-v1 (Korean 특화). 미래 후보가 재오픈하려면 이 6개 중 누구도 달성하지 못한 `full` lift 증명 필요.
- `eval/run_eval.ablation_runs()`가 `requires_torch_min_version` 게이트 획득. 게이트는 투명 (skip 시 stderr log) + additive — 기존 분석 변형 행 무영향. `m3_full` 행은 `torch < 2.6` 머신에서 skip; `torch >= 2.6` 머신에서는 이전과 같이 정상 실행.
- Issue #447이 이 ADR + `docs/eval/embedding-ablation.md` Phase 1.5 섹션 landing 시 close.

## See also

- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.5 — 전체 결과 + 읽기 가이드.
- [ADR 0001](./0001-preserve-naive-baseline.md) — `naive_baseline` lift가 기본값 변경 트리거하지 않는 이유.
- [ADR 0002](./0002-metadata-first-retrieval.md) — 메타데이터 우선 dominance 이유.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — 원본 deferral.
- [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — Phase 1.3 (BGE-M3) closure.
- [ADR 0032](./0032-eval-saturation-routed-subset.md) — Phase 1.4 routed-subset falsifier (KURE-v1 n=11 preliminary).
