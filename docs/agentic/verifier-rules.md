# Verifier decision rules

이 저장소의 모든 답변을 게이팅하는 결정론적(deterministic) 검증기(verifier)에 대한
읽기 가이드다. 아래 규칙은 두 가지 병렬 형태로 표현된다 —
**code**(`rag_core.py` file:line 참조 포함)와 **pseudo-prompt**
(LLM 검증기가 소비할 형태의 자연어 지시문). 두 칼럼은 의도적으로 줄 단위로
대등하게 작성되어, 향후 결정론적 검증기를 LLM 검증기로 교체할 때
문서화된 기준선(baseline)을 갖도록 한다.

이것은 동작 명세이지 튜토리얼이 아니다. 함께 읽을 것:

- [ADR 0003 — answer / citation contract](../adr/0003-structured-answer-citation-contract.md) — 각 규칙이 기록해 넣는 schema.
- [ADR 0004 — verifier retry policy](../adr/0004-verifier-retry-policy.md) — 이 문서가 구현하는 strict → relaxed staging.
- [`rag_answer_schema.py`](../../rag_answer_schema.py) — `ANSWER_STATUS_*` 와 `ANSWER_SCHEMA_VERSION` 의 정식 정의.

## 상수

| Constant | Value | Defined in |
|---|---|---|
| `ANSWER_SCHEMA_VERSION` | `2` | [`rag_answer_schema.py:42`](../../rag_answer_schema.py) |
| `ANSWER_STATUS_SUPPORTED` | `"supported"` | [`rag_answer_schema.py:38`](../../rag_answer_schema.py) |
| `ANSWER_STATUS_PARTIAL` | `"partial"` | [`rag_answer_schema.py:39`](../../rag_answer_schema.py) |
| `ANSWER_STATUS_INSUFFICIENT` | `"insufficient"` | [`rag_answer_schema.py:40`](../../rag_answer_schema.py) |
| `PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` | `2` | [`rag_core.py:2278`](../../rag_core.py) |
| `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` | `0.5` | [`rag_core.py:2277`](../../rag_core.py) |
| Low-score floor (literal) | `0.18` | [`rag_core.py:2313`](../../rag_core.py) |

## 결정 트리 — `verify_evidence`

검증기([`verify_evidence`](../../rag_core.py), `rag_core.py:2282-2368`)는
4단계 게이트다. 각 stage 는 단락(short-circuit)하거나, 차단(block)하거나,
`verification_reason` 을 추가한다. 최종 판정은 `verified =
not blocking_reasons` 이다. `partial_topic_grounding` 만 non-blocking 이다.

### Stage A — 근거(evidence) 존재

```python
# rag_core.py:2311-2312
if not evidence:
    return False, ["no_evidence"]
```

> **Pseudo-prompt.** 검색 시스템이 chunk 를 하나도 반환하지 않았다면,
> 사유 `no_evidence` 와 함께 `verified=false` 를 출력하고 멈춘다. 빈
> 근거 묶음을 채점하려 들지 말 것.

### Stage B — 환각 하한선(hallucination floor, 항상 strict)

```python
# rag_core.py:2313-2314
if evidence[0]["score"] < 0.18:
    reasons.append("low_top_score")
```

> **Pseudo-prompt.** 검색된 최상위 chunk 의 유사도 점수가 `0.18` 미만이면
> reasons 리스트에 `low_top_score` 를 추가한다. 이 규칙은 strict 와
> relaxed stage 양쪽에 적용된다 — Stage D 참조.

`0.18` 임계값은 코드 안의 리터럴이며 튜닝 대상이 아니다. 환각 하한선으로
존재한다: 이 점수 미만에서는 부분 토픽 매치조차 거부하여, 노이즈에 근거한
그럴듯해 보이는 답변을 막는다.

### Stage C — 토픽 근거 연결(topic grounding, strict vs relaxed 분기)

```python
# rag_core.py:2322-2341
if topics:
    matched_topic_count = sum(
        1
        for topic in topics
        if any(
            form in combined or form in combined_canonical
            for form in expand_forms(topic.lower())
        )
    )
    if matched_topic_count < len(topics):
        if (
            allow_partial_topic
            and matched_topic_count >= PARTIAL_TOPIC_GROUNDING_MIN_MATCHED
            and (matched_topic_count / len(topics)) >= PARTIAL_TOPIC_GROUNDING_MIN_FRACTION
        ):
            reasons.append(PARTIAL_TOPIC_GROUNDING_REASON)
        else:
            reasons.append("topic_not_grounded")
```

