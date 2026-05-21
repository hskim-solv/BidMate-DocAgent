# Balanced Comparison Ranking

## 문제(problem)

비교(comparison) 쿼리(예: "기관 A와 기관 B의 보안 요구사항 차이는?")의 경우 기존 검색 컷은 단순한 전역 top-k 정렬이었다. 한 비교 대상의 어휘가 질문을 지배하거나 코퍼스의 chunk 수가 비대칭일 때, top-k 슬롯 전부가 단일 문서로 채워질 수 있다. 하위 영향:

- 검증기가 `missing_comparison_doc` / `missing_comparison_entity` 를 표시하고 재시도를 유발한다(추가 latency).
- 재시도도 실패하면(편향이 구조적이므로) 답변은 부분(partial) / 한쪽으로 치우친(one-sided) 비교가 된다.

## 접근(approach)

커버리지 인지(coverage-aware) top-k 컷을 `query_type == "comparison" AND target_count >= 2` 에 게이팅하여 **점수 계산 후 `retrieve()` 내부에서** 적용한다. 컷은:

1. 비교 대상별로 점수가 가장 높은 chunk 를 `min_per_target` 개 고른다.
2. 남은 슬롯을 전역 점수 정렬 후보로 채운다.
3. 반환 리스트에서 점수 내림차순을 보존한다.

선택은 검증기가 근거를 보기 **전에** 일어나므로, 공정한 pool 은 허위 재시도를 줄이면서도 실제로 대상이 부재한 케이스는 여전히 보류(abstain)할 수 있게 한다.

`select_supporting_evidence`(entity 그룹화, 답변 시점에 사용)는 변경되지 않으며 하위 안전망 역할을 한다.

## 설정(configuration)

이 동작은 파이프라인 preset 에 부착된 `comparison_balance` 설정 번들로 게이팅된다:

```python
DEFAULT_COMPARISON_BALANCE = {
    "enabled": True,
    "min_per_target": 1,   # guaranteed slots per comparison target
    "k_per_target": 3,     # adaptive top_k per target
    "headroom": 2,         # extra slots beyond k_per_target * target_count
    "max_top_k": 12,       # absolute ceiling on adaptive top_k
}
```

- `agentic_full` 은 이 설정을 활성화한 채 출하된다.
- `naive_baseline` 은 이 키를 포함하지 **않는다** — 기준선 검색 경로는 변경되지 않는다.
- 호출별 비활성화는 `run_rag_query(..., comparison_balance={"enabled": False})` 로 한다.

활성화되고 `target_count >= 2` 일 때, `make_plan` 은 다음을 설정한다:

```text
top_k = clamp(k_per_target * target_count + headroom, 6, max_top_k)
```

2개 대상의 경우: `top_k = clamp(8, 6, 12) = 8`. 3개 대상의 경우: `top_k = clamp(11, 6, 12) = 11`.

## 대상 식별(target identification)

`comparison_targets_for_analysis(analysis)` 에서:

- `analysis["matched_doc_ids"]` 항목이 2개 이상이면, balancing 은 `chunk.doc_id` 로 그룹화한다.
- 그렇지 않고 `analysis["entities"]`(매치된 기관)가 2개 이상이면, balancing 은 `chunk.agency` 로 그룹화한다.
- 그 외에는 헬퍼가 `scored[:top_k]` 와 동등한 no-op 이다.

doc_id 는 고유하므로 우선되며, agency fallback 은 분석기가 기관은 매치했으나 doc_id 는 매치하지 못한 케이스를 처리한다.

## 진단(diagnostics)

쿼리가 대상 2개 이상의 비교일 때마다, balancing 활성화 여부와 무관하게 plan dict 에 `comparison_coverage` 필드가 추가된다:

```json
{
  "comparison_coverage": {
    "targets": ["asym-agency-a", "asym-agency-b"],
    "target_field": "doc_id",
    "before": {"asym-agency-a": 6, "asym-agency-b": 1},
    "after":  {"asym-agency-a": 7, "asym-agency-b": 1},
    "balanced": true,
    "min_per_target": 1
  }
}
```

이는 `diagnostics.filter_stage_attempts[].comparison_coverage` 에도 표면화되어 stage 별 재시도를 디버깅할 수 있다.

