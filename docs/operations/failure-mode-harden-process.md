# 실패 모드 하든(harden) 프로세스

ADR 0059 failure classifier + supply 2 대시보드를 *닫힌 에러 루프(closed
error loop)* 로 바꾸는 **monotone-harden** 워크플로: 감사(audit)가
표면화하는 모든 실패 모드는 카테고리, eval 예제, 래칫(ratcheting) 천장을
얻는다 — 그래서 같은 회귀가 조용히 재발할 수 없다.

이것은 Phase 5 감사(#992)의 항목 3 이다. 계약은 ADR 0062 다.

## 루프

```
audit surfaces a failure mode  (e.g. #1005 retrieval_miss, #1020 verifier_false_negative)
        │
        ▼
(a) category exists in failure_classifier.py?  ──no──▶  add category + lock test
        │ yes                                            (tests/test_failure_classifier.py)
        ▼
(b) ≥5 representative examples in real-eval set?  ──no──▶  add hardcase examples
        │ yes                                              (eval/real_config.local.yaml)
        ▼
(c) ceiling set in test_failure_rate_regression.py?  ──no──▶  set ceiling = current rate + margin
        │ yes
        ▼
(d) supply 2 dashboard renders it  (scripts/render_failure_distribution.py)
        │
        ▼
fix lands ──▶ lower committed rate ──▶ TIGHTEN ceiling in same PR ──▶ loop closes tighter
```

래칫은 **한 방향**으로만 돌아간다: 천장은 fix 가 landing 되면 내려가며,
명시적 `[ALLOW_REGRESSION]` 정당화 없이는 절대 올라가지 않는다.

## 각 표면의 역할

| surface | file | role |
|---|---|---|
| classifier | `eval/scorers/failure_classifier.py` | 7-category first-match-wins 라벨 (ADR 0059) |
| classifier lock | `tests/test_failure_classifier.py` | ordering 을 고정해 Finding #1 이 `verifier_false_negative` 로 유지되게 함 |
| dashboard | `scripts/render_failure_distribution.py` | distribution + ADR 0059 계약 ✓ 렌더 (supply 2) |
| **regression gate** | `tests/test_failure_rate_regression.py` | **커밋된 baseline 의 래칫 천장 (ADR 0062)** |
| baseline | `reports/real100/baseline.aggregate.json` | 게이트가 읽는 커밋된 aggregate (ADR 0005 경계) |

## 새로 표면화된 실패 모드 추가하기

1. **카테고리를 확정한다.** 모드가 기존 7-category 라벨에 맞으면
   단계 3 으로 건너뛴다. 진정으로 새것이라면 `failure_classifier.py` 의
   `FAILURE_CATEGORIES` 와 `classify_failure()` 에 추가하되,
   first-match-wins ordering 을 존중한다(ADR 0059).
   `tests/test_failure_classifier.py` 에 유닛 테스트를 추가한다.

2. **≥5 개 예제를 추가한다.** 그 모드를 보이는 대표적인 hardcase 쿼리를
   최소 5개 `eval/real_config.local.yaml`(gitignore, ADR 0005)에 추가한다.
   이는 rate 에 안정적인 분모 신호를 준다.

3. **천장을 설정한다.** baseline 을 regen(`make real-eval` +
   `make real-eval-baseline-update STRICT=1`)하고, 새 카테고리의
   커밋된 rate 를 읽어,
   `tests/test_failure_rate_regression.py` 의 `CEILING_RATE_BY_CATEGORY` 에
   `current_rate + margin` 으로 추가한다. margin 은 variance 감사(#1025)가
   측정한 cross-HEAD variance 를 흡수한다 — 최초 도입 시에는
   넉넉히 설정한 뒤 조인다(tighten).

4. **대시보드가 렌더하는지 검증한다.**
   `scripts/render_failure_distribution.py` 를 재실행한다; 새 카테고리가
   `reports/real100/failure_distribution.md` 에 나타난다.

## fix 이후 천장 조이기

fix PR 이 게이트된 rate 를 낮출 때:

1. fix 의 HEAD 에서 baseline 을 regen 한다.
2. 카테고리의 `CEILING_RATE_BY_CATEGORY` 항목을 새
   `current_rate + small_margin` 으로 **같은 PR 에서** 낮춘다.
3. `test_ceilings_are_monotone_sane` 은 천장을 현재 rate
   *아래로* 설정하는 것(역전된 래칫)을 가드한다.

## 절대 카운트가 아닌 rate 인 이유

variance 감사(#1025)는 절대 카운트가 *HEAD 별로는* 결정론적이지만
cross-HEAD 로는 변동함을 발견했다(`verifier_false_negative` 가
PR #1001 / #1004 / #1018 전반에 49 ↔ 65 ↔ 76 으로 변동, 반면 same-HEAD N=3
실행은 byte-identical 이었다). 문서화된 margin 이 있는 rate 는 그 cross-HEAD
variance 를 흡수한다; 히스토리컬 variance 를 넘어선 진짜 회귀는 여전히
게이트를 발화시킨다. fix 의 전/후는 항상 **같은 커밋에서** 비교하라 — cross-HEAD
비교는 fix 를 그 사이의 변경(예: ADR 0058
hybrid 전환)과 혼동시킨다.

## 워크 예제 (이 루프를 먹인 감사들)

| audit | mode | committed rate | ceiling |
|---|---|---:|---:|
| #1020 | `verifier_false_negative` | 0.344 (76/221) | 0.40 |
| #1005 | `retrieval_miss` | 0.290 (64/221) | 0.34 |
| — | total failures | 0.814 (180/221) | 0.86 |

각 감사의 follow-up fix(Issue F verifier 하든, Issue A top_k
ablation, …)는 이 rate 를 낮춘 뒤 천장을 조이는 것을 목표로 한다.