> **Pseudo-prompt.** analysis 의 각 `topic` 에 대해, 결합된 근거 텍스트가
> 해당 토픽 또는 그 정규화/정준(canonical) 형태를 포함하는지 확인한다
> (ADR 0007 / issue #170 에 따른 한국어 금액/날짜 OR-매칭).
>
> - **모든** 토픽이 매치되면 이 stage 는 조용히 통과한다.
> - 최소 한 토픽이 누락되었고 AND 호출자가 이번이 마지막 시도임을 알리며
>   (`allow_partial_topic=true`) AND `matched ≥ 2` 와 `matched / total ≥ 0.5`
>   가 **모두** 성립하면, **non-blocking** 사유 `partial_topic_grounding`
>   을 추가한다. 답변은 `insufficient` 가 아니라 `partial` 로 표면화된다.
> - 그 외에는 blocking 사유 `topic_not_grounded` 를 추가하고 `verified`
>   를 false 로 둔다.

두 하한선(`≥ 2 matched` AND `≥ 50%`)은 서로 다른 이유로 존재하며,
둘 다 회귀 가드로 문서화되어 있다:

- 비율 하한선(`50%`)은 2-of-5 같은 약하게 균형 잡힌 케이스를 거부한다.
- 매치 수 하한선(`≥ 2`)은 issue #69 이후 real-data 의 의도된 보류 쿼리를
  `partial` 로 뒤집었던 1-of-2 우발적 겹침(incidental-overlap) 패턴을
  잘라낸다(issue #89, [`rag_core.py:2301-2304`](../../rag_core.py) 참조).

둘 중 하나의 하한선이라도 누락한 LLM 검증기 프롬프트는
[`tests/test_partial_topic_grounding.py`](../../tests/test_partial_topic_grounding.py) 를 회귀시킨다.

### Stage D — 비교 커버리지(comparison coverage, strict, entity 수준)

```python
# rag_core.py:2343-2363
entities = analysis.get("entities") or []
if analysis.get("query_type") == "comparison" and len(entities) > 1:
    covered = {item.get("agency") for item in evidence}
    missing = [entity for entity in entities if entity not in covered]
    if missing:
        reasons.append("missing_comparison_entity:" + ",".join(missing))
    if topics:
        # … per-entity topic coverage check …
        if missing_topic_entities:
            reasons.append("missing_comparison_topic:" + ",".join(missing_topic_entities))

matched_doc_ids = analysis.get("matched_doc_ids") or []
if analysis.get("query_type") == "comparison" and len(matched_doc_ids) > 1:
    # … per-doc coverage …
    if missing_doc_ids:
        reasons.append("missing_comparison_doc:" + ",".join(missing_doc_ids))
```

> **Pseudo-prompt.** `query_type == "comparison"` 이고 AND 둘 이상의
> 엔티티 / 문서가 요청된 쿼리에 한해서만:
>
> - 요청된 엔티티 중 근거 chunk 가 하나도 붙지 않은 것이 있으면
>   `missing_comparison_entity:<entity1>,<entity2>` 를 추가한다.
> - 어떤 엔티티에 근거는 있으나 그 chunk 중 어느 것도 토픽을 다루지
>   않으면 `missing_comparison_topic:<entity>` 를 추가한다.
> - 여러 `matched_doc_ids` 가 요청되었고 그중 최소 하나가 이를 다루는
>   근거가 없으면 `missing_comparison_doc:<doc_id>` 를 추가한다.
>
> 이 세 사유는 모두 **blocking** 이다.

### Stage E — 최종 판정

```python
# rag_core.py:2365-2368
blocking_reasons = [reason for reason in reasons if reason != PARTIAL_TOPIC_GROUNDING_REASON]
return not blocking_reasons, reasons
```

> **Pseudo-prompt.** reasons 리스트를 필터링한다: `partial_topic_grounding`
> 은 non-blocking 이고 나머지는 모두 blocking 이다. `verified = (blocking
> 사유가 남지 않음)` 을 **전체** reasons 리스트(발생한 non-blocking 사유
> 포함 — answer-status 매핑이 이를 필요로 함)와 함께 반환한다.

## 상태 매핑 — `answer_status`

[`answer_status`](../../rag_core.py)(`rag_core.py:2641-2666`)와
[`answer_status_reason`](../../rag_core.py)(`rag_core.py:2516-2539`)는
`(verified, reasons)` 튜플을 ADR 0003 계약 필드로 변환한다. 매트릭스:

| `verified` | reasons 에 `partial_topic_grounding` 포함 | reasons 에 `missing_requested_entity:*` 포함 | `query_type == "comparison"` AND `claims` 비어 있지 않음 AND `missing_comparison*` 사유 존재 | → `status` | → `status_reason.code` |
|---|---|---|---|---|---|
| `True` | 아니오 | 아니오 | 해당 없음 | `supported` | `verified` |
| `True` | **예** AND `claims` 비어 있지 않음 | 해당 없음 | 해당 없음 | `partial` | `partial_topic_grounding` |
| `True` | 아니오 | **예** | 해당 없음 | `insufficient` 로 떨어짐 | `insufficient_evidence` |
| `False` | 해당 없음 | 해당 없음 | **예** | `partial` | `partial_comparison` |
| `False` | (그 외 모든 형태) | 해당 없음 | 해당 없음 | `insufficient` | `insufficient_evidence` |

> **Pseudo-prompt.** `verified`, `verification_reasons`, `claims` 가
> 주어지면 `status` 를 결정한다:
>
> - **`supported`** — `verified=true` 이고 `partial_topic_grounding`
>   도 없고 `missing_requested_entity:*` 도 없을 때만.
> - **`partial`** — (a) `verified=true` AND reasons 에
>   `partial_topic_grounding` 가 있고 AND claims 가 만들어졌거나,
>   (b) `verified=false` AND 쿼리가 비교(comparison)였고 AND 최소
>   하나의 `missing_comparison_*` 사유가 존재하고 AND 최소 하나의
>   claim 이 만들어진 경우.
> - **`insufficient`** — 그 외 모든 경우. 답변은 `claims` 대신
>   `insufficiency` 블록을 담는다.
>
> 명확화를 `status_reason.code` 에 인코딩한다: `verified` /
> `partial_topic_grounding` / `partial_comparison` /
> `insufficient_evidence`.

## 인용 게이팅(citation gating) — `build_claims`

[`build_claims`](../../rag_core.py)(`rag_core.py:2542-2547`)는 검증기가
근거를 수용하거나 OR 쿼리가 최소 부분적 엔티티 커버리지를 갖춘 비교인
경우에만 호출된다. claim 은 `citations[]` 를 방출하며, 각 인용은
`doc_id` + `chunk_id` 를 최상위 `evidence` 리스트에 고정한다(ADR 0003 불변식).

> **Pseudo-prompt.** `support` 를 evidence 리스트의 특정 `(doc_id,
> chunk_id)` 쌍으로 해소할 수 없는 claim 은 만들지 말 것. 해소되는
> 인용이 없는 claim 은 환각으로 간주되어 제외된다.

비교 쿼리의 경우, [`build_comparison_claims`](../../rag_core.py)
(`rag_core.py:2549-2564`)는 최소 하나의 근거 chunk 를 가진 엔티티마다
claim 을 하나씩 방출하고, 나머지 엔티티는 대신 `insufficiency` 블록에
투입된다. 추출(extract) 쿼리의 경우,
[`build_extract_claims`](../../rag_core.py)(`rag_core.py:2567-2601`)는
metadata 에 묶인 문장을 우선하여 최대 두 개의 claim 을 선택한다.

## 재시도 정책(retry policy) — ADR 0004 매핑

검색 오케스트레이터([`rag_core.py:3886-3906`](../../rag_core.py))는
검증 시도를 스케줄링한다:

```python
# rag_core.py:3886-3906
if verifier_retry:
    is_last_attempt = attempt_index == len(stage_sequence) - 1
    verified, verification_reasons = verify_evidence(
        analysis,
        evidence,
        allow_partial_topic=is_last_attempt,
    )
...
if verified:
    break
if attempt_index < len(stage_sequence) - 1:
    retry_count += 1
```

| Attempt | `allow_partial_topic` | 동작 |
|---|---|---|
| 0 (strict) | `False` | 모든 토픽이 매치되어야 한다. `partial_topic_grounding` 은 발동할 수 없다. |
| 1 (relaxed, last) | `True` | `≥2 / ≥50%` 게이트가 성립하면 Stage C 가 `partial_topic_grounding` 을 발동할 수 있다. 다른 stage 는 모두 strict 유지. |
| (세 번째 재시도 없음) | — | relaxed stage 도 실패하면 `status` 는 `insufficient` 가 되거나, 비교 쿼리의 경우 comparison-coverage 경로를 통해 `partial` 이 된다. |

> **Pseudo-prompt.** `verifier_retry` 가 켜져 있을 때, 첫 시도가 실패하면
> 검증기를 두 번 실행한다. **두 번째이자 마지막** 시도에서만
> `allow_partial_topic=true` 로 설정하여 relaxed partial-topic 경로가
> 발동할 수 있게 한다. 세 번째로 재시도하지 말 것 — 대신 `insufficient`
> 로 에스컬레이션한다.

## 회귀 기준선(regression baseline)

결정론적 검증기를 언젠가 LLM 검증기로 교체한다면, LLM 이 충족해야 하는
계약은 다음 테스트들이다(`tests/test_partial_topic_grounding.py`):

| Test | Line | 고정 대상 |
|---|---|---|
| `test_strict_rejects_partial_topic_match` | [`tests/test_partial_topic_grounding.py:52`](../../tests/test_partial_topic_grounding.py) | strict 모드는 매치되지 않은 토픽을 거부 |
| `test_relaxed_accepts_partial_topic_match_above_threshold` | [`tests/test_partial_topic_grounding.py:60`](../../tests/test_partial_topic_grounding.py) | relaxed 모드는 3-of-4 = 0.75 를 수용 |
| `test_relaxed_rejects_one_of_two_partial_topic_match` | [`tests/test_partial_topic_grounding.py:79`](../../tests/test_partial_topic_grounding.py) | issue #89 — relaxed 모드는 1-of-2 = 0.5 를 거부 (matched-count 하한선) |
| `test_relaxed_still_rejects_zero_topic_match` | [`tests/test_partial_topic_grounding.py:102`](../../tests/test_partial_topic_grounding.py) | relaxed 모드는 0-of-N 를 거부 (out-of-corpus 보존) |
| `test_relaxed_still_rejects_below_fraction` | [`tests/test_partial_topic_grounding.py:114`](../../tests/test_partial_topic_grounding.py) | relaxed 모드는 1-of-4 = 0.25 를 거부 (fraction 하한선) |
| `test_low_top_score_still_blocking_in_relaxed_stage` | [`tests/test_partial_topic_grounding.py:125`](../../tests/test_partial_topic_grounding.py) | `0.18` 환각 하한선이 양쪽 stage 에서 유지 |
| `test_out_of_corpus_query_still_abstains` | [`tests/test_partial_topic_grounding.py:149`](../../tests/test_partial_topic_grounding.py) | end-to-end 보류가 보존됨 |

## LLM 이행 시 반대 점검(counter-checks)

향후 PR 이 검증을 LLM judge 경로로 라우팅한다면(ADR 0004 의 Alternatives
섹션에서 public surface 에 대해 명시적으로 거부된 경로), 다음은 단순한
프롬프트 번역이 결정론적 동작에서 흔히 어긋나는 지점들이다:

1. **`0.18` 점수 하한선 → 상대 신뢰도.** LLM 은 원시(raw) 검색 점수를
   보지 못한다. 점수를 명시적 지시문과 함께 숫자 필드로 프롬프트에
   노출하거나, 리터럴 임계값을 신뢰도 기반 판단으로 교체하되 그 교체가
   `test_low_top_score_still_blocking_in_relaxed_stage` 에서 회귀하지
   않음을 증명한다.
2. **비선형 토픽 게이트(`≥ 2 AND ≥ 50%`).** 단일 비율이 아니라 별개의
   두 하한선이다. "부분 토픽 매치를 수용하라"는 지시를 받은 LLM 은
   1-of-2 = 50% 를 수용하는 경향이 있다 — 바로 issue #89 가 회귀
   가드하는 케이스다. `test_relaxed_rejects_one_of_two_partial_topic_match`
   예시로 프롬프트를 few-shot 한다.
3. **`partial_topic_grounding` 은 non-blocking 이다.** 이는 검증 사실이
   아니라 정책 신호다: 자연스럽게 들리는 LLM 검증기는 일단 `verified=true`
   로 결정하고 나면 이를 더 이상 보고하지 않을 수 있는데, 그러면
   answer-status 매핑이 의존하는 `partial` vs `supported` 구분이 무너진다.
   프롬프트는 두 비트의 출력을 모두 요구해야 한다: verified 플래그 AND
   전체 reasons 리스트(발동 시 non-blocking 마커 포함).
4. **비교 커버리지의 정확성.** 결정론적 검증기는 요청된 엔티티 / 문서 중
   **하나라도** 근거가 없으면 비교 쿼리를 거부한다. LLM 은 더 관대한
   경향이 있다("내가 가진 것들로 충분히 가깝다"). `entities` 와
   `matched_doc_ids` 리스트를 프롬프트에 노출하고 어느 것이 커버되는지
   명시적으로 열거하도록 요구한다.
5. **한국어 금액/날짜 OR-매칭.** Stage C 는 `expand_forms` 와
   `normalize_text` 를 사용해 `1억 5천만원` 을 `150,000,000원` 등에
   매치한다. 두 형태를 모두 노출하지 않는 LLM 프롬프트는 real RFP
   데이터에서 under-match 한다. 프롬프트에 `combined` 와 함께
   `combined_canonical` 도 전달한다.

위 각 항목은 테스트 가능하다: 해당 회귀 테스트를 골라 LLM 기반 구현에
대해 실행한다. 어떤 회귀든 ADR 0003 하에서 계약 위반이며 `schema_version`
증가 또는 문서화된 재명세(re-spec)를 요구한다.
