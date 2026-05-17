# 0027: LoRA-fine-tuned embedding adapter는 additive 분석 변형

- **Status**: Superseded
- **Superseded by**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) § "Additive opt-in pattern (generalization)"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive baseline invariant), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (additive-opt-in 패턴), [ADR 0019](./0019-embedding-default-stays-minilm.md) (default 교체 재개 기준), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 종결), issue #179

## TL;DR

- KURE-v1 위 LoRA-fine-tuned adapter를 **additive 분석 변형**으로 추가 — `BIDMATE_EMBEDDING_LORA_ADAPTER` env-var gated, default 미설정 시 pre-#434 byte-identical.
- "have you fine-tuned a model?" 시니어 인터뷰 신호 + 도메인 특화 embedding이 메타데이터 우선 라우팅이 가리는 dense-only lift 회복 가능성 테스트.
- HF Hub adapter는 `<repo>@<sha>` commit SHA pinning(silent-republish supply-chain 차단).

## 배경

Phase 1.2([ADR 0019](./0019-embedding-default-stays-minilm.md)) + Phase 1.3([ADR 0021](./0021-bge-m3-completes-phase-1-3.md))가 공공 n=42 합성 표면에서 off-the-shelf embedding 후보 4종(MiniLM-L12-v2, e5-large-instruct, KoSimCSE-roberta-multitask, BGE-M3) 측정. 모두 `full` 파이프라인에서 bit-identical 메트릭 — 대부분 쿼리에서 메타데이터 우선 검색(ADR 0002)이 dense vector 우회. `naive_baseline`(dense-only, ADR 0001 invariant)에서 BGE-M3 + e5-large-instruct가 accuracy +18.8 pp(0.656 → 0.844) lift — 파이프라인이 우회 불가일 때 dense vector가 여전히 의미.

issue #179가 *trained* embedding artifact 추가 — `nlpai-lab/KURE-v1` 위 LoRA-fine-tuned adapter — Phase 1.2/1.3이 의도적으로 제외(off-the-shelf only)한 "pretrain → fine-tune → evaluate" cycle 포함. portfolio 동기는 한국 시장 senior AI engineer role의 "have you fine-tuned a model?" 인터뷰 신호; 기술 동기는 도메인 특화 embedding이 메타데이터 우선 파이프라인이 가리는 dense-only lift 회복 여부 테스트.

trained adapter는 third-party artifact: 공공 Hugging Face Hub 호스팅 PEFT delta, index-build 시점 `rag_core.embed_texts`가 `peft.PeftModel.from_pretrained(...).merge_and_unload()`로 로드. repo에 신규 artifact class(pinned, optional, reviewable) 도입 + ADR 0011/0017/0023이 정립한 additive-ablation 패턴과의 통합 codify.

## 결정

LoRA adapter를 환경 변수 gated **additive 분석 변형**으로 추가, default(env 미설정)는 pre-#434 동작과 bit-identical.

**3개 load-bearing 규칙:**

1. **`rag_core.embed_texts` 확장은 env-var gated.** PEFT branch는 `BIDMATE_EMBEDDING_LORA_ADAPTER`가 path / HF Hub repo id로 set일 때만 실행. 미설정(CI default) 시 함수는 pre-#434 구현과 byte-identical. PEFT는 조건문 *내부* lazy import → hashing-only 공공 CI는 패키지 설치 불필요.
2. **`eval/config.yaml`에 신규 분석 변형 row 2개 추가** — `agentic_full_finetuned`(`full` clone) + `naive_baseline_finetuned`(`naive_baseline` clone). 이 row의 `embedding_model` + `embedding_lora_adapter` key는 `scripts/run_embedding_ablation.py`가 index-build 시점 읽는 문서; `eval/run_eval.normalize_run_config`가 silently drop → 기본 결정적 표면에서 **correctness 메트릭**(`accuracy`, `groundedness`, `citation_precision`, `abstention`, `answer_format_compliance` — canonical `REPRODUCIBLE_METRICS` set)은 parent row와 byte-equal. Latency / `stage_latency`는 μs-scale run-to-run drift — 모든 분석 변형 공통, 계약 위배 아님(`tests/test_eval_reproducibility_regression.py`와 동일 제외). 회귀 테스트(`tests/test_finetuned_ablation_baseline_invariant.py`)가 structural(normalize_run_config) + end-to-end(eval_summary correctness-metric) 양 layer invariant pin.
3. **HF Hub adapter는 commit SHA pin** — `eval/config.yaml`에 tag/branch 아닌 `<repo>@<sha>` 형식. silent-republish supply-chain 구멍 close: 동일 tag re-push는 repo SHA 변경 없이 eval 결과 변경. SHA pin은 모든 adapter swap이 git diff.

