# 0011: LLM 답변 합성을 분석 변형으로 추가

(원래 [#142](https://github.com/hskim-solv/BidMate-DocAgent/pull/142) 에서 ADR 0007 로 머지됐으나, 먼저 머지된 governance ADR [`0007-issue-linked-branch-naming.md`](./0007-issue-linked-branch-naming.md) 과 파일명 충돌로 0011 로 번호 재지정.)

- **Status**: proposed
- **Date**: 2026-05-11
- **Related**: extends [ADR 0001](./0001-preserve-naive-baseline.md); preserves [ADR 0003](./0003-structured-answer-citation-contract.md); reuses backend pattern from [ADR 0006](./0006-llm-judge-on-real-data-only.md); **complemented by** [ADR 0024](./0024-agentic-full-llm-as-api-default.md) (API 프리셋 기본값은 `agentic_full_llm` 로 전환; 백엔드 기본은 `stub` 유지); 구현 워크스루는 [`docs/agentic/answer-policy.md`](../agentic/answer-policy.md#계약-강제-메커니즘)
- **Deciders**: hskim
- **Update (PR-I, issue #405, 2026-05-12)**: API 표면 기본 프리셋이 `agentic_full` → `agentic_full_llm` 로 전환 ([ADR 0024](./0024-agentic-full-llm-as-api-default.md)). 본 ADR 이 정한 *백엔드* 추가성 계약은 불변 — `BIDMATE_SYNTHESIS_BACKEND=stub` 가 여전히 기본이라 공개 API 호출도 결정론적 stub 렌더러에서 LLM 합성 프리셋을 실행. CLI (`naive_baseline`, ADR 0001) 와 함수 레벨 (`agentic_full`) 기본은 그대로.

## TL;DR

- 파이프라인은 end-to-end 추출형 — `generate_answer` 가 검색된 문장을 그대로 이어붙임.
- LLM 합성을 *추가 분석 변형* 으로 도입: 추출형 기준선·ADR 0003 계약 보존, `summary` / `answer_text` 만 재작성.
- 백엔드 dispatch (`stub` 기본 / `anthropic` / `openai_compatible`) 로 공개 CI 결정론 유지 + 실데이터·라이브 데모만 라이브 LLM.

## 배경

파이프라인은 end-to-end 추출형. [`rag_core.py:L2242`](../../rag_core.py) 의 `generate_answer` 가 검색된 문장으로 `claims` 를 만들고 chunk-id 접미사를 붙여 `render_answer_text` (L2494) 가 `answer_text` 를 연결. 공개 데모를 결정론·무료·환각 한계로 묶기 위한 설계로, 인용된 모든 문자열은 근거 chunk 의 verbatim.

근거 연결 엄밀성 면에서 옳은 트레이드오프지만 시스템 reader 에게 보이는 세 가지 갭이 남는다.

1. **읽기 흐름이 기계적.** `render_answer_text` 가 claim 문자열에 `[chunk_id]` 를 붙여 잇기만 함 — 사람이 쓴 답변처럼 읽히지 않고, 비교 답변은 분석이 아닌 병렬 bullet 리스트로 보임.
2. **파이프라인에 LLM 표면 자체가 없음.** 프롬프트 엔지니어링, 구조화 출력, tool use, prompt caching — 2026 년 AI 엔지니어 표면의 기본기 — 가 들어설 자리가 없음. 검색 시스템으로는 평가되지만 LLM 애플리케이션으로는 평가 불가.
3. **비용 / 지연 / 모델 트레이드오프가 eval 매트릭스에 부재.** ADR 0006 이 실데이터 eval 표면에 *평가자* 로서 LLM 을 도입했으나, 시스템 자체에 대한 비교 표면이 없음.

추출형 기본을 뒤집으면 ADR 0001 (단순 경로 기준선 보존) 과 충돌하고 ADR 0003 인용 계약이 위험. 올바른 수는 ADR 0001 이 naive baseline 을 지킨 방식과 같음 — **추출형 경로를 일급 기준선으로 두고 LLM 합성을 그 옆에 추가.**

## 결정

LLM 답변 합성은 **추가** 분석 변형 경로로 허용 (대체 아님). 구체적으로:

- [`rag_core.py`](../../rag_core.py) 에 새 `prompt_profile` 값 `llm_synthesis` 를 `minimal_grounded_extractive` (naive), `structured_grounded_claims` (agentic_full 추출형) 와 함께 도입.
- 새 `PIPELINE_PRESETS` 항목 `agentic_full_llm` 이 `prompt_profile=llm_synthesis` 로 두고 나머지 검색·검증기 설정은 `agentic_full` 상속.
- [`eval/config.yaml`](../../eval/config.yaml) 에 `agentic_full` (추출형) + `agentic_full_llm` (LLM) 둘 다 분석 변형 run 으로 등록 — 모든 eval 호출이 side-by-side 비교를 생성. `agentic_full` 는 회귀 가드 유지, `agentic_full_llm` 가 새 컬럼.
- `naive_baseline` 은 **불변**. ADR 0001 불변식 유지.

### 계약 보존 (ADR 0003)

`generate_answer` 는 계속 `schema_version: 2` JSON 반환. LLM 합성 경로는:

- `build_claims` 를 **재사용** 해 claim 리스트 생산. claim 과 인용은 여전히 추출형 — `chunk_id` 참조는 동일한 `evidence` 로 resolve.
- **`summary` 와 `answer_text` 만 재작성.** LLM 에 `(query, analysis, claims, evidence_chunks)` 를 주고 사람이 읽기 좋은 summary + 장형 `answer_text` 생산. 둘 다 ADR 0003 의 검증 가능 계약 밖 ("`answer_text` 는 … 검증 가능 계약의 일부 아님; tooling 은 여기에 의존 금지").
- **새 인용을 도입 불가.** LLM 이 `evidence` 에 없는 chunk id 를 emit 하면 합성 reject + 추출형 `render_answer_text` 로 폴백. 이 가드는 soft check 아닌 hard postcondition.
- **`status`, `claims`, `insufficiency`, `status_reason` 변경 불가.** 합성 *이전* 결정론 검증기가 계산한 입력만 받음.

`status != supported` 면 합성 전체 skip + 오늘과 동일한 추출형 경로. 보류 메시지는 결정론 유지.

### 백엔드 pluggability

ADR 0006 패턴 재사용: `BIDMATE_SYNTHESIS_BACKEND`:

- `stub` (기본) — 결정론 fixture; claim 을 템플릿 단락으로 연결. 네트워크 없음. `make smoke`, `pr-eval.yml`, 테스트에서 사용.
- `anthropic` — Claude API (Sonnet 4.6 기본, `BIDMATE_SYNTHESIS_MODEL` 로 Haiku 4.5 opt-in). `ANTHROPIC_API_KEY` 필요. 시스템 프롬프트 + few-shot 예시 prompt caching 사용 (실 eval run 전반 ≥ 80% 토큰 감소). tool use 로 출력 형태 `{summary: str, answer_text: str, used_chunk_ids: list[str]}` 강제.
- `openai_compatible` — 일반 OpenAI 호환 엔드포인트; 동일 형태·가드. vLLM / llama.cpp / Solar / KURE-finetuned 모델을 파이프라인 손 안 대고 한국 스택 스토리에 스왑 가능.

### 주기

- **공개 합성 CI**: `BIDMATE_SYNTHESIS_BACKEND=stub`. Eval 델타 job 은 `naive_baseline` vs `agentic_full` (둘 다 결정론) 비교 유지 + `agentic_full_llm` 를 stub 백엔드로 *추가* 컬럼 보고. stub 은 plumbing 운동 + 계약 lock 용도 — 실 LLM 품질 주장 아님.
- **실데이터 eval**: `BIDMATE_SYNTHESIS_BACKEND=anthropic`. LLM 컬럼 집계 메트릭은 ADR 0005 commit 경계 넘김; raw 프롬프트·raw 응답은 로컬. 토큰 수·쿼리당 비용은 집계되어 commit 가능.
- **라이브 데모**: `anthropic` 백엔드, rate-limit, prompt-cached.

## 결과

**Wins**

- 시스템이 LLM 표면 (프롬프트 엔지니어링, 구조화 출력, tool use, prompt cache, streaming) 획득 + ADR 0003 위험 없음. "no new chunk_ids" 가드가 인용 계약을 기계적으로 보존.
- Eval 매트릭스 1 컬럼 추가. `agentic_full` (추출형·결정론) 와 `agentic_full_llm` (LLM·stub or 라이브) 가 side-by-side → LLM 경로가 ADR 0001 하에서 agentic 파이프라인이 그랬듯 자기 슬롯을 *earn* 해야 함.
- 지연·비용 frontier 가 가시화: 추출형 ~ms, stub-LLM 무시할 오버헤드, anthropic-LLM 토큰 + ms. 캐싱·모델 선택에 대한 향후 ADR 이 측정 가능한 기준선 보유.
- ADR 0006 백엔드 패턴 재사용 → 코드베이스에 "LLM 추가 방법" 의 일관 관용구 1개.

**Costs**

- 답변 렌더링 경로 3개 유지: 추출형, stub-LLM, 라이브-LLM. 공유 입력 계약 (`(answer_dict, evidence)` → `answer_text`) 으로 완화. 회귀 테스트 1개가 셋 다 운동.
- 라이브-eval run 당 토큰 소비. 실데이터 수동 주기 (~ 100 케이스 × cached prompt) + 공개 CI `stub` 기본으로 bound. 비용은 `reports/real100/aggregate.json` 에 노출.
- 사용자가 이해할 환경 변수 family 1개 추가. 기본이 `stub` (오프라인·무키) 으로 완화.

**Constraints (불변)**

- ADR 0001: `naive_baseline` 가 [`pipeline_cli_choices()`](../../rag_core.py) 유지 + CLI 기본.
- ADR 0003: `schema_version: 2`, `status` 값, `claims[].citations`, `evidence[]` 불변. `schema_version` **bump 안 함**.
- ADR 0005: 실데이터 케이스별 LLM 출력은 로컬. 집계 (평균 비용·지연·`citation_precision` 델타) 만 commit.

## 추가 opt-in 패턴 (일반화)

ADR 0011 이 후속 ADR 0015, 0017, 0027 이 verbatim 재사용한 반복 패턴 확립. 해당 ADR 들은 여기 Superseded 로 통합; 결정 자체는 불변. 패턴:

1. **기본은 결정론·무료.** `stub` (또는 `regex`) 백엔드가 모든 CI 호출에서 실행 — 네트워크·비용·재현성 없음.
2. **단일 env-var 로 opt-in.** `BIDMATE_<FEATURE>_BACKEND` 가 `stub` (기본) | `anthropic` | `openai_compatible` dispatch. 미상·실패 백엔드는 조용히 stub 로 degrade.
3. **상류 계약 변경 금지.** 기능은 *진단* 또는 *추가 분석 변형 row* 표면에만 기록 — `answer.status`, `claims`, `citations`, `naive_baseline` 메트릭은 수정 불가.
4. **`eval/config.yaml` 에 새 분석 변형 row 1개.** 기능은 코드 경로뿐 아니라 컬럼으로도 측정 가능.
5. **stub-matches-baseline 불변식이 계약 테스트.** `test_*_baseline_invariant.py` 가 stub-백엔드 출력과 결정론 기준선의 byte-equal 검증.

**통합된 instance:**

| ADR | 기능 | Env-var | Stub 불변식 |
|-----|---------|---------|---------------|
| 0015 | 비용 telemetry (토큰, USD 추정) | n/a — 진단 전용 | `SYNTHESIS_SCHEMA_VERSION` bump; 미상 모델 → `None` |
| 0017 | LLM 메타데이터 추출 | `BIDMATE_METADATA_BACKEND` | `stub` 가 `regex` 위임; byte-equal |
| 0027 | LoRA 임베딩 어댑터 | `BIDMATE_EMBEDDING_LORA_ADAPTER` | unset = pre-#434 byte-identical; lazy PEFT import |

## 검토한 대안

- **추출형 경로를 LLM 합성으로 전면 대체.** Reject: ADR 0001 보존 논증과 충돌 + LLM 인용 드리프트에 대한 회귀 가드 제거. 결정론 CI 표면 상실.
- **명명 프리셋 없이 CLI 플래그 뒤에만 LLM 합성 추가.** Reject: ADR 0001 의 "조용한 경로는 썩는다" 가 적용. 출시 가치가 있다면 모든 eval 호출에서 돌아가는 명명 프리셋이 되어 `agentic_full` 대비 델타가 항상 가시.
- **LLM 이 `claims` 와 `citations` 도 재작성.** 현재 reject: 구성상 ADR 0003 위반 (인용이 `evidence` 로 resolve 보장 안 됨). 더 엄격한 인용 검증 pass (emit 한 모든 chunk_id 가 resolve 필요; 모든 claim 이 ≥ 1 chunk 인용 필요) 와 `schema_version: 3` 동반 후속 ADR 로 revisit.
- **tool use / 구조화 출력 없는 free-text LLM 엔드포인트.** Reject: `used_chunk_ids ⊆ evidence.chunk_ids` postcondition 이 parse 에 brittle. tool use 가 가드를 단순 집합 멤버십 체크로 만듦.
