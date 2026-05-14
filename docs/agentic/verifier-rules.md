# Verifier decision rules

A reading guide to the deterministic verifier that gates every answer
in this repo. The rules below are expressed in two parallel forms —
**code** (with `rag_core.py` file:line references) and **pseudo-prompt**
(natural-language directives in the shape an LLM verifier would
consume). The two columns are intentionally line-by-line equivalent so
a future swap from the deterministic verifier to an LLM verifier has a
documented baseline.

This is a behavioral specification, not a tutorial. Read alongside:

- [ADR 0003 — answer / citation contract](../adr/0003-structured-answer-citation-contract.md) — the schema each rule writes into.
- [ADR 0004 — verifier retry policy](../adr/0004-verifier-retry-policy.md) — the strict → relaxed staging this implements.
- [`rag_answer_schema.py`](../rag_answer_schema.py) — canonical definitions of `ANSWER_STATUS_*` and `ANSWER_SCHEMA_VERSION`.

## Constants

| Constant | Value | Defined in |
|---|---|---|
| `ANSWER_SCHEMA_VERSION` | `2` | [`rag_answer_schema.py:42`](../rag_answer_schema.py) |
| `ANSWER_STATUS_SUPPORTED` | `"supported"` | [`rag_answer_schema.py:38`](../rag_answer_schema.py) |
| `ANSWER_STATUS_PARTIAL` | `"partial"` | [`rag_answer_schema.py:39`](../rag_answer_schema.py) |
| `ANSWER_STATUS_INSUFFICIENT` | `"insufficient"` | [`rag_answer_schema.py:40`](../rag_answer_schema.py) |
| `PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` | `2` | [`rag_core.py:2278`](../rag_core.py) |
| `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` | `0.5` | [`rag_core.py:2277`](../rag_core.py) |
| Low-score floor (literal) | `0.18` | [`rag_core.py:2313`](../rag_core.py) |

## Decision tree — `verify_evidence`

The verifier ([`verify_evidence`](../rag_core.py), `rag_core.py:2282-2368`)
is a four-stage gate. Each stage either short-circuits, blocks, or
appends a `verification_reason`; the final verdict is `verified =
not blocking_reasons`. Only `partial_topic_grounding` is non-blocking.

### Stage A — evidence existence

```python
# rag_core.py:2311-2312
if not evidence:
    return False, ["no_evidence"]
```

> **Pseudo-prompt.** If the retrieval system returned no chunks at all,
> output `verified=false` with reason `no_evidence` and stop. Do not
> attempt to grade an empty bag of evidence.

### Stage B — hallucination floor (always strict)

```python
# rag_core.py:2313-2314
if evidence[0]["score"] < 0.18:
    reasons.append("low_top_score")
```

> **Pseudo-prompt.** If the top retrieved chunk's similarity score is
> below `0.18`, append `low_top_score` to the reasons list. This rule
> applies in both strict and relaxed stages — see Stage D.

The `0.18` threshold is a literal in code, not a tunable. It exists as
a hallucination floor: below this score, even partial topic matches
are rejected to avoid plausible-sounding answers grounded on noise.

### Stage C — topic grounding (strict vs relaxed split)

```python
# rag_core.py:2322-2341
if topics:
    matched_topic_count = sum(
        1
        for topic in topics
        if any(
            form in combined or form in combined_canonical
            for form in expand_forms(topic.lower())
        )
    )
    if matched_topic_count < len(topics):
        if (
            allow_partial_topic
            and matched_topic_count >= PARTIAL_TOPIC_GROUNDING_MIN_MATCHED
            and (matched_topic_count / len(topics)) >= PARTIAL_TOPIC_GROUNDING_MIN_FRACTION
        ):
            reasons.append(PARTIAL_TOPIC_GROUNDING_REASON)
        else:
            reasons.append("topic_not_grounded")
```

