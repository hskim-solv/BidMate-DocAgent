# 0046: Out-of-distribution evaluation domain — Korean legal contracts

- **Status**: accepted
- **Date**: 2026-05-15
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md)
  · [ADR 0018](./0018-korean-public-rag-bench.md) · [ADR 0002](./0002-metadata-first-retrieval.md)
  · issue #822
- **Deciders**: hskim

## Context

The current evaluation surface has two layers:

| Surface | Source | n | Domain |
|---------|--------|---|--------|
| Public synthetic | [`eval/config.yaml`](../../eval/config.yaml) | ~30 | Korean RFP (synthetic) |
| Private real-data | `eval/real_config.local.yaml` (gitignored, ADR 0005) | n=21 → n≥30 (ADR 0044) | Korean RFP (private) |
| Supplementary | KorQuAD / news QA via ADR 0018 | varies | General Korean Wikipedia / news |

Both RFP surfaces share the same lexicon, the same metadata families
(발주기관 / 사업명 / 공고번호 / 기간), and the same comparison-query
patterns.  ADR 0018's Korean public RAG bench tests *general Korean
language*, but its document structure (encyclopedia / news article) is
qualitatively different from RFP — it stresses tokenizer / embedding
quality, not the **structural retrieval patterns** the BidMate pipeline
is designed around (metadata-first, comparison-aware balanced top-k,
verifier topic grounding).

A reviewer asking *"will these numbers hold on another domain that
*looks like* an RFP?"* has no answer.  The only public signal is
ADR 0018's general-language bench, which is too far away in structure
to be informative.

This is a senior-portfolio gap — **single-domain accuracy is a
1-dimensional signal**.  This ADR closes the gap by adding a domain
that is structurally adjacent to RFP yet drawn from outside the
private corpus.

## Decision

The OOD evaluation domain is **Korean legal contracts** (한국어 법률
계약서) — service ToS, standard contracts, NDAs, government model
clauses.  Three reasons, in order of weight:

