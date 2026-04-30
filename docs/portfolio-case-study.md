# Portfolio Case Study

이 문서는 BidMate Agent를 AI/RAG Engineer 포트폴리오 관점에서 검토할 수 있도록 문제 선택, 성공 기준, 실패, 비교 실험, 의사결정, 검증 방식, 다음 실험 설계를 한 흐름으로 정리한다.

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
| Abstention Accuracy | 없는 정보를 물었을 때 추측하지 않는지 확인 | answerable=false 케이스에서 abstained 확인 |
| Latency / Retry Rate | 검증 루프가 비용과 지연을 얼마나 만드는지 확인 | `reports/eval_summary.json`의 p50/p95, retry |

현재 README의 성능표는 `reports/eval_summary.json`에서 갱신된다. 수치는 공개 synthetic 평가셋 기준이며, 원본 RFP 전체 성능으로 일반화하지 않는다.

## 3. 어떤 실패가 났는가

초기 RAG 흐름에서 중요했던 실패는 세 가지다.

1. 메타데이터 불일치로 후보 문서가 검색 단계에서 누락됨
2. 비교 질의에서 한쪽 기관 문서만 상위 evidence로 노출됨
3. "그럼 일정은?" 같은 후속 질문에서 이전 엔터티가 사라짐

이 실패들은 생성 모델의 문장 품질 문제가 아니라 retrieval과 verification의 문제로 분류했다. 그래서 해결 방향도 답변 템플릿을 꾸미는 쪽이 아니라, query analysis, metadata filter, evidence coverage 검증을 강화하는 쪽으로 잡았다.

## 4. 어떤 실험을 비교했는가

문서와 코드에서는 다음 접근을 비교 축으로 둔다.

| 접근 | 장점 | 한계 | 판단 |
|---|---|---|---|
| keyword-only | 단순하고 설명 가능 | 표현 차이와 후속 질문에 약함 | baseline 후보 |
| dense-only | 의미 유사도 검색에 유리 | 기관/문서 단위 제약을 놓칠 수 있음 | 단독 사용은 보류 |
| metadata-first + dense/rerank | 기관/사업 단위 후보를 줄인 뒤 본문 유사도를 반영 | 메타데이터가 틀리면 후보 누락 위험 | 현재 채택 |
| verifier/retry 없음 | 빠르고 단순 | 근거 부족이나 비교 누락을 감지하기 어려움 | 공개본에서는 보류 |
| verifier/retry 있음 | missing evidence를 감지하고 재검색 가능 | latency와 retry 비용 증가 | 현재 채택 |

공개본의 현재 구현은 metadata-first 검색에 dense/lexical/metadata 점수를 결합하고, verifier가 topic/entity coverage를 확인한다. 검증 실패 시 metadata filter를 완화하고 top-k를 넓혀 1회 retry한다.

## 5. 왜 A안이 아니라 B안을 채택했는가

이 프로젝트에서는 유창한 생성보다 근거 재현성과 리뷰 가능성을 우선했다.

- A안: retrieve 후 바로 generate
- B안: analyze/plan/retrieve 후 verify/retry를 거쳐 extractive answer 생성

B안을 택한 이유는 다음과 같다.

- RFP QA에서는 답변이 맞아 보여도 citation이 틀리면 실무 의사결정에 쓰기 어렵다.
- 비교 질의는 모든 대상 기관이 evidence에 포함되는지 확인해야 한다.
- 부재 정보 질문에서는 "모른다"를 안정적으로 말하는 것이 성능이다.
- LLM/API 의존도를 줄이면 공개 포트폴리오에서 재현성과 리뷰 가능성이 높아진다.

이 결정의 비용도 명시한다. retry가 발생하면 latency가 증가하고, synthetic 평가셋이 작기 때문에 현재 수치는 기능 검증에 가깝다. 따라서 다음 단계에서는 데이터셋 확대와 latency/retry 비용 분석이 필요하다.

## 6. 에이전트 산출물을 어떻게 검증했는가

산출물 검증은 답변 텍스트만 보는 방식이 아니라, 입력-검색-근거-응답-평가 파일이 이어지는지 확인하는 방식으로 설계했다.

검증 흐름은 다음과 같다.

```text
data/raw synthetic RFP
  -> scripts/build_index.py
  -> data/index/index.json
  -> app.py / eval/run_eval.py
  -> outputs/answer.json, reports/eval_summary.json
  -> README metrics check
```

평가 케이스는 `eval/config.yaml`에 정의한다. 각 케이스는 query, expected doc ids, expected terms, answerable 여부를 가진다. `eval/run_eval.py`는 실행 결과의 evidence doc ids, answer/evidence text, abstained flag를 비교해 요약 지표를 만든다.

README 성능표는 수동으로 주장하지 않고 `scripts/update_readme_metrics.py`로 `reports/eval_summary.json`과 동기화한다. `--check` 모드는 README의 실측 표가 보고서와 어긋나면 실패하도록 만든다.

## 7. 다음 실험을 왜 그렇게 설계했는가

다음 실험은 새 기능을 늘리기보다 현재 병목을 더 잘 측정하는 방향으로 설계한다.

1. 평가셋 확대 및 카테고리 세분화
   - 이유: 현재 공개 synthetic 평가셋은 작아 회귀 방지와 흐름 검증에는 충분하지만 일반화 성능을 주장하기 어렵다.
   - 방향: 단일 추출, 다문서 비교, 후속 질문, 부재판별, 제출조건/일정/예산 카테고리를 분리한다.

2. citation 자동 검증 강화
   - 이유: RFP QA의 신뢰는 답변보다 근거 연결에서 결정된다.
   - 방향: citation chunk가 expected terms를 실제로 포함하는지, answer 문장과 같은 claim을 지지하는지 별도 점검한다.

3. latency와 retry 비용 분석
   - 이유: verifier/retry는 품질을 높일 수 있지만 운영 비용과 응답 지연을 만든다.
   - 방향: 첫 질의 모델 로드 시간과 순수 query latency를 분리하고, retry가 발생한 케이스를 별도로 추적한다.

이 순서는 포트폴리오 관점에서도 중요하다. "더 복잡한 agent"를 만들기 전에, 어떤 실패를 줄이기 위해 어떤 평가를 추가하는지 설명할 수 있어야 한다.
