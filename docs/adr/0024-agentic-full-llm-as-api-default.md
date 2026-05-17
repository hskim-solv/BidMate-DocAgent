# 0024: agentic_full_llm을 API default로 (preset만; backend default는 stub 유지)

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (CLI default는 naive_baseline 유지), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (보완 — backend additive opt-in 유지), [ADR 0022](./0022-langgraph-orchestration-stage-1.md) (직교 — orchestrator 경로도 opt-in), issue #405

## TL;DR

- 외부 senior review #1/#2 — README "Agentic RAG" 표기와 API default 불일치 지적("extractive-only by design"으로 결론).
- API default preset만 `agentic_full` → `agentic_full_llm` flip(이 ADR 유일 코드 변경). backend default `stub` 유지 → CI 결정성 + 비용 0 보존.
- CLI default `naive_baseline`(ADR 0001) + 함수-level default `agentic_full` + API default `agentic_full_llm` 3개 정책선이 회귀 테스트로 pin.

## 배경

외부 senior review(2026-05) finding #1/#2가 "Agentic RAG" README label과 API 표면 default 불일치 비판. `pipeline` 파라미터 없이 `POST /query` 호출 시 reviewer는 `agentic_full`(추출형 `structured_grounded_claims` 프리셋)을 받음 → "extractive-only by design"으로 결론. 기술적으로 맞지만(ADR 0001이 `naive_baseline`을 최소 분석 변형으로 예약; ADR 0011이 `agentic_full_llm`을 additive opt-in으로 추가) *기본 표면*이 공개 framing과 불일치.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md)은 LLM 답변 합성을 `agentic_full_llm` 프리셋 하 `answer_text` / `summary` 렌더링 교체 *additive* 프리셋으로 머지, *backend*는 `BIDMATE_SYNTHESIS_BACKEND` opt-in(default `stub`, 결정적). "no new chunk_ids" 가드가 ADR 0003 인용 계약 보존 — LLM이 검색된 근거 밖 chunk_id 인용 시 합성 거부 + 추출형 렌더러 fallback.

reviewer 비판은 *API 표면에서* 정당: `agentic_full_llm` 존재해도 기본 API 호출이 `agentic_full` 노출. PR-I는 "보수적 흡수" — API preset default flip(backend default flip 없이). ADR 0011은 accepted 유지; 본 ADR은 *보완*(supersede 아님)이며 ADR 0011이 확보한 backend-level additivity 보존하면서 preset-level dispatch 변경.

## 결정

**3개 정책선, 3개 별도 default — 코드 + 테스트로 pin:**

1. **CLI default(`app.py`, `rag_pipeline_presets.DEFAULT_CLI_PIPELINE_NAME`)는 `naive_baseline` 유지.** ADR 0001 재현성 불변.
2. **함수-level default(`rag_pipeline_presets.DEFAULT_RAG_PIPELINE_NAME`, `run_rag_query(pipeline=…)`)는 `agentic_full` 유지.** `eval/run_eval.py`, `scripts/run_benchmark.py`, `demo/streamlit_app.py`, 테스트 스위트 직접 호출자는 기존 동작 유지. `pipeline=` 없이 `run_rag_query(…)` 호출자는 본 ADR 이전과 동일 프리셋 수신.
3. **API 표면 default(`api/main.py:DEFAULT_API_PIPELINE`)는 `agentic_full_llm`으로 flip** — 본 ADR 유일 코드 변경.

*backend* default는 `BIDMATE_SYNTHESIS_BACKEND=stub` 유지(ADR 0011 무변경). 기본 API 호출은 `agentic_full_llm` 프리셋의 structured-grounded-claims 검색 + **stub synthesis** 렌더러 실행 — 결정적, token-less, CI-reproducible. 실제 LLM 합성은 operator가 `BIDMATE_SYNTHESIS_BACKEND=anthropic`(또는 `openai_compatible`) 설정 시에만 활성 — ADR 0011 표면 그대로.

3 경계는 명시 회귀 테스트(`tests/test_api_default_pipeline_regression.py`)로 pin → 후일 기여자가 silently collapse 불가.

## "preset만, backend 아님" 분리 이유

backend default도 `anthropic` / `openai_compatible`로 flip하면:

