# 0008: Evidence text boundary and instruction-like-pattern neutralization

- **Status**: accepted
- **Date**: 2026-05-11
- **Deciders**: hskim-solv
- **Related**: [`rag_verifier.py`](../../rag_verifier.py) (`evidence_text_for_verification`, `neutralize_instruction_patterns`, `EVIDENCE_BOUNDARY` — extracted from `rag_core.py` in PR-J1 / issue #465; `rag_core` keeps re-exports for backward compatibility), [`scripts/llm_judge.py:_build_prompt`](../../scripts/llm_judge.py), [ADR 0003](0003-structured-answer-citation-contract.md), [ADR 0006](0006-llm-judge-on-real-data-only.md), [ADR 0028](0028-security-screen-additive.md) (complementary query-side defense)

## Context

Retrieved-evidence text in this repo originates from external RFP documents and flows into two downstream consumers:

1. The deterministic verifier (`rag_core.py:evidence_text_for_verification`, joined and substring-matched against topics/entities).
2. The LLM judge (`scripts/llm_judge.py:_build_prompt`, embedded directly into a chat prompt — see ADR 0006).

The main answer generator is extractive (ADR 0003 — no LLM call), so traditional "prompt injection" does not bypass it. But a malicious or accidentally-malformed RFP chunk containing chat template tokens (`<|im_start|>`, `<|im_end|>`), role tags (`SYSTEM:`, `ASSISTANT:`, `USER:`), or instruction-override phrases ("Ignore previous instructions") can still:

- Influence the LLM judge into an unsupported verdict, which then feeds the committable `agreement_with_verifier` aggregate.
- Affect any downstream LLM consumer (planner, generator) if introduced in future cycles.
- Pollute traces, logs, and eval artifacts with strings that look like real prompt boundaries.

Before this ADR, evidence text was joined with bare spaces and passed through unchanged. There was no single choke point where adversarial content could be neutralized.

## Decision

Introduce a single helper, `neutralize_instruction_patterns(text: str) -> str`, in `rag_core.py` and apply it at every site where document-controlled text crosses into a verifier or LLM consumer.

Neutralization rules (all case-insensitive):

- **Chat template tokens** `<|im_start|>`, `<|im_end|>`, `<|system|>`, `<|user|>`, `<|assistant|>`, `<|tool|>`, `<|begin_of_text|>`, `<|end_of_text|>`, `<|fim_*|>`, `<|endoftext|>` → replaced with the literal sentinel `[REDACTED_CHAT_TOKEN]`.
- **Role-tag lines** matching `^\s*(SYSTEM|ASSISTANT|USER|TOOL)\s*:\s*.+$` (anchored at line start, multiline) → wrapped with `[INSTRUCTION_LIKE]...[/INSTRUCTION_LIKE]`.
- **Instruction-override lines** matching `^\s*(ignore|disregard|forget|override|bypass)\s+(previous|prior|all|any|the)\s+(instructions?|prompts?|rules?|directives?|system).*$` → wrapped with the same `[INSTRUCTION_LIKE]` markers.

Application sites:

- `evidence_text_for_verification` (rag_core.py) — neutralizes `title`, `agency`, `project`, `section`, `text`, and each metadata value.
- `scripts/llm_judge.py:_build_prompt` — neutralizes the per-chunk text and joins chunks with the public constant `EVIDENCE_BOUNDARY = "\n[---EVIDENCE_BOUNDARY---]\n"`; also neutralizes `query` and `summary` before formatting into the prompt template.

The helper and the boundary constant are public (no leading underscore) so other future consumers can reuse them without re-implementing the rules.

## Consequences

**Wins**:

- The LLM judge (ADR 0006) and any future LLM consumer cannot be misled by RFP-embedded chat tokens or role tags.
- Citations remain readable — text content is preserved verbatim, only wrapped with markers.
- Single-point change: one function in `rag_core.py`, two call sites updated. No API or answer-contract bumps (ADR 0003 unchanged, `schema_version` not bumped).
- Regression test (`tests/test_prompt_injection_regression.py`) prevents silent removal during refactors.

**Costs / constraints**:

- Regulatory RFP sections that legitimately contain phrases like "이전 지시사항 무시" pick up an `[INSTRUCTION_LIKE]` marker — readers must understand the marker is defensive, not pejorative.
- `evidence_text_for_verification` output now contains marker tokens (`[INSTRUCTION_LIKE]`, `[/INSTRUCTION_LIKE]`, `[REDACTED_CHAT_TOKEN]`); tests asserting exact string equality on that output must accommodate them.
- Future contributors must extend `neutralize_instruction_patterns` rather than introducing parallel sanitizers at call sites.

**Contract**: callers must treat the marker tokens above as defensive annotations, not as content. The verifier substring-matching contract is unaffected because topic strings do not overlap with the marker syntax.

## Alternatives considered

- **Strip patterns silently** — rejected: destroys evidence and breaks citation auditability. A reviewer reading a citation must see what was in the source.
- **New `Sanitizer` class with pluggable rules** — rejected: CLAUDE.md "Reuse over invent". One function suffices until a second consumer needs different rules.
- **Sanitize at the LLM judge boundary only** — rejected: defense-in-depth, and the verifier already calls `evidence_text_for_verification`, so the single function is the natural choke point.
- **Skip the change because the system is extractive** — rejected: ADR 0006's LLM judge already consumes evidence text, and future generative pipelines are explicitly anticipated.