> **Pseudo-prompt.** For each `topic` in the analysis, check whether
> the combined evidence text contains the topic or any of its
> normalized/canonical forms (Korean money/date OR-matching per ADR
> 0007 / issue #170).
>
> - If **all** topics are matched, this stage passes silently.
> - If at least one topic is missing AND the caller signals this is
>   the last attempt (`allow_partial_topic=true`) AND **both**
>   `matched ≥ 2` and `matched / total ≥ 0.5`, append the
>   **non-blocking** reason `partial_topic_grounding`. The answer will
>   surface as `partial` rather than `insufficient`.
> - Otherwise, append the blocking reason `topic_not_grounded` and
>   leave `verified` false.

The two floors (`≥ 2 matched` AND `≥ 50%`) exist for distinct reasons,
both documented as regression guards:

- The fraction floor (`50%`) rejects weakly-balanced cases like 2-of-5.
- The matched-count floor (`≥ 2`) cuts the 1-of-2 incidental-overlap
  pattern that flipped real-data intended-abstention queries to
  `partial` after issue #69 (see issue #89, [`rag_core.py:2301-2304`](../rag_core.py)).

An LLM verifier prompt that drops either floor will regress
[`tests/test_partial_topic_grounding.py`](../tests/test_partial_topic_grounding.py).

### Stage D — comparison coverage (strict, entity-level)

```python
# rag_core.py:2343-2363
entities = analysis.get("entities") or []
if analysis.get("query_type") == "comparison" and len(entities) > 1:
    covered = {item.get("agency") for item in evidence}
    missing = [entity for entity in entities if entity not in covered]
    if missing:
        reasons.append("missing_comparison_entity:" + ",".join(missing))
    if topics:
        # … per-entity topic coverage check …
        if missing_topic_entities:
            reasons.append("missing_comparison_topic:" + ",".join(missing_topic_entities))

matched_doc_ids = analysis.get("matched_doc_ids") or []
if analysis.get("query_type") == "comparison" and len(matched_doc_ids) > 1:
    # … per-doc coverage …
    if missing_doc_ids:
        reasons.append("missing_comparison_doc:" + ",".join(missing_doc_ids))
```

> **Pseudo-prompt.** Only for queries where `query_type == "comparison"`
> AND more than one entity / doc is requested:
>
> - If any requested entity has no evidence chunk attached to it,
>   append `missing_comparison_entity:<entity1>,<entity2>`.
> - If an entity has evidence but none of those chunks cover any of
>   the topics, append `missing_comparison_topic:<entity>`.
> - If multiple `matched_doc_ids` were requested and at least one has
>   no covering evidence, append `missing_comparison_doc:<doc_id>`.
>
> All three of these reasons are **blocking**.

### Stage E — final verdict

```python
# rag_core.py:2365-2368
blocking_reasons = [reason for reason in reasons if reason != PARTIAL_TOPIC_GROUNDING_REASON]
return not blocking_reasons, reasons
```

> **Pseudo-prompt.** Filter the reasons list: `partial_topic_grounding`
> is non-blocking; everything else blocks. Return
> `verified = (no blocking reasons remain)` paired with the **full**
> reasons list (including any non-blocking reasons — the answer-status
> mapping needs them).

## Status mapping — `answer_status`

[`answer_status`](../rag_core.py) (`rag_core.py:2641-2666`) and
[`answer_status_reason`](../rag_core.py) (`rag_core.py:2516-2539`)
translate the `(verified, reasons)` tuple into the ADR 0003 contract
fields. The matrix:

| `verified` | reasons include `partial_topic_grounding` | reasons include `missing_requested_entity:*` | `query_type == "comparison"` AND `claims` non-empty AND any `missing_comparison*` reason | → `status` | → `status_reason.code` |
|---|---|---|---|---|---|
| `True` | no | no | n/a | `supported` | `verified` |
| `True` | **yes** AND `claims` non-empty | n/a | n/a | `partial` | `partial_topic_grounding` |
| `True` | no | **yes** | n/a | falls through to `insufficient` | `insufficient_evidence` |
| `False` | n/a | n/a | **yes** | `partial` | `partial_comparison` |
| `False` | (any other shape) | n/a | n/a | `insufficient` | `insufficient_evidence` |

> **Pseudo-prompt.** Given `verified`, `verification_reasons`, and
> `claims`, decide `status`:
>
> - **`supported`** — only when `verified=true`, no
>   `partial_topic_grounding`, and no `missing_requested_entity:*`.
> - **`partial`** — either (a) `verified=true` AND
>   `partial_topic_grounding` is in reasons AND claims were built, or
>   (b) `verified=false` AND the query was a comparison AND at least
>   one `missing_comparison_*` reason exists AND at least one claim
>   was built.
> - **`insufficient`** — every other case. The answer will carry an
>   `insufficiency` block instead of `claims`.
>
> Encode the disambiguation in `status_reason.code`: `verified` /
> `partial_topic_grounding` / `partial_comparison` /
> `insufficient_evidence`.

## Citation gating — `build_claims`

[`build_claims`](../rag_core.py) (`rag_core.py:2542-2547`) is only
called when the verifier accepts evidence OR when the query is a
comparison with at least partial entity coverage. Claims emit
`citations[]` where each citation pins `doc_id` + `chunk_id` to the
top-level `evidence` list (ADR 0003 invariant).

> **Pseudo-prompt.** Do not build any claim whose `support` cannot be
> resolved to a specific `(doc_id, chunk_id)` pair in the evidence
> list. A claim without a resolving citation is treated as
> hallucinated and excluded.

For comparison queries, [`build_comparison_claims`](../rag_core.py)
(`rag_core.py:2549-2564`) emits one claim per entity that has at least
one evidence chunk; the remaining entities feed the `insufficiency`
block instead. For extract queries,
[`build_extract_claims`](../rag_core.py) (`rag_core.py:2567-2601`)
selects up to two claims, preferring metadata-bound sentences.

## Retry policy — ADR 0004 mapping

The retrieval orchestrator
([`rag_core.py:3886-3906`](../rag_core.py)) schedules verification
attempts:

```python
# rag_core.py:3886-3906
if verifier_retry:
    is_last_attempt = attempt_index == len(stage_sequence) - 1
    verified, verification_reasons = verify_evidence(
        analysis,
        evidence,
        allow_partial_topic=is_last_attempt,
    )
...
if verified:
    break
if attempt_index < len(stage_sequence) - 1:
    retry_count += 1
```

| Attempt | `allow_partial_topic` | Behaviour |
|---|---|---|
| 0 (strict) | `False` | All topics must match. `partial_topic_grounding` cannot fire. |
| 1 (relaxed, last) | `True` | Stage C may fire `partial_topic_grounding` if the `≥2 / ≥50%` gates hold. All other stages stay strict. |
| (no third retry) | — | If the relaxed stage still fails, `status` becomes `insufficient` or, for comparison queries, `partial` via the comparison-coverage path. |

> **Pseudo-prompt.** When `verifier_retry` is on, run the verifier
> twice if the first attempt failed. On the **second and final**
> attempt only, set `allow_partial_topic=true` so the relaxed
> partial-topic path can fire. Do not retry a third time — escalate
> to `insufficient` instead.

## Regression baseline

If the deterministic verifier is ever swapped for an LLM verifier, the
following tests are the contract the LLM must satisfy
(`tests/test_partial_topic_grounding.py`):

| Test | Line | Pins |
|---|---|---|
| `test_strict_rejects_partial_topic_match` | [`tests/test_partial_topic_grounding.py:52`](../tests/test_partial_topic_grounding.py) | strict mode rejects any unmatched topic |
| `test_relaxed_accepts_partial_topic_match_above_threshold` | [`tests/test_partial_topic_grounding.py:60`](../tests/test_partial_topic_grounding.py) | relaxed mode accepts 3-of-4 = 0.75 |
| `test_relaxed_rejects_one_of_two_partial_topic_match` | [`tests/test_partial_topic_grounding.py:79`](../tests/test_partial_topic_grounding.py) | issue #89 — relaxed mode rejects 1-of-2 = 0.5 (matched-count floor) |
| `test_relaxed_still_rejects_zero_topic_match` | [`tests/test_partial_topic_grounding.py:102`](../tests/test_partial_topic_grounding.py) | relaxed mode rejects 0-of-N (out-of-corpus preservation) |
| `test_relaxed_still_rejects_below_fraction` | [`tests/test_partial_topic_grounding.py:114`](../tests/test_partial_topic_grounding.py) | relaxed mode rejects 1-of-4 = 0.25 (fraction floor) |
| `test_low_top_score_still_blocking_in_relaxed_stage` | [`tests/test_partial_topic_grounding.py:125`](../tests/test_partial_topic_grounding.py) | `0.18` hallucination floor holds in both stages |
| `test_out_of_corpus_query_still_abstains` | [`tests/test_partial_topic_grounding.py:149`](../tests/test_partial_topic_grounding.py) | end-to-end abstention preserved |

## LLM migration counter-checks

If a future PR routes verification through an LLM judge (the path
explicitly rejected for the public surface in ADR 0004's Alternatives
section), these are the points where naïve prompt translation tends to
diverge from the deterministic behaviour:

1. **`0.18` score floor → relative confidence.** LLMs do not see raw
   retrieval scores. Either expose the score in the prompt as a
   numeric field with explicit instructions, or replace the literal
   threshold with a confidence-based judgement and prove on
   `test_low_top_score_still_blocking_in_relaxed_stage` that the
   replacement does not regress.
2. **Non-linear topic gate (`≥ 2 AND ≥ 50%`).** Two distinct floors,
   not a single fraction. An LLM asked to "accept partial topic
   matches" tends to accept 1-of-2 = 50% — exactly the case issue #89
   regression-guards against. Few-shot the prompt with the
   `test_relaxed_rejects_one_of_two_partial_topic_match` example.
3. **`partial_topic_grounding` is non-blocking.** This is a policy
   signal, not a verification fact: a perfectly natural-sounding LLM
   verifier may stop reporting it once it has decided `verified=true`,
   which collapses the `partial` vs `supported` distinction the
   answer-status mapping depends on. The prompt must require both
   bits of output: a verified flag AND the full reasons list,
   including the non-blocking marker when it fires.
4. **Comparison-coverage exactness.** The deterministic verifier
   rejects a comparison query if **any** requested entity / doc lacks
   evidence. An LLM tends to be more permissive ("close enough on the
   ones I have"). Surface the `entities` and `matched_doc_ids` lists
   in the prompt and require explicit enumeration of which are
   covered.
5. **Korean money/date OR-matching.** Stage C uses `expand_forms` and
   `normalize_text` to match `1억 5천만원` against `150,000,000원`
   etc. An LLM prompt that does not surface both forms will under-match
   on real RFP data. Pass `combined_canonical` alongside `combined`
   in the prompt.

Each item above is testable: pick the corresponding regression test
and run it against the LLM-backed implementation. Any regression is a
contract break under ADR 0003 and demands a `schema_version` bump or
a documented re-spec.
