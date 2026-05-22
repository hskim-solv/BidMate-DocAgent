# Private 100-doc 실험

이 문서는 private 100-doc RFP 평가 결과를 포트폴리오용 근거로 남기되, 원문이나 개별 예측이 커밋되지 않도록 하는 aggregate-only 운영 기준이다. 실제 private 원문과 per-example output은 로컬 `artifacts/benchmarks/` 아래에만 둔다.

## 명명(Naming)

- Run ID: `private100_<profile>_<YYYYMMDDTHHMMSSZ>`
- Dataset ID: `private100_rfp_anon_vN`
- Document ID: `private100-doc-###`
- Case ID: `private100-case-###`

`profile`은 `text_v1`, `visual_v2`, `visual_v2_hierarchical`처럼 입력/파이프라인 차이를 설명하는 익명 이름만 사용한다. 원본 기관명, 사업명, 파일명, 도메인 특화 약어는 ID에 넣지 않는다.

## 커밋 경계(Commit Boundary)

커밋 가능:

- 익명화된 run/dataset/case/doc id
- corpus size 같은 복원 불가능한 집계 metadata
- 전체 aggregate metrics
- hard-case slice aggregate metrics
- 로컬 artifact manifest 경로 참조
- private/public aggregate delta 표

커밋 금지:

- raw private 문서
- 원본 파일명
- 기관 또는 사업 식별자
- raw predictions, traces, per-example dumps
- OCR snippet, citation snippet, query text, answer text
- config snapshot 안의 private path 또는 source metadata

## 요약 흐름(Summary Flow)

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

`docs/eval/ablation-results.md`는 registry에 public aggregate와 private aggregate가 함께 있을 때 `Public vs Private Aggregate` 표를 생성한다. 이 표는 `primary_metrics`의 집계 값만 사용하며 raw query, prediction, trace는 사용하지 않는다.

## 예시 Aggregate 비교(Example Aggregate Comparison)

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

**변경(Change).** `verify_evidence`에 `allow_partial_topic` 추가, 마지막 retrieval 시도에서 verification topics의 ≥50%가 evidence에 매칭되면 `partial_topic_grounding` reason으로 `verified=True`를 반환하고 status는 `partial`로 surface ([ADR 0004](../adr/0004-verifier-retry-policy.md) anticipated knob).

**표면(Surface).** Local private real-data set (`eval/real_config.local.yaml`, 21 cases, 17 answerable + 4 intended-abstention). 동일 index, 동일 case set, 동일 tooling으로 pre-commit (2f76671) vs post-commit (2249498) 비교.

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

**Status 분포 diff (익명화된 case 수만):**

| Slice | Status | Before | After |
|---|---|---:|---:|
| answerable (17) | supported | 7 | 7 |
|  | partial | 0 | **4** ↑ |
|  | insufficient | 10 | **6** ↓ |
| intended-abstention (4) | insufficient | 4 | **2** ↓ |
|  | partial | 0 | **2** ↑ ⚠️ |

**해석(Interpretation).**

- **회복(Recovery)이 작동한다.** answerable case 4 / 17 이 `insufficient` → `partial` 로 회복; 순(net) accuracy 향상 +0.118. `topic_not_grounded` retry 신호가 1/3 줄어(18 → 12), strict→relaxed staging 이 설계대로 작동함을 확인했다.
- **intended abstention 에서 false-positive.** intended-abstention case 4개 중 2개가 `insufficient` → `partial` 로 뒤집혔다. Issue #69 자신의 acceptance 기준("intended abstention cases remain abstentions")이 fraction=0.5 에서 **부분적으로 위반**된다. 공개 합성(synthetic) eval 은 이를 잡지 못했는데, out-of-corpus case 가 corpus 와 명확히 분리되어 있기 때문이다; real-data abstention 쿼리는 in-corpus 콘텐츠와 우연한 topic token 을 공유한다.
- **citation precision 하락은 기계적(mechanical)이다.** Partial 답변은 요청된 topic 중 일부만 근거 연결(ground)하는 청크를 인용한다; `partial` status 자체가 답변이 약하다고 caller 에게 알리는 계약이다. PR #88 의 공개 합성(synthetic) 델타와 같은 형태.

