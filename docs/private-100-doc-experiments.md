# Private 100-doc Experiments

이 문서는 private 100-doc RFP 평가 결과를 포트폴리오용 근거로 남기되, 원문이나 개별 예측이 커밋되지 않도록 하는 aggregate-only 운영 기준이다. 실제 private 원문과 per-example output은 로컬 `artifacts/benchmarks/` 아래에만 둔다.

## Naming

- Run ID: `private100_<profile>_<YYYYMMDDTHHMMSSZ>`
- Dataset ID: `private100_rfp_anon_vN`
- Document ID: `private100-doc-###`
- Case ID: `private100-case-###`

`profile`은 `text_v1`, `visual_v2`, `visual_v2_hierarchical`처럼 입력/파이프라인 차이를 설명하는 익명 이름만 사용한다. 원본 기관명, 사업명, 파일명, 도메인 특화 약어는 ID에 넣지 않는다.

## Commit Boundary

커밋 가능:

- anonymized run/dataset/case/doc id
- corpus size 같은 복원 불가능한 집계 metadata
- overall aggregate metrics
- hard-case slice aggregate metrics
- local artifact manifest path reference
- private/public aggregate delta table

커밋 금지:

- raw private documents
- original filenames
- organization or project identifiers
- raw predictions, traces, per-example dumps
- OCR snippets, citation snippets, query text, answer text
- config snapshot 안의 private path 또는 source metadata

## Summary Flow

private run은 로컬 manifest를 먼저 만든 뒤, registry/docs에는 aggregate만 반영한다. 실측 private 수치를 공개 커밋에 남길 때도 아래 경계를 지킨다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest artifacts/benchmarks/<private100_run_id>/run_manifest.json
```

이 저장소의 예시 fixture는 흐름 검증용이며 실측 성과가 아니다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest benchmarks/examples/private100_aggregate_manifest.example.json \
  --registry /private/tmp/private100-registry.json \
  --docs /private/tmp/private100-summary.md
```

`docs/ablation-results.md`는 registry에 public aggregate와 private aggregate가 함께 있을 때 `Public vs Private Aggregate` 표를 생성한다. 이 표는 `primary_metrics`의 집계 값만 사용하며 raw query, prediction, trace는 사용하지 않는다.

## Example Aggregate Comparison

아래 값은 `benchmarks/examples/private100_aggregate_manifest.example.json`에 들어 있는 anonymized fixture 예시다. 실측 private 100-doc 결과로 해석하면 안 된다.

| Metric | Public primary | Private fixture primary | Delta |
|---|---:|---:|---:|
| Cases | 26 | 100 | +74 |
| Accuracy | 1.000 | 0.810 | -0.190 |
| Groundedness | 1.000 | 0.790 | -0.210 |
| Citation Precision | 1.000 | 0.730 | -0.270 |
| Citation Grounding | 1.000 | 0.700 | -0.300 |
| Abstention | 1.000 | 0.770 | -0.230 |

실제 실험에서는 이 표보다 `by_hardcase_category`를 우선 확인한다. 전체 성능 하락이 `table_heavy`나 `noisy_ocr` 같은 slice에 집중되면 parser/layout 또는 citation grounding 쪽 병목으로 분류한다.
## Real-data Decision Log

이 섹션은 retrieval / verifier policy 변경의 **real-data aggregate-only** before/after를 기록한다. ADR 0005의 commit boundary를 준수해 case ID·query text·doc ID·파일명은 절대 포함하지 않는다. 목적은 "왜 이렇게 짰는가?" 그리고 "그 결정이 real-data에서 어떻게 작동했는가?" 두 질문에 답할 수 있는 자료를 남기는 것이다.

### Entry: 2026-05-11 — Partial-topic grounding @ fraction=0.5 (#69)

**Change.** `verify_evidence`에 `allow_partial_topic` 추가, 마지막 retrieval 시도에서 verification topics의 ≥50%가 evidence에 매칭되면 `partial_topic_grounding` reason으로 `verified=True`를 반환하고 status는 `partial`로 surface ([ADR 0004](./adr/0004-verifier-retry-policy.md) anticipated knob).

