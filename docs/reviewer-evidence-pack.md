# Reviewer Evidence Pack

이 문서는 채용 리뷰어 또는 면접관이 BidMate Agent의 데모 흐름, 대표 질의, 성공/실패/개선 근거를 5분 안에 확인할 수 있도록 정리한 한 페이지 가이드다.

## 5-minute demo flow

아래 흐름은 README의 기본 경로와 동일하며, CLI 인터페이스와 산출물 경로를 바꾸지 않는다.

```bash
python3 scripts/build_index.py --input_dir data/raw --output_dir data/index

python3 app.py \
  --input_dir data/index \
  --output_dir outputs \
  --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"

python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml

python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
```

확인할 산출물은 다음 세 가지다.

- [`../data/index/index.json`](../data/index/index.json): 공개 synthetic RFP에서 만든 검색 인덱스
- [`../outputs/answer.json`](../outputs/answer.json): 대표 질의 응답, claim 단위 citation, evidence
- [`../reports/eval_summary.json`](../reports/eval_summary.json): 평가 요약, query type별 metric, ablation 결과

## Representative queries

대표 질의는 [`../eval/config.yaml`](../eval/config.yaml)의 공개 synthetic 평가 케이스에서 뽑았다. `answer.status`는 기대되는 응답 상태이며, expected terms와 doc id는 평가 기준으로 쓰이는 확인 포인트다.

| Scenario | Query | Expected `answer.status` | Expected terms | Expected evidence doc ids |
|---|---|---|---|---|
| Single-doc security | `기관 A의 보안 통제 요구사항은?` | `supported` | `보안 통제`, `로그` | `rfp-agency-a-ai-quality` |
| Single-doc chatbot SLA | `기관 C의 챗봇 응답 시간 목표는?` | `supported` | `2초`, `상담 이관` | `rfp-agency-c-chatbot` |
| Multi-doc AI comparison | `기관 A와 기관 B의 AI 요구사항 차이 알려줘` | `supported` | `품질관리`, `MLOps` | `rfp-agency-a-ai-quality`, `rfp-agency-b-mlops-governance` |
| Multi-doc security comparison | `기관 A와 기관 B의 보안 요구사항 차이를 비교해줘` | `supported` | `보안 통제`, `개인정보 비식별화` | `rfp-agency-a-ai-quality`, `rfp-agency-b-mlops-governance` |
| Follow-up with state | `그 기관이 요구한 보안 조건도 보여줘` after `기관 A의 AI 요구사항은?` | `supported` | `보안 통제`, `로그` | `rfp-agency-a-ai-quality` |
| Abstention | `기관 A의 블록체인 납품 실적은?` | `insufficient` | missing topic: `블록체인` | none |

후속 질문은 세션 상태 파일로 재현한다.

```bash
python3 app.py \
  --input_dir data/index \
  --output_dir outputs \
  --query "기관 A의 AI 요구사항은?" \
  --session_state outputs/session_state.json \
  --reset_session

python3 app.py \
  --input_dir data/index \
  --output_dir outputs \
  --query "그 기관이 요구한 보안 조건도 보여줘" \
  --session_state outputs/session_state.json
```

## Evidence map

| Evidence type | Where to look | What it proves |
|---|---|---|
| Success example | [`../outputs/answer.json`](../outputs/answer.json) | 비교 질의에서 기관별 claim과 citation이 분리되어 나온다. |
| Aggregate metrics | [`../reports/eval_summary.json`](../reports/eval_summary.json) | 단일 추출, 다문서 비교, 후속 질문, 부재판별이 같은 평가 루프에서 측정된다. |
| Ablation impact | [`./ablation-results.md`](./ablation-results.md) | verifier/retry가 groundedness, citation, abstention에 주는 영향을 비교한다. |
| Failure taxonomy | [`./failure-cases.md`](./failure-cases.md) | metadata mismatch, partial coverage, citation drift 같은 실패 유형을 분리한다. |
| Improvement direction | [`./retrospective.md`](./retrospective.md) | 평가셋 확대, citation 검증 강화, latency/retry 비용 분석을 다음 작업으로 둔다. |

## Interview recap

- **Problem**: RFP QA는 긴 문서에서 예산, 일정, 요구사항, 제출조건을 찾는 문제를 넘어 다문서 비교와 근거 검증이 핵심이다.
- **Design choice**: 생성 유창성보다 재현 가능한 근거성을 우선해 query analysis, metadata-first retrieval, reranking, verifier/retry, structured answer policy를 연결했다.
- **Validation**: `eval/config.yaml`의 공개 synthetic 케이스로 answer accuracy, groundedness, citation precision, answer format compliance, abstention, latency/retry를 함께 본다.
- **Observed failures**: 후보 문서 누락, 비교 질의의 partial coverage, 후속 질문의 엔터티 소실, unsupported over-answering을 주요 위험으로 분류했다.
- **Improvement path**: 데이터셋을 확장하고, citation chunk가 claim을 직접 지지하는지 더 강하게 검증하며, retry가 품질 대비 지연을 얼마나 만드는지 분리 측정한다.

## Reviewer checklist

- README의 성능표가 `reports/eval_summary.json`과 동기화되는가?
- 대표 질의의 `answer.claims[*].citations`가 기대 문서와 직접 연결되는가?
- 부재 정보 질문에서 `insufficient`로 멈추고 근거 없는 claim을 만들지 않는가?
- 실패 사례와 다음 개선 방향이 코드/평가 결과와 같은 흐름으로 설명되는가?
