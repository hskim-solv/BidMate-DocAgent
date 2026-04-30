# 평가 템플릿 + 자동 채점 사용 가이드

이 파일들은 `dev_queries_v1.jsonl`에 맞춰 바로 실험 비교를 시작할 수 있게 만든 **최소 평가 운영 세트**입니다.

이 구조는 중급 프로젝트 가이드의 핵심 평가 축인  
**단일 문서 정확 추출 / 여러 문서 비교·종합 / 후속 질문 이해 / 문서에 없는 내용에 대한 안전한 응답**을 분리해서 보려는 목적에 맞춰 설계했습니다. fileciteturn6file0

## 포함 파일

- `eval_results_template.csv`
  - 질문 44개가 이미 들어 있고, 시스템 실행 결과만 채우면 됩니다.
- `evaluate_dev_results.py`
  - 결과 CSV를 읽어서 질문별 점수와 전체 요약을 만듭니다.

## `eval_results_template.csv`에서 채워야 할 핵심 컬럼

- `system_answer`
  - 시스템이 실제로 생성한 답변
- `predicted_doc_ids`
  - 시스템이 근거로 사용했다고 보는 문서 ID  
  - 여러 개면 `D07|D08` 처럼 `|` 로 구분
- `predicted_chunk_ids`
  - 있으면 기록, 없으면 비워도 됨
- `retrieved_context_count`
  - 컨텍스트 청크 개수
- `latency_ms`
  - 응답 시간(ms)
- `retry_count`
  - 재검색 / retry 횟수
- `run_name`
  - 예: `bm25_v1`, `dense_v1`, `dense_rerank_v1`
- `model_name`
  - 예: `gpt-5-mini`, `gpt-5-nano`, `rule_based`

## 사람이 나중에 체크할 수 있게 남겨둔 컬럼

- `manual_answer_correct`
- `manual_grounded`
- `manual_doc_match`
- `manual_abstention_correct`

규칙 기반 자동 채점만으로 애매한 문항이 남을 수 있어서,  
최종 발표용 수치는 이 수동 점검 컬럼으로 보정하는 방식이 좋습니다.

## 자동 채점 스크립트가 보는 것

### 1. `answer_pass`
- 일반 문항: `must_include`의 절반 이상이 답변에 들어가거나 `acceptable_aliases`가 잡히면 통과
- 부재판별 문항: “확인되지 않는다 / 명시되지 않는다 / 문서에 없다” 류 표현이 있으면 통과

### 2. `doc_hit`
- `predicted_doc_ids`와 `target_doc_ids`가 하나라도 겹치면 1

### 3. `grounded_pass`
- 답변이 맞고(`answer_pass=1`), 문서도 맞으면(`doc_hit=1`) 통과
- `predicted_doc_ids`를 안 적은 경우에는 보수적으로 `answer_pass`만 반영

### 4. `citation_precision`, `citation_recall`
- 예측 문서 ID가 실제 타깃 문서와 얼마나 겹치는지 계산

### 5. `latency_ms`, `retry_count`
- 실험 간 속도와 retry 비용 비교용

## 실행 예시

```bash
python evaluate_dev_results.py \
  --results eval_results_template_filled.csv \
  --out-prefix outputs/bm25_v1
```

## 생성 결과

위 명령을 실행하면 아래 파일이 생깁니다.

- `outputs/bm25_v1_per_question.csv`
- `outputs/bm25_v1_summary.json`
- `outputs/bm25_v1_summary.md`

## 추천 운영 방식

### 실험 1
- `run_name=bm25_v1`
- lexical baseline
- `predicted_doc_ids` 반드시 기록

### 실험 2
- `run_name=dense_v1`
- dense retrieval 추가

### 실험 3
- `run_name=dense_rerank_v1`
- rerank 추가

### 실험 4
- `run_name=metadata_retry_v1`
- metadata filter + verifier/retry 추가

이렇게 하면 각 실험의  
정확도 / groundedness / abstention / latency / retry cost  
를 한 프레임에서 비교할 수 있습니다.

## 권장 보완

자동 채점은 시작점으로는 충분하지만, 아래 8~10문항은 사람이 직접 확인하는 편이 좋습니다.

- 비교형 문항
- PDF 저신호 문항
- 수치 표기가 다양한 문항
- 부재판별 문항

## 다음 단계

이제 바로 이어서 붙이면 좋은 것은 둘 중 하나입니다.

1. **실행 결과를 자동으로 `eval_results_template.csv`에 채워 넣는 runner 스크립트**
2. **최종 발표용 성능표(markdown 표) 자동 생성 스크립트**