CLI default는 `naive_baseline` 유지(ADR 0001). `embed_texts`의 함수-level default `model_name`은 `paraphrase-multilingual-MiniLM-L12-v2` 유지([ADR 0019](./0019-embedding-default-stays-minilm.md)). 본 ADR은 ADR 0019 재개 기준 *미트리거* — 기준은 `full` 파이프라인 ≥ +5 pp lift + 95% CI 비중첩 필요; Phase 1.2당 메타데이터 우선 설계가 embedding 단독으로 거의 불가능.

## "adapter는 index-build 시점만, 쿼리 시점 아님" 이유

`rag_core.embed_texts`(line 566–586)는 첫 호출에 adapter 1회 merge 후 `MODEL_CACHE`에 `(model_name, local_only, adapter_path)` key로 캐싱.

**(1) `merge_and_unload()` 비용은 amortize, 반복 아님.** `PeftModel.merge_and_unload()`는 base-model weight tensor 전체를 메모리에서 재작성 — PEFT overhead 없는 plain `SentenceTransformer` 산출 one-time 비용. per-query 실행은 매 encode 호출마다 그 비용 지불. `MODEL_CACHE` 캐싱으로 merge가 process lifetime당 1회(또는 index-build run당 1회) 발생, 이후 쿼리 시점 embedding은 non-adapted 경로만큼 빠름.

