# Phase 4 — query ↔ metadata coverage 분석

index_dir=`data/index/real100_kordoc` · eval_config=`eval/real_config.local.yaml` · commit `9af8d73a63` · n_answerable=118

Phase 4 oracle ceiling(모든 query 에 gold 메타데이터)과 현실 ceiling(query 에서 도출 가능한 메타데이터만) 사이의 격차를 정량화한다. 버킷은 상호 배타적이며, 우선순위는 metadata-identifiable → content-query → underspecified 이다.

## query 의미 분류(semantic classes)

| 분류 | n | % | gold 존재 | \|gold\| 중앙값 | \|gold\| 평균 |
|---|---|---|---|---|---|
| metadata-identifiable | 40 | 33.9% | 37/40 | 5 | 11 |
| content-query | 77 | 65.3% | 77/77 | 6 | 18.5 |
| underspecified | 1 | 0.8% | 0/1 | 0 | 0.0 |

## 해석(interpretation)

* **metadata-identifiable (33.9%)**: gold agency/project 가 query 와 char-4gram 을 공유한다. 메타데이터 routing 이 현실적으로 작동할 수 있는 cohort 이며 — 메타데이터 routing 의 현실 ceiling 은 oracle 의 전체 coverage 가 아니라 이 비율로 bound 된다.
* **content-query (65.3%)**: agency/project 신호는 없지만 gold 청크가 존재한다 (77/77 에 gold 있음). 프로젝트 *내부* 콘텐츠(기능/스펙/요구사항)를 묻는다. content matching 은 이들에 도달하나, 메타데이터 routing 은 필터링할 대상이 없다. 여기서 gold 집합이 오히려 *더 크다*(중앙값 6 vs metadata-identifiable 5) — 콘텐츠 답변이 더 많은 청크에 걸친다.
* **underspecified (0.8%)**: 메타데이터 신호도 없고 도출 가능한 gold 도 없다 — context-dependent(follow_up)이거나 어떤 retrieval 로도 해결 못 할 만큼 모호하다. 미미하므로 숨은 retrieval-불가 ceiling 은 없다.

**Headline**: oracle ceiling(+0.22 recall@10)은 counterfactual 이다 — 메타데이터를 전혀 언급하지 않는 65.3% 의 query 에도 gold 메타데이터를 썼다. 메타데이터 routing 은 ~33.9% metadata-identifiable cohort 로 bound 된 좁은 add-on 이며; 주된 retrieval lever 는 여전히 content matching(Phase 2 chunking + Phase 3 ranking mode)이다.

## 방법(method)

* 메타데이터 신호에 **char-4gram overlap**(공백 무시)을 쓴다. 한국어 복합명사는 공백으로 구분되지 않아 토큰 overlap 이 과소 계산하기 때문이다(예: "대학재정정보시스템").
* **gold** = `eval.scorers.chunk_metrics.derive_gold_chunk_ids` (doc_id ∈ expected_doc_ids 이고 청크 텍스트가 expected_term 을 포함).
* 결정적(deterministic): 동일 index + eval_config → byte-identical 출력. run 헤더의 1줄 CLI 로 재현.
