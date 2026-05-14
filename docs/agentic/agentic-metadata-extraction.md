# Agentic Metadata Extraction (issue #180 / ADR 0017)

> **Status:** wired into `ingestion.py` as the additive
> `metadata["extracted"]` sidecar. Default backend is `regex`
> (ADR 0001 invariant). LLM backends require an API key and are opt-in
> via `BIDMATE_METADATA_BACKEND`.

The classic regex / CSV-column passthrough fills RFP metadata
(`agency`, `project`, `budget`, deadlines) cheaply and deterministically
— it is the default and ships unchanged. This module adds an **additive**
LLM-driven extraction path that reads the same body text and returns a
strict eight-field JSON payload via tool / function calling. The two
paths coexist on the same chunk; downstream consumers can pick which
one to trust per field.

## Schema

`rag_metadata_extraction.MetadataExtraction` (eight fields):

| Field                 | Type           | Notes                                                |
|-----------------------|----------------|------------------------------------------------------|
| `agency`              | `str \| None`  | 발주 기관 short name (한글 가능).                    |
| `project_name`        | `str \| None`  | 사업명.                                              |
| `budget_amount`       | `float \| None`| Amount only — no `원` / `만원` / commas.              |
| `budget_currency`     | `str \| None`  | ISO 4217 (KRW by default for Korean RFPs).           |
| `deadline_iso`        | `str \| None`  | `YYYY-MM-DD`.                                        |
| `submission_date_iso` | `str \| None`  | `YYYY-MM-DD`.                                        |
| `contact_email`       | `str \| None`  | First email matched in body text.                    |
| `contact_name`        | `str \| None`  | Conservative — regex baseline leaves this `None`.    |

The tool schema (`TOOL_DEFINITION` in `rag_metadata_extraction.py`)
uses `additionalProperties: false` so an LLM response cannot smuggle
unexpected fields into the chunk metadata.

## Backends

Switched via `BIDMATE_METADATA_BACKEND`:

| Backend                | Default | Deterministic | Network | Notes                                                                                       |
|------------------------|---------|---------------|---------|---------------------------------------------------------------------------------------------|
| `regex`                | ✅      | ✅            | —       | The ADR 0001 invariant. Reads CSV columns + an email regex from body text.                  |
| `stub`                 | —       | ✅            | —       | Delegates to `regex`. Used by tests; guarantees `stub == regex` bit-for-bit.                |
| `anthropic_tool_use`   | —       | —             | yes     | Claude API (`extract_rfp_metadata` tool). `ANTHROPIC_API_KEY` required.                     |
| `openai_function_call` | —       | —             | yes     | OpenAI-compatible (`BIDMATE_METADATA_API_KEY` + `BIDMATE_METADATA_MODEL` + `_BASE_URL`).    |

Failure handling: any backend exception (missing SDK, missing key,
malformed response, network error) silently falls back to the regex
baseline. The pipeline never loses metadata to a tool-use error.

## Wire-up

`ingestion.normalize_ingestion_row` is the seam — every successfully
indexed row gets the extracted sidecar before the document leaves the
ingestion path:

```python
document = {
    "doc_id": validation.doc_id,
    "title": clean_cell(row.get("사업명")) or Path(validation.file_name).stem,
    "agency": clean_cell(row.get("발주 기관")),
    "project": clean_cell(row.get("사업명")),
    "metadata": metadata,
    "sections": [{"heading": "본문", "text": text}],
    "source_path": str(validation.source_path),
}
document["metadata"]["extracted"] = extract_rfp_metadata(document).as_dict()
```

The top-level `agency` / `project` fields are deliberately left
untouched — they feed the answer/citation contract (ADR 0003) and
metadata-first retrieval; rebinding them to an LLM value mid-pipeline
would break determinism on the public synthetic surface. The LLM
value lives in the sidecar so reviewers can A/B it per field.

## Eval ablation

`eval/config.yaml` row `full_llm_metadata` runs the standard
`agentic_full` pipeline against an index built with the LLM backend
enabled. Because the extraction happens at *ingest* time, this row is
meaningful only when the index was built with
`BIDMATE_METADATA_BACKEND=anthropic_tool_use` (or
`openai_function_call`); under the default `regex` backend it is
identical to `full`. The latency budget mirrors `full` — per-query
latency is unchanged; the cost shifts to a one-time index build.

## How to A/B locally

```bash
# 1. Build a regex-extracted index (the default).
python scripts/build_index.py

# 2. Build an LLM-extracted index into a separate directory.
BIDMATE_METADATA_BACKEND=anthropic_tool_use \
ANTHROPIC_API_KEY=$YOUR_KEY \
BIDMATE_INDEX_DIR=data/index_llm_metadata \
  python scripts/build_index.py

# 3. Compare per-field extraction agreement on the two payloads
#    (script lives operator-side per ADR 0005; see issue #180
#    acceptance criteria for the per-field accuracy table).
```

The per-field accuracy table (regex vs. `anthropic_tool_use` on
`data/raw` + the private 100-doc corpus) is captured operator-side
per ADR 0005 and surfaced via `reports/eval_summary.json` deltas
rather than committed here — the private corpus rows are the
authoritative signal and never land in the public repo.

## Failure modes & escalations

| Symptom                                                       | Likely cause                                                                                      | Fix                                                                                  |
|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| `metadata["extracted"]` is identical to the regex baseline    | Backend env not set, SDK missing, or the API key is empty — `extract_rfp_metadata` fell back.     | Verify `BIDMATE_METADATA_BACKEND` + `ANTHROPIC_API_KEY` and re-run `build_index.py`. |
| Index build is slow under `anthropic_tool_use`                | One Claude call per document — by design. The synthesis-prompt + tool schema are cached server-side. | Run ingest once and reuse `data/index`. Per-query latency is unchanged.              |
| Per-field accuracy lower than regex on Korean RFPs            | Conservative-prompt drift — the LLM should *omit* fields, not invent them.                        | Sanity-check `SYSTEM_PROMPT` and add a contrastive example in the next ADR follow-up. |

## Related

- [ADR 0001 — preserve naive baseline](../adr/0001-preserve-naive-baseline.md)
- [ADR 0003 — structured answer / citation contract](../adr/0003-structured-answer-citation-contract.md)
- [ADR 0011 — LLM synthesis as additive ablation](../adr/0011-llm-synthesis-as-additive-ablation.md)
- [ADR 0017 — LLM metadata extraction as additive](../adr/0017-llm-metadata-extraction-additive.md)
- [`rag_metadata_extraction.py`](../rag_metadata_extraction.py) — backends + tool schema
- [`ingestion.py`](../ingestion.py) — wire-up seam
- [`tests/test_ingestion_metadata_wireup_regression.py`](../tests/test_ingestion_metadata_wireup_regression.py) — additive-contract test suite
