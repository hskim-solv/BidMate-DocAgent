# 0021: BGE-M3가 ADR 0019 조건 2를 충족; 기본 embedding은 MiniLM 유지

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (기준선 보존), [ADR 0002](./0002-metadata-first-retrieval.md) (메타데이터 우선 우세), [ADR 0019](./0019-embedding-default-stays-minilm.md) (보류), [ADR 0032](./0032-eval-saturation-routed-subset.md) (라우팅 축 falsifier, 2026-05-13), [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.3, issue #389
- **Update (ADR 0032 라우팅 축 falsifier, 2026-05-13)**: [ADR 0032](./0032-eval-saturation-routed-subset.md)가 routed-subset 측정(n=11, 메타데이터 우선 우회)을 수행. BGE-M3는 torch < 2.6 환경 제약(ADR 0021 §Decision 동일)으로 skip. 측정된 4개 모델 모두 routed subset에서 spread = 0.0pp — saturation cross-validation 결과 일치.

## TL;DR

- BGE-M3로 ADR 0019 조건 2(러너 완주) 충족. 그러나 조건 3(`full` ≥+5pp lift)은 미충족 — 모든 메트릭 `+0.0`.
- 기본 embedding `MiniLM-L12-v2` 유지. "0pp on full" 패턴이 5개 후보(MiniLM/e5-base/e5-large-instruct/KoSimCSE/BGE-M3)로 강화됨.
- ADR 0019는 *accepted* 유지. 본 ADR은 supersede가 아니라 조건 4(deferral 종결 문서화) 동반자.

## 배경

[ADR 0019](./0019-embedding-default-stays-minilm.md)는 embedding 기본값 결정을 4개 명시 재개 조건으로 보류했다:

1. 두 환경 제약(`torch >= 2.6`, `huggingface-hub < 1.0`) 해소를 위한 `requirements.txt` 업그레이드.
2. `python3 scripts/run_embedding_ablation.py --models <MiniLM> BAAI/bge-m3 intfloat/multilingual-e5-large-instruct` 가 n=42 public synthetic corpus에 완주.
3. BGE-M3 / e5-large-instruct 중 최소 하나가 **`full` 파이프라인**에서 accuracy 또는 groundedness ≥ +5pp lift, 95% CI 비중첩. *(ADR 0001에 따라 `naive_baseline` lift는 분석 변형으로 보존되므로 미카운트.)*
4. 후속 ADR(002x) 생성 + 후보 측정 출력이 `docs/eval/embedding-ablation.md` Phase 1.2에 추가.

Phase 1.2(issue #174)에서 e5-large-instruct, KoSimCSE-roberta-multitask, OpenAI text-embedding-3-large / e5-base를 정리 — BGE-M3가 마지막 갭. `torch >= 2.6`은 `requirements.txt:8`에 반영됨. Phase 1.3(issue #389)이 갭 종결.

본 ADR은 Phase 1.3의 **조건 4 동반자** — ADR 0019 supersede가 **아님**.

## 결정

**기본 embedding으로 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 유지.** ADR 0019는 *accepted* 유지; 본 ADR은 Phase 1.3 증거 추가 + ADR 0019 조건 2 충족 표시.

### Phase 1.3 측정 내용

재현(`torch 2.11.0`, `sentence_transformers 2.7.0`, `huggingface-hub 0.36.2` clean `.venv`):

```
python3 scripts/run_embedding_ablation.py \
    --models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
             BAAI/bge-m3
```

`full` agentic 파이프라인(n=42, BGE-M3 vs MiniLM):

| metric | MiniLM | BGE-M3 | Δ |
|---|---:|---:|---:|
| accuracy | 0.906 | 0.906 | **+0.0** |
| groundedness | 0.929 | 0.929 | **+0.0** |
| citation_precision | 0.905 | 0.905 | **+0.0** |
| abstention | 1.000 | 1.000 | **+0.0** |
| format compliance | 0.905 | 0.905 | **+0.0** |

CI 중첩이 아니라 bit-identical. Phase 1.2의 e5-large-instruct / KoSimCSE 결과와 동일한 형태.

`naive_baseline`(ADR 0001 보존 분석 변형; 미카운트):

| metric | MiniLM | BGE-M3 | Δ |
|---|---:|---:|---:|
| accuracy | 0.656 | 0.844 | **+18.8** |
| groundedness | 0.595 | 0.714 | **+11.9** |
| citation_precision | 0.488 | 0.548 | +6.0 |
| format compliance | 0.548 | 0.667 | **+11.9** |

BGE-M3는 e5-large-instruct만큼 dense-only 검색을 lift. agentic 파이프라인이 메타데이터 우선 라우팅(ADR 0002)으로 lift를 흡수.

### ADR 0019 조건 정산

| condition | status after Phase 1.3 |
|---|---|
| 1. requirements.txt 환경 업그레이드 | ✅ 충족 (`torch >= 2.6` pin, `huggingface-hub` `0.36.2 < 1.0`) |
| 2. 러너 완주 | ✅ 4 후보(MiniLM / e5-large-instruct / KoSimCSE / BGE-M3) 모두 충족 |
| 3. ≥+5pp `full` lift, CI 비중첩 | ❌ 모든 후보 미트리거(`full` `+0.0`) |
| 4. 교체 또는 종결 문서화 ADR | ✅ 본 ADR |

조건 3이 binding gate, 미트리거. ADR 0019의 "조건 1–2 충족·3 미충족(0pp 패턴 유지) 시 ADR 유지 + 문서 갱신만" 절 적용 — 다만 다음 기여자가 재논의하지 않도록 **deferral 종결 명시** 보조 ADR로 본 ADR을 별도 작성.

## 결과

- `rag_core.py`의 `DEFAULT_EMBEDDING_MODEL`은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 유지.
- `EMBEDDING_BACKEND=hashing`은 CI / smoke-test 기본값 유지(다운로드/GPU 불필요).
- "0pp-on-full" 결과는 이제 5 측정 pivot(MiniLM 2019, e5-base 2023, e5-large-instruct 2024 SoTA, KoSimCSE 한국어 특화, BGE-M3 multi-functional) 기반. 재개를 원하면 `full` 행을 visibly shift하는 후보 필요 — 현대 multilingual / 한국어 특화는 고갈.
- 본 ADR + `docs/eval/embedding-ablation.md` Phase 1.3 머지 시 issue #389 close. raw `eval_summary.json`은 `reports/embedding-ablation/` (gitignore, public synthetic corpus 재실행으로 재현).

## 재개 조건 (ADR 0019 승계)

원 ADR 0019 재개 조건은 *향후* embedding 후보에 그대로 유효. `nlpai-lab/KURE-v1` 등 미등재 후보를 러너에 추가해 `full` lift가 보이면 조건 3 재트리거 + 신규 후속 ADR 개시. 측정 인프라(`scripts/run_embedding_ablation.py`)는 동일, 신규 tooling 불필요.

## Phase 1.4 update — ADR 0032 routed-subset saturation falsifier (2026-05-13)

본 ADR의 "0pp on full" 패턴이 메타데이터 우선 absorption artifact인지 [ADR 0032](./0032-eval-saturation-routed-subset.md)가 routed-subset 측정 표면(n=11, `agentic_full_routed`)으로 falsify 시도. 결과: MiniLM / e5-large-instruct / KoSimCSE / KURE-v1 모두 routed accuracy 0.400, spread **0.0pp**(threshold +3pp). Saturation cross-validated. BGE-M3 Phase 1.4 측정도 torch ≥ 2.6 blocker로 동일 skip.

## See also

- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.3 — 전체 수치 + 읽기 가이드.
- [ADR 0001](./0001-preserve-naive-baseline.md) — `naive_baseline` lift가 기본값 교체 트리거가 아닌 이유.
- [ADR 0002](./0002-metadata-first-retrieval.md) — "0pp-on-full" 패턴이 경험적으로 지지하는 load-bearing 설계.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — 본 ADR이 종결하는 보류.
- [ADR 0032](./0032-eval-saturation-routed-subset.md) — Phase 1.4 routed-subset 측정. "0pp on full"이 saturation artifact가 아님을 cross-validate.
- [ADR 0037](./0037-kure-v1-closes-phase-1-5.md) — Phase 1.5 KURE-v1 n=100 정식 측정. issue #447 close.
