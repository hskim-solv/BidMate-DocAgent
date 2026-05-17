# 0017: LLM 메타데이터 추출을 추가 백엔드로 (0011 확장)

- **Status**: Superseded
- **Superseded by**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) § "Additive opt-in pattern (generalization)"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [#180](https://github.com/hskim-solv/BidMate-DocAgent/issues/180), [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md)

## TL;DR

- `rag_metadata_extraction` 모듈을 `rag_synthesis` 와 1:1 미러링 — `regex` 기본, `stub`/`anthropic_tool_use`/`openai_function_call` 백엔드.
- `stub` ↔ `regex` byte-equivalence 가 계약 단위 테스트 — ADR 0001 naive 기준선 불변식 유지.
- 8 필드 스키마 (#180) lock; LLM 추출은 opt-in, ingestion 경로 불변.

## 배경

오늘의 검색·답변 경로용 메타데이터는 [`ingestion.normalize_metadata`](../../ingestion.py) — 구조화 CSV 컬럼 + 결정론 regex 파싱 (예산 정규화, ISO 날짜 강제) 에서 옴. CSV row 가 불완전하거나 body 가 비구조 필드 (`contact_email`, `contact_name`) 운반하는 문서엔 regex 경로의 hard ceiling — 더 줄 신호 없음.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 이 이미 [`rag_synthesis.py`](../../rag_synthesis.py) 에 추가 LLM 백엔드 패턴 확립: 결정론 stub 기본, opt-in `anthropic` tool-use 백엔드, openai-compatible 대안, tool + 시스템 프롬프트 캐싱, SDK·키 누락 시 graceful 폴백. 이슈 #180 가 메타데이터 추출에 동일 shape 필요 — [ADR 0001](./0001-preserve-naive-baseline.md) naive 기준선 불변식 안 깨고 LLM-추출 메타데이터를 regex 기준선과 기존 eval 표면에서 비교.

## 결정

`rag_synthesis` 1:1 미러링하는 새 [`rag_metadata_extraction`](../../rag_metadata_extraction.py) 모듈 추가:

- 공개 진입점 `extract_rfp_metadata(document, backend=...)` 가 #180 의 8 필드 (`agency`, `project_name`, `budget_amount`, `budget_currency`, `deadline_iso`, `submission_date_iso`, `contact_email`, `contact_name`) 를 가진 typed `MetadataExtraction` dataclass 반환.
- 백엔드 (`BIDMATE_METADATA_BACKEND`): `regex` (기본 — ADR 0001 불변식 보존), `stub` (`regex` 위임 → stub 모드 byte-for-byte identical), `anthropic_tool_use`, `openai_function_call`.
- `stub` ↔ `regex` byte-equivalence 가 **계약 단위 테스트**. stub 모드 run 의 LLM 비용 0 + 스키마 drift 0 보장 → downstream consumer (eval 분석 변형 row, 대시보드) 가 LLM 경로 미활성 시 안정.
- tool 정의 `extract_rfp_metadata` 는 보수적: 모든 필드 선택 + `additionalProperties: false` → LLM 이 비구조 페이로드 smuggle 불가.
- 어떤 백엔드 예외든 `extract_rfp_metadata` 가 `_regex_backend` 로 폴백. 파이프라인이 SDK·네트워크 실패로 메타데이터 조용히 잃지 않음.
- body 텍스트는 LLM 전송 전 ~8000 chars 로 truncate. 매우 긴 RFP 는 후반 contact 누락 가능 — 첫 iteration 허용 + truncation 코호트 vs regex eval 회귀 non-trivial 시만 revisit.

## 결과

- `rag_synthesis` 친숙한 reader 가 `rag_metadata_extraction` 을 한 번에 이해: 동일 env-key 활성화, 실 백엔드 동일 `# pragma: no cover - network` 격리, 동일 stub-matches-baseline 계약 테스트, 동일 dataclass 노출 8 필드 스키마.
- 메타데이터 어휘를 #180 8 필드에 lock. 필드 추가는 스키마 변경 — #180 downstream eval 비교 표가 이 정확한 shape 키이므로 ADR 개정 필요.
- LLM 추출은 env var opt-in, 자동 절대 아님. ingestion 경로 불변; LLM 경로는 요청하는 eval 분석 변형 row (`agentic_full_llm_metadata`, follow-up PR) 만 호출.
- 비용 표면은 ADR 0011 가격 카드 패턴 따름: LLM 분석 변형 실행 시 `rag_synthesis` 의 동일 `compute_cost_usd` 훅 (Sonnet 4.6 기본) 상속 → 메타데이터 추출 토큰 소비 10× 리팩터가 답변 합성 10× 와 동일 방식으로 flag.

## 검토한 대안

- **`ingestion.normalize_metadata` 내부에 LLM 호출 매장.** Reject — 결정론 CSV reader 를 네트워크 백엔드와 결합 + 기본으로 ADR 0001 불변식 위반. `normalize_metadata` 의존 opt-in 표면이 조건부 import 경로 가지게 됨 — 정확히 ADR 0011 이 피한 smell.
- **stub 백엔드 skip + mock `anthropic` 클라이언트로 테스트 gate.** Reject — `rag_synthesis` 의 동일 접근이 SDK 모킹 없이 CI 결정론 유지 증명. mock 은 drift; stub-matches-baseline 불변식은 PR 마다 검사.
- **OpenAI 의 JSON 모드 (tool / function call 없음).** Reject — tool / function-call 표면이 구조화 스키마 계약 부여. raw JSON 모드는 모델 측 환각에 fragile + parser 레이어에 `additionalProperties: false` enforcement 중복.
