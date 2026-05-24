# ADR 0054 — 답변 조건부(conditional-on-answer) 채점기 의미론

- Status: Accepted
- Implemented: #959 (2026-05-18) — `eval/scorers/case.py` conditional-on-substantive-answer semantics + n=221 gauge regen
- Date: 2026-05-18
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline 불변량), ADR 0003 (answer-contract schema_version=2), ADR 0005 (eval 분리), retired aggregate policy (리더보드 표면), ADR 0053 (변별력(distinguishing-power) floor — **본 ADR 이 보강(augment), supersede 아님**)
- Augments: ADR 0053
- Issue: #958

## Context

PR #946 (ADR 0053 Step 5b) 가 `scripts/distinguishing_power.py` 를 ship 하고 비공개 100-doc 실 corpus 에서 `n=221` 첫 측정을 산출했다. 게이지(gauge)는 **5개 메트릭 중 3개를 "signal NOT alive"** 로 보고 — `groundedness`, `citation_precision`, `answer_format_compliance` 모두 `random_retrieval` floor 를 *밑돈다(under-perform)*:

| metric | default (full) | random_retrieval | gap | signal_alive |
|---|---:|---:|---:|:---:|
| accuracy | 29.66% | 2.54% | **+27.12pp** | ✓ |
| claim_citation_alignment | 96.28% | 88.24% | **+8.04pp** | ✓ |
| groundedness | 25.34% | 36.20% | **−10.86pp** | ❌ |
| citation_precision | 19.02% | 34.84% | **−15.82pp** | ❌ |
| answer_format_compliance | 20.81% | 44.80% | **−23.98pp** | ❌ |

출처: `reports/real100/distinguishing_power.md` (n=221), 게이지 2026-05-17 표면화.

### Root cause — the Goodhart trap

`random_retrieval` 은 답 불가능 케이스의 **≈89%** 에서 올바르게 보류(abstain)한다 (검증기가 noisy 후보를 reject → `status: insufficient`). 그러면 수정 전(pre-fix) `eval/scorers/case.py:79-92` 분기가 모든 (답 불가능 AND 보류 AND 근거 없음) 케이스에서 `groundedness` 와 `citation_precision` 에 **공허한 참(vacuous-truth) 1.0** 을 할당했다:

```python
# pre-fix (eval/scorers/case.py:89-91)
else:  # answerable=False
    groundedness = 1.0 if abstained and not evidence else 0.0
    citation_precision = 1.0 if abstained and not evidence else 0.0
    abstention = 1.0 if abstained else 0.0
```

이 공허한 1.0 들을 평균에 접어 넣으면 **고-보류(high-abstention) run 의 품질 점수가 부풀려진다(inflate)**:

* `random_retrieval` 은 89% 보류 → groundedness 평균이 ~0.89 × 1.0 만큼 끌어올려짐 → 실질적인(substantive) ~6% 대신 36.20% 로 보고.
* `single_chunk` 은 더 낮은 보류 (~7%) → inflation 훨씬 작음 → 8.14% 로 보고 (진실에 더 가까움).
* `full` 기본은 중간 정도 보류 → 적당한 inflation, 그러나 random 이 훨씬 더 자주 보류하므로 여전히 random 보다는 작음.

이 역전(flip)은 정확히 random 이 full 보다 더 많이 보류하기 때문에 발생한다 — 바로 **게이지가 시끄럽게 실패해야 할(fail loudly)** 영역인데, 공허한 1.0 이 그 실패를 가린다.

### Why it's a double-count, not just a definitional quirk

보류 정확성(refusal correctness)은 **이미 두 개의 보완적 신호로 측정된다**:

