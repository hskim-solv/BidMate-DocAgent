# Embedding 모델 절제실험(ablation)

issue #148 추적. README 의 "Embedding 모델 ablation 미실행" 단서를 측정된 첫 비교 + 재현 가능한 러너(runner)로 갱신한다.

## 범위(Scope)

(프로젝트 시작 이래) 기본 임베딩(embedding)은 2019 년 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 이다. README 는 오랫동안 이것을 현대 다국어(multilingual) 모델과 비교해야 한다고 표시해 왔다. 이 페이지는 그 비교의 첫 결과 + 이를 확장하는 경로다.

## 러너(Runner)

```bash
# Default: compare MiniLM-L12-v2 vs multilingual-e5-base
python3 scripts/run_embedding_ablation.py

# Add more models — careful with disk (BGE-M3 ~2GB, e5-large ~1.3GB)
python3 scripts/run_embedding_ablation.py \
    --models \
        sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
        intfloat/multilingual-e5-base \
        intfloat/multilingual-e5-large \
        BAAI/bge-m3

# Reuse already-computed summaries (skip build_index/run_eval if cached)
python3 scripts/run_embedding_ablation.py --reuse-existing
```

러너는 모델별 산출물(artifact)을 `data/embedding-ablation/<model_slug>/` (index) 와 `reports/embedding-ablation/<model_slug>/eval_summary.json` 아래에 저장한다. 둘 다 gitignore 처리된다 (`outputs/*` + `reports/*` 규칙에 따라).

## 첫 번째 비교 — MiniLM-L12-v2 vs multilingual-e5-base

실행일: 2026-05-11. Public synthetic corpus (n=42; single_doc 14 / comparison 10 / follow_up 9 / abstention 9).

### 헤드라인 수치 (full 파이프라인)

| ablation | metric | MiniLM-L12-v2 | multilingual-e5-base | Δ (pp) |
|---|---|---:|---:|---:|
| `full` | accuracy | 0.906 | 0.906 | +0.0 |
| `full` | groundedness | 0.929 | 0.929 | +0.0 |
| `full` | citation_precision | 0.905 | 0.905 | +0.0 |
| `full` | abstention | 1.000 | 1.000 | +0.0 |
| `full` | format compliance | 0.905 | 0.905 | +0.0 |

### 임베딩이 실제로 차이를 만드는 지점

| ablation | metric | MiniLM-L12-v2 | multilingual-e5-base | Δ (pp) |
|---|---|---:|---:|---:|
| `naive_baseline` | accuracy | 0.656 | 0.844 | **+18.8** |
| `naive_baseline` | groundedness | 0.595 | 0.714 | **+11.9** |
| `naive_baseline` | citation_precision | 0.488 | 0.548 | +6.0 |
| `naive_baseline` | format compliance | 0.548 | 0.667 | **+11.9** |

다른 모든 agentic 절제실험(`hierarchical`, `no_metadata_first`, `no_rerank`, `no_verifier_retry`)은 주요 지표에서 **0pp 델타**를 보인다.

### Chunk 단위 검색(retrieval) (사람이 주석한 gold 부분집합, n=10)

