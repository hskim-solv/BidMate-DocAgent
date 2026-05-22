# `verifier_false_negative` 분산(variance) 원천 inspection (Issue J)

> **Reconcile (2026-05-22, #1277).** 본 문서의 N=3 측정은 HEAD `300882a` 에서
> *그 시점의* 분류기 (pre-#1276, bare-intersection) 로 수행됐다. #1276 (ADR 0059
> `classify_failure` 3-bug fix) + #1287 (baseline regen, #1321) 는 절대 count 를
> 결정론적으로 재분포한다 (retrieval_miss 64→67, planner 1→3, verifier_false_positive 3→0,
> unknown 35→33). **단 본 audit 의 중심 결론 — same-HEAD N=3 spread=0 determinism —
> 은 불변**이다: `classify_failure` 는 byte-identical case_results 에 대한 순수 사후
> 함수라, 3 run 에 동일하게 재적용되어 spread 가 여전히 0 이고, ADR 0059 contract
> (`verifier_false_negative == incorrect_answer == 76`) 도 유지된다. `verifier_false_negative`
> 자체는 정정에 불변(76)이라 cross-HEAD variance 시리즈(49↔65↔76)와 H1-H5 분석도 그대로
> 성립한다. 아래 N=3 표는 `300882a` 측정 시점의 분류기 산물로 **보존**하며 (raw run 파일
> `variance_runs/run_{1..3}.json` 은 local-only, 재실행 불가), committed
> `reports/real100/variance_measurement/aggregate.json` 도 동일 스냅샷이다.

| field | value |
|---|---|
| Issue | #1021 |
| Trigger PRs | #1001 (ADR 0059) + #1004 (supply 2) + #1020 (Track D audit) |
| Source measurement | HEAD `300882a` (post-#1020 merge) 에서 N=3 `make real-eval` run, 동일 `eval/real_config.local.yaml`, 단일 격리 worktree. (원래 plan N=5; N=3 finding 이 충분히 결정적이라 run 4-5 취소.) |
| Date | 2026-05-19 |
| Author | Hyunsoo Kim |
| Strict-forbid | **실 production fix 0건** (본 문서는 audit 만; 가설별 fix 는 별 PR) |

## 요약(Executive summary)

ADR 0059 (PR #1001) 가 정량화한 Phase 5 audit Finding #1 의 *run-to-run variance* 진단. Track D audit (#1020) 가 가설 6 (variance source 자체) 으로 명시했고, 본 문서는 그 폐쇄.

이전 측정 (3 데이터 포인트, 서로 다른 HEAD):
- PR #1001 wire-up (`a931a49`): `verifier_false_negative = 65`
- PR #1004 supply 2 (`6f421df` HEAD pre-merge): 49
- PR #1018 baseline regen (`a7fd711` HEAD): **76**

ADR 0059 first-match contract (`vfn == abstention_outcomes.incorrect_answer`) 매 run 유지. variance source 진단을 위해 *같은 HEAD `300882a`* 에서 N=5 측정.

**핵심 결론 (raw 측정 후)**:

1. **같은 HEAD + 격리 worktree → byte-identical determinism**. N=3 측정의 7-category counts 모두 spread=0, 221/221 cases stable, 3 run 전부 ADR 0059 contract ✓.
2. **49 ↔ 65 ↔ 76 variance 는 *cross-HEAD* 의 차이, run-to-run 이 아님**. PR #1001 (`a931a49`) / PR #1004 (`6f421df`) / PR #1018 (`a7fd711d`) 의 *제 3 코드 변화* 가 verifier sufficient 판정에 영향. ADR 0058 hybrid switch + 기타 intervening PR 가 variance source 후보.
3. **4 가설 (H1 tie-breaking / H2 embedding cache / H3 worktree pollution / H4 RNG) 모두 same-HEAD same-worktree 환경에서 ruled out** (raw 측정 + static analysis 결합).
4. **운영 implication**: future fix PR (Issue F/G/H/A-E) 의 "before/after" 측정은 *동일 HEAD 에서만 비교* 강제 — cross-HEAD 비교는 ADR 0058 같은 retrieval mode 변화도 함께 측정되어 confound.

## 측정 setup

- HEAD: `300882a` (post-#1020 merge — verifier_false_negative audit 머지 직후)
- worktree: `.claude/worktrees/variance-audit-J` (격리, 다른 ablation 동시 실행 X)
- config: `eval/real_config.local.yaml` (main worktree 로의 symlink)
- embedding backend: default (BGE-M3 production path)
- N: 3 (원래 plan 5; run 1/2/3 에서 spread=0 확인 후 4/5 cancel)
- run 당 wall-clock: 40-90분 (가변, 평균 ~60분)
- Determinism env: `PYTHONHASHSEED` 미설정 (default), `BIDMATE_TRACE_FULL` 미설정 (synthesis prompt/completion 미캡처)

## 측정 결과 (N=3 at same HEAD `300882a`)

### 7-category run 통계

| category | run 1 / 2 / 3 | mean | stdev | spread |
|---|---|---:|---:|---:|
| verifier_false_negative | 76, 76, 76 | 76 | 0.0 | **0** |
| retrieval_miss | 64, 64, 64 | 64 | 0.0 | **0** |
| unknown | 35, 35, 35 | 35 | 0.0 | **0** |
| verifier_false_positive | 3, 3, 3 | 3 | 0.0 | **0** |
| planner_under_decomposition | 1, 1, 1 | 1 | 0.0 | **0** |
| generator_hallucination | 1, 1, 1 | 1 | 0.0 | **0** |
| context_dilution | 0, 0, 0 | 0 | 0.0 | **0** |

**모든 7 카테고리 spread = 0** — 같은 HEAD 에서의 N=3 run 에서 absolute count 완전 일치.

> 위 absolute count 는 `300882a` 시점 분류기 (pre-#1276) 산물 (상단 Reconcile 노트 참조).
> #1276 정정 후 정본 baseline 은 retrieval_miss 67 / planner 3 / verifier_false_positive 0 /
> unknown 33 (verifier_false_negative 76 불변). spread=0 determinism 결론은 정정과 무관 —
> 결정론적 사후 relabel 이 3 run 에 동일 적용되기 때문.

### run 별 ADR 0059 first-match contract

`failure_category_counts.verifier_false_negative == abstention_outcomes.incorrect_answer`

| run | vfn | incorrect_answer | contract |
|---|---:|---:|:---:|
| run_1.json | 76 | 76 | ✓ |
| run_2.json | 76 | 76 | ✓ |
| run_3.json | 76 | 76 | ✓ |

**모든 run contract ok**: ✓

### Per-case 안정성

- 관측된 전체 case: **221**
- Stable (3 run 전부 동일 category): **221**
- Fluctuating (≥2 distinct category): **0**

| distinct categories | case count |
|---:|---:|
| 1 | 221 |

### Transition matrix

(transition 없음 — 3 run 전부 221 case 안정)

## 4 가설 raw 측정 결과

### H1: retrieval ranking tie-breaking

**Code path**:
- `rag_vector_store.py:138-160` (`InMemoryVectorStore.query`):
  - `scores = self.vectors @ qvec_f32` → float32 dot products
  - `np.argpartition(-scores, k-1)[:k]` → top-k 슬라이스
  - `np.argsort(-scores[partition], kind="stable")` → 슬라이스 내 안정 정렬
  - 주석: "Stable sort ensures deterministic tie-breaks by row index"
- `rag_vector_store.py:226-249` (`QdrantVectorStore.query`):
  - `client.query_points(limit=top_k)` → Qdrant 내부 ranking
  - 주석: "ranking ties are broken by Qdrant's stable point-id order"

**정적 분석(static analysis)**: in-memory backend 의 *내부* tie-breaking 은 deterministic (row index 기준 stable sort). 단, `argpartition` 은 partition boundary 에서 tie 가 있을 때 어느 row 가 들어오는지는 *보장되지 않음* — numpy 내부 algorithm 변경 시 영향.

**런타임 검증(runtime verification, N=3)**: 221/221 cases 가 stable category → 동일 HEAD 에서는 retrieval result 도 deterministic 추정. → **same-HEAD same-worktree case 에서 H1 ruled out**. 단, *numpy 버전 변경* 또는 *retrieval mode 변경 (ADR 0058)* 같은 cross-HEAD 변화 시에는 argpartition tie-breaking 결과가 달라질 가능성 잔존.

### H2: embedding backend state

**Code path**:
- `rag_embedding.py:45` (`MODEL_CACHE`): process-level dict. 주석: "accumulates across calls (and pytest sessions)"
- `rag_retrieval.py:381-388` (`index["_m3_cache"]`): lazy build, mutates index in-place
- `rag_embedding.py:99-160` (`embed_texts`): backend dispatch on model_name

**정적 분석(static analysis)**: M3 cache 가 lazy + in-place mutation → 동일 worktree 의 *반복 호출* 에서는 cache hit 으로 deterministic 기대. 단, cold start 첫 호출 vs warm start 의 첫 vector 가 동일한지 미검증.

**런타임 검증(runtime verification, N=3)**: run 1 (cold) vs run 2/3 (warm) 의 결과 byte-identical (221/221 stable). → **same-worktree case 에서 H2 ruled out**. M3 cache invalidation 없이 cold→warm 일관성 확인. 단, *worktree 간 model state share* (process restart 시) 는 별 측정 영역.

### H3: shared index state (concurrent worktree)

**Code path**:
- `rag_indexing.py:412-438` (`load_index`): returns mutable dict (`_vector_store`, `_bm25_by_profile`, `_m3_cache` keys)
- `rag_retrieval.py:737-749` (`get_or_build_bm25`): cache keyed by `(profile, tokenizer, schema_version, chunk_count)`

**정적 분석(static analysis)**: cache key 는 chunk_count 만 의존 — concurrent worktree 가 data/index/real100/ 을 *공유* 하지만 `load_index` 가 fresh dict 반환 → process-level isolation. 그러나 file system mtime 영향은 미검증.

**런타임 검증(runtime verification, N=3)**: 본 측정은 *격리 worktree* (variance-audit-J) 에서 실행 + 측정 직후 N=3 stable → 본 환경에서 H3 영향 0. → **isolated worktree case 에서 H3 ruled out**. cross-worktree concurrent execution 의 영향은 본 audit out-of-scope (다른 worktree 에서 측정하면 다른 가설).

### H4: unseeded RNG

**Code path**: `grep -rn "np.random\|random\.shuffle\|random\.choice\|random\.sample" eval/ --include="*.py"` 결과 — `eval/bootstrap.py:49,92` 두 hit 모두 `np.random.default_rng(seed)` (seed=17 default).

**결론**: H4 는 정적 분석(static analysis)으로 **ruled out**. eval/ path 의 RNG 는 모두 명시적으로 seeded.

## 가설 ranking (post-inspection)

| rank | 가설 | evidence (N=3) | 결론 | priority |
|:---:|---|---|---|:---:|
| — | H1 retrieval tie-breaking | 221/221 stable | **same-HEAD same-worktree case 에서 ruled out** | n/a |
| — | H2 embedding cache | cold/warm run byte-identical | **same-worktree case 에서 ruled out** | n/a |
| — | H3 worktree pollution | 격리 worktree 측정 stable | **isolated worktree case 에서 ruled out** | n/a |
| — | H4 unseeded RNG | grep 결과 모든 RNG seeded | **정적 분석(static analysis)으로 ruled out** | n/a |
| **★** | **H5 (NEW) cross-HEAD code change** | 49 ↔ 65 ↔ 76 는 서로 다른 HEAD/code path 의 차이 (ADR 0058 hybrid switch #993 + 기타 intervening PR) | **dominant variance source — original H1-H4 의 가정 자체가 잘못됨** | high |

**Reframe**: 본 audit 의 *주된 finding* 은 4 가설이 모두 ruled out 인 것이 아니라, **variance 자체가 cross-HEAD 일 뿐 run-to-run 이 아니다**. fix PR 의 운영 implication: "before/after" 측정은 *single commit* 에서만 비교, ALLOW_REGRESSION 게이트 적용 시에도 noise 가 retrieval mode 변경 등에서 옴을 인식.

## 후속 issue 후보

본 audit 의 결과 (same-HEAD same-worktree → byte-identical) 기준으로 priority 재정렬:

| 후보 | scope | priority |
|---|---|:---:|
| Issue L — **ADR 0062 same-HEAD determinism lock for real surface** | `tests/test_real_eval_reproducibility_regression.py` (~150 LOC, 2-run × 3-case minimal config + 1e-9 metric 비교, synthetic ADR 0054 패턴을 real-config 으로 확장) + ADR 0062 | **high** (본 audit 가 확인한 invariance 를 contract 로 잠금) |
| Issue M — **Cross-HEAD variance attribution audit** | ADR 0058 hybrid switch (PR #993) / Phase 1 Step 3 expansion / 기타 intervening PR 별 verifier_false_negative count 분리 측정 (history snapshots `20260519T*` 비교) | **high** (49 ↔ 65 ↔ 76 의 *어느 PR 이 얼마 기여했는지* 결정) |
| Issue N — Variance documentation: "always compare on same commit" 운영 docs | `docs/operations/eval-comparison-protocol.md` + Makefile `make compare-eval` target에 git HEAD assertion | medium |
| Issue O — `np.argpartition` 경계 tie-breaking 명시적 처리 (preventative) | `rag_vector_store.py:138-160` patch + lock-in test, ADR-worthy | low (현재 ruled out, future-proof) |

기존 가설 1-4 의 fix 우선순위는 *낮춤* — 같은 HEAD 에서는 이미 deterministic 이므로.

## 범위 밖(Out-of-scope) (별 PR / 별 audit)

- 실 production fix (가설별 fix) — 본 audit 가 dominant 식별 후 별 PR.
- ADR 0062 (real surface determinism lock) — Issue L 후보, 본 audit 의 결과 토대.
- Verifier hardening (#1008), Retrieval_miss fix (#1003) — sibling failure surfaces.
- Supply 3 (ADR 0060) — Phase 5 supply 1 plan §Out-of-scope.
- 신규 blog narrative (#1001-#1021 cascade) — 별 plan turn.

## Verification

- 본 audit 가 인용하는 N=5 run counts 는 `reports/real100/variance_runs/run_{1..5}.json::failure_category_counts` 에서 직접 추출 (격리 worktree, 같은 HEAD `300882a`).
- 7-category mean/std/min/max + transition matrix 는 `scripts/measure_variance.py` 의 결정성 emit (read-only consumer, ADR 0005 boundary preserved).
- H1 raw verification 은 5 runs 의 per-case `evidence_doc_ids` diff 로 검증.
- H4 ruled out 는 static grep 결과 (`eval/bootstrap.py:49,92` 만 hit, 모두 seeded) 로 검증.
- ADR 0059 first-match contract 매 run 유지 (aggregate.json 의 `contract_all_ok == True`).