* `abstention` rate (`eval/run_eval.py:597`) — 모델이 올바르게 거부한 답 불가능 케이스의 비율.
* `abstention_outcomes` 3-bin (`eval/run_eval.py:377-411`, PR #464) — `correct_refusal` / `incorrect_answer` / `boundary_partial` 분해.

동일한 correct-refusal 신호를 세 번째로 `groundedness` / `citation_precision` / `answer_format_compliance` 에 접어 넣는 것은 모든 aggregate 를 가장 많이 보류하는 파이프라인 쪽으로 편향시키는 이중 집계(double-count)다. ADR 0053 의 게이지가 이를 표면화했고, ADR 0054 는 그것을 만든 채점기(scorer)를 고친다.

`answer_format_compliance` 도 같은 형태다 — `score_answer_format` (`eval/scorers/format.py:64-82`) 는 `status=insufficient`, `claims=[]`, `min_claims=0` 을 *모든 검사 통과(all checks pass)* → 1.0 으로 취급한다. 동일한 correct_refusal 케이스에서 이 자명하게 참인(trivially-true) 1.0 이 고-보류 run 의 format-compliance 평균을 부풀린다.

## Decision

1. **품질 메트릭은 실질적 답변 시도(substantive answer attempt)에 조건부다.** `accuracy`, `groundedness`, `citation_precision`, `answer_format_compliance` 는 모델이 실질적 답변을 산출(또는 시도)한 경우에 **한해서만** 측정된다. 비실질적(non-substantive) 경로는 `None` 을 반환하고 평균 분모(denominator)에서 제외된다.

   `eval/scorers/case.py` 에서 구체적으로:

   ```python
   # post-fix
   if answerable:
       accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
       groundedness = 1.0 if term_match and evidence and not abstained else 0.0
       citation_precision = citation_doc_precision if citation_term_match else 0.0
       abstention = None
   else:
       accuracy = None                  # was already None — unchanged
       groundedness = None              # was vacuous 1.0 — now None
       citation_precision = None        # was vacuous 1.0 — now None
       abstention = 1.0 if abstained else 0.0
   # post-process: format_compliance is also vacuously 1.0 on the
   # (unanswerable AND abstained AND no-evidence) path → None there too.
   if not answerable and abstained and not evidence:
       answer_format_payload["answer_format_compliance"] = None
   ```

2. **보류 정확성은 `abstention` (rate) + `abstention_outcomes` (3-bin, PR #464) 로 배타적으로 측정된다.** 어떤 품질 메트릭도 보류 정확성(refusal-correctness) 성분을 운반하지 않는다.

3. **`metric_block` 분모는 자동이다.** `eval/run_eval.py:470-516` 은 이미 5개 메트릭 전반에 None-filter 패턴 (`[r[m] for r in case_results if r[m] is not None]`) 을 갖고 있다; 거기엔 패치 불필요. 같은 패턴이 `by_query_type`, `by_hardcase_category`, `by_slice`, `by_metadata_field` (모두 `metric_block` 호출) 로 이어진다.

4. **변별력(distinguishing-power) 게이지는 새 로직이 아니라 투명성(transparency)을 얻는다.** `scripts/distinguishing_power.py` 가 `_safe_abstention(run)` 을 추가해 run 별 `abstention_rate` + `num_predictions` + `effective_n` (= num_predictions − `abstention_outcomes` bin 합) 을 게이지 JSON + markdown 에 표면화한다. `signal_alive` 는 여전히 GAUGED_METRICS 에서만 엄격히 계산된다 — 채점기 수정이 *1차* 방어, 게이지 투명성이 *2차* 방어다.

## Why these semantics, not the alternatives

| 대안 | 기각 사유 |
|---|---|
| 공허한 1.0 을 유지하고 `signal_alive` threshold 를 강화 | 병이 아니라 증상을 치료. 모든 downstream 소비자 (README 헤드라인, eval-delta CI gate, by_query_type aggregate) 가 여전히 부풀려진 평균을 상속. 수정은 채점기에서 이뤄져야 한다. |
| 비실질적 케이스에 `None` 대신 `0.0` 반환 | 한쪽 이중 집계 방향을 다른 방향으로 대체할 뿐 — 고-보류 run 이 이제 인위적으로 깎인다(deflate). `None` 이 "이 메트릭은 이 케이스에 적용되지 않는다" 를 올바르게 말한다. |
| `groundedness` 를 "올바른 거부도 grounded 로 카운트" 하도록 정의 | 진정으로 다른 두 성공 표면 (실질적 grounding vs. 보류 정확성) 을 혼동(conflate). `abstention_outcomes` 3-bin 이 존재하는 이유 자체가 보류 정확성을 별도 축으로 표면화하기 위함이다. |
| `eval/scorers/format.py` 를 직접 패치 | format 채점기 안에서 `answerable AND abstained AND not evidence` 술어를 복제해야 함 (그렇지 않으면 그 필드들을 보지 못함). 세 필드가 모두 이미 scope 안에 있는 `case.py` 에서 후처리(post-process)하는 편이 더 깔끔하다. |

## Consequences

### Positive

- **변별력(distinguishing-power) 게이지가 신호를 되찾는다.** 각 ablation run 의 품질 메트릭 평균이 이제 실질적-답변 성능만 반영한다. 3개 거짓-음성(false-negative) 게이지 판정 (groundedness / citation_precision / answer_format_compliance) 은 n=221 재생성(regen) 후 역전될 것으로 예상 — *실제로 역전되는지는 재측정으로 검증되며*, 여기서 단언하지 않는다.
- **암묵적 Goodhart 압력을 제거** — 더 많이 보류하려는 압력 (수정 전에는 accuracy 를 제외한 모든 품질 평균을 조용히 부풀렸음).
- **리더보드 서사(narrative)를 시니어 reviewer 의 독법과 정렬**: "시도에는 품질, 보류에는 거부, 결코 둘을 동시에 세지 않음."
- **포트폴리오 서사**: PR #946 이 함정을 표면화 → 본 PR 이 수정. 한-PR 폐루프(closed loop), 면접에서 인용 가능.

### Negative

- **`baseline.aggregate.json` 가 설계상 이동(shift)한다.** 고-보류 run 의 품질 평균이 하락 (공허한 1.0 제거). `pr-eval.yml:185` 통과를 위해 `[ALLOW_REGRESSION: ADR 0054 metric-semantics shift]` PR 태그 필요.
- **수정 전(pre-fix) 메트릭 값은 commit 된 모든 보고서 (README 헤드라인, 블로그 글, `reports/real100/baseline.aggregate.json` history) 에서 이제 stale 하다.** README L12 헤드라인 + `distinguishing_power.md` 재렌더가 본 PR 에 포함; downstream 포트폴리오 서사 갱신은 엔지니어링 repo 범위 밖 (비공개 `BidMate-DocAgent-portfolio` repo).
- **By-query-type / by-hardcase-category 부분집합**은 모든 케이스가 비실질적인 슬라이스 (답 가능 케이스 없음, 또는 모든 답 가능 케이스가 보류) 에서 분모를 잃는다. 그 슬라이스는 이제 메트릭을 오해 소지 있는 0.0/1.0 대신 `None` 으로 보고한다. `metric_block` aggregate 에서 자연스럽게 표면화.

### Invariance check

- **ADR 0001 (naive_baseline preset, byte-identical 결정성)**: 보존. `tests/test_eval_reproducibility_regression.py` 는 절대 메트릭 값이 아니라 *동일 config 의 두 run 간* byte-identity 를 단언 — 결정론적 None-fix 는 여전히 run1 vs. run2 출력이 동일.
- **ADR 0003 (answer-contract schema_version=2)**: 무변경. 패치는 채점기 레이어에만 있음; prediction dict shape 와 answer payload 계약은 untouched.
- **ADR 0005 (eval 분리 public/private)**: 무변경. Aggregate-only artifact (`baseline.aggregate.json`, `distinguishing_power.{md,aggregate.json}`) 만 commit 경계를 넘는 유일한 항목으로 유지.
- **ADR 0044 / 0052 (real-eval n 궤적)**: 무변경. n=221 이 측정 스케일로 유지; per-case 채점 규칙만 이동.
- **ADR 0052 (real-eval hardcase 확장)**: 무변경. 동일 221 케이스를 조건부 의미론 하에 재채점.
- **ADR 0053 (변별력 floor ablation)**: **보강(augmented)**. 게이지 공식 `(default − floor) / (1 − floor)` 무변경. `signal_alive` 로직 변경 없이 새 투명성 블록 (run 별 `abstention_rate` / `effective_n`) 추가.

## Out of scope

- **특정 게이지 갭을 쫓기 위한 answer LLM 보류 threshold 재튜닝.** 측정 레이어 수정만; 파이프라인 튜닝은 Phase 3.
- **`eval/config.yaml` 에 합성 답-불가능 보류 케이스 추가** — 이미 그런 케이스 23개 보유 (`abstention_missing_*` prefix). 본 PR 에 새 합성 표면 없음.
- **`gauge` 정의 자체** (`(default − floor) / (1 − floor)` 공식). 수정 후(post-fix) 측정이 여전히 거짓 음성을 보이면, 그것은 Phase 3 ADR 0055 후보 — 게이지 강화 또는 메트릭별 가중치.
- **게이지용 per-case 데이터 export.** ADR 0005 경계 보존; 게이지는 aggregate-only 유지.

## Verification

<!-- verifies-key: eval/scorers/case.py:groundedness = None -->
<!-- verifies-key: eval/scorers/case.py:citation_precision = None -->
<!-- verifies-key: eval/scorers/case.py:answer_format_payload -->
<!-- verifies-key: scripts/distinguishing_power.py:_safe_abstention -->
<!-- verifies-key: tests/test_scorers_case_abstention.py:TestUnanswerableCorrectRefusal -->
<!-- verifies-key: tests/test_scorers_case_abstention.py:TestMetricBlockExcludesNoneFromSubstantiveMean -->

## References

- ADR 0053 (`docs/adr/0053-distinguishing-power-floor-ablations.md`) — 이 함정을 표면화한 게이지.
- PR #946 — 첫 n=221 측정, 본 ADR 상단 표의 출처.
- PR #464 — `abstention_outcomes` 3-bin (보류 정확성 측정의 나머지 절반).
- `eval/scorers/case.py:79-92` — 패치된 분기.
- `eval/run_eval.py:470-516` — `metric_block` None-filter (이미 존재).
- `scripts/distinguishing_power.py` — 수정 전 부풀려진 값을 소비한 게이지.
- `reports/real100/distinguishing_power.md` — 수정 전 및 (재생성 후) 수정 후 게이지 출력.