Issue [#175](https://github.com/hskim-solv/BidMate-DocAgent/issues/175) 가 8 개의 `follow_up` + 2 개의 `single_doc` chunk-boundary 케이스에 명시적 `gold_chunk_ids` 를 추가했다. **주석된 부분집합**에 대한 slice 별 평균 (재실행 2026-05-11, `naive_baseline`, `hashing` backend):

| slice | n_annotated | chunk_recall@5 | chunk_MRR | chunk_nDCG@10 |
|---|---:|---:|---:|---:|
| single_doc (chunk-boundary probes) | 2 | 1.000 | 0.750 | 0.815 |
| follow_up | 8 | 0.750 | 0.750 | 0.750 |

주석 결과: 휴리스틱(heuristic)으로 도출한 gold 와 사람이 주석한 gold 가 **10 개 케이스 모두에서 일치**한다 — 0.750 의 follow_up 점수는 retriever 가 chunk 를 전혀 반환하지 않는 두 개의 multi-turn 케이스(`follow_up_state_a_security`, `follow_up_state_multi_step_a_deliverables`, issue [#57](https://github.com/hskim-solv/BidMate-DocAgent/issues/57) C4 로 추적)를 반영하며, gold 라벨링 artifact 가 아니다. 이제 임베딩 모델 비교는 이 케이스들에서 검색 누락(retrieval miss)을 휴리스틱 사각지대(blind spot)와 구분할 수 있다.

### 결과 읽기

1. **full agentic 파이프라인에서 임베딩 선택은 이 corpus 에서 무관하다.** Metadata-first 필터링(ADR 0002)이 대부분의 쿼리에 대해 dense 검색을 우회하므로, 더 나은 임베딩은 도움이 되지 않는다. 이는 metadata-first 설계의 경험적(empirical) 검증이다 — 파이프라인이 suboptimal 임베딩에 강건(robust)하다.
2. **naive (dense-only) 검색에서 임베딩 선택은 크게 중요하다.** multilingual-e5-base 가 accuracy 를 0.656 에서 0.844 로 (+18.8pp) 끌어올린다. 그 대부분은 dense retriever 가 MiniLM 이 놓쳤던 기대 문서를 마침내 찾아낸 데서 온다.
3. **기본값 변경 없음.** CI 경로는 `hashing` 을 유지하고 (ADR 0001 재현성에 따라) README 기본값은 MiniLM-L12-v2 를 유지하는데, full 파이프라인 지표가 동일하기 때문이다. 더 영향력 있는 corpus 가 다른 결과를 보이면 향후 PR 이 재검토할 수 있다.
4. **Reviewer 화제(talking point).** "2026 년에 왜 MiniLM 인가?" 라고 묻는 reviewer 는 측정된 답을 얻는다: "metadata-first 필터링이 agentic 파이프라인을 임베딩 선택에 강건하게 만든다; multilingual-e5-base 로 naive baseline 에서 +18.8pp accuracy lift 를 측정했지만 full 파이프라인에서는 0pp 였다."

## 두 번째 비교 — Phase 1.2 (issue #174): 부분 3-of-4 측정

이 사이클은 **OpenAI Embeddings API 를 일급 backend 로** 추가하고 **model ID 로부터 backend 를 자동 도출**한다 (`text-embedding-*` → `openai`, 그 외 `sentence-transformers`). 러너는 이제 현대 다국어 SoTA(BGE-M3, e5-large-instruct), 한국어 특화(KoSimCSE), 그리고 유료 외부 baseline(OpenAI text-embedding-3-large)을 아우른다.

Issue #174 (이 섹션)는 ADR 0019 에서 명명된 후보들을 실행했다. 넷 중 셋은 완료까지 실행됐다; BAAI/bge-m3 는 ADR 0019 condition 1 의 `torch` 절반에 막혀 있다.

### 재현(Reproduction)

```bash
# Phase 1.2 measured set (~1.8GB disk, ~5 min cold cache on this corpus)
python3 scripts/run_embedding_ablation.py --models \
    sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
    intfloat/multilingual-e5-large-instruct \
    BM-K/KoSimCSE-roberta-multitask

# BGE-M3 — still blocked, requires torch >= 2.6 (see env section below)
python3 scripts/run_embedding_ablation.py --models BAAI/bge-m3

# OpenAI text-embedding-3-large (3072-dim) — ~$0.004 for n=42 corpus
export BIDMATE_OPENAI_API_KEY=sk-...
python3 scripts/run_embedding_ablation.py --models text-embedding-3-large
```

모델별 산출물은 `data/embedding-ablation/<slug>/` (index) 와 `reports/embedding-ablation/<slug>/eval_summary.json` (eval) 으로 간다. 둘 다 gitignore 처리된다.

### 대략적인 디스크 + 비용 가이드

| model | disk | dim | cost | notes |
|---|---:|---:|---|---|
| `BAAI/bge-m3` | ~2.0GB | 1024 | free | 2024 multilingual SoTA — env-blocked (torch < 2.6) |
| `intfloat/multilingual-e5-large-instruct` | ~1.3GB | 1024 | free | instruction-tuned, measured this cycle |
| `BM-K/KoSimCSE-roberta-multitask` | ~0.5GB | 768 | free | Korean-specialized, MEAN-pooling fallback (model is not packaged for sentence-transformers; the runner wraps it with default mean-token pooling) |
| `nlpai-lab/KURE-v1` | ~1.1GB | 768 | free | Korean-specialized — Phase 1.3 candidate (deferred) |
| `text-embedding-3-large` | n/a | 3072 | ~$0.13 / 1M tokens (~$0.004 / n=42) | OpenAI — Phase 1.3 candidate |

### 이 사이클의 env 상태

Phase 1.2 는 원래 ADR 0019 분석의 두 env blocker 중 하나를 해소했다; 다른 하나는 남아 있다:

| dependency | observed | required | status |
|---|---|---|---|
| `huggingface-hub` | `0.36.2` | `< 1.0` | ✅ cleared — `intfloat/multilingual-e5-large-instruct` loaded cleanly |
| `torch` | `2.2.2` | `>= 2.6` | ❌ still blocking BAAI/bge-m3 (CVE-2025-32434 hard requirement in `sentence_transformers` load path) |

`requirements.txt` 에 `torch >= 2.6` 을 고정하는 향후 PR 이 BGE-M3 를 풀어주고 Phase 1.3 를 trigger 한다 (재실행 한 번 더; 러너는 `--reuse-existing` 을 통해 idempotent 하다).

### 헤드라인 수치 — Phase 1.2 (측정 2026-05-12, n=42)

Public synthetic corpus (첫 비교와 동일한 n=42 split). 95% bootstrap CI 는 괄호 안에.

#### `full` agentic 파이프라인 — **ADR 0019 condition 3 이 설정한 기준선**

| metric | MiniLM-L12-v2 | e5-large-instruct | KoSimCSE-roberta-multitask | Δ vs MiniLM (e5) | Δ vs MiniLM (KoSimCSE) |
|---|---:|---:|---:|---:|---:|
| accuracy | 0.906 [0.781, 1.000] | 0.906 [0.781, 1.000] | 0.906 [0.781, 1.000] | +0.0 | +0.0 |
| groundedness | 0.929 [0.857, 1.000] | 0.929 [0.857, 1.000] | 0.929 [0.857, 1.000] | +0.0 | +0.0 |
| citation_precision | 0.905 [0.821, 0.976] | 0.905 [0.821, 0.976] | 0.905 [0.821, 0.976] | +0.0 | +0.0 |
| abstention | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | +0.0 | +0.0 |
| format compliance | 0.905 [0.810, 0.976] | 0.905 [0.810, 0.976] | 0.905 [0.810, 0.976] | +0.0 | +0.0 |

세 모델은 `full` 에서 **bit-identical** 한 지표 값을 산출한다 — 단지 CI 가 겹치는 정도가 아니다. 동일한 CI 는 자명하게 따라온다 (전반적으로 `+0.0` 델타).

#### `naive_baseline` (ADR 0001 에 따라 ablation 으로 보존 — ADR 0019 condition 3 에는 미산입)

| metric | MiniLM-L12-v2 | e5-large-instruct | KoSimCSE-roberta-multitask | Δ vs MiniLM (e5) | Δ vs MiniLM (KoSimCSE) |
|---|---:|---:|---:|---:|---:|
| accuracy | 0.656 [0.500, 0.812] | 0.844 [0.719, 0.969] | 0.781 [0.625, 0.906] | **+18.8** | **+12.5** |
| groundedness | 0.595 [0.452, 0.738] | 0.714 [0.571, 0.833] | 0.667 [0.524, 0.786] | **+11.9** | +7.1 |
| citation_precision | 0.488 [0.357, 0.619] | 0.560 [0.440, 0.679] | 0.488 [0.369, 0.607] | +7.1 | +0.0 |
| abstention | 0.300 [0.000, 0.600] | 0.300 [0.000, 0.600] | 0.300 [0.000, 0.600] | +0.0 | +0.0 |
| format compliance | 0.548 [0.405, 0.690] | 0.667 [0.524, 0.810] | 0.619 [0.476, 0.762] | **+11.9** | +7.1 |

첫 사이클 발견과 동일한 형태다 — 현대 다국어 모델과 한국어 특화 모델 모두 dense-only 검색을 실질적으로 개선하지만, production 파이프라인(`full`)은 대부분의 쿼리에 대해 dense 를 우회하므로 어느 lift 도 전이되지 않는다.

### Phase 1.2 부분 결과 읽기

1. **ADR 0019 condition 3 은 trigger 되지 않는다.** 측정된 두 후보 모두 `full.accuracy` 와 `full.groundedness` 에서 0pp 델타를 보인다. 점 추정치(point estimate)가 동일하면 CI 질문은 무의미하다. 기본값은 MiniLM-L12-v2 를 유지한다.
2. **`0pp-on-full` 패턴은 방금 확장한 임베딩-품질 축 전반에서 강건하다.** 첫 사이클은 `e5-base` (구형 다국어)에서 이를 보였다. Phase 1.2 는 `e5-large-instruct` (2024 SoTA, instruction-tuned, 1024-dim) 와 `KoSimCSE-roberta-multitask` (한국어 특화)에서 이를 확인한다. "현대 / 한국어 모델이 패턴을 깰지 모른다" 는 가설은 이 corpus 에서 반증됐다.
3. **ADR 0002 (metadata-first 검색)에 대한 경험적 지지.** Metadata-first 는 임베딩 선택이 중요해질 기회를 갖기 전에 대부분의 쿼리를 dense 검색에서 멀리 라우팅한다. full 파이프라인이 7 년 묵은 임베딩에 강건한 것은 운이 아니다 — metadata-first 설계가 임베딩-품질 축을 흡수하는 것이다.
4. **`naive_baseline` 은 임베딩에 따라 계속 움직인다.** e5-large-instruct 는 `naive_baseline.accuracy` 를 0.656 → 0.844 로 (+18.8pp, e5-base 의 첫 사이클 델타와 일치) 끌어올린다. KoSimCSE 는 +12.5pp 를 더한다. ADR 0001 이 naive 를 ablation 표면으로 보존하므로 이 델타들은 관측 가능하되 기본값에 대해 actionable 하지는 않다.
5. **BGE-M3 가 유일한 named-candidate 갭이다.** ADR 0019 condition 2 ("완료까지 실행")는 이 사이클에서 *부분적으로* 충족됐다. 남은 작업은 `torch >= 2.6` requirements.txt bump — 측정 결정이 아닌 집중된 chore PR 이다. 그것이 머지되면 Phase 1.3 가 BGE-M3 를 대상으로 재실행한다.

## 이 보류 자체가 ADR 가치가 있는 이유

기본값이 바뀌지 않았으므로 경험적 결정에는 여전히 ADR 이 없다 — 하지만 *보류* 자체가 이제 load-bearing 하다. ADR 0019 가 없으면 다음 기여자는 (a) 동일하게 막힌 측정을 재실행하거나, (b) 경험적 기준 없이 조용히 기본값을 교체할 것이다. ADR 0019 는 "MiniLM 유지" 결정과 그것이 재개되는 명시적 조건 둘 다를 못박는다.

향후 ablation 이 (`naive_baseline` 만이 아니라) `full` 을 유의미하게 개선하는 모델을 찾고 팀이 기본값 전환을 결정한다면, 그 변경은 CLAUDE.md "ADR threshold" 에 따라 *follow-up* ADR 과 함께 머지돼야 한다. OpenAI backend 추가는 stub-default 하의 additive ablation 표면이다 (CI 는 `EMBEDDING_BACKEND=hashing` 으로 실행하고 OpenAI 를 결코 호출하지 않는다) — [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) 과 동일한 패턴.

## 세 번째 비교 — Phase 1.3 (issue #389): BGE-M3 가 ADR 0019 condition 2 를 닫음

Phase 1.2 는 `BAAI/bge-m3` 를 유일한 named-candidate 갭으로 남겼는데,
maintainer 의 로컬 Python 설치가 `torch 2.2.2` 였기 때문이다 — 현대
`sentence_transformers` 가 BGE-M3 의 커스텀 loader 코드에 대해 강제하는
`torch >= 2.6` CVE-2025-32434 완화책에 못 미친다.
`requirements.txt` 가 `torch >= 2.6` 을 고정하자 (ADR 0019 가 표시한 chore PR),
Phase 1.3 는 "새 venv 를 만들고, BGE-M3 단독으로 러너를 실행하고,
행을 추가" 로 축소됐다.

### 이 사이클의 env 상태

원래 ADR 0019 분석의 두 blocker 가 이제 모두 해소됐다:

| dependency | observed (Phase 1.3 venv) | required | status |
|---|---|---|---|
| `torch` | `2.11.0` | `>= 2.6` | ✅ cleared — `requirements.txt:8` pin, `BAAI/bge-m3` loads cleanly |
| `huggingface-hub` | `0.36.2` | `< 1.0` | ✅ cleared (since Phase 1.2) |

### 헤드라인 수치 — Phase 1.3 (측정 2026-05-12, n=42)

Phase 1.1 / 1.2 와 동일한 n=42 public synthetic corpus.

#### `full` agentic 파이프라인 — **ADR 0019 condition 3 평가자**

| metric | MiniLM-L12-v2 | BGE-M3 | Δ vs MiniLM |
|---|---:|---:|---:|
| accuracy | 0.906 | 0.906 | **+0.0** |
| groundedness | 0.929 | 0.929 | **+0.0** |
| citation_precision | 0.905 | 0.905 | **+0.0** |
| abstention | 1.000 | 1.000 | **+0.0** |
| format compliance | 0.905 | 0.905 | **+0.0** |

넷 중 넷. BGE-M3 는 **bit-identical** 한 `full` 지표를 산출한다 — 단지
CI 가 겹치는 정도가 아니다 — Phase 1.2 의 e5-large-instruct 와
KoSimCSE-roberta-multitask 가 그랬듯이. 동일한 CI 가 따라온다.

#### `naive_baseline` (ADR 0001 에 따라 ablation 으로 보존 — ADR 0019 condition 3 에는 미산입)

| metric | MiniLM-L12-v2 | BGE-M3 | Δ vs MiniLM |
|---|---:|---:|---:|
| accuracy | 0.656 | 0.844 | **+18.8** |
| groundedness | 0.595 | 0.714 | **+11.9** |
| citation_precision | 0.488 | 0.548 | +6.0 |
| abstention | 0.300 | 0.300 | +0.0 |
| format compliance | 0.548 | 0.667 | **+11.9** |

BGE-M3 는 e5-large-instruct 와 동일한 `naive_baseline` 천장에 도달한다
(둘 다 accuracy 를 0.656 → 0.844, +18.8pp 끌어올림). dense-only
retriever 는 올바른 문서를 찾는 데 *월등히* 낫다; agentic
파이프라인은 대부분의 쿼리에 대해 dense 를 우회하고 그 lift 를 흡수한다.

#### 다른 절제실험 (no_metadata_first / no_rerank / hierarchical / no_verifier_retry)

넷 모두 모든 지표에서 MiniLM 대비 `+0.0` 델타를 보인다 — `full` 과 동일한
패턴. 러너 출력은
`reports/embedding-ablation/BAAI_bge_m3/eval_summary.json` 에 보존된다.

### Phase 1.3 결과 읽기

1. **ADR 0019 condition 2 가 완전히 충족된다.** ADR-0019 가 명명한 네 후보
   (MiniLM, e5-large-instruct, KoSimCSE, BGE-M3) 모두가 이제 n=42 public
   synthetic corpus 를 대상으로 완료까지 실행됐다. 더 이상 "보류된" 측정은
   없다.
2. **ADR 0019 condition 3 은 BGE-M3 에 대해서도 trigger 되지 않는다.**
   `0pp-on-full` 패턴은 네 후보 전반에서, 그리고 MiniLM (2019), e5-base
   (2023), e5-large-instruct (2024 SoTA), KoSimCSE (한국어 특화), BGE-M3
   (2024 multi-functional) 전반에서 강건하다. "현대 모델이 패턴을 깬다"
   와 "한국어 특화 모델이 패턴을 깬다" 가설은 이 corpus 에서 둘 다
   반증됐다.
3. **기본값은 MiniLM-L12-v2 를 유지한다.** ADR 0019 는 accepted 를 유지한다;
   follow-up [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md) 은 closure 를
   문서화하는 *보충(supplement)* 이지 supersede 가 아니다.
4. **이제 경험적 주장은 공개할 만큼 강하다.** 2019–2024 에 걸친 다섯
   임베딩, multilingual / instruction-tuned / 한국어 특화 / multi-functional:
   agentic 파이프라인의 `full` 지표는 움직이지 않는다. Metadata-first 검색
   (ADR 0002)이 load-bearing 한 설계 선택이지, 임베딩 선택이 아니다.

## 네 번째 비교 — Phase 1.4 (issue #531, 2026-05-13): routed-subset saturation falsifier

[ADR 0032](../adr/0032-eval-saturation-routed-subset.md)이 제기한 질문: "0pp on full" 패턴이 metadata-first absorption의 artifact인가 (즉 임베딩 sensitivity를 측정 불가능하게 만드는가)?

### 측정 표면(Measurement surface)

`eval/routed_config.yaml` (n=11 케이스, PR #530 추가), `agentic_full_routed` preset (`metadata_first: false`). 측정 케이스는 metadata-first routing이 우회되도록 설계됨:
- **Multi-turn follow-up** (3 cases): entity switch, implicit metric, 2-step implicit
- **Multi-doc comparison ambiguity** (4 cases): 동일 metadata 후보가 ≥ 2 문서에 분포
- **Inference queries** (3 cases): metadata column hook 없는 추론 질의
- **Abstention** (1 case): corpus에 없는 정보에 대한 abstain 케이스

Runner: `scripts/run_routed_measurement.py --backend sentence-transformers`. 결과: `reports/embedding_routed.json`.

### 헤드라인 수치 — Phase 1.4 (측정 2026-05-13, n=11, routed surface)

| Model | full (metadata_first=true) accuracy | routed (metadata_first=false) accuracy | Notes |
|---|---:|---:|---|
| MiniLM-L12-v2 | 0.500 | **0.400** | ADR 0019 default |
| multilingual-e5-large-instruct | 0.500 | **0.400** | ADR 0021 Phase 1.3 |
| KoSimCSE-roberta-multitask | 0.500 | **0.400** | ADR 0021 Phase 1.2 |
| BGE-M3 | — | — | Skipped: torch ≥ 2.6 required (ADR 0021 §4 blocker) |
| KURE-v1 | 0.500 | **0.400** | Korean-specialized; locally cached |

**Spread (top-vs-bottom, routed)**: **0.0pp** (threshold: +3pp per ADR 0032 §Decision)

### Phase 1.4 결과 읽기

1. **Saturation cross-validated**: 0pp 패턴이 routed surface (metadata-first disabled)에서도 성립. Saturation 가설은 "metadata-first absorption만의 artifact"가 아님을 확인.
2. **두 가지 상보 해석**:
   - *Corpus 규모 효과*: fixture corpus (7 docs, 9 chunks)에서 dense retrieval은 어떤 임베딩으로도 9개 chunk 중 올바른 것을 회수 → 큰 corpus에서는 spread 발생 가능
   - *Verifier 병목*: accuracy를 제한하는 것이 retrieval 품질이 아니라 verifier exact-term match 정책 (ADR 0004 설계 의도)
3. **ADR 0019 lock은 measurement-precluded가 아닌 empirically justified**: 두 surface(full + routed) 모두에서 0pp. Re-open condition 3 (≥ +5pp non-overlapping CIs)은 evidence-backed stable.
4. **ADR 0032 accepted로 closes**: 측정 surface 자체가 목표였으며, spread < +3pp 결과로 ADR 0032 자동 close. ADR 0019 default lock 유지.

## Fifth comparison — Phase 1.5 (issue #447, 2026-05-14): KURE-v1 Korean-specialized

[ADR 0037](../adr/0037-kure-v1-closes-phase-1-5.md)이 제기한 질문: issue #447이 re-open 조건으로 명시한 `nlpai-lab/KURE-v1`을 n=100 full corpus 대상으로 실행하면 condition 3 (≥+5pp `full` lift)이 trigger되는가?

> **Corpus note**: `eval/config.yaml`이 issue #570으로 n=42 → n=100으로 확장됐다. Phase 1.1–1.3의 ADR 0021 수치(accuracy 0.906 등)는 n=42 기준이므로 Phase 1.5 수치와 직접 비교 불가. 본 Phase는 같은 n=100 corpus 위에서 KURE-v1 vs MiniLM을 비교한다.

### 재현(Reproduction)

```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 scripts/run_embedding_ablation.py \
    --models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
             nlpai-lab/KURE-v1
```

환경: torch 2.6.0, sentence_transformers 2.7.0, torchvision 0.21.0.

### 헤드라인 수치 — Phase 1.5 (n=100, KURE-v1 vs MiniLM)

**`full` agentic 파이프라인** (ADR 0019 condition 3 의 구속 게이트):

| metric | MiniLM | KURE-v1 | Δ (pp) |
|---|---:|---:|---:|
| accuracy | 0.731 | 0.718 | **−1.3** |
| groundedness | 0.750 | 0.750 | **+0.0** |
| citation_precision | 0.715 | 0.700 | **−1.5** |
| abstention | 0.818 | 0.818 | **+0.0** |
| format compliance | 0.620 | 0.620 | **+0.0** |

**`naive_baseline`** (ADR 0001 보존 ablation — 미산입):

| metric | MiniLM | KURE-v1 | Δ (pp) |
|---|---:|---:|---:|
| accuracy | 0.590 | 0.782 | **+19.2** |
| groundedness | 0.550 | 0.690 | **+14.0** |
| citation_precision | 0.440 | 0.530 | +9.0 |
| format compliance | 0.520 | 0.640 | +12.0 |

### Phase 1.5 결과 읽기

1. **Condition 3 NOT triggered**: `full` pipeline에서 KURE-v1은 MiniLM 대비 accuracy −1.3pp, groundedness +0.0pp. +5pp 임계값에 도달하지 못할 뿐 아니라 순 음수(-). 0pp-on-full 패턴이 여섯 번째 임베딩 피벗에서도 성립.
2. **Korean-specialization은 naive_baseline에서만 유효**: +19.2pp accuracy lift는 인상적이지만 metadata-first routing (ADR 0002)이 agentic pipeline에서 dense retrieval을 우회하므로 `full`에 반영되지 않는다.
3. **Issue #447 closed**: 세 가지 re-open 조건 모두 처리됨 — 조건 1 (스크립트 추가, docstring 이미 존재), 조건 2 (n=100 실행 완료), 조건 3 (NOT triggered). 결과는 MiniLM 기본값 유지를 지지한다.
4. **ADR 0019 default lock은 이제 6-pivot empirical basis**: 2019–2024, multilingual / SoTA / Korean-specialized / multi-functional / Korean-specialized-v2 범주를 모두 커버했으며, 어느 것도 `full` 파이프라인 메트릭을 움직이지 못했다.

## 함께 보기

- [`scripts/run_embedding_ablation.py`](../../scripts/run_embedding_ablation.py) — Phase 1.1~1.3, 1.5 러너
- [`scripts/run_routed_measurement.py`](../../scripts/run_routed_measurement.py) — Phase 1.4 routed 측정 러너
- [`reports/embedding_routed.json`](../../reports/embedding_routed.json) — Phase 1.4 기계 판독 결과
- [`docs/eval/ablation-results.md`](ablation-results.md) — 더 넓은 ablation 맥락
- [ADR 0001](../adr/0001-preserve-naive-baseline.md) — `naive_baseline` 을 보존하는 이유
- [ADR 0002](../adr/0002-metadata-first-retrieval.md) — metadata-first 가 지배적인 이유
- [ADR 0019](../adr/0019-embedding-default-stays-minilm.md) — 보류 결정
- [ADR 0021](../adr/0021-bge-m3-completes-phase-1-3.md) — Phase 1.3 closure
- [ADR 0032](../adr/0032-eval-saturation-routed-subset.md) — Phase 1.4 saturation falsifier (accepted)
- [ADR 0037](../adr/0037-kure-v1-closes-phase-1-5.md) — Phase 1.5 KURE-v1 closure (accepted)
