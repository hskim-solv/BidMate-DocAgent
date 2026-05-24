# Pre-Improvement Readiness Checklist

## TL;DR

성능 개선 전 Definition of Ready는 private real-eval 기준선(baseline)을 먼저
검증하는 것이다. 순서는 반드시 parse audit -> eval dataset audit -> validate-only
-> baseline run -> failure taxonomy -> improvement hypothesis 이다.

이 문서는 audit-only PR 범위다. retrieval(검색), reranker(재순위),
prompt(프롬프트), chunking(청킹), verifier(검증기) 개선을 하지 않는다.

## Scope

목표는 개선 전 측정 표면(measurement surface)이 준비됐는지 확인하는 것이다.
성능 claim은 public fixture smoke 또는 synthetic benchmark가 아니라 private
real-eval aggregate에서만 후보로 삼을 수 있다.

| surface | allowed use | performance claim |
|---|---|---|
| public fixture smoke | CI smoke, regression(회귀) sanity | No |
| synthetic benchmark | reproducible framework check, ablation(절제) setup | No |
| private real-eval aggregate | credible baseline claim candidate | Aggregate-only candidate |

`private real-eval aggregate`도 raw output 자체가 아니라 privacy check를 통과한
aggregate summary만 claim 후보가 된다.

## Definition Of Ready

성능 개선 PR을 시작하기 전 다음 항목이 준비돼야 한다.

- Parse audit 완료: private 문서가 local-only 경로에서 읽히고, 문서 수, parse 성공/실패 수, page metadata coverage, empty text count, duplicate risk가 aggregate로만 기록된다.
- Eval dataset audit 완료: private question/evidence set의 row count, answerable/unanswerable 비율, explicit gold evidence coverage, multi-document/multi-chunk case count가 aggregate로만 기록된다.
- Validate-only 통과: private runner가 config, documents, manifest, questions, gold evidence, index/output path safety를 fail-closed로 검증한다.
- Baseline run 완료: 개선 전 Naive RAG 기준선(baseline)을 같은 private config로 1회 이상 실행하고, raw outputs는 local ignored path에만 둔다.
- Failure taxonomy 작성: baseline 결과를 retrieval-miss, reranker issue, citation/page metadata issue, verifier false positive/negative, answer synthesis issue, abstention failure, parse/metadata issue 등으로 aggregate 분류한다.
- Improvement hypothesis 작성: 어떤 개선이 어떤 failure mode를 줄일지, 어떤 metric이 움직여야 하는지, 어떤 guardrail metric이 악화되면 안 되는지 명시한다.

위 순서가 바뀌면 안 된다. 특히 improvement hypothesis는 baseline run과 failure
taxonomy 이후에만 작성한다.

## Required Order

1. Parse audit
2. Eval dataset audit
3. Validate-only
4. Baseline run
5. Failure taxonomy
6. Improvement hypothesis

## Local-Only Output Path

Audit output은 ignored local path인 다음 경로에만 쓴다.

```text
experiments/private_runs/readiness_audit
```

이 경로 아래 artifact는 commit하지 않는다. repository에 남길 수 있는 것은 raw
content가 제거된 aggregate summary 또는 문서화된 checklist뿐이다.

## Exact Local Commands

이 readiness workflow의 단일 local config는 `eval/real_config.local.yaml`이다.
별도의 `configs/eval/private_real_eval.local.yaml`를 만들지 않는다.

Parse/data readiness audit:

```bash
python3 scripts/audit_private_data_readiness.py --config eval/real_config.local.yaml --out-dir experiments/private_runs/readiness_audit
```

Validate-only:

```bash
python3 scripts/check_private_real_eval_readiness.py --config eval/real_config.local.yaml
```

Baseline run:

```bash
python3 scripts/run_private_real_eval.py --config eval/real_config.local.yaml
```

## Privacy Boundary

다음 값은 어떤 형태로도 commit 금지다.