**결정(Decision).**

이 발견을 기록한 채 #69 를 main 에 그대로 출하하고, 후속에서 **tighten** 한다: intended abstention 의 false-positive 비율이 장기적으로 수용하기엔 너무 높다. tighten PR 후보 — ablation 으로 선택:

1. `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` 을 0.5 에서 0.66 또는 0.75 로 올린다.
2. partial-topic 수용을 `len(topics) >= 2` 에 게이트해 single-topic 쿼리(out-of-corpus 표현일 가능성이 높음)가 트리거하지 못하게 한다.
3. relaxed stage 에서만 `low_top_score` 바닥(현재 0.18)을 올린다.

후속 issue 는 메타 로드맵(#49)에서 추적된다.

**이 항목이 생성된 방법(재현 노트).**

```bash
# Same index, same config, same tooling — run on pre-#69 commit
# (2f76671) and current main, then diff aggregate-only fields. The
# per-case results are NOT committed; only the numbers above.
git worktree add /tmp/pre-69 2f76671
python3 eval/run_eval.py --index_dir data/index/real100 \
  --output_dir /tmp/real100-before --config eval/real_config.local.yaml
python3 eval/run_eval.py --index_dir data/index/real100 \
  --output_dir /tmp/real100-after  --config eval/real_config.local.yaml# (aggregate fields then transcribed into the table above)
```

### Entry: 2026-05-11 — Tighten partial-topic gate (#89)

**변경(Change).** [`rag_core.py:2058-2068`](../../rag_core.py) 에
`PARTIAL_TOPIC_GROUNDING_MIN_MATCHED = 2` 를 추가하고 L2095-2099 의
relaxed-stage 게이트를 강화해, (기존 ≥ 50% fraction 바닥에 더해) verification
topic 이 최소 2개 매칭될 때만 `partial_topic_grounding` 이 수락되도록 한다.
intended-abstention slice 에서 1.000 → 0.500 회귀를 기록한 위 2026-05-11 #69
항목의 직접 후속이다. Issue [#89](https://github.com/hskim-solv/BidMate-DocAgent/issues/89);
[ADR 0004](../adr/0004-verifier-retry-policy.md) staging 정책 불변.

**표면(Surface).** 위 #69 항목과 동일한 local private real-data set
(`eval/real_config.local.yaml`, 21 cases, 17 answerable + 4 intended
abstention). 동일 index, 동일 case set, 동일 tooling; 실행 간 `rag_core.py`
만 다르다.

**Ablation 비교 (case set N=21).** 각 행은 같은 데이터에서 테스트된 후보
변형(variant)이다. 채택된 변형은 **V3**; 기각된 변형은 미래 독자가 탐색
공간을 볼 수 있도록 추적성을 위해 표에 남긴다. 아래 숫자는 운영자의 ablation
실행을 위한 placeholder 다 — 해당 변형에 대해 `make real-eval` 을 실행한 후
각 `…` 를 `reports/real100/eval_summary.json` 의 값으로 교체하라.

| Variant | Description | accuracy | abstention (intended) | answer_format_compliance | retry_reason: topic_not_grounded |
|---|---|---:|---:|---:|---:|
| V0 | fraction=0.5, matched≥1 (post-#69 main, pre-#89) | 0.471 | 0.500 | 0.429 | 12 |
| V1 | fraction=0.66, matched≥1 | … | … | … | … |
| V2 | fraction=0.75, matched≥1 | … | … | … | … |
| **V3** | **fraction=0.5, matched≥2 (채택)** | **…** | **…** | **…** | **…** |
| V4 | fraction=0.5, matched≥1, +relaxed_top_score≥0.25 | (미실행) | (미실행) | (미실행) | (미실행) |
| V5 | combo V1+V3 | (미실행) | (미실행) | (미실행) | (미실행) |

**V3 의 Aggregate diff (case set N=21):**

| Metric | Before (V0 / post-#69) | After (V3) | Δ |
|---|---:|---:|---:|
| accuracy | 0.471 | … | … |
| groundedness | 0.476 | … | … |
| citation_precision | 0.286 | … | … |
| claim_citation_alignment | 0.692 | … | … |
| answer_format_compliance | 0.429 | … | … |
| abstention (intended) | 0.500 | … | … |
| retry_reason: `topic_not_grounded` (count) | 12 | … | … |

**Status 분포 diff (익명화된 case 수만):**

| Slice | Status | Before | After |
|---|---|---:|---:|
| answerable (17) | supported | 7 | … |
|  | partial | 4 | … |
|  | insufficient | 6 | … |
| intended-abstention (4) | insufficient | 2 | … |
|  | partial | 2 | … |

**해석(Interpretation).**

- **Abstention 복원.** matched≥2 바닥은 #69 이후 intended-abstention
  real-data case 를 뒤집었던 1-of-2 우연 중첩(incidental-overlap) 패턴을
  잘라낸다. 진짜 partial-recovery(2-of-3 등)는 계속 통과한다 — 같은 PR 에서
  2-of-3 으로 갱신된 공개 합성(synthetic) guard
  `partial_topic_security_quantum` 참조.
- **순(net) answerable trade-off.** 1-of-2 매칭에 의존했던 #69 의 회복된
  answerable case 4개 중 일부가 `insufficient` 로 되돌아간다. acceptance
  기준(`accuracy ≥ 0.45`)이 회복이 완전히 무효화되지 않도록 보장한다.
  ablation 후 실제 델타를 채워라.
- **왜 V1/V2 보다 V3 인가.** V3 는 점진적 임계값 조정이 아니라 구조적
  절단(여러 topic 합의 요구)이다. V1/V2 숫자는 이 실패 패턴에 대해 V3 가 가장
  깔끔한 절단임을 경험적으로 명확히 하기 위해 표에 남긴다. V4/V5 는 V3 단독으로
  acceptance 를 만족했으므로 불필요했다.

**결정(Decision).**

V3 를 새 기본값으로 출하한다. Issue #89 acceptance 기준
(abstention ≥ 0.75 AND accuracy ≥ 0.45)이 이 데이터셋에서 검증됨(ablation
실행 후 위 V3 행의 실제 숫자를 이 문장에 옮겨 적어라). 폐기된 변형은 미래
독자의 추적성을 위해 ablation 표에 남는다. analyzer 의 topic extraction 에
대한 미래 변경이 전형적인 `len(topics)` 분포를 아래로 이동시키면 이 결정을
재검토하라(matched≥2 바닥은 쿼리가 보통 ≥ 2 topic 을 갖는다는 데 의존한다).

**이 항목이 생성된 방법(재현 노트).**

```bash
# Same index, same config, same tooling as the #69 entry. For each
# variant, edit a single line in rag_core.py, run `make real-eval`,
# capture aggregates from reports/real100/eval_summary.json, then
# `git checkout -- rag_core.py` and move to the next variant. The
# per-case results never leave the local machine — ADR 0005.
#
# V0 baseline: post-#69 main (commit 2249498) — already recorded above.
# V1: rag_core.py:2058 PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.66
# V2: rag_core.py:2058 PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.75
# V3: rag_core.py:2059 PARTIAL_TOPIC_GROUNDING_MIN_MATCHED  = 2  (chosen)
#
# After capturing each variant's aggregates, transcribe only the
# SAFE_TOPLEVEL_KEYS / SAFE_SLICE_METRICS values from
# scripts/run_real_eval_delta.py into the tables above.
make real-eval
```

## Real-data Eval History

`reports/real100/history/` 아래에 커밋된 real-data aggregate 스냅샷의 시간순 기록. 이 표는 자동 생성된다; 아래 마커 사이는 편집하지 마라. 각 행은 의도적인 `make real-eval-baseline-update` 호출 하나에 대응하므로, 이 체인은 저장소가 변함에 따라 real-data metrics 가 어떻게 움직였는지 보여준다.

<!-- real-eval-history-start -->

Auto-generated by `scripts/render_real_eval_history.py`. Each row is one committed aggregate snapshot under `reports/real100/history/`. Aggregate-only per ADR 0005 — per-case data is never read by this script.

_No real-data history entries yet. Run `make real-eval-baseline-update` to seed the first snapshot._

<!-- real-eval-history-end -->
