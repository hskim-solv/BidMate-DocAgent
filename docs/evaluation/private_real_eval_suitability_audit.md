# Private Real-Eval Suitability Audit

> **Snapshot note.** 이 audit 의 verdict 는 작성 당시 checkout 에 대한 historical
> readiness snapshot 이며, 현재 private eval 준비 상태나 claim 근거가 아니다. 새
> 작업·PR·claim 에서 private eval readiness 를 주장하려면 현재 `real100_v2` 표면을
> `make real-eval-v2-check`, `make real-eval-v2-inventory`,
> `make real-eval-v2-guard` 로 다시 검증해야 한다.

## Executive Summary

최종 verdict: **A. Not ready**.

현재 checkout에는 진짜 Naive RAG 기준선(baseline)을 측정하는 데 필요한
private real-eval 입력이 없다. local private config, private 문서 디렉터리,
`data/data_list.csv`, private question/gold evidence 세트, private real-data
index, 최신 local `reports/real100/eval_summary.json`가 모두 없다.

기존 `reports/real100/*` aggregate-only artifact는 과거 real100 계열 private
run이 있었음을 보여준다. 그러나 이 artifact만으로는 현재 private baseline을
재현하거나 감사할 수 없다. 또한 run surface, case 수, corpus/index chunk 수가
artifact마다 다르므로, 현재 runnable private eval setup의 단일 출처(source of
truth)가 아니라 historical aggregate evidence로만 취급해야 한다.

이 감사는 private 원문 텍스트를 읽거나 보고서에 복사하지 않았다. 아래 내용은
존재 여부, schema, aggregate count, gitignore/privacy boundary만 점검한 결과다.

## Current Private Real-Eval Paths Found

| path | 상태 | suitability |
|---|---|---|
| `eval/real_config.local.yaml` | missing; `eval/*.local.yaml`로 ignored | local config missing |
| `eval/real_config.example.yaml` | present | partial template only |
| `eval/real_config.local.example.yaml` | present | partial template only |
| `configs/eval/private_real_eval.local.yaml` | missing; 현재 ignore 안 됨 | 사용 시 unsafe default location |
| `configs/eval/private_real_eval.template.yaml` | missing | template missing |
| `eval/private_hardcase.example.yaml` | present | hardcase template, 현재 real eval 아님 |
| `harness/real.example.yaml` | present | local private eval을 가리키는 harness template |
| `data/files/` | missing; ignored | private source docs missing |
| `data/files_kordoc/` | missing; ignored | regenerated cache missing |
| `data/data_list.csv` | missing; ignored | manifest missing |
| `data/private/` | missing; 현재 ignore 안 됨 | 사용 시 unsafe default location |
| `data/index/real100/` | missing; `data/index/*`로 ignored | private index missing |
| `data/index/real100_kordoc/` | missing; explicitly ignored | private kordoc index missing |
| `data/index-private-hardcase/` | missing; 현재 ignore 안 됨 | private template output path로는 unsafe |
| `reports/real100/eval_summary.json` | missing; ignored | current raw local summary missing |
| `reports/real100/*.aggregate.json` | present and tracked | historical aggregate-only artifacts |
| `reports/private_real_eval_summary.redacted.json` | missing; `reports/*`로 ignored | 현재 committable redacted summary 아님 |
| `experiments/private_runs/` | missing; 현재 ignore 안 됨 | 사용 시 unsafe output location |

Config verdict: **missing for current use**. 기존 example은 시작점으로는 유용하지만
`benchmark_type: private_real_eval`, `eval_type: private_real_eval`, 명시적
latency scope, private Naive RAG 기준선(baseline) run을 충분히 고정하지 않는다.
현재 committed `configs/eval/rag_quality_v1.yaml`은 public fixture용이며
`data/index`, `data/eval/rag_questions.jsonl`,
`data/eval/gold_evidence.jsonl`를 가리킨다.

## Data Inventory Summary

현재 private document inventory: **missing**.

현재 `data/` 아래에 보이는 디렉터리는 tracked fixture/support 성격의
`data/eval`, `data/index`, `data/lexicon`, `data/raw`, `data/training`뿐이다.
expected private path인 `data/files/`, `data/files_kordoc/`,
`data/private/files/`는 없다.

