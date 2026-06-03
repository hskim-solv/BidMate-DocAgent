# BGE-M3 multi-channel 검색(retrieval) spike (`retrieval_backend = "m3"`)

issue #151 추적. BGE-M3 의 세 검색(retrieval) 채널을 N-way RRF 로 융합(fusion)한
결과를 정직하게 측정하고, MiniLM hybrid 기준선(`hybrid_bm25`, ADR 0010)과
정면 비교한다.

## 왜 ADR 가 아니라 spike 인가

ADR 0010 의 "Alternatives considered"(72-85행)는 BGE-M3 sparse + ColBERT
multi-vector 채널을 별도 ablation 으로 명시적으로 미룬다. 원래 hybrid PR 이
임베딩 모델 교체를 함께 묶었기 때문에 sparse-채널 기여도가 교란(confound)되었을
것이기 때문이다. 이어서 ADR 0021 은 BGE-M3 를 **dense embedding** 으로 `full`
에서 측정해 향상(lift)을 찾지 못했고, 모델은 기본값으로 채택되지 않았다. 이
spike 가 검증하는 가설은 ADR 0021 이 검증하지 못한 것이다: **BGE-M3 의 가치는
dense 채널 단독이 아니라 multi-channel 출력에 있다.**

이는 ADR 0019 → ADR 0021 로 이어진 것과 동일한 measure-first 패턴이다. 이
spike 가 `hybrid_bm25` 대비 의미 있는 향상(lift)을 보이면, 후속 PR 이 sparse +
colbert 벡터를 디스크에 영속화(index schema bump 2 → 3)하고 ADR 0010 의 보완으로
ADR 0025 를 작성한다. 향상이 없으면 이 문서가 음성 결과(negative result)를
기록하고 채널은 미뤄진 채로 둔다.

## 범위(Scope)

- `FlagEmbedding.BGEM3FlagModel` 을 통한 **3-채널 인코딩**:
  - dense(텍스트당 1024-dim L2-normalized 벡터 — 아무것도 대체하지 않고,
    인덱스가 사용한 기존 dense 채널과 병행)
  - sparse(텍스트당 SPLADE-style `{token_id: weight}` dict)
  - multi-vector / ColBERT(텍스트당 per-token `(T_i, 1024)` 행렬;
    채점 시 late-interaction max-sim 합산)
- [`rag_core.apply_fusion_and_reranking`](../../rag_core.py) 의 **N-way RRF 융합(fusion)**
  — 기존 2-way `hybrid` 수식(`rrf_k / 2.0` 정규화)이 N=3 에 대해
  `rrf_k / N` 으로 일반화된다.
- **Opt-in, in-memory 전용.** Sparse + colbert 출력은 첫 m3 쿼리 시 프로세스당
  인덱스당 한 번 계산되어 `index["_m3_cache"]` 로 캐시된다. spike 를 위한
  디스크 포맷 변경이나 `index.json` 스키마 bump 는 없다(`INDEX_SCHEMA_VERSION`
  은 2 유지).
- **공개 CI 표면 불변.** `pr-eval.yml` 은 `EMBEDDING_BACKEND=hashing` 으로
  실행되고 `m3_*` ablation 행은 opt-in 이므로, 합성(synthetic) CI 는 절대
  `FlagEmbedding` 을 설치하지 않는다.

## Runner

```bash
# Install the optional dependency
pip install -r requirements-m3.txt

# Sanity check — m3 row in eval/config.yaml is opt-in; the default
# config.yaml runs all rows, but the m3 row will raise without the
# dependency installed.
python3 eval/run_eval.py \
  --index_dir data/index \
  --output_dir outputs \
  --config eval/config.yaml

# Optional — just the m3 row (faster iteration during the spike)
python3 eval/run_eval.py \
  --index_dir data/index \
  --output_dir outputs/m3_spike \
  --config eval/config.yaml \
  --runs m3_full
```

Historical real-data eval note: 이 spike 가 처음 작성될 때의 5b gate 흐름은
`make real-eval` + `make real-eval-delta` 로 legacy `real100` 표면을 확인했다.
이 명령 조합과 `reports/real_eval_delta.json` 해석은 archive-only 운영 기록이며,
현재 새 작업·PR·claim 의 private eval 근거로 사용하지 않는다.

