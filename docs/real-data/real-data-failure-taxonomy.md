# 실데이터 실패 분류 및 우선순위 백로그

이슈 [#47](https://github.com/hskim-solv/BidMate-DocAgent/issues/47)의 결과물. real100 평가셋에서 발견된 실패 모드를 6 카테고리로 분류하고, 후속 작업의 우선순위를 정한다. 본 문서는 평가 산출물(`reports/real100/eval_summary.json`)을 기반으로 작성하며, 원본 RFP 문서, 발주 기관/사업명, 질의 원문은 포함하지 않는다.

## 배경

저장소에는 이미 공개 합성 baseline, private hard-case 스캐폴딩, 재현 가능한 smoke harness, 리뷰어용 문서가 정비되어 있다. 다음 단계의 고가치 작업은 (a) 실데이터에서 어디가 실제로 깨지는지 검증하고, (b) 그 실패를 코드 경로에 매핑한 뒤, (c) impact·effort로 정렬된 백로그를 만드는 것이다. 본 문서는 그 결과물이며, 실제 fix 구현은 후속 이슈로 분리한다.

## 분석 방법

- **평가셋**: 실데이터 인덱스(`data/index/real100`, 100 docs, gitignored) 대상으로 21 case(기존 6 + 신규 15 probe). probe set은 6 카테고리에 ~2-3건씩 분포하도록 설계.
- **실패 판정**:
  - 답변 가능 케이스에서 `accuracy`/`groundedness`/`citation_precision`/`answer_format_compliance` 중 하나라도 0.
  - abstention 케이스에서 `expected_answer_status` ≠ `answer_status`.
- **분류 신호**: `case_results`의 `retry_trigger_reasons`, `context_resolution_status`, `doc_match`, `term_match`, `citation_term_match`, `citation_doc_precision`.
- **재현**: `python eval/run_eval.py --config eval/real_config.local.yaml --index_dir data/index/real100 --output_dir reports/real100`. 입력(`data/files/`, `data/data_list.csv`, `eval/real_config.local.yaml`)과 출력(`reports/real100/`)은 git 추적 대상이 아니다.
- **redaction**: 본 문서에는 카테고리별 빈도·sanitized 증상·코드 위치만 인용한다. 실제 doc_id, 발주기관명, 사업명, 질의 원문은 모두 `eval/real_config.local.yaml`(gitignored)에만 둔다.

## 분석 중 발견된 회귀 (별도 핫픽스)

실패 분석 사전 단계에서 두 가지 코드 회귀를 발견하여 본 PR에 함께 포함했다.

| ID | 위치 | 증상 | 수정 |
|---|---|---|---|
| R1 | `rag_core.py:2664` | `retry_count > 0` + `len(stage_attempts) < 2`일 때 `IndexError`로 `eval/run_eval.py` 실행 자체가 실패 | guard 조건에 `len(stage_attempts) >= 2` 추가 |
| R2 | `rag_core.py:2596-2615` | 머지 충돌 처리 누락으로 retrieval loop 본문(`retrieve()`/`verify_evidence()`/`stage_attempts.append()`)이 통째로 사라져 모든 답변 가능 질의가 abstain | b0727db1 시점의 본문을 복원 |

R2는 `eval/run_eval.py`로 detection 가능했으나 회귀 테스트가 없어 머지 후에도 잡히지 않았다. 회귀 가드(answerable single-doc smoke 케이스에서 evidence가 비어있지 않음을 assert하는 테스트)를 후속 백로그 P0에 등록한다.

## 통합 실패 분류

이슈 #47이 제시한 6 카테고리를 [`docs/failure-cases.md`](failure-cases.md)의 9 항목과 통합하여 다음과 같이 정리한다.

| ID | 카테고리 | 기존 failure-cases.md 매핑 | 주요 신호 |
|---|---|---|---|
| C1 | 메타데이터/엔터티 정규화 | #1 | retrieval miss + retry 후에도 `topic_not_grounded` |
| C2 | 발주기관/사업명 모호성 | #1 일부 + 신규 | 동일 substring 다수 후보 → 잘못된 후보 fallback |
| C3 | 청크 경계/섹션 오류 | #7, #8 | (real100에서는 retrieval miss에 가려 단독 evidence 미수집) |
| C4 | 후속 질문 문맥 소실 | #3 | `context_resolution=resolved`이지만 retrieval에서 entity 누락 |
| C5 | 인용 불일치/약한 근거 | #4, #5, #9 | answer term ≠ citation chunk text → `citation_term_match=False` |
| C6 | 잘못된 abstention | 신규 | 답변 가능 질의가 abstain (12건 중 9건이 이 패턴) |

OCR/parser-stage 실패는 `eval/run_parser_eval.py`의 `FAILURE_TAXONOMY`로 분리 추적하며, 본 문서에서는 다시 분류하지 않는다.

### 케이스별 카테고리 매핑 (sanitized)

| 익명 ID | 1차 카테고리 | 패턴 요약 |
|---|---|---|
| P-01 | C1 | 부분 substring 발주기관명 → entity 정규화는 성공, retrieval miss |
| P-02 | C1 | 영문 약어 사업명 → 정규화는 성공, retrieval miss |
| P-03 | C5 | 학교명 약어 → retrieval/answer 모두 정답, citation chunk에 정답 term 부재 |
| P-04 | C2 | 광역 substring(여러 산하 기관과 충돌) → 잘못된 후보로 verifier 실패 |
| P-05 | C2 | 동일 발주기관의 ≥2 사업 → clarification 없이 abstain |
| P-06 | C1 | 다중 fact 동시 요청(금액 + 일정) → entity는 normalize되나 retrieval miss |
| P-07 | C5 | retrieval/answer 모두 정답, citation chunk에 정답 term 부재 |
| P-08 | C4 | 1단계 후속(`그 사업의 X`) → context resolved지만 query에 entity 미주입 |
| P-09 | C4 | cross-doc switch(`그러면 다른 사업도`) → context를 not_needed로 분류, retrieval miss |
| P-10 | C4 | 2단계 implicit chain → context_resolution=`not_needed from none`, clarification 미발화 |
| P-11 | C5 | 의역 질문(기간을 일수 단위 환산형으로 묻는 형태) → literal term 부재, retrieval miss |
| P-12 | C5 | 다중 fact aggregate(여러 metadata field를 한 번에 정리해 달라는 요청) → anchor 토큰 분산, retrieval miss |
| P-13~15 | C6 (정답) | out-of-corpus / near-miss 발주기관 → 모두 올바르게 abstain |

기준선 6 case는 모두 supported(P-base-1~5) 또는 정상 abstention(P-base-6)으로 통과한다. 기준선이 통과하므로 R2 핫픽스의 회귀-수정 효과는 확인된다.

## 카테고리별 분석

### C1. 메타데이터/엔터티 정규화 (빈도 3/12, Impact H, Effort M)

**사용자 관점 증상**: 발주기관명을 부분 substring 또는 영문 약어 형태로 입력하면 시스템이 답을 못 찾는다. 같은 케이스를 풀네임으로 다시 질의하면 정상 답변이 돌아온다.

**추정 원인**: `analyze_query`([rag_core.py:1392](../../rag_core.py#L1392))는 metadata target과의 부분 매칭으로 정규화된 후보(verifier "확인 필요 대상"에 등장)는 산출하지만, 그 후보가 metadata filter 또는 dense retrieval의 시드로 충분히 활용되지 않는다. retry 단계의 strict→reduced→relaxed 완화가 발생해도 정규화 결과가 retrieval query에 재주입되지 않는다.

**코드 변경 후보**:
- [rag_core.py:280](../../rag_core.py#L280) — entity normalization 사전 확장
- [rag_core.py:1392](../../rag_core.py#L1392) — `analyze_query`의 `matched_doc_ids` 산출
- [rag_core.py:1222](../../rag_core.py#L1222) — `metadata_filters_from_matches`
- [rag_core.py:1550](../../rag_core.py#L1550) — `retrieve` 호출에서 normalized entity를 retrieval query에 결합

**수용 조건 힌트**: 부분 substring 발주기관명 + 사업 키워드 조합 단일 단계에서 `doc_match=True`.

### C2. 발주기관/사업명 모호성 (빈도 2/12, Impact M, Effort M)

**사용자 관점 증상**: 동일 substring을 가진 여러 발주기관이 코퍼스에 있을 때(예: 광역시 본청 vs 산하 자치구), 또는 한 발주기관에 다수 사업이 있을 때 retrieval 자체가 실패하고 clarification도 발생하지 않는다. **(부분 해결, issue #72)** single-turn metadata ambiguity는 `metadata_ambiguity_details` (rag_core.py:1313)가 이미 검출하고 `make_metadata_clarification_result` (rag_core.py:3029)가 clarification 응답을 만든다. #72에서 clarification 메시지를 `agency · project (doc_id)` 형식으로 강화해 사용자가 후보 사업명을 직접 보고 재질의할 수 있게 했다. 합성 표면 probe set: `data/raw/rfp_agency_e_water_quality_*.json` + `eval/config.yaml`의 `single_turn_ambiguity_water_*` 케이스.

**추정 원인**: ~~`resolve_conversation_context`는 conversation state 기반 모호성만 처리하고, 단일 질의 안에 내재된 entity 모호성은 처리하지 않는다.~~ **(검출 자체는 이미 동작; 메시지 가독성과 합성 회귀 가드만 부족했음)**. 단, real-data에서는 metadata 매칭이 노이즈가 많아 0.05 confidence delta를 통과 못 해 verifier 단계까지 도달하는 케이스가 있을 수 있음 — scoring 개선은 후속 작업.

**코드 변경 후보**:
- ~~[rag_core.py:1301](../../rag_core.py#L1301) — `resolve_conversation_context` 확장(single-turn ambiguity)~~ **(불필요, #72에서 확인 — 검출은 별도 함수에서 이미 동작)**
- [rag_core.py:1313](../../rag_core.py#L1313) — `metadata_ambiguity_details`의 0.05 confidence_delta 튜닝(real-data noisy matching에 대응)
- [rag_core.py:2069](../../rag_core.py#L2069) — `answer_status`에 명시적 `clarification` status 추가(#72에서는 `insufficient + code=metadata_ambiguity_clarification`로 surface; 별도 status로 격상은 ADR 0003 contract 변경이라 보류)

**수용 조건 힌트**: 동일 발주기관에 ≥2 사업이 있는 질의에서 `supported` 또는 `clarification`으로 응답, abstain 없음. **(공개 합성 표면 충족, real-data 측정은 후속 작업)**

### C3. 청크 경계/섹션 오류 (직접 evidence 없음, Impact M, Effort M)

**사용자 관점 증상**: real100 probe set에서는 C1/C2 retrieval miss에 가려 단독으로 분리 관측되지 않았다. 합성 평가셋과 visual_v2 parser eval에서 별도 추적 중([docs/failure-cases.md](./failure-cases.md) #7-8, [docs/chunking-diagnostics.md](../retrieval/chunking-diagnostics.md), `eval/run_parser_eval.py`).

**추정 원인**: 미관찰. real100에서는 선행 retrieval miss(C1/C2)가 청크 단위 분석에 도달하기 전에 abstain을 유발하므로 청크 경계 영향 단독 분리가 불가능. 합성 set에서는 section_boundary_missing/table_cell_mismatch가 parser FAILURE_TAXONOMY로 추적된다.

**후속 작업**: C1/C2 fix 후 다시 측정해야 단독 영향이 보인다. 청크 경계 의도를 분리 검증할 probe(예: 답이 인접 chunk 경계를 가로지르는 케이스, 답이 heading-only chunk에만 존재하는 케이스)를 별도 설계 필요. **(부분 진행)** 합성 표면에서는 issue #73이 [`docs/chunking-diagnostics.md` §"Chunk-boundary probe set"](../retrieval/chunking-diagnostics.md)에 3-case probe set과 `total_chunks_in_section` 진단 필드를 추가했다 — `chunk_seq_in_section / total_chunks_in_section` 조합으로 chunking failure(C3)를 upstream miss(C1/C2)와 evidence 단계에서 분리 가능. real-data 단독 분리는 여전히 C1/C2 후속 작업이 필요.

**잠재적 코드 변경 후보**:
- [rag_core.py:712](../../rag_core.py#L712) — `split_section_text`
- [rag_core.py:809](../../rag_core.py#L809) — `build_chunks`
- [rag_core.py:824](../../rag_core.py#L824) — `make_chunk` (chunk_seq_in_section 활용)

### C4. 후속 질문 문맥 소실 (빈도 3/12, Impact H, Effort S)

**사용자 관점 증상**: 단순 1단계 후속 질문(`그 사업의 X`)에서 conversation state는 정상 활성화되나(`context_resolution=resolved`) retrieval은 빈 evidence를 반환. 2단계 이상의 implicit chain에서는 context resolution 자체가 비활성화(`status=not_needed from none`)되며 clarification도 발화되지 않는다. cross-doc switch(`그러면 다른 사업도`) 패턴은 시스템이 새 entity를 인식하지 못한 채 이전 context로 retrieval을 시도해 실패.

**추정 원인**:
- ~~`resolve_conversation_context`는 활성 entity를 추출해 `effective_context_entities`로 넘기지만, retrieval query 텍스트는 원본 질의 그대로 사용한다.~~ **(부분 해결, issue #71)** path 1 (explicit `context_entities`)도 path 2 (conversation_state)와 동일하게 entity prefix를 retrieval query에 주입하도록 통합. dense / lexical retriever가 anchor를 회복한다. 동일 helper(`inject_entities_into_query`)로 두 path가 대칭이 되어 회귀 단순화.
- 다단계 implicit chain은 conversation state turn 간 entity carry-over 로직이 깊이 1까지만 처리되는 것으로 보인다. (#71에서 미해결, 후속 작업)
- cross-doc switch는 `analyze_query`가 새 entity를 매칭하면서도 이전 turn의 evidence가 우선 활용되어 새 doc으로 재정렬되지 않는다. (#71에서 미해결, 후속 작업)

**코드 변경 후보**:
- ~~[rag_core.py:1301](../../rag_core.py#L1301) — resolved entity를 `retrieval_query`에 inline~~ **(완료, #71)**
- [rag_core.py:387](../../rag_core.py#L387) — `empty_conversation_state` turn carry-over 깊이
- [rag_core.py:2574](../../rag_core.py#L2574) — 두 번째 `analyze_query` 호출 시 effective_context_entities 결합 강화 (deprecated by #71의 query string 주입; turn carry-over 깊이가 핵심 후속 작업)

**수용 조건 힌트**: `그 사업의 X` 형태 1단계 후속에서 `doc_match=True`. 2단계 이상 implicit chain은 `needs_clarification`로 폴백.

### C5. 인용 불일치/약한 근거 (빈도 4/12, Impact H, Effort S)

**사용자 관점 증상**: 답변 텍스트가 정답 term을 포함하고(`term_match=True`) 정답 doc을 인용하나(`citation_doc_precision=1.0`), citation으로 지목된 chunk 본문에 그 term이 직접 등장하지 않는다(`citation_term_match=False`). 답변은 supported지만 evidence text가 약한 케이스. 직접 인용이 아닌 의역(예: 기간을 일수로 환산해 묻는 형태) 또는 다중 fact aggregate 형태(여러 metadata field를 한 번에 정리해 달라는 요청)에서는 retrieval 자체가 anchor 토큰을 잃고 실패.

**추정 원인**: `make_citation`([rag_core.py:2052](../../rag_core.py#L2052))이 doc_id 단위로만 매칭을 검증하고, citation으로 지목한 chunk 본문에 claim term이 실제로 존재하는지는 확인하지 않는다. 답변 생성기는 metadata에 있는 사업금액·사업기간을 claim에 사용하지만, citation은 본문 chunk를 가리키는 패턴. 의역/aggregate 질문은 verifier가 literal term 매칭에 의존해 실패.

**코드 변경 후보**:
- [rag_core.py:1843](../../rag_core.py#L1843) — `verify_evidence`에 chunk 본문 ↔ claim term 정렬 검증 추가
- [rag_core.py:2052](../../rag_core.py#L2052) — `make_citation`에서 chunk text와 claim text 정렬 검증
- [rag_core.py:2032](../../rag_core.py#L2032) — `make_claim`에서 metadata-derived claim과 chunk-derived claim 분리

**수용 조건 힌트**: C5 4 케이스에서 `citation_term_match=True` 달성, 또는 metadata-only claim의 경우 citation을 metadata reference로 명시.

### C6. 잘못된 abstention (빈도 9/12, Impact H, Effort M)

**사용자 관점 증상**: real100 12 실패 중 9건이 "답변 가능했어야 할 질의가 abstain"으로 끝났다. retry_trigger_reason은 일관되게 `topic_not_grounded × 2`(strict + relaxed 두 단계 모두 거부). 이는 C1/C2/C4 retrieval 약점이 곧장 false abstention으로 직결되는 것을 의미한다. 반대로 의도된 abstention 3 case(P-13~15)는 모두 올바르게 abstain — abstention 자체는 robust하나 너무 자주 발화된다.

**추정 원인**: `verify_evidence`([rag_core.py:1843](../../rag_core.py#L1843))의 topic grounding 기준이 너무 엄격해 부분 매칭/약한 매칭 evidence를 모두 거절. relaxed 단계에서도 evidence 임계값이 strict와 거의 동일하게 작동.

**코드 변경 후보**:
- [rag_core.py:1843](../../rag_core.py#L1843) — `verify_evidence`에 partial topic grounding 모드
- [rag_core.py:1222](../../rag_core.py#L1222) — `metadata_filters_from_matches` relaxed 단계 임계값 완화
- [rag_core.py:2069](../../rag_core.py#L2069) — `answer_status`의 `partial` 활용 폭 확대

**수용 조건 힌트**: 본 카테고리 9건 중 절반 이상이 `partial` 또는 `supported`로 회복. 의도된 abstention 3 case(P-13~15)는 그대로 abstain 유지(false negative 방지).

## 우선순위 백로그

| 우선순위 | ID | 제목 | 카테고리 | Impact | Effort | 코드 후보 |
|---|---|---|---|---|---|---|
| P0 | R2-test | retrieval loop 회귀 테스트 추가 | (인프라) | H | S | `tests/` 신규 — answerable single-doc 1건에서 evidence 비어있지 않음 assert |
| P0 | C6-1 | 부분 매칭 evidence 허용으로 false abstention 감축 | C6 | H | M | `rag_core.py:1843`, `:1222` |
| P1 | C5-1 | citation chunk text와 claim term 정렬 검증 | C5 | H | S | `rag_core.py:2052`, `:1843` |
| P1 | C4-1 | resolved entity를 retrieval query에 inline 결합 | C4 | H | S | `rag_core.py:1301`, `:2574` |
| P1 | C1-1 | 부분 substring/약어 entity의 retrieval 시드 보강 | C1 | H | M | `rag_core.py:280`, `:1392`, `:1222` |
| P2 | C2-1 | single-turn entity 모호성에서 clarification status 도입 | C2 | M | M | `rag_core.py:1301`, `:2069` |
| P2 | C5-2 | metadata-derived claim의 citation을 metadata reference로 분리 | C5 | M | M | `rag_core.py:2032`, `:2052` |
| P3 | C4-2 | 2단계 이상 implicit chain → `needs_clarification` 폴백 | C4 | M | S | `rag_core.py:1301`, `:387` |
| P3 | C3-1 | chunk boundary 시나리오 별도 probe 설계 + 진단 강화 | C3 | M | M | `docs/chunking-diagnostics.md`, `rag_core.py:712` |

각 항목은 본 PR 머지 후 후속 GitHub 이슈 stub로 분리해 추적한다(본 PR 범위 외).

Effort: **S**(≤1일), **M**(1-3일), **L**(1-2주). Impact: **H**(카테고리 단위 회복), **M**(엣지 케이스 회복), **L**(품질 정리).

## 한계와 후속 작업

- 본 분석은 21 case(6 baseline + 15 probe) 기준. C3(청크 경계) 단독 evidence는 C1/C2 retrieval miss에 가려져 수집 못함 — C1/C2 fix 후 재측정 필요.
- 발견된 회귀 R1·R2는 본 PR에서 핫픽스했으나 **회귀 테스트는 P0 backlog로 분리 등록**. 머지 직후 별도 PR로 추가 권장.
- C6(false abstention)와 C1/C2/C4(retrieval miss)는 강한 상관: C6의 일차 원인은 보통 다른 카테고리의 retrieval miss. 후속 fix 시 C6 단독 측정이 어렵고 다른 카테고리 회복과 함께 평가해야 함.
- 본 문서가 인용한 실데이터 평가 결과는 git에 포함되지 않으며, 재현은 위 [분석 방법](#분석-방법) 섹션의 명령으로 가능.
- 공개 README의 성능표는 본 분석 결과로 업데이트하지 않는다(이슈 #47 out-of-scope 조건).

## 참고

- 기존 실패 카테고리: [docs/failure-cases.md](failure-cases.md)
- parser-stage 실패 분류: `eval/run_parser_eval.py`의 `FAILURE_TAXONOMY` ([failure-cases.md](failure-cases.md)에서 참조)
- 실데이터 ingestion 흐름: [docs/real-data-ingestion.md](real-data-ingestion.md)
- private hard-case benchmark 운영 기준: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- 청크 진단: [docs/chunking-diagnostics.md](../retrieval/chunking-diagnostics.md)
- 답변 정책: [docs/answer-policy.md](../agentic/answer-policy.md)