source document directory가 없으므로 현재 private file count, extension,
total size, readability, sensitive filename risk, duplicate/near-duplicate 여부,
target-domain coverage를 산출할 수 없다. 기존 tracked EDA aggregate는 과거
private corpus가 100 documents, mostly HWP, large kordoc-derived chunk corpus였음을
시사한다. 별도 embedding aggregate는 다른 chunk count의 real100 corpus를
기록한다. 이는 참고 맥락일 뿐 현재 local data가 존재하거나 동일하거나 readable
하다는 증거가 아니다.

Data inventory verdict: **missing**.

## Manifest Suitability

`data/data_list.csv`가 없다. 따라서 row count, missing file count, duplicate
`doc_id` count, invalid path count, split/eval group, page count, source
category, privacy/redaction flag를 현재 private setup 기준으로 감사할 수 없다.

현재 ingestion validator가 요구하는 CSV schema는 다음 Korean columns다.

- `공고 번호`
- `사업명`
- `발주 기관`
- `파일형식`
- `파일명`
- `텍스트`

이 schema는 private index build에는 사용할 수 있지만, reproducible private
baseline benchmark manifest로는 부족하다. `split`/`eval_group`, page count,
source category, privacy/redaction flag를 요구하지 않고, stable benchmark
`doc_id` column을 강제하지 않고 notice/file metadata에서 `doc_id`를 파생한다.

권장 manifest contract:

- stable anonymized `doc_id`
- local `file_path` 또는 `file_name`
- `document_type`
- `split` 또는 `eval_group`
- page count when available
- source category
- privacy/redaction flag
- source digest 또는 manifest version
- file existence validation result

Manifest verdict: **missing**.

## Question Set Suitability

현재 private question set: **missing**.

local private config 또는 expected private question file에서 private question을 찾지
못했다. committed public fixture set은 16 rows, 13 answerable, 3 unanswerable이지만
public fixture이며 private real-data baseline benchmark가 아니다.

historical aggregate artifact는 21, 36, 221 prediction surface처럼 서로 다른 run
size를 기록한다. 현재 private config와 question file이 없으므로 authorship,
lexical leakage, difficulty distribution, Korean/English mix, table-heavy coverage,
similar-clause disambiguation, multi-document synthesis, recommended 15-25%
unanswerable share를 검증할 수 없다.

Classification: **not usable due to missing current labels/questions**.

Threshold assessment:

- smoke-level real eval, at least 10 questions: **not verifiable now**
- first baseline signal, at least 30 questions: **not verifiable now**
- portfolio-level baseline claim, at least 100 questions: **not verifiable now**

## Gold Evidence Suitability

현재 private gold evidence: **missing**.

`data/private/gold_evidence.jsonl`, `data/eval/private/gold_evidence.jsonl`,
`reports/real100/gold_evidence.jsonl`, local private config reference 등에서
private gold evidence를 찾지 못했다. committed public fixture
`data/eval/gold_evidence.jsonl`은 16 rows이지만 `question_id` + `gold_evidence`
wrapper shape만 확인되며 현재 private real-eval gold가 아니다.

main real-eval scorer는 `doc_id`, `chunk_id`, `page_span`, `required_terms`,
`support_claim` 형태의 explicit `gold_evidence`를 소비할 수 있다. 그러나 explicit
label이 없으면 `expected_doc_ids` + `expected_terms`로 gold chunk를 파생하는
fallback도 유지한다. 이 fallback은 같은 indexed corpus 안의 expected term overlap에서
label을 만들기 때문에 credible real 검색(retrieval) claim의 주 gold source로는
부적합하다.

Gold evidence verdict: **missing for private baseline**.

Blocking requirements:

- answerable question마다 explicit evidence
- stable unique evidence IDs 또는 stable `question_id` + evidence index
- `doc_id`와 `chunk_id`
- 가능한 경우 page number 또는 `page_span`
- support span/text는 local-only 보관, committed report는 redacted aggregate만
- unanswerable question에는 fake evidence 없음
- multi-chunk/multi-document question에는 multiple evidence records
- support span이 source/index text에 존재하는지 local verification

## Index Readiness

현재 private index: **missing**.

`data/index/real100/`와 `data/index/real100_kordoc/`가 없다. 현재 존재하는
`data/index`는 5 documents / 6 chunks의 committed public smoke fixture index다.
이는 private real-data index가 아니며 의미 있는 `top_k` baseline measurement에
비해 너무 작다.

historical aggregate는 과거 private kordoc index가 tens of thousands of chunks
수준이었음을 시사한다. 하지만 현재 local index metadata가 없으므로 다음을 확인할
수 없다.

