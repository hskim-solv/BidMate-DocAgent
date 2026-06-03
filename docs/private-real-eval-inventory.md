# Private Real-Eval Local Path Inventory

이 문서는 private real-eval 이 실제 코드에서 참조하는 local/private 경로를
required input, optional input, regenerable cache, output artifact,
deprecated/dead reference 로 분리한다. 조사 기준은 repo-wide `rg` 로
`real_config|REAL_EVAL|data_list|files_kordoc|data/files|eval_summary|reports/real100_v2|cache|cached|artifacts|runs|index|indices|embedding|embeddings|faiss|chroma|vector|bm25|retrieval|ocr|parsed|layout|page_images|thumbnails|jsonl|parquet|sqlite|\.db`
패턴을 검색하고, `find data eval reports scripts tests -maxdepth 4` 로
실제 tree 를 대조한 결과다.

Current claim-bearing private eval work uses the `real100_v2` config and
aggregate surface. Legacy compatibility configs remain documented because
direct/local tools still accept them, but they are not the current evidence
surface for new PRs, claims, or handoffs.

## Inventory

| path | category | referenced by | required before run? | can regenerate? | recommended env/config key |
|---|---|---|---:|---:|---|
| `data/private/real100_v2/real_config_v2.local.yaml` | required input for current private eval | `REAL100_V2_CONFIG`, `make real-eval-v2-*`, v2 judge/rationality targets | yes | no | `REAL100_V2_CONFIG` |
| `eval/real_config.local.yaml` | compatibility local input | `eval/run_eval.py --config`, `scripts/smoke_real.sh`, case proposer/promote tools | yes for direct compatibility runs; no for current v2 claim surface | no | `REAL_EVAL_CONFIG` |
| `data/data_list.csv` | required input | `scripts/validate_data_list.py`, `scripts/build_index.py --metadata_csv`, `eval/case_proposer.py`, `scripts/eda_real100.py` | yes | no | `REAL_EVAL_DATA_LIST`, `real_eval.data_list` |
| `data/files/` | required input | `scripts/build_index.py --files_dir`, `scripts/validate_data_list.py --files_dir`, kordoc source hashing | yes | no | `REAL_EVAL_DATA_DIR`, `real_eval.document_dirs.default` |
| `data/files_kordoc/` | regenerable cache | `ingestion._resolve_kordoc_cache_dir`, `scripts/build_kordoc_manifest.py`, `BIDMATE_KORDOC_CACHE_DIR` | no | yes | `REAL_EVAL_KORDOC_DATA_DIR`, `real_eval.document_dirs.kordoc` |
| `.cache/real_eval/` | regenerable cache | resolver-owned root for OCR/parsed/layout/embedding cache placement | no | yes | `REAL_EVAL_CACHE_DIR`, `real_eval.cache.root` |
| `data/index/real100_v2/` | regenerable cache | `app.py --input_dir`, `eval/run_eval.py --index_dir`, `scripts/smoke_real.sh`, `make real-eval-v2-chroma` | no | yes | `REAL_EVAL_INDEX_DIR`, `real_eval.index.root`; hashing/offline surface |
| `data/index/real100_minilm/` | deprecated / removed artifact | 폐지된 real-eval-minilm stub(archive-only) | no | yes | `REAL_EVAL_INDEX_DIR`; MiniLM sentence-transformers baseline |
| `data/index/real100_m3/` | deprecated / removed artifact | 폐지된 real-eval-semantic stub(archive-only) | no | yes | `REAL_EVAL_INDEX_DIR`; BGE-M3 semantic comparison |
| `data/index/real100_kordoc/` | deprecated / removed artifact | Phase 4 metadata retrieval reports(archive-only) | no | yes | `REAL_EVAL_INDEX_DIR` for kordoc-only runs |
| `outputs/real100_v2/` | output artifact | `scripts/smoke_real.sh`, `app.py --output_dir` | no | yes | `OUTPUT_DIR` |
| `reports/real100_v2/` | output artifact | `eval/run_eval.py --output_dir`, `scripts/run_real_eval_delta.py` | no | yes | `REAL_EVAL_REPORT_DIR`, `real_eval.reports.output_dir` |
| `reports/real100_v2/eval_summary.json` | output artifact | `make real-eval-v2-chroma`(`-chroma-llm`), `scripts/run_real_eval_delta.py --head`, ship PR body cache check | no | yes | derived from `REAL_EVAL_REPORT_DIR` |
| `reports/real100_v2/baseline.aggregate.json` | optional input | `scripts/run_real_eval_delta.py --base`, baseline provenance checks | no | no | `REAL_EVAL_BASELINE_SUMMARY`, `real_eval.reports.baseline_summary` |
| `reports/real100_v2/judge.local.json` | output artifact | `scripts/llm_judge.py`, `scripts/run_real_eval_delta.py` optional fold-in | no | yes | `REAL_EVAL_REPORT_DIR` |
| `reports/real100_v2/traces/` | output artifact | trace/rationality judge workflows | no | yes | `REAL_EVAL_REPORT_DIR` |
| `reports/real100_v2/judge.aggregate.json` | aggregate output artifact | `make real-eval-v2-judge`, `scripts/llm_judge.py --out-aggregate` | no | yes | `REAL100_V2_REPORT_DIR` |
| `reports/real100_v2/judge_ragas.aggregate.json` | aggregate output artifact | `make real-eval-v2-ragas-judge`, `eval/judges/llm_judge.py --out-aggregate` | no | yes | `REAL100_V2_REPORT_DIR` |
| `reports/real100_v2/rationality.aggregate.json` | aggregate output artifact | `make real-eval-v2-rationality-judge`, `scripts/run_rationality_judge.py` | no | yes | `REAL100_V2_REPORT_DIR` |
| `reports/real100_v2/rationality.md` | local review output artifact | `make real-eval-v2-rationality-judge`, `scripts/run_rationality_judge.py` | no | yes | `REAL100_V2_REPORT_DIR`; gitignored |
| `reports/real100_v2_chroma_llm/*.local.json` | output artifact | v2 judge/rationality make targets | no | yes | `REAL100_V2_JUDGE_INPUT_REPORT_DIR`, `REAL100_V2_RATIONALITY_INPUT_REPORT_DIR` |
| `reports/real100_v2_chroma_llm/traces/` | output artifact | `eval/run_eval.py`, `scripts/run_rationality_judge.py` | no | yes | `REAL100_V2_RATIONALITY_INPUT_REPORT_DIR` |
| `reports/judge_cache/` | regenerable cache | RAGAS/LLM judge cache comments in `scripts/run_real_eval_delta.py` and ADR 0014 | no | yes | judge CLI cache args |
| `reports/rationality_cache/` | regenerable cache | rationality judge cache option | no | yes | rationality judge CLI cache args |
| `reports/proposed/*.local.yaml` | output artifact | case proposer/review/promote cycle | no | yes | case proposer CLI args |
| `artifacts/runs/` | output artifact | `scripts/run_harness.py`, harness docs | no | yes | harness config / CLI |
| `artifacts/matrices/` | output artifact | `scripts/run_harness.py --matrix`, harness docs | no | yes | harness config / CLI |
| `harness/*.local.yaml` | required input for harness real only | `make harness-real`, `scripts/run_harness.py` | yes for harness-real | no | harness CLI `--config` |
| `reports/retrieval/phase35_m3_20260518T090328Z/` | deprecated / removed artifact | retired Phase 3.5 report | no | no | none |
| `reports/retrieval/phase35_m3_20260518T214937Z_kordoc_no_m3/` | deprecated / removed artifact | retired Phase 3.5 report | no | no | none |

