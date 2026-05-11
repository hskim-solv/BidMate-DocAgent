# Senior-Positioning Narrative

이 문서는 채용 리뷰어 또는 면접관이 BidMate Agent를 보고 **"이 결과물이 시니어 엔지니어링 시그널을 얼마나 보여주는가?"** 를 빠르게 판단할 수 있도록 정리한 narrative다.

기존 reviewer 문서와의 역할 분담:

- [`portfolio-case-study.md`](./portfolio-case-study.md): 7가지 포트폴리오 질문에 대한 답 (왜/무엇을/어떻게)
- [`reviewer-evidence-pack.md`](./reviewer-evidence-pack.md): 5분 데모 흐름과 대표 질의·산출물 위치
- [`engineering-governance.md`](./engineering-governance.md): 코드/ADR/테스트/평가/리뷰 산출물이 서로 어떻게 강제되는가
- **이 문서**: 위 자료들을 어떤 **시니어 시그널**로 읽어야 하는지 — 인터뷰 답변 톤으로 정리

내용을 새로 만들지 않고 기존 자료를 어디서 어떻게 봐야 하는지 가리킨다.

## 시니어 시그널 한눈에 보기

| 시그널 | 어디서 확인하나 |
|---|---|
| 아키텍처 결정이 **사후 합리화가 아닌 기록된 결정**으로 남아있다 | [`docs/adr/`](./adr/README.md) — 6개 ADR, status-tracked |
| **측정 가능한 성공 기준**을 미리 잡고 그 기준으로 평가한다 | [`portfolio-case-study.md` §2](./portfolio-case-study.md), [`eval/config.yaml`](../eval/config.yaml), README headline 표 |
| 합성 평가의 한계를 알고 **공개/비공개 평가 분리**로 보완한다 | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md), [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) |
| **실패를 분류·우선순위화**한 뒤 백로그로 만든다 | [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md), 메타 이슈 #49 |
| 회귀가 **다시 발생하지 않도록 테스트로 잠근다** | `tests/test_*_regression.py`, [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Real-data Decision Log |
| **거버넌스가 코드와 같이 진화**한다 (rule book → 규칙 → 자동화) | [`CLAUDE.md`](../CLAUDE.md), [`docs/engineering-governance.md`](./engineering-governance.md), `.github/workflows/` |
| **재현 가능한 시연**으로 주장 가능한 수치만 README에 올린다 | `make smoke`, `scripts/update_readme_metrics.py --check`, README "핵심 성능표" |

## 시니어 시그널 1 — 아키텍처 결정의 추적성

각 ADR은 **하나의 의사결정**을 다룬다. 6개를 빠르게 읽고 나면, 이 시스템에서 어떤 선택이 load-bearing인지가 명확해진다.

| ADR | 결정 | 시니어 관점에서 왜 중요한가 |
|---|---|---|
| [0001](./adr/0001-preserve-naive-baseline.md) | naive baseline을 ablation으로 보존 | 후속 retrieval 변경의 효과를 항상 baseline 대비로 측정 가능 |
| [0002](./adr/0002-metadata-first-retrieval.md) | metadata-first retrieval | 의미 유사도 단독의 함정(기관·문서 단위 제약 누락)을 회피한 trade-off |
| [0003](./adr/0003-structured-answer-citation-contract.md) | answer/citation 계약 (`schema_version: 2`) | 후속 변경이 silent contract drift를 만들 수 없게 잠금 |
| [0004](./adr/0004-verifier-retry-policy.md) | strict→relaxed verifier staging | 비용(latency)을 인정하면서 partial coverage를 잡는 명시적 정책 |
| [0005](./adr/0005-eval-split-public-synthetic-private-local.md) | 공개 합성 vs 비공개 로컬 평가 분리 | 외부 공개 제약과 일반화 한계를 인정하면서 reproducibility를 지키는 설계 |
| [0006](./adr/0006-llm-judge-real-data-only.md) | LLM-judge는 real-data 표면에서만 | 공개본의 결정성과 실제 신호를 동시에 살리는 비대칭 결정 |

**인터뷰 talking point**: "ADR 0005가 없었다면 공개본의 abstention 회귀(#69의 `1.000 → 0.500` 사건)는 아무도 보지 못했을 것이다. 공개 합성만 보던 시기에는 1-of-2 incidental overlap 패턴이 잡히지 않았다." — 근거: [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) 2026-05-11 entry.

## 시니어 시그널 2 — 측정의 엄격성

엔지니어가 "성능이 좋아졌다"고 말할 때 시니어 리뷰어가 보는 것은 **무엇을 어떻게 측정했는가**다.

이 프로젝트의 측정 시스템은 다음과 같이 분리되어 있다.

```
공개 합성 표면 (eval/config.yaml)        비공개 real-data 표면 (eval/real_config.local.yaml)
  - PR마다 CI에서 자동 실행                  - 운영자 머신에서만 실행 (ADR 0005)
  - 결정성 보장 (낮은 분산)                  - 실제 분포 신호 (높은 분산)
  - reproducible: make smoke                 - aggregate-only commit (private)
  - 보장: contract / regression              - 보장: real-world generalization
```

리뷰어가 측정 엄격성을 점검할 때 볼 곳:

- **CI eval delta**: 모든 PR에 자동 코멘트되는 metric diff (`.github/workflows/pr-eval.yml`). PR #98이 `abstention 0.857 → 1.000`을 어떻게 surface했는지 보면 됨.
- **Real-data Decision Log**: [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Decision Log 섹션. 변경별 before/after aggregate, status distribution, 결정의 이유까지 기록.
- **README headline 표**: `scripts/update_readme_metrics.py --check`가 CI에서 강제. README의 숫자는 손으로 적을 수 없다.

**인터뷰 talking point**: "synthetic abstention이 perfect score(1.000)인데도 real-data abstention이 0.500이라는 사실을 발견하지 못했다면, 이 시스템은 silent regression 위에서 성능을 주장하고 있었을 것이다. ADR 0005는 그 격차를 일부러 surface한다."

## 시니어 시그널 3 — 실패를 시스템적으로 다룬다

실패는 발생하는 것이 아니라 **분류되고, 우선순위가 매겨지고, 회귀 가드로 잠긴다**.

- 실패 분류: [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md) — 6개 카테고리(C1–C6) + 9개 우선순위 백로그
- 회귀 가드: `tests/test_*_regression.py` 패턴. 각 테스트의 docstring이 originating issue를 링크 — 예: `tests/test_partial_topic_grounding.py`는 #69, #89를 모두 링크
- 결정 기록: 변경마다 [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Decision Log entry로 ablation 비교 + 채택 이유 + reproducibility recipe 남김

**인터뷰 talking point**: "issue #69(`PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.5`)는 `accuracy +0.118`을 기록했지만 `intended-abstention`을 회귀시켰다. 합성 표면이 잡지 못한 이 trade-off를 ADR 0005 기반의 비공개 평가가 잡았고, 후속 issue #89가 `matched ≥ 2` 구조적 floor로 해결했다 — 회귀 가드(`test_relaxed_rejects_one_of_two_partial_topic_match`)와 합성 케이스(`abstention_one_of_two_topic_overlap`)를 함께 추가해 다음번 합성 CI에서도 잡히게 만들었다."

이 한 사건이 **C6(false abstention) 실패 카테고리 → real-data로 발견 → ablation 비교 → 구조적 fix → 회귀 잠금**의 full loop을 모두 보여준다.

## 시니어 시그널 4 — 거버넌스가 코드와 같이 진화한다

규칙은 문서에만 적혀있는 것이 아니라 **자동화로 강제**된다.

| 규칙 | 어디에 적혀있나 | 어떻게 강제되나 |
|---|---|---|
| Pre-PR 7-item 체크리스트 | [`.github/pull_request_template.md`](../.github/pull_request_template.md) | PR template + 리뷰 게이트 |
| Real-data delta 첨부 (load-bearing 변경) | [`.github/pull_request_template.md`](../.github/pull_request_template.md) §5b | `.githooks/pre-push` 옵션 hook + PR 가이드 |
| ADR threshold | [`CLAUDE.md`](../CLAUDE.md) §"Core principles" + [`docs/adr/README.md`](./adr/README.md) | 리뷰어 명시적 질문 |
| Public/private eval 분리 | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md) | `scripts/run_real_eval_delta.py`의 `SAFE_TOPLEVEL_KEYS` / `FORBIDDEN_KEYS` enforcement |
| Answer contract immutability | [ADR 0003](./adr/0003-structured-answer-citation-contract.md) | `score_answer_format` in `eval/run_eval.py` |
| README metrics ↔ report 동기화 | `scripts/update_readme_metrics.py` + CI gate | `scripts/update_readme_metrics.py --check` (CI) |
| Naive baseline 보존 | [ADR 0001](./adr/0001-preserve-naive-baseline.md) | `eval/config.yaml`의 `naive_baseline` ablation 매번 실행 |

거버넌스가 어떻게 anti-pattern을 차단하는지는 [`engineering-governance.md` §"Anti-patterns this governance is designed to prevent"](./engineering-governance.md) 참조.

## 시니어 시그널 5 — 재현성을 갖춘 시연

리뷰어가 클론한 직후 한 명령으로 시스템을 돌려볼 수 있다.

```bash
make smoke   # build_index → sample query → eval → README check
```

- 외부 API/네트워크 의존 없음 (`EMBEDDING_BACKEND=hashing`)
- 결정성 (`hashing` backend) → 같은 입력에 같은 출력
- 산출물: `outputs/answer.json`, `reports/eval_summary.json`

운영 데모는 [`docs/api-demo.md`](./api-demo.md)의 FastAPI 한 줄 startup으로 분리되어 있다 — playground이지만 measurement source는 절대 아님 ([`engineering-governance.md` table](./engineering-governance.md) 참조).

## 인터뷰에서 받을 만한 질문과 답의 위치

| 질문 | 답이 있는 곳 |
|---|---|
| "왜 RAG에서 generation 모델보다 retrieval/verification에 더 투자했나요?" | [`portfolio-case-study.md` §3, §5](./portfolio-case-study.md) |
| "성능 숫자를 어떻게 신뢰할 수 있나요?" | 이 문서 §2 + README "핵심 성능표" + `make smoke` |
| "real-data와 synthetic의 격차를 어떻게 다루나요?" | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md) + [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) |
| "회귀 발생을 어떻게 막나요?" | 이 문서 §3 + `tests/test_*_regression.py` |
| "한국어 RFP의 메타데이터 기반 retrieval은 어떤 trade-off가 있나요?" | [ADR 0002](./adr/0002-metadata-first-retrieval.md) + [`docs/retrieval-hardening.md`](./retrieval-hardening.md) |
| "abstention/insufficient는 왜 별도 status로 두었나요?" | [ADR 0003](./adr/0003-structured-answer-citation-contract.md) + [`docs/answer-policy.md`](./answer-policy.md) |
| "확장한다면 다음 우선순위는?" | [`portfolio-case-study.md` §7](./portfolio-case-study.md) + 메타 이슈 #49 |

## 이 프로젝트가 입증하지 않는 것 (정직한 범위)

시니어 시그널은 **무엇을 입증하지 않는지 명확히 말하는 것**도 포함한다.

- **대규모 generalization 성능**: 공개 합성 평가는 N=37, 비공개 real-data 표면은 N=21. 둘 다 일반화 주장의 근거가 아니라 **흐름·계약 검증**의 surface다. README는 이 한계를 명시한다 ([`portfolio-case-study.md` §2 마지막 문단](./portfolio-case-study.md)).
- **상업적 LLM 의존성에서의 성능**: 공개본은 결정성을 위해 hashing embedding + extractive answer를 사용한다. 운영 환경에서 dense embedding + LLM generation을 결합할 경우의 실측치는 별도 surface가 필요.
- **현존 RFP QA 솔루션과의 직접 비교**: 이 프로젝트는 비교 벤치마크가 아니라 **하나의 설계 결정 흐름**의 portfolio다. 절대 SOTA 주장이 아니다.

## 읽는 순서 (시간 예산별)

**5분 — 리뷰 우선**
1. [`reviewer-evidence-pack.md`](./reviewer-evidence-pack.md) (5-min demo + 대표 질의)
2. README "핵심 성능표"

**15분 — 포트폴리오 평가**
1. 이 문서 §"시니어 시그널 한눈에 보기" 표
2. [`portfolio-case-study.md`](./portfolio-case-study.md) §3, §5, §7
3. ADR 0005 + 0003 (load-bearing 결정 둘만)

**30분 — 깊이 있는 평가**
1. [`engineering-governance.md`](./engineering-governance.md) 전체
2. ADR 6개 모두 (5분씩)
3. 이 문서 §3의 #69 → #89 case study
4. [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) Decision Log 1–2 entries
