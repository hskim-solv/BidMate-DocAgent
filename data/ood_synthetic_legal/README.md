# OOD synthetic Korean legal contracts

50-document corpus implementing [ADR 0046](../../docs/adr/0046-ood-evaluation-domain-selection.md)'s out-of-distribution evaluation surface.  These files are *public synthetic* — generated deterministically from public-domain 표준약관 patterns (공정거래위원회 / 법무부) so they live in the repo without violating the ADR 0005 private/public boundary.

## Composition

5 contract categories × 10 instances = **50 documents**.

| Category | Korean label | Pattern source |
|---|---|---|
| `service_tos` | 서비스 이용약관 | 공정위 모델약관 (전자상거래·SaaS) |
| `nda` | 비밀유지계약 (NDA) | 표준 양자 NDA 보일러플레이트 |
| `consortium` | 컨소시엄 협약 | 정부 R&D 사업 공동개발 협약 |
| `data_processing` | 개인정보 처리 위탁계약 | 개인정보 보호법 표준 양식 |
| `sla` | 서비스 수준 협약 (SLA) | IT 서비스 운영 SLA 표준 |

Each document carries:

- `doc_id`: `legal-{category}-{NN}` (e.g. `legal-nda-01`)
- `title`: category + 양 당사자 + instance ID
- `agency` (BidMate `agency` field): party A (갑)
- `project`: category Korean label
- `metadata`: `category`, `party_a`, `party_b`, `effective_date`, `amount_krw`, `instance_index`
- `sections`: 5 clauses (제1조 ~ 제5조), each ~50–100자

## Regeneration

Reproducible:

```bash
python3 scripts/generate_ood_legal.py --output data/ood_synthetic_legal/
```

Seed (`SEED = 20260515`) and template tables are frozen in [`scripts/generate_ood_legal.py`](../../scripts/generate_ood_legal.py).  Re-running with the same flags overwrites every file byte-for-byte; commit the diff only if you intend to change the template or add a new category.

`manifest.json` is rewritten on each run with `count`, `by_category`, and `seed` so downstream eval scripts can sanity-check the corpus surface before running.

## Verification

[`tests/test_ood_legal_dataset.py`](../../tests/test_ood_legal_dataset.py) asserts:

- Exactly 50 files + `manifest.json`
- 10 documents per category
- Schema sanity: every doc has the required keys + 5 sections
- Determinism: regeneration produces byte-identical output

## Intent recap (ADR 0046)

This corpus is *not* a BidMate product surface — it exists so the eval pipeline can answer *"do the retrieval primitives transfer beyond the RFP lexicon?"*.  The minimum-bar invariant (E4 enforces) is `accuracy(ood_legal-full) ≥ 0.6 × accuracy(rfp-full)`.  See [`docs/adr/0046-ood-evaluation-domain-selection.md`](../../docs/adr/0046-ood-evaluation-domain-selection.md) for the threshold derivation.
