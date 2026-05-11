# Portfolio Case Study

이 문서는 BidMate Agent를 AI/RAG Engineer 포트폴리오 관점에서 검토할 수 있도록 문제 선택, 성공 기준, 핵심 실험을 1인칭 *가설 → 실험 → 측정 → 결과 → 다음 행동* 형식으로, 산출물 검증과 다음 실험 설계까지 한 흐름으로 정리한다.

> 시니어 엔지니어링 시그널(아키텍처 결정 추적성, 측정 엄격성, 거버넌스, 회귀 잠금)과 인터뷰 talking point가 필요하면 [`senior-positioning.md`](./senior-positioning.md)를 함께 보면 된다.

## 1. 왜 이 문제를 골랐는가

RFP 문서 이해는 긴 문서에서 조건을 찾는 검색 문제처럼 보이지만, 실제로는 실무 의사결정에 필요한 근거를 정확히 연결하는 문제다. 예산, 일정, 요구사항, 제출조건이 여러 문서에 흩어져 있고, 질문은 단일 문서 추출뿐 아니라 기관 간 비교, 후속 질문, 문서에 없는 정보 판별까지 포함된다.

따라서 이 문제는 단순 검색 데모보다 RAG 시스템의 핵심 역량을 더 잘 드러낸다.

- retrieval이 올바른 문서와 chunk를 찾는가
- answer가 근거 chunk와 연결되는가
- 정보가 없을 때 추측하지 않고 abstain하는가
- 재현 가능한 평가셋과 실행 절차로 다시 검증할 수 있는가

원본 RFP는 외부 공유 제약이 있으므로 공개본에서는 synthetic RFP를 사용했다. 이는 실제 원본 데이터를 공개하지 못하는 제약 안에서도 데이터 흐름, 평가 방식, 산출물 검증 절차를 재현 가능하게 보여주기 위한 선택이다.

## 2. 성공 기준을 어떻게 정했는가

성공 기준은 "답이 그럴듯한가"가 아니라 "근거 기반으로 검증 가능한가"를 중심으로 잡았다.

| 기준 | 이유 | 공개본 검증 방식 |
|---|---|---|
| Answer Accuracy | 기대 문서와 핵심 용어가 답변/근거에 포함되는지 확인 | `expected_doc_ids`, `expected_terms` |
| Groundedness | 답변이 evidence 없이 생성되지 않는지 확인 | answer와 evidence text의 핵심 용어 매칭 |
| Citation Precision | citation이 기대 문서로 연결되는지 확인 | evidence doc id와 expected doc id 비교 |
| Answer Format Compliance | 구조화 답변이 상태, claim target, claim citation 계약을 지키는지 확인 | `answer.status`, `answer.claims`, `expected_claim_targets` |
| Abstention Accuracy | 없는 정보를 물었을 때 추측하지 않는지 확인 | answerable=false 케이스에서 abstained 확인 |
| Latency / Retry Rate | 검증 루프가 비용과 지연을 얼마나 만드는지 확인 | `reports/eval_summary.json`의 p50/p95, retry |

현재 README headline 표는 `reports/eval_summary.json`에서 갱신되며, 모든 수치는 공개 synthetic 평가셋(n=42, bootstrap 95% CI, seed=17, 1000 resamples) 기준이다. 원본 RFP 전체 성능으로 일반화하지 않는다.

## 3. 실험 노트

