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

## Measurement gaps

Three regex patterns + marker-token wrapping is **not** an
exhaustive defense. Until issue #828 the ADR did not surface the
attack vectors that the current rules do not yet cover. Documented
here so the gap lives at the decision-record layer rather than only
in tests:

- **Defense surface today**: regex set in
  [`rag_verifier.py:262/266/269`](../../rag_verifier.py); per-attack
  positive cases live in
  [`tests/test_prompt_injection_regression.py`](../../tests/test_prompt_injection_regression.py)
  and the per-vector adversarial pinning in
  [`tests/test_evidence_boundary_attack_vectors.py`](../../tests/test_evidence_boundary_attack_vectors.py).
- **Marker-bypass / marker-tag confusion** — **closed by issue #830 surgical PR**:
  `_LITERAL_MARKER_RE` in `rag_verifier.py` now rewrites any literal
  `[INSTRUCTION_LIKE]` / `[/INSTRUCTION_LIKE]` token in input to
  `[INPUT_MARKER]` BEFORE applying the wrap, so every marker token
  in the output was written by the defense (not by the attacker).
- **Remaining unaddressed attack vectors** (tracking issue
  [#830](https://github.com/hskim-solv/BidMate-DocAgent/issues/830)):
  - **Chat-token aliasing**: tokens with surrounding whitespace
    (`< |im_start| >`), fullwidth lookalikes (`＜｜im_start｜＞`),
    or partial matches (`<|im_star`) are not normalized.
    Pinned by
    `tests/test_evidence_boundary_attack_vectors.py::TestVector3ChatTokenAliasing`.
    Fix path: NFKC unicode normalization before regex match.
  - **Role-tag case (fullwidth only)**: ASCII `IGNORECASE` already
    handles `SyStEm:`; the gap is fullwidth
    (`ＳＹＳＴＥＭ:`). Pinned by
    `TestVector4RoleTagCaseUnicode::test_4b_fullwidth_role_tag_NOT_defended`.
    Fix path: same NFKC normalization as chat-token aliasing.
  - **Instruction-override paraphrases**: regex requires keywords
    like `ignore` / `disregard`; semantic paraphrases ("reset
    everything we discussed") pass through. Pinned by
    `TestVector5InstructionOverrideParaphrase`. Out of scope for
    the deterministic verifier per the ADR's Alternatives section
    — would require an LLM classifier.
- **Decision rule for a regex change**: a new rule (or a relaxation)
  requires ≥1 new attack vector covered with no >0 false-positive
  regressions on the real-corpus survey set (Korean legal language
  often legitimately quotes "이전 지시사항 무시" in
  regulation-quote contexts).
- **Adversarial corpus expansion plan**: covered in #830 (start
  with the existing regression set, grow per attack vector above).
- **Cross-link**: the LLM judge (ADR 0006) has its own
  evaluation surface; defense regressions surface as
  `agreement_with_verifier` deltas in the leaderboard. Adversarial
  expansion benchmarks should be added there once #830 ships.

## Alternatives considered

- **Strip patterns silently** — rejected: destroys evidence and breaks citation auditability. A reviewer reading a citation must see what was in the source.
- **New `Sanitizer` class with pluggable rules** — rejected: CLAUDE.md "Reuse over invent". One function suffices until a second consumer needs different rules.
- **Sanitize at the LLM judge boundary only** — rejected: defense-in-depth, and the verifier already calls `evidence_text_for_verification`, so the single function is the natural choke point.
- **Skip the change because the system is extractive** — rejected: ADR 0006's LLM judge already consumes evidence text, and future generative pipelines are explicitly anticipated.