1. **Structural adjacency to RFP.**  Both domains share:
   - Section / clause / sub-clause hierarchy (제 N 조, 제 N 항)
   - Named-party metadata (갑·을 vs 발주기관·수행기관)
   - Date / amount / duration fields
   - Comparison queries are natural ("갑과 을의 책임 차이", "표준
     약관 대비 추가 조항")

   The metadata-first retrieval (ADR 0002) and comparison-balanced
   top-k strategies should *transfer* — measuring whether they do is
   the point.

2. **Public data availability.**  Korean legal contracts are released
   in the public domain by 법무부 (Ministry of Justice), 공정거래위원회
   (FTC) 표준약관 series, 정부24, and 국가법령정보센터.  Synthetic
   variants can be generated from these templates without touching
   any private RFP material.  ADR 0005 commit boundary preserved.

3. **Orthogonal to existing public benches.**  ADR 0018 (Korean
   public RAG bench) covers general-purpose Korean text.  Adding
   *another* general-language bench would not measure new things.
   Legal contracts pull on the same retrieval primitives as RFP
   (named-entity / metadata / numbered sections) but with a different
   vocabulary, so any accuracy drop attributable to vocabulary alone
   is informative.

### Concrete scope (planned, lands in E2-E4)

| PR | Output |
|----|--------|
| E2 | 50 synthetic legal-contract documents in `data/ood_synthetic_legal/`; per-doc questions covering single-doc / comparison / extraction / abstention |
| E3 | `eval/config.yaml`: new preset `ood_legal` (mirrors `agentic_full` ablation set against the legal corpus); `eval/run_ood_eval.py` runs it; LLM judge config in `eval/synthetic_judge.py` extended |
| E4 | RFP-vs-OOD delta table in `reports/ood_eval.md`; leaderboard adds an *OOD* column alongside *naive_baseline* / *agentic_full*; readme metric sync gated as usual (issue #739) |

### Minimum-bar invariant

The OOD ablation **passes** if `agentic_full` on OOD reaches
`≥ 0.6 × accuracy(RFP-full)` with non-overlapping 95% CI on the
public-synthetic RFP run.  This is not a *promotion* threshold —
it is the senior-signal *floor*: anything below means the pipeline
overfits the RFP-specific lexicon and the published numbers should
carry a generalization caveat.

The threshold sits intentionally low (60% of RFP accuracy, not 80%)
because legal vocabulary differs sharply from RFP — a 40% drop is
plausible without indicating a pipeline failure.  A *cliff* below 60%
would.

### What this ADR is *not*

- Not a claim that legal-contract retrieval is the BidMate product
  scope.  It is an *evaluation* surface only.
- Not a substitute for ADR 0044's expansion of the private real-data
  case set.  Real-data measurement remains the primary signal; OOD
  is the generalization check.
- Not a promotion path.  No leaderboard ranking, no GitHub release
  badge — just a comparison column and a delta table.

## Alternatives considered

### (a) Academic papers / scientific articles

*Rejected*: structurally too distant.  Section structure is
section / subsection, but the metadata families (author / venue /
year / DOI) have no analog in RFP.  Comparison queries are unnatural
(researchers don't ask "compare paper A and paper B's methodology"
in the way RFP reviewers compare two bids).  False-positive risk
(*any* accuracy drop blamed on domain rather than pipeline).

### (b) Medical / clinical documents

*Rejected*: Korean public-domain medical text is sparse (HIPAA-style
privacy norms apply).  Synthetic generation risks producing
unverifiable claims, which corrupts the judge signal.

### (c) English RFPs

*Rejected*: bypasses the Korean lexicon (`korean_lexicon` module) and
the morphology-aware tokenizers (ADR 0031).  Too many variables
change at once — any delta is uninterpretable.

### (d) Larger RFP private set instead of a second domain

*Rejected* as an *OOD* substitute: scaling the same domain tightens
the CI but does not test generalization.  ADR 0044 already covers
this axis.

## Consequences

**Wins**

- The portfolio gains a published OOD generalization number — a
  second axis of signal that bare RFP accuracy cannot deliver.
- Pipeline regressions that hide behind RFP-specific lexicon overfit
  become visible.
- ADR 0002 (metadata-first) and the comparison-balance retrieval
  strategy get a structural-adjacency check, not a general-language
  check.

**Costs**

- Synthetic legal-corpus generation requires care: clause text must
  be plausible without being copied from any private document; the
  judge prompt must not assume legal expertise.
- An additional eval preset means an additional CI minute and an
  additional leaderboard column.  Acceptable trade-off; latency SLO
  in `eval/config.yaml` per-preset gating handles this.
- Adds a new domain glossary entry — *contract clause* / *party* /
  *standard clause* / *amendment* — to the `korean_lexicon` module
  (E2 / E3 PR will add).

**Unchanged**

- ADR 0001 `naive_baseline` invariant: no changes to the baseline
  preset; OOD adds a *new* preset, not a modification.
- ADR 0003 answer-contract: unchanged.  Legal-contract answers use
  the same dict schema.
- ADR 0005 boundary: legal-corpus data lives in `data/ood_synthetic_legal/`
  (public synthetic) only.  No private legal corpus enters the repo.

### Re-open conditions

This ADR is re-evaluated if:

- The OOD floor (≥ 0.6 × RFP accuracy) is missed by a large margin
  (< 0.4 × RFP) — the domain is too far away to be informative.
- A different OOD domain (e.g. Korean academic papers post a
  vocabulary-matched corpus is released) becomes clearly more
  RFP-adjacent.
- The product scope shifts to actually serve legal-contract retrieval,
  at which point the legal corpus is no longer OOD.

## Verification

This ADR is plan-only.  The two preconditions it relies on are checked
at PR time; E2 / E3 / E4 PRs lift the floor invariant.

<!-- verifies-key: eval/config.yaml:naive_baseline -->
<!-- verifies-key: docs/adr/0018-korean-public-rag-bench.md:Korean public -->

E2 / E3 / E4 PRs must show:

1. `data/ood_synthetic_legal/` exists with ≥ 50 documents (E2)
2. `eval/config.yaml` has an `ood_legal` preset (E3)
3. `reports/ood_eval.md` shows the RFP↔OOD delta table (E4)
4. The floor invariant `accuracy(ood_legal-full) ≥ 0.6 × accuracy(rfp-full)` holds
5. ADR 0001 `naive_baseline` preset unchanged on the RFP surface
