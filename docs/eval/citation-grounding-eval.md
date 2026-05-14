# Citation grounding evaluation

이 문서는 citation 평가 기준을 정리한다. 기존 `citation_precision`은 whole-answer 문서/근거 term 중심 지표로 유지하고, `claim_citation_alignment`는 claim마다 citation chunk가 해당 claim을 직접 지지하는지 별도로 측정한다. visual parsing v2에서 page/bbox metadata가 있을 때는 page/region grounding 지표도 추가 계산한다.

## 목적
- 답변 citation이 올바른 문서뿐 아니라 올바른 page/region을 가리키는지 분리해 측정한다.
- whole-answer citation 품질과 claim-level citation drift를 분리한다.
- text v1과 visual v2를 비교할 때 region metadata가 없는 경우와 잘못 정렬된 경우를 구분한다.
- downstream citation drift를 parser-stage `bbox_missing`, `bbox_misaligned` 오류와 연결해 해석한다.

## Eval case fields
`eval/*.yaml`의 case는 기존 필드에 더해 아래 선택 필드를 가질 수 있다. 필드가 없으면 page/region grounding 지표는 `null`로 남고 기존 QA 평가는 그대로 동작한다.

```yaml
expected_citation_pages:
  - doc_id: parser-fixture-doc
    pages: [1]

expected_citation_regions:
  - doc_id: parser-fixture-doc
    page_number: 1
    bbox: [10, 40, 280, 100]
    min_iou: 0.5

expected_claim_citations:
  - target: 기관 A
    expected_doc_ids: [rfp-agency-a-ai-quality]
    expected_terms: ["보안 통제", "로그"]
```

`expected_citation_pages`는 citation의 `page_span` 또는 `regions[*].page_number`와 비교한다. `expected_citation_regions`는 같은 `doc_id`와 `page_number`의 `regions[*].bbox`를 gold bbox와 IoU로 비교하며, `min_iou` 기본값은 `0.5`다.

`expected_claim_citations`는 선택 필드다. 지정하면 해당 target claim의 citation이 기대 doc id와 expected terms를 직접 포함해야 한다. 지정하지 않은 claim도 기본적으로 claim text가 cited evidence text에 의해 지지되는지 token/substring 기반으로 점검한다.

## Report fields
`reports/eval_summary.json`에는 다음 additive metric이 기록된다.

| Field | Meaning |
|---|---|
| `citation_page_precision` | 기대 page anchor 중 citation page metadata가 맞은 비율 |
| `citation_region_precision` | 기대 region anchor 중 citation bbox가 IoU 기준을 통과한 비율 |
| `citation_grounding` | page/region grounding score의 평균. 둘 다 없으면 `null` |
| `claim_citation_alignment` | claim별 citation chunk가 claim text와 기대 claim terms를 직접 지지한 비율 |
| `citation_grounding_error_counts` | page/region grounding 실패 taxonomy count |
| `claim_citation_error_counts` | claim-level citation alignment 실패 taxonomy count |

case result에는 `citation_grounding_errors`와 `claim_citation_errors`가 포함된다.

| Code | Meaning |
|---|---|
| `page_missing` | citation에 page metadata가 없어 page 검증 불가 |
| `page_mismatch` | page metadata는 있으나 기대 page와 불일치 |
| `region_unavailable` | 기대 page의 bbox region metadata가 없음 |
| `region_misaligned` | bbox가 있으나 IoU threshold 미달 |

Claim-level 오류는 다음처럼 해석한다.

| Code | Meaning |
|---|---|
| `claim_missing_citation` | claim에 citation이 없음 |
| `citation_not_in_evidence` | claim citation chunk가 top-level evidence에 없음 |
| `claim_text_not_supported_by_citation` | citation text가 claim text를 직접 지지하지 않음 |
| `expected_claim_doc_mismatch` | target별 expected doc id와 citation doc id가 다름 |
| `expected_claim_terms_missing` | target별 expected terms가 citation text에 없음 |
| `expected_claim_missing` | expected target claim이 출력되지 않음 |

## Examples
Correctly grounded citation:

```json
{
  "doc_id": "parser-fixture-doc",
  "chunk_id": "parser-fixture-doc::chunk-001",
  "page_span": [1, 1],
  "regions": [
    {
      "page_number": 1,
      "bbox": [10, 40, 280, 100],
      "block_id": "parser-fixture-doc::p001::b002"
    }
  ]
}
```

Drifting citation:

```json
{
  "doc_id": "parser-fixture-doc",
  "chunk_id": "parser-fixture-doc::chunk-003",
  "page_span": [2, 2],
  "regions": [
    {
      "page_number": 2,
      "bbox": [200, 200, 260, 260]
    }
  ]
}
```

첫 번째 예시는 문서, page, bbox가 모두 gold anchor와 맞는다. 두 번째 예시는 같은 문서의 다른 page 또는 다른 bbox를 가리키므로 기존 document-level citation precision은 통과할 수 있지만 page/region grounding은 실패한다.

## Parser-stage linkage
`eval/run_parser_eval.py`의 `bbox_missing`은 downstream에서 `region_unavailable`로 이어질 수 있다. `bbox_misaligned`는 citation이 올바른 chunk를 선택해도 `region_misaligned`로 나타날 수 있다. 따라서 visual v2 분석에서는 QA report의 `citation_grounding_error_counts`와 parser report의 `failure_counts`를 함께 본다.

text v1 또는 HWP fallback처럼 page/region metadata가 없는 입력은 region grounding 품질이 낮다고 단정하지 않는다. 해당 run은 gold field를 두지 않거나 `region_unavailable`을 metadata coverage 한계로 분류한다.