## `data/files/` vs `data/files_kordoc/`

`data/files/` 는 private 원본 문서 디렉터리다. `data_list.csv` 의 `파일명`
컬럼과 `scripts/build_index.py --files_dir` 가 이 디렉터리를 required
input 으로 사용한다. 원본 HWP/PDF 가 없으면 cache 를 재생성할 수 없으므로
friendly error 로 중단해야 한다.

`data/files_kordoc/` 는 원본 문서에서 추출한 kordoc Markdown cache 다.
`ingestion._resolve_kordoc_cache_dir` 는 `BIDMATE_KORDOC_CACHE_DIR` 를 먼저 보고,
없으면 `<files_dir>_kordoc` sibling convention 을 사용한다. 이 디렉터리는
있으면 live `npx kordoc` 를 건너뛰는 cache bypass 로 쓰이고, 없으면 원본
문서에서 재생성 가능해야 한다. 따라서 required input 이 아니다.

## Cache, Index, Report Rules

- Cache/index 는 missing 이어도 hard failure 가 아니다. 원본 input 이 있으면
  재생성(regeneration) 경로로 진행한다.
- Existing legacy/non-v2 private `real100` index 의 metadata 가
  `num_documents >= 50` 이고 `0 < num_chunks <= 1000` 이면 stale/invalid CSV
  fallback index 로 표시한다. 이 heuristic 은 archive-only v1/legacy path 점검용이며,
  현재 `real100_v2` index claim 은 `data/index/real100_v2/` manifest 와
  `make real-eval-v2-guard` 로 별도 검증한다.
- `reports/real100_v2/eval_summary.json` 은 output artifact 다. 실행 전 required
  input 으로 요구하면 안 된다.
- Baseline comparison 은 `REAL_EVAL_BASELINE_SUMMARY` 또는
  `real_eval.reports.baseline_summary` 로 명시 분리한다.

## Removed 898-Chunk History

`data/index/real100_m3` 의 898-chunk 이력과 두 `phase35_m3_*` report 는
private real100 계열에서 CSV `text` fallback 으로 생성된 insufficient corpus
artifact 로 retired 처리했다. Public fixture smoke corpus 의 작은 index 는 이
정책의 적용 대상이 아니며, Phase 2 chunking ablation 의 `12843`, `30937`,
`55281` 같은 의도적 chunking 변형도 제거 대상이 아니다.
