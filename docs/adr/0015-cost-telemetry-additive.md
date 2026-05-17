# 0015: 비용 telemetry 를 추가 관측성으로 (0011, 0013 확장)

- **Status**: Superseded
- **Superseded by**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) § "Additive opt-in pattern (generalization)"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (LLM 합성), [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (트레이스 백엔드), `rag_synthesis.py`, `tests/test_synthesis_cost_telemetry.py`

## TL;DR

- LLM 합성에 쿼리당 USD 비용 추정 추가 — `cache_read_tokens` / `cache_write_tokens` / `cost_estimate_usd` 키.
- `compute_cost_usd` 가 단일 source of truth; 미상 모델은 `None` 반환 (가격 invent 안 함).
- `SYNTHESIS_SCHEMA_VERSION` 2 로 bump; ADR 0003 answer 계약은 손 안 댐 (`diagnostics` 거주).

## 배경

LLM 합성 경로 (ADR 0011) 가 이미 `diagnostics.synthesis` 에 `tokens_in` / `tokens_out` 포착, 그러나 공개 합성 표면 기본은 stub 백엔드라 CI 비용은 늘 0. 실데이터 흐름 (`BIDMATE_SYNTHESIS_BACKEND=anthropic`) 에선 operator 가 *답변 비용* 이나 *프롬프트 캐싱이 실제 도움 되는지* 에 대한 in-repo 신호 부재 — 둘 다 시니어 LLM-Ops 리뷰 1순위 질문.

트레이스 백엔드 (ADR 0013) 가 span 데이터를 LangFuse/OTel 에 송신하나, 그 백엔드들은 선택·쿼리 downstream. 파이프라인 자체가 비용 추정을 운반해야 — noop 트레이스 백엔드 케이스 ("operator 가 로컬 실행, LangFuse 계정 없음") 에서도 감사 흔적이 남도록.

실 청구 source of truth 는 Anthropic 콘솔 — 그것을 대체하려는 게 아님. 기존 eval 메트릭 옆에 거주할 *order-of-magnitude 회귀 신호* ("이 리팩터가 토큰 소비 10x") 필요.

## 결정

쿼리당 LLM 비용을 ADR 0013 이 트레이스 다루는 방식과 동일하게 — *additive*, *pluggable*, *fail-closed*.

구체적으로:

1. `rag_synthesis.SYNTHESIS_SCHEMA_VERSION` 을 **2** 로 bump. `synthesis` meta dict 가 새 키 3개 (항상 존재, `None` 가능) 획득:
   - `cache_read_tokens`
   - `cache_write_tokens`
   - `cost_estimate_usd`
2. `rag_synthesis.compute_cost_usd(model, tokens_in, tokens_out, cache_read_tokens, cache_write_tokens)` 가 Mtok 당 가격 표 단일 source of truth. 미상 모델은 `None` 반환 (stub / openai-compatible 배포 가격 invent 안 함).
3. Anthropic 백엔드가 SDK `usage` 객체에서 `cache_read_input_tokens` 와 `cache_creation_input_tokens` 포착. tool 정의에 기존 시스템 프롬프트 캐시 breakpoint 옆 `cache_control: ephemeral` 부여 → 반복 쿼리 캐시-히트 표면 극대화.
4. 가격 카드는 `PRICING_PER_MTOK_USD` 에 base 모델 id 키 (longest-prefix match 로 dated SKU resolve). 업데이트는 본 ADR 이력에 한 줄 provenance 노트 + 작은 PR.

기본 백엔드는 `stub` 유지 — 공개 CI 결제·비용 보고·가격 카드 의존 없음.

## 결과

Easier:

- 실데이터 리뷰가 `diagnostics.synthesis.cost_estimate_usd` 직접 읽어 "쿼리당 $" 답 가능. `eval/run_eval.py` 집계는 follow-up PR.
- "프롬프트 캐싱 활성" 이 더 이상 wish 아님 — 2번째 호출의 `cache_read_tokens > 0` 가 증명. 계약 테스트 (`test_meta_promotes_payload_cache_tokens`) 가 표면 lock.
- ADR 0003 답변 계약 미접촉; 비용은 `diagnostics` 에 거주, 명시적으로 비계약 표면.

Harder / costs:

- `SYNTHESIS_SCHEMA_VERSION` 2 로 bump. v1 pin 한 consumer 는 업데이트 필요 — ADR 0003 의 "조용한 drift 없음" 가드를 합성 meta 블록에 적용. 병행 v2 dict 도입보다 저렴 판단.
- Anthropic 가 새 tier 발표 시 가격 카드 종종 업데이트. owner: 다음 ADR-noteworthy 합성 변경 여는 자. 상수는 `rag_synthesis.py:PRICING_PER_MTOK_USD`.
- OpenAI 호환 배포 가격 미적용. 로컬 vLLM/llama.cpp 는 0 청구, 유료 배포는 배포별 override 필요 — 본 범위 외.

## 검토한 대안

- **토큰만 추적, USD skip**: 유지 보수 쉬움 (가격 카드 없음), 그러나 시니어 신호 "쿼리당 $" 가 정확히 reviewer 요구. 토큰만으론 rate card 지식 필요.
- **Anthropic 결제 API 에서 비용 소스**: 정답 제공하나 유료-API dep + 오프라인 CI 약속 깨짐. CLAUDE.md non-goal 위반.
- **`answer` dict 에 비용 embed**: ADR 0003 위반 (answer 는 검증 가능 계약; 비용은 생성의 부수효과). `diagnostics` 표면이 옳은 자리.
- **별도 `rag_cost.py` 모듈**: 조기 추상화. 비용 표는 현재 유일 생산자 (합성) 옆 거주; 두 번째 생산자 (예: 평가자 백엔드) 등장 시 추출.
