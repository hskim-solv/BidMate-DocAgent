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
| 아키텍처 결정이 **사후 합리화가 아닌 기록된 결정**으로 남아있다 | [`docs/adr/`](./adr/README.md) — 14개 ADR (12 accepted / 2 proposed), status-tracked, supersession chains 명시 |
| **측정 가능한 성공 기준**을 미리 잡고 그 기준으로 평가한다 | [`portfolio-case-study.md` §2](./portfolio-case-study.md), [`eval/config.yaml`](../eval/config.yaml), README headline 표 |
| 합성 평가의 한계를 알고 **공개/비공개 평가 분리**로 보완한다 | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md), [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) |
| **실패를 분류·우선순위화**한 뒤 백로그로 만든다 | [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md), 메타 이슈 #49 |
| 회귀가 **다시 발생하지 않도록 테스트로 잠근다** | `tests/test_*_regression.py`, [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Real-data Decision Log |
| **거버넌스가 코드와 같이 진화**한다 (rule book → 규칙 → 자동화) | [`CLAUDE.md`](../CLAUDE.md), [`docs/engineering-governance.md`](./engineering-governance.md), `.github/workflows/` |
| **재현 가능한 시연**으로 주장 가능한 수치만 README에 올린다 | `make smoke`, `scripts/update_readme_metrics.py --check`, README "핵심 성능표" |

## 시니어 시그널 1 — 아키텍처 결정의 추적성

각 ADR은 **하나의 의사결정**을 다룬다. 14개를 빠르게 읽고 나면, 이 시스템에서 어떤 선택이 load-bearing인지와 supersession chain이 명확해진다.

| ADR | 상태 | 결정 | 시니어 관점에서 왜 중요한가 |
|---|---|---|---|
| [0001](./adr/0001-preserve-naive-baseline.md) | accepted | naive baseline을 ablation으로 보존 | 후속 retrieval 변경의 효과를 항상 baseline 대비로 측정 가능 |
| [0002](./adr/0002-metadata-first-retrieval.md) | accepted | metadata-first retrieval | 의미 유사도 단독의 함정(기관·문서 단위 제약 누락)을 회피한 trade-off |
| [0003](./adr/0003-structured-answer-citation-contract.md) | accepted | answer/citation 계약 (`schema_version: 2`) | 후속 변경이 silent contract drift를 만들 수 없게 잠금 |
| [0004](./adr/0004-verifier-retry-policy.md) | accepted | strict→relaxed verifier staging | latency 비용을 인정하면서 partial coverage를 잡는 명시적 정책 |
| [0005](./adr/0005-eval-split-public-synthetic-private-local.md) | accepted | 공개 합성 vs 비공개 로컬 평가 분리 | 외부 공개 제약과 일반화 한계를 인정하면서 reproducibility를 지키는 설계 |
| [0006](./adr/0006-llm-judge-on-real-data-only.md) | accepted | LLM-judge는 real-data 표면에서만 (refines 0004) | 공개본의 결정성과 실제 신호를 동시에 살리는 비대칭 결정 |
| [0007](./adr/0007-issue-linked-branch-naming.md) | accepted | issue-linked 브랜치 네이밍 (`<type>/issue-N`) | 추적성을 doc이 아니라 CI(`branch-and-issue-check.yml`)로 강제 |
| [0008](./adr/0008-evidence-boundary.md) | accepted | evidence boundary defense | prompt injection을 contract surface에서 차단 — 보안 의식의 명시화 |
| [0009](./adr/0009-external-baseline-comparison.md) | proposed | LangChain/LlamaIndex 외부 baseline 분리 비교 (extends 0001) | "왜 자체 구축?" 질문에 비대칭 metric(citation/grounding)으로 정량 답변 |
| [0010](./adr/0010-hybrid-bm25-dense-retrieval-rrf.md) | accepted | hybrid BM25 + dense + RRF | retrieval 보강은 *추가 ablation*으로만; 단일 backend로 결합 안 함 |
| [0011](./adr/0011-llm-synthesis-as-additive-ablation.md) | proposed | LLM 합성은 additive ablation (extends 0001, preserves 0003) | answer_text 렌더링만 LLM 교체; claims/citations/status는 결정적 verifier가 그대로 결정 |
| [0012](./adr/0012-llm-judge-on-public-synthetic.md) | accepted | LLM-judge on public synthetic, stub-default (refines 0006, reuses 0011) | judge backend는 결정적 stub으로 CI 통과; real backend는 운영자 옵트인 |
| [0013](./adr/0013-observability-as-additive-pluggable-surface.md) | accepted | observability를 additive·pluggable·fail-closed로 | trace backend(LangFuse/OTel) 장애가 query를 깨뜨리지 않음; LLM Ops 의식의 코드화 |
| [0014](./adr/0014-ragas-judge-additive-synthetic.md) | accepted | RAGAS judge as additive enrichment (extends 0012) | 외부 표준 메트릭으로 cross-validation; 결정적 stub-default 유지 |

**인터뷰 talking point 1 (real-data 회귀)**: "ADR 0005가 없었다면 공개본의 abstention 회귀(#69의 `1.000 → 0.500` 사건)는 아무도 보지 못했을 것이다. 공개 합성만 보던 시기에는 1-of-2 incidental overlap 패턴이 잡히지 않았다." — 근거: [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) 2026-05-11 entry.

**인터뷰 talking point 2 (additive ablation 규율)**: "ADR 0011은 LLM 합성을 *추가*하지만 ADR 0001의 extractive baseline을 *대체하지 않는다*. `agentic_full_llm` preset은 같은 claims/citations에 answer_text만 LLM으로 렌더링하고, evidence에 없는 chunk_id를 인용하면 거부되고 extractive로 fallback. ADR 0013의 observability도 같은 패턴 — additive + fail-closed. 새 기능이 들어와도 기존 measurement surface가 손상되지 않게 보존한다는 규율이다."

**인터뷰 talking point 3 (보안 contract)**: "ADR 0008은 prompt injection 방어를 *답변 contract의 일부*로 정의한다. evidence boundary 마커로 LLM이 외부 텍스트를 instruction이 아닌 데이터로 보도록 강제 — 검증 가능한 자리(테스트 `test_prompt_injection_regression.py`)에 보안이 잠겨있어야 시니어 코드 리뷰에서 통과한다."

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
make smoke      # build_index → sample query → eval → README check
make reproduce  # smoke + SHA-256 over the environment-invariant metric subset
```

- 외부 API/네트워크 의존 없음 (`EMBEDDING_BACKEND=hashing`)
- 결정성 (`hashing` backend) → 같은 입력에 같은 출력
- 산출물: `outputs/answer.json`, `reports/eval_summary.json`
- **크로스머신 재현성 증명**: `make reproduce`가 `eval_summary.json`에서 latency·timestamp 같은 host-dependent 필드를 제거한 후 SHA-256을 계산한다. 같은 해시가 다른 머신(Linux container 등)에서 나오면 결정성 주장이 *증명 가능*한 형태로 backing된다 — `BASELINE=<hash> make reproduce`로 비교 시 mismatch는 exit 2.

운영 데모는 [`docs/api-demo.md`](./api-demo.md)의 FastAPI 한 줄 startup으로 분리되어 있다 — playground이지만 measurement source는 절대 아님 ([`engineering-governance.md` table](./engineering-governance.md) 참조).

**구조화 로깅**: `BIDMATE_LOG_FORMAT=json make demo`로 stdout JSON 로그를 흘려보내면 stage별 `query_start`/`query_complete` 이벤트가 `query_hash`/`latency_ms`/`status`/`retry_count`/`abstained` 필드와 함께 떨어진다. 로그 aggregation(CloudLogging/ELK/Datadog)에 그대로 꽂아 운영 관찰성을 확장 가능. 구현은 [`bidmate_logging.py`](../bidmate_logging.py).

## 인터뷰에서 받을 만한 질문과 답의 위치

| 질문 | 답이 있는 곳 |
|---|---|
| "왜 RAG에서 generation 모델보다 retrieval/verification에 더 투자했나요?" | [`portfolio-case-study.md` §3, §5](./portfolio-case-study.md) |
| "성능 숫자를 어떻게 신뢰할 수 있나요?" | 이 문서 §2 + README "핵심 성능표" + `make smoke` |
| "real-data와 synthetic의 격차를 어떻게 다루나요?" | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md) + [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) |
| "회귀 발생을 어떻게 막나요?" | 이 문서 §3 + `tests/test_*_regression.py` |
| "한국어 RFP의 메타데이터 기반 retrieval은 어떤 trade-off가 있나요?" | [ADR 0002](./adr/0002-metadata-first-retrieval.md) + [`docs/retrieval-hardening.md`](./retrieval-hardening.md) |
| "abstention/insufficient는 왜 별도 status로 두었나요?" | [ADR 0003](./adr/0003-structured-answer-citation-contract.md) + [`docs/answer-policy.md`](./answer-policy.md) |
| "prompt injection은 어떻게 막나요?" | [ADR 0008](./adr/0008-evidence-boundary.md) + `tests/test_prompt_injection_regression.py` |
| "LangChain/LlamaIndex 안 쓰고 왜 자체 구축?" | [ADR 0009](./adr/0009-external-baseline-comparison.md) — 비대칭 metric(citation/abstention)을 외부 시스템이 producer 못하는 게 정량 답변 |
| "LLM-as-judge bias는 어떻게 다루나요?" | [ADR 0012](./adr/0012-llm-judge-on-public-synthetic.md) + [ADR 0014](./adr/0014-ragas-judge-additive-synthetic.md) — stub-default + RAGAS cross-check |
| "운영에서 latency/cost/trace는 어떻게 봅니까?" | [ADR 0013](./adr/0013-observability-as-additive-pluggable-surface.md) + [`docs/observability.md`](./observability.md) — LangFuse/OTel pluggable, fail-closed |
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