- current manifest/documents provenance
- `doc_id`, `page`, `page_span`, `chunk_id` metadata coverage
- chunk count relative to `top_k`
- embedding backend
- staleness
- source manifest traceability
- smoke/synthetic index와의 분리 여부

Index verdict: **missing**.

## Metric Readiness

Code readiness: **partially suitable**. Current data readiness: **not suitable**.

main eval path에서 구현 또는 사용 가능한 metric:

- `chunk_recall_at_5`, `chunk_recall_at_10`, `chunk_recall_at_20`
- `chunk_mrr_at_5`, `chunk_mrr`
- `chunk_ndcg_at_5`, `chunk_ndcg_at_10`, `chunk_ndcg_at_20`
- `citation_precision`
- `claim_citation_alignment`
- `citation_page_precision` when `expected_citation_pages` exists
- `citation_page_coverage` as gold-free page metadata coverage
- `citation_region_precision`, `citation_region_coverage` when region data exists
- `abstention`, `abstention_outcomes`, failure category counts
- warm per-query latency와 stage latency aggregates

credible private Naive RAG baseline claim을 막는 metric gaps:

- 현재 private explicit gold evidence가 없어 retrieval metrics를 신뢰할 수 없다.
- `expected_terms` fallback은 real baseline claim의 primary gold source로 쓰면 안 된다.
- 별도 `eval/naive_rag` contract는 `faithfulness`, `answer_relevancy`를 노출하지만
  구현은 placeholder/rule-based다. 즉 retrieved chunk 안 citation membership과
  expected-term containment이며 semantic Faithfulness 또는 Answer Relevancy로
  발표하면 안 된다.
- LLM generation이 disabled인 경우 generation latency가 아니라 deterministic answer
  assembly latency로 표기해야 한다.
- citation check가 doc/chunk identity만 보면 page-level citation accuracy라고 부르면
  안 된다.
- `missing_page_number_rate`, `page_metadata_coverage`, `unsafe_answer_rate`,
  `unanswerable_detection_rate`는 private redacted summary의 headline-safe field로
  분리해야 한다.

Metric verdict: **partially suitable implementation, blocked by missing data and
label contract**.

## Latency Measurement Scope

main eval path는 in-process query latency와 warm stage latency summary를 기록한다.
ingestion, parsing, chunking, embedding/index build, 보통의 index load time은 제외된다.
historical aggregate에는 `latency`와 `stage_latency`가 있지만 현재 raw
`eval_summary.json`은 없다.

private baseline reporting에 필요한 latency fields:

- `warm_query_latency_ms`
- `retrieval_latency_ms`
- deterministic answer assembly latency 또는 explicit generation latency
- 측정 시 `index_load_latency_ms`
- `benchmark_excludes_setup_costs: true/false`
- ingestion/index build time은 별도 측정 시 별도 report
- cold/warm split with sample counts

Latency verdict: **partially instrumented, not auditable for current private
setup**.

## Privacy And Gitignore Safety

좋은 safety findings:

- `data/files/`, `data/files_kordoc/`, `data/private/`, `data/data_list.csv`,
  local private config paths, `reports/real100/eval_summary.json`의 known private
  raw/source file은 tracked 상태가 아니다.
- `eval/*.local.yaml`은 ignored다.
- `data/files/`, `data/files_kordoc/`, `data/data_list.csv`는 ignored다.
- `data/index/*`는 public fixture allowlist를 제외하고 ignored이며
  `data/index/real100`도 여기에 포함된다.
- `reports/real100/eval_summary.json`와 local JSONL/raw report files는 ignored다.
- tracked `reports/real100`와 Phase 4 retrieval artifact에 대한 eval artifact
  privacy checks가 통과한다.

Safety gaps:

- `configs/eval/private_real_eval.local.yaml`은 ignored가 아니다. 이 위치를 쓰려면
  `.gitignore`에 `configs/eval/*.local.yaml`가 필요하다.
- `data/private/`는 ignored가 아니다. operator가 이 경로를 쓰려면 `.gitignore`에
  `data/private/`가 필요하다.
- `eval/private_hardcase.example.yaml`이 index output으로 가리키는
  `data/index-private-hardcase/`가 ignored가 아니다.
- `experiments/private_runs/`는 ignored가 아니며 `experiments/runs/`만 ignored다.
- `reports/private_real_eval_summary.redacted.json`은 broad `reports/*` rule 때문에
  ignored다. 기본적으로 안전하지만, committable redacted summary로 삼으려면 explicit
  allowlist와 privacy regression guard가 필요하다.

