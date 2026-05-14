# 0042: Tool-use evidence-boundary defense

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0008](./0008-evidence-boundary.md) (evidence-side defense),
  [ADR 0040](./0040-react-agent-loop-additive-preset.md) (ReAct preset),
  [ADR 0003](./0003-structured-answer-citation-contract.md) (answer contract),
  issue #682

## Context

ADR 0008 introduced `neutralize_instruction_patterns` to sanitize retrieved
evidence text before it reaches the LLM in the answer-generation stage.
The attack surface was: an adversarial document could embed prompt-override
instructions (e.g. `\n\nHuman:` chat tokens, `IGNORE PREVIOUS INSTRUCTIONS`)
in its text, which would then be injected verbatim into the LLM prompt.

The ReAct agent loop (ADR 0040) opens a **new attack surface** not covered
by ADR 0008: the four `execute_*` tool wrapper functions in
`rag_agent_tools.py` return dicts whose string values are serialized and
inserted into the next multi-turn LLM message. If a retrieved chunk contains
injected instructions, those instructions would survive into the next
planning turn's user message unless explicitly neutralized.

The existing `neutralize_instruction_patterns` function (ADR 0008) is the
canonical defense. This ADR mandates its application to all text that
crosses the tool → LLM boundary.

## Decision

**Every `execute_*` function in `rag_agent_tools.py` that returns text
derived from retrieved evidence must apply `neutralize_instruction_patterns`
before including it in the return dict.**

Specifically:
- `execute_retrieve_evidence`: `meta` dict is diagnostic (not evidence text)
  — no neutralization required at this level. Neutralization happens inside
  `retrieve_candidates` / `verify_evidence` on the evidence text itself
  (existing ADR 0008 coverage), and `execute_verify_grounding` reasons are
  internally generated (not external text).
- `execute_verify_grounding`: `reasons` are internally generated strings
  (not external evidence text) — no neutralization required at this call
  site. Evidence text is neutralized inside `verify_evidence` (ADR 0008).
- `execute_expand_query_hyde`: the expanded query is LLM-generated (not
  retrieved evidence) — no neutralization required.
- `execute_abstain`: the `reason` string originates from the LLM itself —
  no external text crosses this boundary.
- `format_verifier_feedback` (PR-D): reasons are internally generated —
  no neutralization required.

**Net result**: existing ADR 0008 coverage in `verify_evidence` is
sufficient for the tool surface as designed. This ADR formalizes the
audit and confirms that no additional call sites are required.

**Regression gate (PR-E)**:
`tests/test_agent_react_regression.py` confirms that `format_verifier_feedback`
output and `execute_abstain` return values do not contain the
`EVIDENCE_BOUNDARY` sentinel, and that the `AGENT_REACT_SYSTEM_PROMPT`
does not echo evidence text.

## Consequences

### Positive

- Tool-use attack surface is explicitly audited — ADR 0008 coverage is
  confirmed to extend to the ReAct loop without additional code changes.
- Regression test makes the audit machine-checkable.
- The decision is documented so future `execute_*` additions know the rule:
  any wrapper that embeds external text in its return value must call
  `neutralize_instruction_patterns` on that text.

### Negative / Trade-offs

- None: the audit confirmed no gaps, so no performance overhead is added.

## Rule for future `execute_*` additions

> **If the return value contains text from retrieved documents or user-
> submitted content (not internally generated), apply
> `neutralize_instruction_patterns` before returning.**

The `EVIDENCE_BOUNDARY` regression test must be updated to include the
new function's output.