- `pytest`가 `ANTHROPIC_API_KEY` / `BIDMATE_SYNTHESIS_API_KEY` 요구. CI는 실제 API 호출용 key fake 불가 → 공공 테스트 스위트 skip / fail.
- healthcheck probe + demo traffic 포함 모든 API hit에 per-query 실비 추가.
- 공공 `eval/run_eval.py` 분석 변형 결정성 깨짐(`full_llm` row가 현재 stub-backend 결과 보고; `docs/eval/embedding-ablation.md` + ADR 0012 동일 패턴).
- ADR 0011의 핵심 trade-off 소거: *agentic synthesis 프리셋은 observable, backend는 opt-in.*

preset만 flip하면 위 모두 보존. API 소비자는 `diagnostics.pipeline == "agentic_full_llm"`("Agentic" label이 응답과 일치) 확인 가능, 렌더러는 결정적 실행. 실제 LLM 응답 원하는 reviewer는 로컬에서 backend env var 설정 — 이전 flow 동일, 단 default preset만 변경 노출.

## 결과

쉬워진 점:

- "Agentic RAG" README label이 ADR 0001 재현성 비용 없이 default API 경험과 일치. CLI reviewer는 여전히 최소 추출형 기준선 수신; API 소비자는 agentic 합성 프리셋 확인.
- ADR 0011 "additive opt-in"이 backend level — 재현성/비용 보험을 실제 buy하는 지점 — 에서 의미 유지.
- 3 default 경계 개별 테스트(`test_cli_default_is_unchanged_naive_baseline`, `test_function_level_default_is_unchanged_agentic_full`, `test_module_constant_pins_agentic_full_llm`) → 향후 silent drift는 PR-eval 시점 검출.

비용 / 정직:

- `agentic_full_llm` + stub backend는 `agentic_full`과 동일 검색 + 검증기 표면이지만 다른 `prompt_profile`(`llm_synthesis` vs `structured_grounded_claims`). stub synthesis 렌더러는 추출형 렌더러와 약간 다른 `answer_text` shape 산출. 본 ADR 전/후 API 응답 비교 소비자는 `answer_text`에 실제 텍스트 diff 관찰(`claims` / `citations` 배열은 ADR 0003 계약으로 추출형 유지).
- 함수-level default는 blast radius 한정 위해 `agentic_full` 유지. ADR 0024 모른 채 코드 읽는 사람은 CLI / eval / API가 *다른* default 갖는 이유 의문 — 3 회귀 테스트 + 본 ADR이 답.

## 검토한 대안

- **`DEFAULT_RAG_PIPELINE_NAME`도 flip(함수-level).** 기각: `eval/run_eval.py` / `scripts/run_benchmark.py` / `demo/streamlit_app.py` / 회귀 테스트 스위트의 암묵 default silently 변경. CLAUDE.md "one PR, one concern" — 별도 소비자 표면 + 별도 정당화.
- **합성 backend default flip(stub → anthropic).** 기각 — 위 "preset만, backend 아님 분리 이유" 참조. CI 결정성 + per-call 비용 실재 우려.
- **쿼리-level `default` flag 추가.** 기각: 모든 caller에 결정 전가, reviewer 지적한 README-vs-default 불일치 미해결.
- **기존 default 문서화 + README framing만 변경.** 기각: reviewer 비판은 *동작*이지 prose 아님. `curl localhost:8000/query` 해서 `agentic_full` 보는 사람은 README 명확화로 설득되지 않음.
- **ADR 0011 전체 supersede.** 기각: ADR 0011이 본 ADR이 유지하는 *backend-level* additivity 확보. supersede는 backend-default 변경 함의 — 명시적으로 원치 않음. 보완-not-supersede가 올바른 관계.

## See also

- [`api/main.py`](../../api/main.py) — `DEFAULT_API_PIPELINE` 상수 + `_resolve_default_pipeline()` chain.
- [`tests/test_api_default_pipeline_regression.py`](../../tests/test_api_default_pipeline_regression.py) — 3 default 경계 pin.
- [ADR 0001](./0001-preserve-naive-baseline.md) — CLI default 정책.
- [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) — 본 ADR이 보완(supersede 아님)하는 additive 합성 표면.