Privacy verdict: **partially suitable with important path-safety gaps**.

## Existing `reports/real100` Summary

`reports/real100/eval_summary.json`이 없으므로 현재 raw private run은 inspect할 수 없다.

tracked aggregate-only files는 존재한다. 여기에는 `baseline.aggregate.json`,
`eda.aggregate.json`, `rag_pipeline.aggregate.json`, failure distribution,
rationality, variance, history, embedding ablation aggregates가 포함된다. 이 파일들은
현재 privacy scanner 기준으로 safe aggregate artifact지만, 현재 private eval input을
대체하지 못한다.

existing aggregate limitations:

- `baseline.aggregate.json`은 `pipeline: agentic_full`이며 Naive RAG baseline이 아니다.
- `baseline.aggregate.json`의 `top_k`는 `null`이다.
- historical aggregate surfaces는 effective run size와 corpus/index description이
  서로 다르다. 서로 다른 실험이라 자연스러운 차이일 수 있지만, 현재 baseline source
  of truth로 쓰기에는 부적합하다.
- `rag_pipeline.aggregate.json`의 해당 surface는 retrieval recall/MRR/nDCG에 대해
  gold-chunk case가 0이다.
- 일부 aggregate metric은 answer/control metric이지 semantic answer judge가 아니다.

Existing summary verdict: **safe as historical aggregate context, not suitable
as current private Naive RAG baseline evidence**.

## Suitability For Baseline Claims

| claim level | current suitability | reason |
|---|---|---|
| smoke-only validation | no | local private config/data/questions/gold/index가 없다 |
| first naive baseline signal | no | explicit private questions와 gold evidence가 없다 |
| portfolio-level baseline claim | no | current reproducible private eval package가 없고 historical aggregate만으로는 부족하다 |

## Blocking Issues

1. Current local private config가 없다.
2. Current private source document directory가 없다.
3. Current manifest가 없다.
4. Current private question set이 없다.
5. Current explicit private gold evidence가 없다.
6. Current private real-data index가 없다.
7. Current raw local `eval_summary.json`이 없다.
8. Existing tracked aggregate summaries는 Naive RAG baseline summaries가 아니다.
9. Alternative private paths가 모두 gitignored 되어 있지 않다.
10. Placeholder answer metrics를 semantic Faithfulness 또는 Answer Relevancy로
    발표하면 안 된다.

## Recommended Fixes

P0:

- `eval/real_config.local.yaml`에 local-only private config를 만들거나,
  `configs/eval/*.local.yaml` 사용 전 ignore rule을 추가한다.
- private local source data, manifest, questions, gold evidence, index, report
  directories를 복구하거나 env vars로 외부 private root를 가리킨다.
- 모든 answerable question에 explicit private gold evidence label을 추가한다.
- support text/span은 local-only로 유지하고, commit은 aggregate redacted summary만 한다.

P1:

- `benchmark_type: private_real_eval`, explicit `top_k`, metric set, index path,
  output path, embedding backend, latency scope를 담은 private benchmark template을
  추가하거나 문서화한다.
- `data/private/`, `data/index-private-hardcase/`, `experiments/private_runs/`,
  `configs/eval/*.local.yaml`가 recommended path로 남는다면 gitignore coverage를
  추가한다.
- privacy scanner coverage가 있는 committable redacted private summary schema를
  추가한다.
- placeholder answer metrics는 `rule_based_groundedness`,
  `term_coverage_accuracy`처럼 이름을 바꾸거나 명확히 주석 처리한다.

P2:

- first baseline signal에는 30+ independently authored private questions를 요구한다.
- portfolio-level claim에는 100+ questions를 요구한다.
- unanswerable cases는 15-25%를 유지한다.
- table/structured-data, similar-clause distractor, multi-chunk, multi-document
  synthesis cases를 명시 포함한다.
- citation metrics 옆에 page metadata coverage와 missing page number rate를 보고한다.

## Next Action

Recommended next task:

**Create private real-eval readiness scaffold without private data**

Scope:

- unsafe candidate private paths에 대한 gitignore coverage 추가
- committed private real-eval config template과 redacted summary schema 추가
- private content를 출력하지 않고 private config, manifest, docs, questions,
  gold evidence, index 존재 여부를 확인하는 local validation script/checklist 추가
- retrieval, reranking, prompt, chunking, generation behavior는 변경하지 않음

이 scaffold와 local private labels/index가 준비되기 전까지, 현재 real data는 credible
Naive RAG baseline measurement에 사용할 수 없다.