- private raw document text
- raw question
- raw answer
- raw evidence
- filename
- exact local path
- `doc_id`
- `chunk_id`

보고서에 포함 가능한 정보는 aggregate count, aggregate metric, normalized failure
category, redacted limitation, redacted run metadata뿐이다. 예시는 question count,
answerable/unanswerable count, parse success rate, missing page metadata rate,
Recall@K aggregate, MRR/nDCG aggregate, citation aggregate, abstention aggregate,
failure category count이다.

## Parse Audit Checklist

- Private document source path가 ignored 또는 repository 밖에 있다.
- Audit output path가 `experiments/private_runs/readiness_audit`이다.
- 문서 원문, 파일명, exact local path를 출력하지 않는다.
- Aggregate document count와 extension/type count만 기록한다.
- Parse success/failure count와 empty/near-empty text count를 기록한다.
- Page/page_span metadata coverage를 aggregate로 기록한다.
- Manifest row와 parse result의 join coverage를 aggregate로 기록한다.

## Eval Dataset Audit Checklist

- Private question/gold evidence 파일이 ignored 또는 repository 밖에 있다.
- Raw question, raw expected answer, raw evidence/support text를 출력하지 않는다.
- Answerable/unanswerable 비율을 aggregate로 기록한다.
- Answerable row마다 explicit gold evidence가 있는지 확인한다.
- Unanswerable row에 fake evidence가 없는지 확인한다.
- Gold evidence가 stable identity를 갖되, committed artifact에는 `doc_id`와
  `chunk_id`를 포함하지 않는다.
- Multi-document, multi-chunk, table/structured-data, similar-clause distractor,
  abstention case coverage를 aggregate로 기록한다.

## Validate-Only Checklist

- `--validate-only`가 raw private content를 출력하지 않고 실패한다.
- Missing input, malformed row, unsafe output path, missing explicit evidence,
  invalid answerable/unanswerable evidence shape가 fail-closed로 잡힌다.
- Validation failure message는 field/category/count만 포함한다.
- Config path와 output path가 local-only/ignored boundary를 만족한다.

## Baseline Run Checklist

- 개선 전 code path를 변경하지 않은 상태에서 실행한다.
- 같은 private config, 같은 private corpus/index provenance, 같은 metric set을 사용한다.
- Raw `answers.jsonl`, `retrieved_chunks.jsonl`, `failure_cases.jsonl`,
  `metrics.json` 등은 ignored local path에만 남긴다.
- Claim 후보는 private raw output이 아니라 redacted aggregate summary다.
- Public fixture smoke 또는 synthetic benchmark 결과를 baseline performance claim로
  사용하지 않는다.

## Failure Taxonomy Checklist

Baseline 이후 failure taxonomy를 aggregate로 작성한다.

- `parse_or_metadata_issue`
- `retrieval_miss`
- `reranker_ordering_issue`
- `citation_or_page_metadata_issue`
- `verifier_false_positive`
- `verifier_false_negative`
- `answer_synthesis_issue`
- `abstention_failure`
- `evaluation_label_issue`
- `latency_or_runtime_issue`

Failure record에는 raw question, raw answer, raw evidence, filename, exact local
path, `doc_id`, `chunk_id`를 넣지 않는다.

## Improvement Hypothesis Checklist

각 hypothesis는 다음 형식으로 작성한다.

- Target failure mode: aggregate taxonomy category only
- Proposed change: retrieval/reranker/prompt/chunking/verifier 중 하나
- Expected metric movement: 예) Recall@10 up, citation precision unchanged
- Guardrail: abstention, citation precision, latency, privacy boundary 중 악화 금지 항목
- Evidence needed: private real-eval aggregate delta only

이 문서와 이 PR은 hypothesis를 실행하지 않는다. 실제 retrieval/reranker/prompt/
chunking/verifier 변경은 별도 PR에서 baseline aggregate와 failure taxonomy를 근거로
진행한다.