현재 M3 retrieval claim 을 다시 열려면 먼저 `make real-eval-v2-check`,
`make real-eval-v2-inventory`, `make real-eval-v2-guard` 로 `real100_v2` 입력/산출물
경계를 검증하고, 별도 `real100_v2` aggregate surface 를 만든 뒤 비교해야 한다.

## 결과(Results)

_eval 실행 후 구현자가 채워 넣는다. 아래 표와 `docs/eval/ablation-results.md`
에 행을 추가한다._

| Ablation | recall@5 | MRR@10 | faithfulness | citation_precision | p50 latency (s) | p95 latency (s) | peak RSS delta (MB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `naive_baseline` (control) | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `full` (control) | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `hybrid_bm25` (control) | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `m3_full` | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## 결정 규칙(Decision rule)

현재 `real100_v2` private eval 표면에서 **세 조건 모두** 충족될 때만 ADR 0025 보완(및
`INDEX_SCHEMA_VERSION = 3` 으로 sparse + colbert 를 디스크에 영속화하는 후속
PR)을 출하한다:

1. `m3_full` recall@5 ≥ `hybrid_bm25` recall@5 + 0.03(절대 3 percentage
   point; 합성(synthetic) eval 노이즈 바닥은 이보다 한참 낮다).
2. `m3_full` faithfulness ≥ `hybrid_bm25` faithfulness − 0.01(의미 있는
   회귀 없음).
3. `m3_full` p95 latency ≤ 2 × `hybrid_bm25` p95(multi-vector 경로는 더 느릴
   것으로 예상되며, 이는 사용자에게 체감되기 전까지의 예산이다).

그렇지 않으면 이 spike 는 음성 결과(negative result)로 남고 채널은 미뤄진다.
ablation 행은 `eval/config.yaml` 에 opt-in 으로 남아, 미래 구현자가 배선(wiring)을
다시 도입하지 않고도 다른 BGE-M3 모델 크기나 융합(fusion) 가중치로 재실행할 수
있다.

## corpus-side 연산에 왜 옵션 (a) 인가

corpus-side sparse + colbert 연산에 대해 세 가지 옵션을 검토했다:

- **(a) 첫 m3 쿼리 시 모든 청크 계산, in-memory 캐시.** — 채택. 프로세스당
  forward pass 1회. 저렴한 엔지니어링, 정직한 sparse-recall 측정.
- (b) dense top-K 에 대해서만 lazy. 더 저렴하지만 dense 채널이 이미 표면화한
  범위로 sparse recall 을 제한 — spike 의 측정 의도를 무력화한다(sparse 의
  기여가 dense recall 과 교란(confound)된다).
- (c) sparse 는 사전(upfront), colbert 는 top-K 에 대해 lazy. 메모리 프로파일은
  최선이지만 측정 전용 변경에 대해 코드 경로 두 개를 유지해야 한다. (a)의
  in-memory colbert 텐서가 runner 를 터뜨리면 재검토 — spike 리포트가 peak RSS
  를 기록하므로 trade-off 를 재검토할 수 있다.

## 알려진 리스크(Known risks)

- **FlagEmbedding 설치 footprint.** torch(이미 pin), datasets, peft 를 끌어온다.
  완화책: opt-in `requirements-m3.txt`; `M3Encoder.__init__` 은 의존성 부재 시
  명확하고 조치 가능한 에러를 발생시킨다. 공개 CI 는 절대 설치하지 않는다.
- **In-memory ColBERT 비용.** real-data corpus 의 경우 ~1k chunks × T_i × 1024
  × float32 ≈ 100 MB 수준. spike 리포트의 peak-RSS 행이 실제 비용을 기록한다.
  eval runner 를 압도하면 옵션 (c) 가 제품화 경로가 된다.
- **`naive_baseline` bit-동일성.** m3 경로는 `retrieval_backend == "m3"` 로
  게이트된다. 기본 `dense` 경로는 절대 `rag_m3` 를 import 하지 않는다. 기존
  `tests/test_naive_baseline_ranking_invariance.py` 스냅샷이 ratchet 이다.
- **인코딩 비대칭성.** BGE-M3 의 레퍼런스 문서는 query vs document 인코딩을
  구분하기 위해 `is_query` 를 사용한다. 모델 자체는 대칭이며 wrapper 는 단순성을
  위해 이 플래그를 생략한다. 후속 측정이 비대칭 채점 향상(lift)을 보이면 플래그를
  깔끔하게 추가할 수 있다.
