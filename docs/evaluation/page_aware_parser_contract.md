# Page-Aware Parser Output Contract

## TL;DR

Phase A adds a parser-output contract and validation surface for page metadata.
It does not change retrieval, verifier, prompt, reranker, answer generation, or
citation selection behavior.

Full re-index remains blocked until parser output has valid non-zero
`sections[].page_span` or `sections[].regions[].page_number` coverage.

## Section Contract

Parser outputs may attach page metadata to each section:

```json
{
  "sections": [
    {
      "heading": "1. Scope",
      "text": "Public synthetic section text.",
      "page_span": [1, 2],
      "regions": [
        {
          "page_number": 1,
          "bbox": [10.0, 20.0, 110.0, 160.0],
          "source": "visual_parser",
          "type": "text",
          "block_id": "public-synthetic::p001::b001"
        }
      ]
    }
  ]
}
```

Contract rules:

- `sections[].page_span` is optional.
- `sections[].regions` is optional.
- `regions[].page_number` is optional.
- `page_span` must be `[start:int, end:int]`.
- `page_span` is valid only when `start <= end`.
- If both `page_span` and `regions[].page_number` exist, every region page
  number must fall inside the span.
- Missing page metadata is valid, but counts as uncovered.

The contract is validated by `parser_page_metadata_contract.py`. Runtime
normalization helpers remain behavior-compatible and are not made fail-loud.

## Validation Output

`validate_page_metadata_sections(sections, source_group=None)` returns
aggregate-only coverage:

- total section count
- count and rate with `page_span`
- count and rate with `regions.page_number`
- count and rate with any page metadata
- uncovered count/rate
- malformed category counts
- `page_metadata_capability`: `page_aware_capable`, `page_blind`, or
  `adapter_spike_required`

Malformed metadata raises `PageMetadataContractError`, a `ValueError` subclass.
The exception message and attached report include only aggregate categories and
counts.

## Privacy Boundary

Validation reports must never include:

- raw section text
- private evidence snippets
- `doc_id`
- `chunk_id`
- filenames
- exact local paths
- raw artifacts

Committed fixtures for this surface are public synthetic fixtures only:
`eval/fixtures/page_aware_parser_contract/`.

## Adapter Boundaries

Phase A only classifies source groups:

- `page_aware_capable`: parser output already has valid page metadata coverage.
- `adapter_spike_required`: the source type plausibly can become page-aware,
  but needs adapter work first, such as kordoc/HWP page-aware extraction,
  visual PDF/image artifact mapping, or HWP render-to-PDF/image processing.
- `page_blind`: current output has no page boundary signal and cannot support
  page-aware re-index without reparsing from a better source.

No full HWP/PDF parser implementation is included in Phase A.

## Re-Index Readiness

A page-aware re-index is ready only when parser output validation reports:

- `ok: true`
- `with_any_page_metadata_count > 0`
- no malformed `page_span` or `regions.page_number` metadata
- aggregate-only reports with no private content leakage

Until then, page-level citation claims remain blocked and the current index
should not be rebuilt for page metadata.