**Surface.** Local private real-data set (`eval/real_config.local.yaml`, 21 cases, 17 answerable + 4 intended-abstention). 동일 index, 동일 case set, 동일 tooling으로 pre-commit (2f76671) vs post-commit (2249498) 비교.

**Aggregate diff (case set N=21):**

| Metric | Before | After | Δ |
|---|---:|---:|---:|
| accuracy | 0.353 | 0.471 | **+0.118** ✅ |
| groundedness | 0.476 | 0.476 | · |
| citation_precision | 0.381 | 0.286 | −0.095 ⚠️ |
| claim_citation_alignment | 0.786 | 0.692 | −0.093 ⚠️ |
| answer_format_compliance | 0.524 | 0.429 | −0.095 ⚠️ |
| abstention (intended) | 1.000 | 0.500 | **−0.500** ⚠️ |
| retry_reason: `topic_not_grounded` (count) | 18 | 12 | −6 ✅ |

**Status distribution diff (anonymized case counts only):**

| Slice | Status | Before | After |
|---|---|---:|---:|
| answerable (17) | supported | 7 | 7 |
|  | partial | 0 | **4** ↑ |
|  | insufficient | 10 | **6** ↓ |
| intended-abstention (4) | insufficient | 4 | **2** ↓ |
|  | partial | 0 | **2** ↑ ⚠️ |

**Interpretation.**

- **Recovery works.** 4 / 17 answerable cases recovered from `insufficient` → `partial`; net accuracy gain +0.118. `topic_not_grounded` retry signal dropped one-third (18 → 12), confirming the strict→relaxed staging is engaging as designed.
- **False-positive on intended abstention.** 2 of 4 intended-abstention cases flipped from `insufficient` → `partial`. Issue #69's own acceptance criterion ("intended abstention cases remain abstentions") is **partially violated** at fraction=0.5. The public synthetic eval did not catch this because its out-of-corpus cases are crisply disjoint from the corpus; real-data abstention queries share incidental topic tokens with in-corpus content.
- **Citation precision drop is mechanical.** Partial answers cite chunks that ground only some of the requested topics; the `partial` status itself is the contract telling callers the answer is weak. Same shape as the public synthetic delta in PR #88.

**Decision.**

Ship #69 as-is in main with this finding logged, then **tighten** in a follow-up: the false-positive rate on intended abstention is too high to accept long-term. Candidates for the tighten PR — pick by ablation:

1. Raise `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` from 0.5 toward 0.66 or 0.75.
2. Gate partial-topic acceptance on `len(topics) >= 2` so single-topic queries (more likely to be out-of-corpus phrasing) can't trigger it.
3. Raise the `low_top_score` floor (currently 0.18) on the relaxed stage only.

Follow-up issue tracked in the meta roadmap (#49).

**How this entry was produced (reproducibility note).**

```bash
# Same index, same config, same tooling — run on pre-#69 commit
# (2f76671) and current main, then diff aggregate-only fields. The
# per-case results are NOT committed; only the numbers above.
git worktree add /tmp/pre-69 2f76671
python3 eval/run_eval.py --index_dir data/index/real100 \
  --output_dir /tmp/real100-before --config eval/real_config.local.yaml
python3 eval/run_eval.py --index_dir data/index/real100 \
  --output_dir /tmp/real100-after  --config eval/real_config.local.yaml
# (aggregate fields then transcribed into the table above)
```

## Real-data Eval History

Chronological record of real-data aggregate snapshots committed under `reports/real100/history/`. The table is auto-generated; do not edit between the markers below. Each row corresponds to one deliberate `make real-eval-baseline-update` invocation, so the chain shows how real-data metrics moved as the repo changed.

<!-- real-eval-history-start -->

Auto-generated by `scripts/render_real_eval_history.py`. Each row is one committed aggregate snapshot under `reports/real100/history/`. Aggregate-only per ADR 0005 — per-case data is never read by this script.

_No real-data history entries yet. Run `make real-eval-baseline-update` to seed the first snapshot._

<!-- real-eval-history-end -->
