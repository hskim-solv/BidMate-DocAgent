# Local gold authoring guide

이슈 [#50](https://github.com/hskim-solv/BidMate-DocAgent/issues/50)의 산출물. 비공개 실데이터(`data/files/`, `data/data_list.csv`) 위에서 답변 정확도와 abstention 동작을 검증할 때 사용하는 `eval/real_config.local.yaml`을 작성·유지하는 방법을 정리한다.

## 무엇을 만드는 파일인가

`eval/real_config.local.yaml`은 **비공개** 평가 입력이다. 다음을 적는다.

- 어떤 질의를 던지는지
- 어떤 답이 나와야 하는지(혹은 답이 없어야 하는지)
- 어떤 문서·문구가 인용되어야 하는지

이 파일이 있어야 [`scripts/smoke_real.sh`](../scripts/smoke_real.sh) 또는 직접 호출하는 `python3 eval/run_eval.py --config eval/real_config.local.yaml ...`이 gold 비교를 한다. 파일이 없으면 인덱싱과 대표 질의까지만 실행되고 평가는 건너뛴다.

## 안전 원칙 (반드시 지킬 것)

- `eval/*.local.yaml`은 [`.gitignore`](../.gitignore)에 등록되어 있다. 절대 git에 커밋하지 않는다.
- 파일 내용에는 발주기관명, 사업명, 공고 번호, 문서 원문 일부 등 민감정보가 포함될 수 있다. PR 본문, 이슈 코멘트, 스크린샷, 외부 채널에 그대로 붙여 넣지 않는다.
- 평가 결과(`reports/real100/eval_summary.json`)도 같은 이유로 git 추적 대상이 아니다. 공유가 필요하면 sanitized 요약(`docs/real-data/real-data-failure-taxonomy.md`처럼 카테고리별 빈도 + sanitized 증상)으로 옮긴다.
- 공개 README의 성능 표는 실데이터 평가 결과로 갱신하지 않는다([이슈 #47 out-of-scope](real-data/real-data-failure-taxonomy.md)).

## 어디서 시작하나

[`eval/real_config.example.yaml`](../eval/real_config.example.yaml)을 같은 폴더에 `real_config.local.yaml`로 복사한 뒤 채운다.

```bash
cp eval/real_config.example.yaml eval/real_config.local.yaml
```

## 필수 필드

최상위 키:

| 키 | 의미 | 비고 |
|---|---|---|
| `mode` | 평가 모드. 항상 `rag`. | 다른 값은 지원하지 않는다. |
| `description` | 사람이 읽는 한 줄 설명. | 자유롭게. |
| `index_dir` | 사용할 인덱스 경로. | 보통 `data/index/real100`. |
| `answer_policy` | 답변 가능/불가 케이스에 어떤 status를 기대하는지. | example과 동일하게 둔다. |
| `ablation_runs` | 실행할 파이프라인 목록. 최소 1개. | 보통 `full` 하나로 충분. |
| `cases` | 실제 케이스 목록. **이 부분이 핵심.** |  |

각 case의 필수 필드:

| 필드 | 의미 |
|---|---|
| `id` | 케이스 식별자. 다른 케이스와 겹치지 않도록 유니크하게 둔다. |
| `query_type` | `single_doc`, `comparison`, `follow_up`, `abstention` 중 하나. 기존 `multi_doc` 값은 호환 alias로 읽힌다. |
| `query` | 사용자가 입력하는 질의 본문. |
| `expected_doc_ids` | 기대되는 정답 doc_id 목록. abstention 케이스에서는 `[]`. |
| `expected_terms` | 답변 텍스트에 등장해야 하는 핵심 term들. |
| `expected_citation_terms` | 인용 chunk 텍스트에 등장해야 하는 term들. |
| `expected_claim_targets` | 답변 claim의 target(보통 발주기관명/사업명). abstention은 `[]`. |
| `answerable` | `true` = 답이 나와야 함. `false` = abstention 케이스. |

선택 필드(필요할 때만):

- `prior_turns`: 후속 질의(follow_up)에서 직전 턴들을 시뮬레이션할 때 사용. 각 turn은 `query` 필드만 있으면 된다.
- `context_entities`: 평가 시점에 강제로 주입할 발주기관/사업명. 보통은 비워둔다.
- `hardcase_categories`: 카테고리별 슬라이스 메트릭에 포함시키고 싶을 때(예: `["C1", "C5"]`).
- `expected_citation_pages`, `expected_citation_regions`: visual 인덱스에서 페이지·영역 단위 grounding을 검증할 때만.
- `gold_chunk_ids`: chunk-level retrieval 메트릭(recall@k / MRR / nDCG@10)의 정답 chunk 목록. 비워두면 `expected_doc_ids` + `expected_terms` 휴리스틱으로 자동 유도된다([`eval/run_eval.py` `derive_gold_chunk_ids`](../eval/run_eval.py)). 휴리스틱이 잡지 못하는 경우나 동일 doc 내 여러 chunk 중 어느 것이 진짜 정답인지 명시하고 싶을 때만 손으로 적는다. chunk id는 `data/index/index.json`의 `chunks[].chunk_id`(보통 `<doc_id>::chunk-NNN`)에서 그대로 복사한다.
  ```yaml
  gold_chunk_ids:
    - rfp-agency-d-spectrometer-probe::chunk-003
  ```
  대화형으로 후보 chunk를 확인하려면 [`scripts/dump_case_chunks.py`](../scripts/dump_case_chunks.py)를 쓴다.

## doc_id를 어떻게 알아내나

[`scripts/build_index.py`](../scripts/build_index.py) 실행 후 `data/index/real100/ingestion_report.json`에 모든 row의 `doc_id`가 기록된다. 보통 `<공고 번호>-<공고 차수>` 형태이며, 공고 번호가 비어 있을 때만 파일명 stem이 사용된다(자세한 규칙은 [PDF/HWP ingestion](./real-data/real-data-ingestion.md#canonical-doc_id-rule)).

이 파일은 비공개이므로 평가 케이스 작성 외 용도로 외부에 공유하지 않는다.

## 답변 가능(answerable) 케이스 예시

PDF/HWP 인덱스의 한 사업에 대해 사업기간과 사업예산을 묻는 케이스.

```yaml
- id: single_doc_budget_schedule
  query_type: single_doc
  query: "발주기관명 사업명의 사업기간과 사업예산을 알려줘"
  expected_doc_ids:
    - 20240001-0
  expected_terms:
    - "1,200,000,000"
    - "2024-03-01"
  expected_citation_terms:
    - "1,200,000,000"
  expected_claim_targets:
    - "발주기관명"
  answerable: true
```

작성 가이드:

- `query`는 사용자가 실제로 칠 만한 어순으로 둔다. 비교 질의면 `차이`/`비교`/`각각` 중 하나를 포함시키는 것이 좋다.
- `expected_terms`에는 답변 텍스트에 반드시 들어가야 하는 핵심 토큰만 넣는다(금액 숫자, 일자, 명사구). 자유 문장 전체를 넣지 않는다.
- `expected_citation_terms`는 인용 chunk 본문에 그대로 등장해야 하는 토큰이다. metadata-derived claim(예: 사업금액이 metadata에서만 나오는 경우)은 citation chunk에 그 숫자가 없을 수 있으므로 보수적으로 둔다(자세한 사례: [`docs/real-data/real-data-failure-taxonomy.md` C5](./real-data/real-data-failure-taxonomy.md#c5-인용-불일치약한-근거-빈도-412-impact-h-effort-s)).

### 후속 질의(follow_up) 변형

```yaml
- id: follow_up_same_project_schedule
  query_type: follow_up
  prior_turns:
    - query: "발주기관명 사업명에 대해 알려줘"
  query: "그 사업의 일정은?"
  expected_doc_ids:
    - 20240001-0
  expected_terms:
    - "2024-03-01"
  expected_citation_terms:
    - "2024-03-01"
  expected_claim_targets:
    - "발주기관명"
  answerable: true
```

`prior_turns`이 conversation state를 채우고, `query`는 그 위에서 follow-up 동작을 검증한다. C4 카테고리 회복 추적용으로 1~2개 두는 것이 좋다.

## 의도된 abstention 케이스 예시

코퍼스에 없는 사실을 물어 시스템이 정상적으로 답을 거부하는지 본다.

```yaml
- id: abstention_unrelated_topic
  query_type: abstention
  query: "발주기관명 사업명에서 블록체인 인증 요구사항 알려줘"
  expected_doc_ids: []
  expected_terms: []
  expected_citation_terms: []
  expected_claim_targets: []
  answerable: false
```

작성 가이드:

- "그 사업이 다루지 않을 법한 키워드"를 고른다. 단, 코퍼스 어디에도 등장하지 않는 토큰을 골라야 false abstention과 구분된다.
- abstention 케이스가 너무 많으면 `abstention_recall`만 부풀려진다. 답변 가능 케이스 대비 1:3~1:4 비율을 권장한다.

## 케이스 작성 후 검증

1. 인덱스부터 갱신한다.
   ```bash
   python3 scripts/build_index.py \
     --metadata_csv data/data_list.csv \
     --files_dir data/files \
     --output_dir data/index/real100 \
     --embedding_backend hashing
   ```
2. CSV 자체에 column / null / duplicate 문제가 없는지 먼저 본다.
   ```bash
   python3 scripts/validate_data_list.py \
     --metadata_csv data/data_list.csv \
     --files_dir data/files \
     --output_path reports/real100/data_list_validation.json
   ```
   exit code가 0이 아니면 인덱스 빌드 전에 fix한다(이슈 [#51](https://github.com/hskim-solv/BidMate-DocAgent/issues/51)).
3. gold를 적용해 평가한다.
   ```bash
   python3 eval/run_eval.py \
     --config eval/real_config.local.yaml \
     --index_dir data/index/real100 \
     --output_dir reports/real100
   ```
4. `reports/real100/eval_summary.json`의 `by_query_type`과 `case_results`를 확인한다. 슬라이스별 빈도와 실패 패턴은 [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md)와 동일한 분류 체계로 정리하면 트래킹이 쉽다.

## 자주 막히는 지점

- **`expected_doc_ids`가 틀려서 정답인데도 fail로 잡힘** — `ingestion_report.json`의 doc_id를 그대로 복사한다. 공고 번호 차수(`0`/`0.0`)가 잘 맞는지 한 번 더 본다.
- **`expected_terms`에 너무 긴 문장을 넣어서 정답이 fail로 잡힘** — 답변 생성 형식과 어순이 달라서이다. 명사·숫자·일자 단위로 쪼갠다.
- **abstention 케이스가 false negative로 잡힘** — 그 키워드가 다른 row의 `텍스트`에 우연히 등장하는 경우이다. 코퍼스에 정말 없는 키워드인지 `grep` 한 번 해본다.
- **follow_up이 abstain으로 빠짐** — 현재 구현은 1단계 follow-up까지만 강하게 처리한다(C4-1, 이슈 [#57](https://github.com/hskim-solv/BidMate-DocAgent/issues/57)). 2단계 implicit chain은 보수적으로 케이스에서 빼두는 것을 권장한다.

## Annotation log — `gold_chunk_ids`

[이슈 #175](https://github.com/hskim-solv/BidMate-DocAgent/issues/175) 일환으로 `eval/config.yaml`의 답변 가능(answerable) 케이스 중 휴리스틱 blind-spot 위험이 가장 높은 10건에 대해 `gold_chunk_ids`를 사람이 직접 확인하고 명시했다.

- **Annotator**: hskim (`times21c@gmail.com`)
- **Date**: 2026-05-11
- **Method**: [`scripts/dump_case_chunks.py`](../scripts/dump_case_chunks.py)로 `expected_doc_ids`에 속한 chunk를 모두 dump하고 본문을 읽어 정답 chunk를 1건 선택.
- **Cases (10)**:
  - `follow_up` (8건, all answerable): `follow_up_schedule`, `follow_up_b_deliverables`, `follow_up_c_response_target`, `follow_up_common_evaluation`, `follow_up_a_team`, `follow_up_c_operation_metrics`, `follow_up_state_a_security`, `follow_up_state_multi_step_a_deliverables`.
  - `single_doc` chunk-boundary 프로브 (2건): `chunk_probe_external_audit_period` (chunk-002), `chunk_probe_report_storage` (chunk-003). agency-D 문서는 3-chunk로 분할되어 있어 단일 doc 내 chunk 선택이 자명하지 않은 유일한 케이스.
- **Result**: 위 10건에서 휴리스틱이 선택한 gold와 사람 annotation이 완전히 일치(per-case `chunk_recall@5`/`MRR`/`nDCG@10` 변동 없음). `follow_up_state_a_security` / `follow_up_state_multi_step_a_deliverables`의 R@5=0은 retriever가 multi-turn 컨텍스트에서 chunk를 가져오지 못하는 **진짜 retrieval 결함**임을 사람 gold로 재확인 (이슈 [#57](https://github.com/hskim-solv/BidMate-DocAgent/issues/57) C4 대응 추적).
- **Skipped**: `abstention` 슬라이스 (9건) 및 `follow_up_state_ambiguous_clarification` — `answerable: false`라 정답 chunk가 존재하지 않음. 강제 annotation은 ADR 0003 abstention 계약을 왜곡한다.

## 참고

- [PDF/HWP ingestion](./real-data/real-data-ingestion.md)
- [실데이터 실패 분류 및 우선순위 백로그](./real-data/real-data-failure-taxonomy.md)
- [답변 정책](./agentic/answer-policy.md)
- [Citation grounding evaluation](./eval/citation-grounding-eval.md)
