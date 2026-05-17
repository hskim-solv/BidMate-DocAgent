# PR Body Translation Log

> 영문 PR 본문을 한국어 압축본으로 교체한 audit trail. GitHub PR body
> metadata 변경만, 코드/식별자/`Closes #N` 보존. issue [#918](https://github.com/hskim-solv/BidMate-DocAgent/issues/918)
> (PR-C of 5-PR stacked readability 시리즈).

## 정책

- **번역 대상**: PR 본문의 자연어 prose. 모든 식별자 (ADR 번호, PR/issue 번호,
  파일 경로, `make` 타깃, env var, `Closes #N`) 보존.
- **압축 목표**: ~50% 감축. 한국어 종결 어미는 "~다/~한다", 표/코드 블록/
  메트릭 수치 유지.
- **검증**: 적용 전 식별자 set diff 자동 검사 (before ⊆ after 보장).

## 일괄 처리: 2026-05-17 — 머지 PR 10개

| PR | 제목 (English) | Before (chars) | After (chars) | 압축률 |
|---:|---|---:|---:|---:|
| [#914](https://github.com/hskim-solv/BidMate-DocAgent/pull/914) | M4-A axis-A real_scale_v2_distractor rebuild (ADR 0050) | 5324 | 4435 | 83% |
| [#913](https://github.com/hskim-solv/BidMate-DocAgent/pull/913) | repoint ADR template verifies-key example | 2338 | 1703 | 72% |
| [#910](https://github.com/hskim-solv/BidMate-DocAgent/pull/910) | env-gated verbose trace enrichment for verifier dump | 3496 | 2946 | 84% |
| [#907](https://github.com/hskim-solv/BidMate-DocAgent/pull/907) | strip kordoc ToC leader-dots + page-footer noise | 3195 | 2710 | 84% |
| [#905](https://github.com/hskim-solv/BidMate-DocAgent/pull/905) | demote kordoc over-promoted bullet headings | 3166 | 2515 | 79% |
| [#903](https://github.com/hskim-solv/BidMate-DocAgent/pull/903) | nested_table_loss tracking in chunk_health | 3813 | 3283 | 86% |
| [#901](https://github.com/hskim-solv/BidMate-DocAgent/pull/901) | pin kordoc HWP/PDF loaders in smoke_real.sh | 2549 | 2404 | 94% |
| [#895](https://github.com/hskim-solv/BidMate-DocAgent/pull/895) | replace pyhwp backend with kordoc (ADR 0049) | 8798 | 7689 | 87% |
| [#894](https://github.com/hskim-solv/BidMate-DocAgent/pull/894) | eval-framework-progressive-audit 5-phase skill | 2161 | 1338 | 61% |
| [#889](https://github.com/hskim-solv/BidMate-DocAgent/pull/889) | retrieval-eval 4-phase measurement protocol skill | 2353 | 2242 | 95% |

**합계**: 37,193c → 31,265c (84%, -5,928c 감축).

## 검증 결과 (적용 전 자동 검사)

10 PR 모두 다음 식별자 set diff `before ⊆ after`:

- ADR 번호 (`ADR 0NNN`)
- PR/issue 번호 (`#NNN`)
- 파일 경로 (``\`*.py|.sh|.md|.yaml|.yml|.json|.jsonl\` ``)
- `make` 타깃 (``\`make <target>\` ``)
- env var (`BIDMATE_*`)
- ADR 0007 컨벤션 키워드 (`Closes #N`)

## 일괄 처리: 2026-05-17 (backfill) — 머지 PR 98개 (#530–#924)

PR-C (#923, 최근 10개) 범위 밖 머지 PR의 영문 본문 일괄 한국어 압축. 5 batch × ~22개 parallel agent 처리.

<details>
<summary>전체 98 PR 표 (펼치기)</summary>

| PR | 제목 (English) | Before (chars) | After (chars) | 압축률 |
|---:|---|---:|---:|---:|
| [#924](https://github.com/hskim-solv/BidMate-DocAgent/pull/924) | chore(test): parallel pytest (xdist) + CI ruff gate (closes #915) | 3153 | 2723 | 86% |
| [#899](https://github.com/hskim-solv/BidMate-DocAgent/pull/899) | docs(eda): RAG pipeline EDA — 7-axis pipeline dynamics | 3487 | 3170 | 90% |
| [#884](https://github.com/hskim-solv/BidMate-DocAgent/pull/884) | feat(eval): case-proposer csv_metadata backend (closes #880) | 4862 | 3835 | 78% |
| [#881](https://github.com/hskim-solv/BidMate-DocAgent/pull/881) | fix(verifier): close marker-bypass / marker-tag-confusion attack ve... | 1639 | 1416 | 86% |
| [#879](https://github.com/hskim-solv/BidMate-DocAgent/pull/879) | feat(eval): by_metadata_field + abstention_calibration aggregates (... | 4708 | 3936 | 83% |
| [#876](https://github.com/hskim-solv/BidMate-DocAgent/pull/876) | feat(hooks): PreToolUse refuses new ADR Write without Verification ... | 3109 | 2260 | 72% |
| [#875](https://github.com/hskim-solv/BidMate-DocAgent/pull/875) | fix(eval): case_proposer reads BOM-prefixed data_list.csv (utf-8-sig) | 1686 | 1404 | 83% |
| [#874](https://github.com/hskim-solv/BidMate-DocAgent/pull/874) | refactor(rag_core): pin ADR 0045 leaf invariant with AST regression... | 2882 | 2145 | 74% |
| [#871](https://github.com/hskim-solv/BidMate-DocAgent/pull/871) | feat(hooks): gh pr create stacked guard (closes #865) | 3499 | 2623 | 74% |
| [#869](https://github.com/hskim-solv/BidMate-DocAgent/pull/869) | test(concurrency): multi-threaded query determinism regression (clo... | 2510 | 1935 | 77% |
| [#867](https://github.com/hskim-solv/BidMate-DocAgent/pull/867) | feat(eval): ood_legal preset + Makefile targets (closes #864) | 3914 | 3094 | 79% |
| [#863](https://github.com/hskim-solv/BidMate-DocAgent/pull/863) | docs(rag_core): document _phase_* mutation contracts + AST-based re... | 3475 | 2630 | 75% |
| [#861](https://github.com/hskim-solv/BidMate-DocAgent/pull/861) | refactor(rag_core): extract ingestion + index I/O to rag_indexing (... | 4317 | 3648 | 84% |
| [#857](https://github.com/hskim-solv/BidMate-DocAgent/pull/857) | feat(vector_store): Qdrant docker compose integration smoke (closes... | 3488 | 2823 | 80% |
| [#855](https://github.com/hskim-solv/BidMate-DocAgent/pull/855) | docs(rag_core): _PROCESS_WARM multi-worker + long-tail caveat (clos... | 3757 | 2563 | 68% |
| [#854](https://github.com/hskim-solv/BidMate-DocAgent/pull/854) | feat(eval): case-proposer prioritizes uncovered docs for ADR 0044 e... | 4379 | 3479 | 79% |
| [#852](https://github.com/hskim-solv/BidMate-DocAgent/pull/852) | feat(testing): clear_model_caches() + autouse session-teardown fixt... | 3750 | 2615 | 69% |
| [#851](https://github.com/hskim-solv/BidMate-DocAgent/pull/851) | fix(eval): metadata_backend discriminator for full vs full_llm_meta... | 3918 | 3074 | 78% |
| [#850](https://github.com/hskim-solv/BidMate-DocAgent/pull/850) | feat(eval): OOD Korean legal contracts synthetic corpus (closes #848) | 3456 | 2789 | 80% |
| [#849](https://github.com/hskim-solv/BidMate-DocAgent/pull/849) | feat(eval): whitelist by_hardcase_category in ADR 0005 commit boundary | 4073 | 3369 | 82% |
| [#847](https://github.com/hskim-solv/BidMate-DocAgent/pull/847) | refactor(rag_core): extract embedding primitives to rag_embedding (... | 4637 | 3934 | 84% |
| [#844](https://github.com/hskim-solv/BidMate-DocAgent/pull/844) | feat(governance): pre-commit guard for ADR ↔ README index parity (c... | 3807 | 3190 | 83% |
| [#838](https://github.com/hskim-solv/BidMate-DocAgent/pull/838) | docs(readme): annotate ablation table with ADR Status mapping (clos... | 3215 | 2542 | 79% |
| [#837](https://github.com/hskim-solv/BidMate-DocAgent/pull/837) | feat(vector_store): Qdrant production server URL mode (closes #834) | 4278 | 3446 | 80% |
| [#836](https://github.com/hskim-solv/BidMate-DocAgent/pull/836) | fix(retrieval): include schema_version + chunk count in BM25 cache ... | 3522 | 2669 | 75% |
| [#835](https://github.com/hskim-solv/BidMate-DocAgent/pull/835) | fix(ci): pr-judge aggregate upload hard-fails on missing file (clos... | 2647 | 2095 | 79% |
| [#832](https://github.com/hskim-solv/BidMate-DocAgent/pull/832) | fix(governance): ADR_FILENAME_RE accepts mixed-case slugs (closes #... | 3010 | 2504 | 83% |
| [#831](https://github.com/hskim-solv/BidMate-DocAgent/pull/831) | docs(adr): add Measurement gaps section to ADR 0004 + 0008 (closes ... | 3218 | 2511 | 78% |
| [#827](https://github.com/hskim-solv/BidMate-DocAgent/pull/827) | fix(docs): repair cross-refs to relocated docs after batch reorg (c... | 3351 | 2806 | 83% |
| [#825](https://github.com/hskim-solv/BidMate-DocAgent/pull/825) | feat(governance): PreToolUse plan-slug race detector hook (closes #... | 3439 | 2521 | 73% |
| [#824](https://github.com/hskim-solv/BidMate-DocAgent/pull/824) | docs(adr): 0046 OOD evaluation domain = Korean legal contracts (clo... | 2635 | 1963 | 74% |
| [#820](https://github.com/hskim-solv/BidMate-DocAgent/pull/820) | docs(adr): ADR 0047 meta-ADR — solo-author governance (closes #817) | 5019 | 3946 | 78% |
| [#814](https://github.com/hskim-solv/BidMate-DocAgent/pull/814) | ci: narrow ADR 0032 embedding-spread gate to actual embedding diff ... | 3042 | 2222 | 73% |
| [#809](https://github.com/hskim-solv/BidMate-DocAgent/pull/809) | docs(adr): ADR 0043 amend — threat model + label authorization + op... | 2587 | 2089 | 80% |
| [#807](https://github.com/hskim-solv/BidMate-DocAgent/pull/807) | refactor(retrieval): import comparison_targets_for_analysis directl... | 3354 | 2818 | 84% |
| [#806](https://github.com/hskim-solv/BidMate-DocAgent/pull/806) | docs(claude): karpathy-guidelines conflict policy + upstream fetche... | 2328 | 1805 | 77% |
| [#802](https://github.com/hskim-solv/BidMate-DocAgent/pull/802) | fix(eval): retrieval_only redefined as raw retrieval ablation (clos... | 3276 | 2683 | 81% |
| [#797](https://github.com/hskim-solv/BidMate-DocAgent/pull/797) | feat(vector_store): add query_by_indices Protocol method to skip fu... | 4946 | 3884 | 78% |
| [#796](https://github.com/hskim-solv/BidMate-DocAgent/pull/796) | feat(governance): ADR Consequences verification lint (closes #793) | 4961 | 3730 | 75% |
| [#794](https://github.com/hskim-solv/BidMate-DocAgent/pull/794) | feat(eval): table_extraction_metrics — cell F1 + table recall + mer... | 2246 | 1819 | 80% |
| [#791](https://github.com/hskim-solv/BidMate-DocAgent/pull/791) | fix(retrieval+trace): raise on dense_similarity shape mismatch + lo... | 4283 | 3249 | 75% |
| [#788](https://github.com/hskim-solv/BidMate-DocAgent/pull/788) | refactor(eval): move judge modules to eval/judges/ subpackage | 1708 | 1423 | 83% |
| [#787](https://github.com/hskim-solv/BidMate-DocAgent/pull/787) | fix(ingestion): HwpNativeLoader falls back on AttributeError (close... | 4588 | 3279 | 71% |
| [#786](https://github.com/hskim-solv/BidMate-DocAgent/pull/786) | feat(eval): compare_table_parsers diff tool for PR-A0/A1 dumps (PR-... | 2132 | 1676 | 78% |
| [#777](https://github.com/hskim-solv/BidMate-DocAgent/pull/777) | feat(eval): Upstage Document Parser extraction script (PR-A1, close... | 1824 | 1453 | 79% |
| [#775](https://github.com/hskim-solv/BidMate-DocAgent/pull/775) | fix(docs): repair external references to relocated docs after batch... | 1346 | 1114 | 82% |
| [#774](https://github.com/hskim-solv/BidMate-DocAgent/pull/774) | feat(answer): enforce status_reason.code as enum (closes #759) | 4175 | 3235 | 77% |
| [#772](https://github.com/hskim-solv/BidMate-DocAgent/pull/772) | feat(eval): expose hwp_native_rate / hwp_fallback_rate in by_format... | 4036 | 3197 | 79% |
| [#766](https://github.com/hskim-solv/BidMate-DocAgent/pull/766) | docs(adr): 0045 rag_core leaf migration plan (closes #762) | 2664 | 2184 | 81% |
| [#765](https://github.com/hskim-solv/BidMate-DocAgent/pull/765) | feat(governance): automate ADR number reservation + collision check... | 4286 | 3393 | 79% |
| [#749](https://github.com/hskim-solv/BidMate-DocAgent/pull/749) | feat(eval): HWP table extraction golden schema + pyhwp dumper (PR-A... | 2632 | 2130 | 80% |
| [#744](https://github.com/hskim-solv/BidMate-DocAgent/pull/744) | feat(ingestion): aggregate HWP fallback rate + chunk health metrics... | 6948 | 5838 | 84% |
| [#740](https://github.com/hskim-solv/BidMate-DocAgent/pull/740) | docs(adr)+test: ADR 0044 real100 eval case expansion policy + struc... | 3128 | 2340 | 74% |
| [#737](https://github.com/hskim-solv/BidMate-DocAgent/pull/737) | feat(ci): pr-judge.yml label-gated live LLM-judge workflow (closes ... | 4357 | 3421 | 78% |
| [#729](https://github.com/hskim-solv/BidMate-DocAgent/pull/729) | feat(governance): hook-fires rolling-window summary (closes #716) | 3542 | 2836 | 80% |
| [#727](https://github.com/hskim-solv/BidMate-DocAgent/pull/727) | docs(adr): ADR 0043 — PR-level live LLM-judge cadence, label-gated ... | 2103 | 1644 | 78% |
| [#726](https://github.com/hskim-solv/BidMate-DocAgent/pull/726) | docs: reference karpathy-guidelines skill in CLAUDE.md | 2367 | 1810 | 76% |
| [#713](https://github.com/hskim-solv/BidMate-DocAgent/pull/713) | docs(docs): move eval/ablation docs to docs/eval/ | 2053 | 1715 | 83% |
| [#712](https://github.com/hskim-solv/BidMate-DocAgent/pull/712) | docs(docs): move agentic/planner docs to docs/agentic/ | 1333 | 1129 | 84% |
| [#710](https://github.com/hskim-solv/BidMate-DocAgent/pull/710) | docs(docs): move HWP docs to docs/hwp/ | 1297 | 1112 | 85% |
| [#709](https://github.com/hskim-solv/BidMate-DocAgent/pull/709) | docs(docs): move operations/deployment docs to docs/operations/ | 1417 | 1117 | 78% |
| [#708](https://github.com/hskim-solv/BidMate-DocAgent/pull/708) | docs(docs): move real-data docs to docs/real-data/ | 1658 | 1351 | 81% |
| [#707](https://github.com/hskim-solv/BidMate-DocAgent/pull/707) | docs(docs): move retrieval/reranker docs to docs/retrieval/ | 1235 | 1034 | 83% |
| [#706](https://github.com/hskim-solv/BidMate-DocAgent/pull/706) | docs(docs): move vision/multichannel docs to docs/vision/ | 1145 | 913 | 79% |
| [#696](https://github.com/hskim-solv/BidMate-DocAgent/pull/696) | feat(eval): retrieval_only ablation preset for chunk_recall@k track... | 1853 | 1469 | 79% |
| [#695](https://github.com/hskim-solv/BidMate-DocAgent/pull/695) | fix(test): isolate retry-abstention test from shared data/raw index... | 1631 | 1281 | 78% |
| [#693](https://github.com/hskim-solv/BidMate-DocAgent/pull/693) | fix(test): regenerate naive_baseline golden after HWP fixture addit... | 1595 | 1200 | 75% |
| [#692](https://github.com/hskim-solv/BidMate-DocAgent/pull/692) | fix(test): replace FORBIDDEN_KEYS substring check with exact key se... | 1101 | 925 | 84% |
| [#691](https://github.com/hskim-solv/BidMate-DocAgent/pull/691) | feat(eval): chunk_recall_at_20 + ndcg_at_20 retrieval metrics (clos... | 2068 | 1629 | 78% |
| [#678](https://github.com/hskim-solv/BidMate-DocAgent/pull/678) | feat(react): ReAct orchestrator + LLMPlanner + agent_react preset (... | 2221 | 2105 | 94% |
| [#668](https://github.com/hskim-solv/BidMate-DocAgent/pull/668) | feat(eval): expand multihop synthetic slice to n=15, ADR 0033 accep... | 2005 | 1730 | 86% |
| [#666](https://github.com/hskim-solv/BidMate-DocAgent/pull/666) | feat(chunking): expose auto-strategy section-detection rate in inge... | 1921 | 1574 | 81% |
| [#663](https://github.com/hskim-solv/BidMate-DocAgent/pull/663) | test(chunking): lock-in Korean sentence_split behavior on abbreviat... | 1257 | 1069 | 85% |
| [#660](https://github.com/hskim-solv/BidMate-DocAgent/pull/660) | feat(planner): Planner Protocol + StaticPlanner foundation (closes ... | 1487 | 1408 | 94% |
| [#645](https://github.com/hskim-solv/BidMate-DocAgent/pull/645) | feat(eval): synthesis cost telemetry → case_results; ADR 0038 cost ... | 3491 | 2950 | 84% |
| [#644](https://github.com/hskim-solv/BidMate-DocAgent/pull/644) | feat(eval): KURE-v1 Phase 1.5 ablation + torch-gate (ADR 0037, clos... | 3037 | 2597 | 85% |
| [#642](https://github.com/hskim-solv/BidMate-DocAgent/pull/642) | fix(reranker): wire rerank_cross_encoder through pipeline + bge_ko ... | 2903 | 2395 | 82% |
| [#641](https://github.com/hskim-solv/BidMate-DocAgent/pull/641) | feat(ingestion): HwpNativeLoader pyhwp-gated default (ADR 0036, clo... | 1634 | 1324 | 81% |
| [#640](https://github.com/hskim-solv/BidMate-DocAgent/pull/640) | docs(adr): ADR 0036 — HwpNativeLoader pyhwp-gated default (closes #... | 1354 | 1011 | 74% |
| [#617](https://github.com/hskim-solv/BidMate-DocAgent/pull/617) | refactor: remove redundant calls in rag_verifier and rag_answer | 717 | 651 | 90% |
| [#616](https://github.com/hskim-solv/BidMate-DocAgent/pull/616) | refactor: simplify ingestion report building and reduce duplicate c... | 734 | 659 | 89% |
| [#609](https://github.com/hskim-solv/BidMate-DocAgent/pull/609) | docs: restore ADR 0020 and private-hardcase-benchmark.md (fixes bro... | 878 | 729 | 83% |
| [#573](https://github.com/hskim-solv/BidMate-DocAgent/pull/573) | fix(hooks): remove dead merge_mode field from auto-ship armed schem... | 1240 | 996 | 80% |
| [#572](https://github.com/hskim-solv/BidMate-DocAgent/pull/572) | fix(hooks): use shlex tokenisation in bash-guard to prevent false p... | 1118 | 769 | 68% |
| [#571](https://github.com/hskim-solv/BidMate-DocAgent/pull/571) | fix(hooks): use mktemp for TEST_SUMMARY_PATH to prevent concurrent-... | 1113 | 883 | 79% |
| [#568](https://github.com/hskim-solv/BidMate-DocAgent/pull/568) | fix(test): skip senior-positioning governance tests when file absent | 551 | 483 | 87% |
| [#566](https://github.com/hskim-solv/BidMate-DocAgent/pull/566) | docs: remove portfolio meta-documents from engineering repo | 1432 | 1250 | 87% |
| [#564](https://github.com/hskim-solv/BidMate-DocAgent/pull/564) | refactor: extract rag_clarification.py from rag_core (C-4) | 2228 | 1813 | 81% |
| [#562](https://github.com/hskim-solv/BidMate-DocAgent/pull/562) | refactor: extract rag_tracing.py from rag_core (C-3) | 1804 | 1505 | 83% |
| [#559](https://github.com/hskim-solv/BidMate-DocAgent/pull/559) | refactor: extract rag_metadata_processing.py from rag_core (C-2) | 2483 | 2189 | 88% |
| [#551](https://github.com/hskim-solv/BidMate-DocAgent/pull/551) | feat(eval): ADR 0032 Step 2 — routed-subset measurement results + p... | 1948 | 1639 | 84% |
| [#549](https://github.com/hskim-solv/BidMate-DocAgent/pull/549) | feat(security): adversarial Korean injection bench + FN-rate gate (... | 961 | 824 | 85% |
| [#544](https://github.com/hskim-solv/BidMate-DocAgent/pull/544) | docs(ingestion): HWPX out-of-scope note + tracking issue cross-link... | 929 | 732 | 78% |
| [#540](https://github.com/hskim-solv/BidMate-DocAgent/pull/540) | fix(hooks): resolve REPO_ROOT in pretooluse-loadbearing.sh to preve... | 1888 | 1517 | 80% |
| [#538](https://github.com/hskim-solv/BidMate-DocAgent/pull/538) | docs(adr): promote ADR 0009 to accepted + First execution results | 3036 | 2491 | 82% |
| [#536](https://github.com/hskim-solv/BidMate-DocAgent/pull/536) | docs(adr): fix ADR 0031 heading typo + add ADR 0033 multi-hop eval ... | 3323 | 2666 | 80% |
| [#535](https://github.com/hskim-solv/BidMate-DocAgent/pull/535) | feat(eval,adr): 5-embedding routed-subset measurement + ADR 0032 ac... | 2216 | 2013 | 90% |
| [#530](https://github.com/hskim-solv/BidMate-DocAgent/pull/530) | feat(eval): add routed_subset measurement surface (ADR 0032 Step 1) | 3960 | 3154 | 79% |

</details>

**합계** (98 PR 번역): 267,954c → 214,931c (80%, -53,023c 감축).

### 제외 (11 PR)

- **Dependabot 자동 생성** (9 PR): #521, #522, #523, #524, #525, #526, #527, #528 + #672 placeholder — upstream changelog content 또는 boilerplate 라 번역 부적합
- **이미 한국어** (2 PR): #898, #681

### 검증

98 PR 모두 identifier parity check `before ⊆ after` 통과:

- ADR 번호 (`ADR 0NNN`)
- PR/issue 번호 (`#NNN`)
- 파일 경로 (`*.py|.sh|.md|.yaml|.yml|.json|.jsonl`)
- env var (`BIDMATE_*`)
- `Closes #N` 키워드 (ADR 0007)
- `### 5b. Real-data delta` 헤더 + escape sentence "No behavior change in retrieval / verifier path." (governance script regex)

## 참고

- [`docs/translation-glossary.md`](../translation-glossary.md) — 번역 용어 단일 출처
- [`docs/contributing-ko.md`](../contributing-ko.md) — 향후 기여자 가이드
- PR-A [#921](https://github.com/hskim-solv/BidMate-DocAgent/pull/921) (핵심 문서 5개), PR-B [#922](https://github.com/hskim-solv/BidMate-DocAgent/pull/922) (템플릿)