다음 5건은 시스템이 현재 형태에 도달하기까지 통과한 핵심 실험이다. 각 항목은 *가설 → 실험 → 측정 → 결과 → 다음 행동* 순서로 적었다. 인용 수치는 [README headline table](../README.md#성능-측정-결과)과 [`docs/ablation-results.md`](./ablation-results.md)에서 가져왔다.

### 3.1 Metadata-first retrieval — 비교 질의의 starvation 문제

- **가설**: 비교 질의("A와 B 중에서…")에서 score 기반 global top-k 컷이 한쪽 문서를 starve시키고, verifier가 evidence 부족을 잡아 불필요한 retry 또는 abstention을 만든다.
- **실험**: 메타데이터 필터링을 retrieval의 1차 단계로 두고 그 위에서 dense top-k를 적용. 비교 대상별 최소 1개 evidence를 보장하는 balanced cut을 추가. ablation으로 `no_metadata_first` 프리셋을 `eval/config.yaml`에 박아 `full`과 직접 비교.
- **측정**: README headline의 bootstrap CI(n=42, seed=17, 1000 resamples). 핵심 지표는 citation precision.
- **결과**: `no_metadata_first` citation precision 0.679 (CI 0.571–0.786) vs `full` 0.905 (CI 0.821–0.976) — CI가 분리되어 metadata-first 효용이 통계적으로 입증된다.
- **다음 행동**: 실데이터 100-doc eval에서 metadata가 누락된 PDF 비율을 측정해 fallback 경로의 가치를 수치화한다([`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md) 참고).

### 3.2 Verifier/retry loop — extractive 품질 보존 비용

- **가설**: extractive 답변이라도 verifier 없이는 grounding이 무너지고 abstention이 무력화된다.
- **실험**: `no_verifier_retry` ablation을 `eval/config.yaml`에 두고 verifier loop를 제거한 채 동일 retrieval 경로를 돌린다. accuracy는 같아 보이는지, groundedness와 abstention이 어떻게 변하는지 비교.
- **측정**: 같은 bootstrap CI 설정. 비교 축은 accuracy / groundedness / abstention / retry rate.
- **결과**: accuracy는 0.906 (`full` 동일)로 변화 없지만 groundedness가 0.929 → 0.762 (−16.7pp), abstention이 1.000 → 0.300으로 붕괴. retry rate는 0.000으로 떨어져 verifier가 만들던 비용이 사라지지만, "모름"을 안정적으로 말하는 능력이 함께 사라진다.
- **다음 행동**: retry trigger의 false-positive 비율을 추적해 verifier가 *언제* retry를 부르는지 cost-quality Pareto에 한 축으로 더한다([#124](https://github.com/hskim-solv/BidMate-DocAgent/issues/124)).

### 3.3 Hybrid BM25 + dense (ADR 0010)

- **가설**: 한국어 RFP의 약어/고유명사/사업번호는 dense 임베딩만으로는 정확 매칭이 약하다 — lexical 신호를 같이 봐야 한다.
- **실험**: BM25 ranker와 dense ranker를 reciprocal rank fusion으로 합치고 `hybrid_bm25` 프리셋으로 `eval/config.yaml`에 추가([ADR 0010](./adr/0010-hybrid-bm25-dense-retrieval-rrf.md)). 공개 synthetic 평가셋에서 ablation row로 측정.
- **측정**: README headline 표의 `hybrid_bm25` row — primary metrics가 `full`과 같은 ceiling에 도달하는지, latency overhead가 얼마나 되는지.
- **결과**: 공개 synthetic 기준 모든 primary metric이 `full`과 동일 (accuracy 0.906±0.12, groundedness 0.929±0.07, citation 0.905±0.08), latency p95는 3.2ms로 약 +0.3ms 추가. n=42에서는 *통계적으로 같음을 검출하기에 CI가 너무 넓다* — 실제 효과는 lexical 신호가 진짜 필요한 실데이터에서만 드러날 가능성이 큼.
- **다음 행동**: `make real-eval-delta`로 private 100-doc에서 BM25 기여도를 측정하고, 약어/사업번호 keyword 클래스별로 분리([#126](https://github.com/hskim-solv/BidMate-DocAgent/issues/126), [#170](https://github.com/hskim-solv/BidMate-DocAgent/issues/170)).

### 3.4 LLM synthesis as additive ablation (ADR 0011)

- **가설**: LLM 합성 경로를 추가해도 extractive baseline의 citation/abstention 계약을 깨지 않을 수 있다 — 단, *대체*가 아니라 *추가 row*로 두는 한.
- **실험**: `agentic_full_llm` 프리셋을 `eval/config.yaml`에 추가하고, 답변 합성을 Anthropic API에 위임하되 citation chunk_id가 응답에 등장하는지 강제 검증([ADR 0011](./adr/0011-llm-synthesis-as-additive-ablation.md)). citation 강제 통과 실패 시 extractive fallback. 공개 synthetic 평가셋에서 ablation row로 측정.
- **측정**: `full_llm`이 `full`과 같은 primary metric ceiling에 머무는지, latency overhead가 LLM 호출만큼만 늘어나는지 — 그리고 가장 중요한 건 abstention regression이 없는지.
- **결과**: `full_llm` accuracy 0.906±0.12 / groundedness 0.929±0.07 / citation 0.905±0.08로 `full`과 동일. latency p95 3.0ms(extractive 2.9ms 대비 +0.1ms, 합성 호출 비용 빼면 extractive와 같다). abstention 1.000 유지. ADR 0001 *extractive baseline invariant*를 깨지 않고 LLM을 추가했다는 것을 ablation 표에서 즉시 검증 가능.
- **다음 행동**: LLM-as-judge(#164)와 진짜 generation 비용 차이를 latency p50/p95에 더해 cost-quality Pareto에 plot.

### 3.5 Embedding 백엔드 ablation — latency-quality trade-off

- **가설**: hashing fallback과 production-grade sentence-transformers 사이에 품질 차이가 미세하다면, CI/CD 재현성을 위해 기본을 hashing으로 두는 게 합리적이다.
- **실험**: 동일 ablation runs를 두 백엔드(`hashing` vs `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)로 측정 — `scripts/run_embedding_ablation.py`로 자동화.
- **측정**: 같은 metric set + 백엔드별 p95 latency 비교.
- **결과**: `full` 기준 hashing이 accuracy 0.906 / groundedness 0.929로 sentence-transformers와 정량 품질이 같지만, **p95 latency가 약 10–200× 차이**. CI/CD 재현성을 우선해 hashing을 기본으로 채택([docs/ablation-results.md latency block](./ablation-results.md)).
- **다음 행동**: BGE-M3, KURE-v1 등 한국어 최적화 임베딩까지 ablation row로 추가([#188 Phase 1.2](https://github.com/hskim-solv/BidMate-DocAgent/issues/188)), 실데이터에서만 드러나는 의미 매칭 gap을 cross-encoder reranker([#192 Phase 1.3](https://github.com/hskim-solv/BidMate-DocAgent/issues/192))와 함께 측정.

## 4. 산출물을 어떻게 검증했는가

산출물 검증은 답변 텍스트만 보는 방식이 아니라, 입력-검색-근거-응답-평가 파일이 이어지는지 확인하는 방식으로 설계했다.

```text
data/raw synthetic RFP
  -> scripts/build_index.py
  -> data/index/index.json
  -> app.py / eval/run_eval.py
  -> outputs/answer.json, reports/eval_summary.json
  -> README metrics check (scripts/update_readme_metrics.py --check)
```

세 가지 잠금 장치:

1. **평가 케이스 명세**: 각 케이스는 `eval/config.yaml`/dev_queries에 query, expected doc ids, expected terms, answerable 여부를 가진다. `eval/run_eval.py`가 evidence doc ids, answer/evidence text, abstained flag를 비교해 요약 지표를 만든다.
2. **README 동기화**: 성능 표는 수동으로 주장하지 않고 `scripts/update_readme_metrics.py --check`로 `reports/eval_summary.json`과 어긋나면 실패. `make check`에 포함되어 CI에서 강제.
3. **실데이터 게이트**: 로드 베어링 파일(`rag_core.py`, `ingestion.py`, `visual_ingestion.py`, `eval/`, `api/`)이 바뀌면 PR 템플릿 5b가 `make real-eval-delta` 첨부를 요구한다(ADR 0005). public synthetic CI delta가 [#69의 intended-abstention regression](https://github.com/hskim-solv/BidMate-DocAgent/issues/69)을 놓쳤기 때문에 도입한 규칙.

## 5. 다음 실험을 왜 그렇게 설계하는가

다음 실험은 새 기능을 늘리기보다 *현재 측정 갭을 메우는* 방향으로 설계한다.

1. **Cost-quality Pareto** ([#124](https://github.com/hskim-solv/BidMate-DocAgent/issues/124))
   - 이유: 5건의 실험 모두 quality 한 축과 cost 한 축에 분포해 있지만 같은 plane에 plot한 적이 없다 — 운영 시 어느 frontier point를 고를지 정량 비교가 필요.
   - 방향: `reports/eval_summary.json`을 읽어 latency/retry vs accuracy/groundedness Pareto 차트와 use-case별 권장 frontier point를 추가.

2. **Multi-turn decay** ([#125](https://github.com/hskim-solv/BidMate-DocAgent/issues/125))
   - 이유: 후속 질문 single-turn은 측정하고 있지만 3/5-turn에서 entity carryover와 abstention discipline이 어떻게 무너지는지는 모른다.
   - 방향: 3/5-turn 시나리오를 eval에 추가, 같은 baseline·`full` pair 위에 *추가 측정 축*으로 — ADR 0001 *extractive baseline invariant* 위반 아님.

3. **Korean RFP per-axis 평가** ([#126](https://github.com/hskim-solv/BidMate-DocAgent/issues/126), [#170](https://github.com/hskim-solv/BidMate-DocAgent/issues/170))
   - 이유: 약칭/한자/금액단위/날짜형식/사업번호 같은 한국어 RFP 특화 신호의 fail rate는 통합 metric에 묻혀 있다.
   - 방향: 정규화 모듈(#170)을 utility로 먼저 추가하고, 그 위에서 per-axis accuracy를 ablation row로 누적(#126).

이 순서는 포트폴리오 관점에서도 중요하다. "더 복잡한 agent"를 만들기 전에, *어떤 실패를 줄이기 위해 어떤 측정 축을 더하는지* 설명할 수 있어야 한다.