## Eval 지표(metric)

`eval/run_eval.py` 는 expected doc_id 가 2개 이상인 `query_type == "comparison"` 케이스마다 두 개의 커버리지 지표를 계산한다. 여전히 `multi_doc` 를 쓰는 구(舊) config 는 `comparison` slice 로 정규화된다:

- `comparison_target_recall` = `|expected_doc_ids ∩ evidence_doc_ids| / |expected_doc_ids|` — 최종(FINAL) 근거(`select_supporting_evidence` topic-grounding trim 이후)에 대해 측정. 검색 커버리지뿐 아니라 topic-grounding 실패에도 민감하다.
- `comparison_pool_recall` = `|expected_doc_ids ∩ pool_doc_ids| / |expected_doc_ids|` — balance 이후 검색 pool(`plan.comparison_coverage.after` 에서 읽음)에 대해 측정. balancing 의 효과를 하위 검증기/topic trimming 으로부터 분리한다.

둘 다 `metric_block` 에서 평균값과 `*_full_coverage_rate`(recall == 1.0 인 비율)로 집계된다. 이들은 `by_slice["comparison"]` / `by_query_type["comparison"]` 와 `by_hardcase_category["one_sided_comparison"]`(또는 해당 케이스가 있는 임의의 slice) 아래에 나타나므로 핵심 수치가 깔끔하게 유지된다.

`comparison_pool_recall` 은 balanced top-k 컷이 제 역할을 하는지에 대한 가장 깔끔한 신호이고, `comparison_target_recall` 은 balancing 과 topic grounding 둘 다에 의존하는 사용자 가시(user-visible) 답변 품질 신호다.

## 도움이 되는 경우

- **비대칭 어휘**: 두 대상이 모두 관련 있음에도, 질문 표현이 한 대상의 도메인 용어와 매치된다. 예: "품질관리 관점에서 기관 A와 기관 B의 차이는?" ("품질관리" 는 기관 A 에 많고, 기관 B 는 "데이터 거버넌스" / "drift" 를 쓴다).
- **비대칭 chunk 수**: 한 문서는 짧은 chunk 가 많고, 다른 문서는 적거나 / 긴 chunk 를 갖는다.
- **비대칭 metadata 신호 강도**: 한 대상은 고신뢰 metadata 매치를 갖고, 다른 대상은 약한 fuzzy 매치만 갖는다.

## 도움이 되지 않는 경우

- **대상이 코퍼스에 실제로 부재**: balancing 은 근거를 합성할 수 없다. 검증기는 여전히 `missing_comparison_doc` 를 표시하고 답변은 보류한다. `tests/test_fuzzy_retrieval.py::test_partial_comparison_keeps_supported_claims_and_missing_target` 로 고정된다.
- **single-doc 및 follow-up 쿼리**: `query_type == "comparison" AND target_count >= 2` 게이트를 통한 명시적 no-op.
- **실제로 한쪽으로 치우친 답변**: 예: "기관 A의 …" — 이들은 비교 분기에 절대 도달하지 않는다.

## 비활성화 방법

- **호출별**: `run_rag_query(..., comparison_balance={"enabled": False})`. plan 은 관측성(observability)을 위해 여전히 `comparison_coverage` 를 기록한다.
- **전역**: `naive_baseline` preset 을 고른다. 기준선 preset 은 `comparison_balance` 키가 없으므로 balancing 이 구조적으로 꺼져 있다.

## 구현 포인터

- `rag_core.py::DEFAULT_COMPARISON_BALANCE` — 기본 config.
- `rag_core.py::comparison_targets_for_analysis` — 대상 추출.
- `rag_core.py::apply_comparison_balance` — balanced 컷.
- `rag_core.py::make_plan` — adaptive top_k.
- `rag_core.py::reassemble_parent_sections` — hierarchical-mode 연결.
- `rag_core.py::summarize_stage_attempt` — stage 별 진단.
- `eval/run_eval.py::score_case` / `metric_block` — eval 지표.
- `tests/test_fuzzy_retrieval.py::BalancedComparisonRerankTest` — 커버리지 테스트.