**(2) 쿼리 시점 hot-swap은 이 use case 아님.** `data/embedding-ablation/<slug>/` 디렉터리 패턴(issue #174)이 각 adapter 변형 embedded chunk vector를 slug별 영속화. 쿼리 시점 adapter 전환은 신규 adapter로 vector 빌드되어 있어야 — 즉 full index rebuild. in-flight re-embedding 없음; adapter 선택은 `scripts/build_index.py` 실행 시점 고정. hot-swap 지원은 복잡성(저장 vector당 adapter version tracking, adapter 변경 시 invalidation) 추가, offline-batch eval use case에는 payoff 없음.

**(3) `data/embedding-ablation/<slug>/` 패턴과의 조합.** `scripts/build_index.py`가 `BIDMATE_EMBEDDING_LORA_ADAPTER` 읽어 run slug에 fold → 각 (base model, adapter) 조합이 자체 디렉터리 도착. 쿼리 시점 `embed_texts` 호출은 동일 `MODEL_CACHE` 엔트리 재사용 — 양 경로가 동일 merge 결과 공유. 패턴은 `BIDMATE_EMBEDDING_BACKEND` + `BIDMATE_EMBEDDING_MODEL`이 이미 별도 index 디렉터리 versioning하는 방식과 병렬.

## 결과

**Easier:**

- "have you fine-tuned a model?" 인터뷰 신호가 재현 artifact에 grounding: Colab-runnable training notebook(`notebooks/embedding_finetune.ipynb`), `eval/config.yaml` SHA-pinned HF Hub adapter, byte-equality invariance 테스트(`tests/test_finetuned_ablation_baseline_invariant.py`).
- additive-ablation 패턴(ADR 0011/0017/0023)이 4번째 인스턴스 획득 — "new capability = new env-var + new 분석 변형 row, never a default swap" 강화.
- adapter 후일 제거는 1줄 변경: `BIDMATE_EMBEDDING_LORA_ADAPTER` unset. default 경로는 pre-#434 동작과 byte-identical; migration 불필요.

**Costs / 정직:**

- 신규 optional dep(PEFT) — install 경로는 `requirements-lora.txt`, `requirements.txt` 아님. hashing-only CI 경로는 PEFT import 안 함.
- 신규 artifact class: HF Hub 호스팅 binary. SHA-pinning 규칙(`eval/config.yaml` `<repo>@<sha>`)이 silent-republish supply-chain 구멍 close; 모든 adapter bump이 git diff.
- `full` 파이프라인 delta는 n=42 공공 합성 표면에서 ~0 pp 예상(Phase 1.2 / ADR 0021 invariance: 메타데이터 우선 라우팅이 embedding variance 흡수). `docs/eval/embedding-finetune.md`는 `naive_baseline_finetuned` delta[TBD — issue #179]를 lead + `full` null을 omission이 아니라 deliberate 결과로 게시.
- `MODEL_CACHE`는 3-tuple key `(model_name, local_only, adapter_path)` 사용. adapted + unadapted 변형 양쪽 로드 process는 full 모델 사본 2개를 동시 메모리 보유.

## 검토한 대안

- **base encoder full fine-tune.** 기각: full fine-tune은 모든 encoder weight 재훈련 필요 — (a) `scripts/generate_finetune_pairs.py` 합성 pair보다 훨씬 큰 labeled dataset 요구, (b) base weight 소멸로 base vs fine-tuned 동일 index 비교 불가, (c) HF Hub artifact가 ~4 MB PEFT delta 아닌 400 MB checkpoint. LoRA는 side-by-side 분석 변형용 base 보존 — eval 표면이 정확히 필요로 하는 것.
- **LoRA를 base에 merge + merged checkpoint를 HF Hub에 re-upload.** 기각: 분석 변형 표면(`naive_baseline` vs `naive_baseline_finetuned`)은 동일 base 모델의 adapter 유/무 비교 필요. merged checkpoint는 full checkpoint 2개 저장 없이 그것 불가능. PEFT delta 접근은 diff 가시 + 비교를 구조적 정확하게 유지(`merge_and_unload()`는 inference 속도용 로컬 런타임; HF Hub는 delta만 저장).
- **commit SHA 대신 HF tag/branch로 adapter pin.** 기각: 동일 tag re-push는 이 repo git diff 없이 eval 결과 silently 변경 — SHA-pin 패턴이 close하도록 설계된 supply-chain 구멍. SHA pinning은 모든 adapter version bump이 `eval/config.yaml` reviewable 1줄 변경.
- **KURE-v1 + BGE-M3 양 adapter 훈련 + 비교.** 보류: BGE-M3의 asymmetric dense/sparse/colbert multi-vector 아키텍처가 LoRA target layer 결정 복잡화(head별 별도 adapter vs unified projection). KURE-v1의 symmetric encoder는 LoRA target 1개만 필요 + 이 도메인의 자연스러운 한국 시장 신호. BGE-M3 fine-tuning 재방문은 follow-up; head-targeting 전략 결정은 신규 ADR 필요.

## See also

- [`rag_core.py`](../../rag_core.py) — `embed_texts` LoRA branch + `MODEL_CACHE` 3-tuple key.
- [`eval/config.yaml`](../../eval/config.yaml) — 신규 `ablation_runs` row 2개 + `latency_budgets` 엔트리.
- [`requirements-lora.txt`](../../requirements-lora.txt) — optional PEFT install 경로.
- [`scripts/generate_finetune_pairs.py`](../../scripts/generate_finetune_pairs.py) — 합성 pair 생성(issue #433).
- `notebooks/embedding_finetune.ipynb` *(issue #435, 미머지)* — training notebook.
- `docs/eval/embedding-finetune.md` *(issue #435, 미머지)* — 모델 카드 + 측정 결과.
- [`tests/test_finetuned_ablation_baseline_invariant.py`](../../tests/test_finetuned_ablation_baseline_invariant.py) — byte-equality invariant pin.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — embedding default 교체 재개 기준(본 ADR 미트리거).
- [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — Phase 1.3 종결(off-the-shelf 측정).
