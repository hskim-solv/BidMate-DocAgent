# 0008: 근거 텍스트 경계 + instruction-like 패턴 무력화

- **Status**: accepted
- **Date**: 2026-05-11
- **Deciders**: hskim-solv
- **Related**: [`rag_verifier.py`](../../rag_verifier.py) (`evidence_text_for_verification`·`neutralize_instruction_patterns`·`EVIDENCE_BOUNDARY` — PR-J1 / issue #465 에서 `rag_core.py` 추출; `rag_core` 는 backward-compat re-export 유지), [`scripts/llm_judge.py:_build_prompt`](../../scripts/llm_judge.py), [ADR 0003](0003-structured-answer-citation-contract.md), [ADR 0006](0006-llm-judge-on-real-data-only.md), [ADR 0028](0028-security-screen-additive.md) (보완적 query-side defense)

## TL;DR

- 근거 텍스트가 검증기/LLM 으로 들어가는 모든 지점에서 `neutralize_instruction_patterns` 적용.
- chat 토큰·role 태그·instruction-override 문구를 marker 로 wrap (silent strip 아님 — 인용 가독성 보존).
- 단일 helper + 단일 `EVIDENCE_BOUNDARY` 상수 — call site 마다 별도 sanitizer 금지.

## 배경

이 repo 의 retrieved-evidence 텍스트는 외부 RFP 문서 출처, 두 downstream consumer 로 흐른다:

1. deterministic 검증기 (`rag_core.py:evidence_text_for_verification`, topic/entity 와 substring 매치)
2. LLM judge (`scripts/llm_judge.py:_build_prompt`, chat 프롬프트에 직접 embed — ADR 0006)

메인 답변 생성기는 extractive(ADR 0003 — LLM 호출 없음), 전통적 "프롬프트 injection" 우회 안 됨. 그러나 chat template 토큰(`<|im_start|>`·`<|im_end|>`), role 태그(`SYSTEM:`·`ASSISTANT:`·`USER:`), instruction-override 문구("Ignore previous instructions")를 담은 악의적/실수 malformed RFP chunk 는 여전히:

- LLM judge 를 unsupported verdict 로 유도 → committable `agreement_with_verifier` aggregate 오염
- 향후 도입될 LLM consumer(planner·generator) 영향
- trace·log·eval artifact 를 진짜 프롬프트 경계처럼 보이는 문자열로 오염

이 ADR 이전엔 근거 텍스트가 bare space 로 join 되어 그대로 전달. 적대 콘텐츠를 무력화할 단일 choke point 없음.

## 결정

`rag_core.py` 에 단일 helper `neutralize_instruction_patterns(text: str) -> str` 도입, document-controlled 텍스트가 검증기/LLM consumer 로 건너가는 모든 site 에 적용.

무력화 rule (모두 case-insensitive):

- **Chat template 토큰** `<|im_start|>`·`<|im_end|>`·`<|system|>`·`<|user|>`·`<|assistant|>`·`<|tool|>`·`<|begin_of_text|>`·`<|end_of_text|>`·`<|fim_*|>`·`<|endoftext|>` → 리터럴 sentinel `[REDACTED_CHAT_TOKEN]` 으로 치환
- **Role-tag 라인** `^\s*(SYSTEM|ASSISTANT|USER|TOOL)\s*:\s*.+$` 매치(line start anchor, multiline) → `[INSTRUCTION_LIKE]...[/INSTRUCTION_LIKE]` wrap
- **Instruction-override 라인** `^\s*(ignore|disregard|forget|override|bypass)\s+(previous|prior|all|any|the)\s+(instructions?|prompts?|rules?|directives?|system).*$` 매치 → 동일 `[INSTRUCTION_LIKE]` marker wrap

적용 site:

- `evidence_text_for_verification` (rag_core.py) — `title`·`agency`·`project`·`section`·`text` + 각 메타데이터 값 무력화
- `scripts/llm_judge.py:_build_prompt` — chunk별 텍스트 무력화 + 공개 상수 `EVIDENCE_BOUNDARY = "\n[---EVIDENCE_BOUNDARY---]\n"` 로 chunk join; `query`·`summary` 도 프롬프트 템플릿 포매팅 전 무력화

helper 와 boundary 상수는 public(leading underscore 없음) — 향후 다른 consumer 가 rule 재구현 없이 재사용 가능.

## 결과

**Wins**:

- LLM judge(ADR 0006) + 향후 LLM consumer 가 RFP-embedded chat 토큰/role 태그에 오도되지 않음
- 인용 가독성 유지 — 텍스트 콘텐츠는 verbatim 보존, marker 만 wrap
- 단일 지점 변경: `rag_core.py` 함수 1개 + call site 2개 갱신. API/답변 계약 bump 없음(ADR 0003 불변, `schema_version` bump X)
- 회귀 테스트(`tests/test_prompt_injection_regression.py`)가 refactor 중 silent 제거 방지

**Costs / 제약**:

- "이전 지시사항 무시" 같은 문구를 정당하게 담은 regulatory RFP 섹션이 `[INSTRUCTION_LIKE]` marker 획득 — reader 는 marker 가 방어용이지 평가적 의미가 아님을 이해해야
- `evidence_text_for_verification` 출력에 marker 토큰(`[INSTRUCTION_LIKE]`·`[/INSTRUCTION_LIKE]`·`[REDACTED_CHAT_TOKEN]`) 포함; 출력 exact string 동등성 단언 테스트는 이를 수용해야
- 향후 기여자는 call site 별 parallel sanitizer 도입 대신 `neutralize_instruction_patterns` 확장 필요

**계약**: 호출자는 위 marker 토큰을 콘텐츠 아닌 방어 주석으로 취급해야. topic 문자열이 marker 문법과 겹치지 않으므로 검증기 substring 매치 계약 영향 없음.

## 측정 갭

3 regex 패턴 + marker-token wrapping 은 **exhaustive 방어 아님**. issue #828 까지 ADR 이 현재 rule 미커버 공격 벡터를 표면화 안 함. 테스트에만 살지 않고 결정 레이어에 갭이 보이도록 여기 문서화:

- **오늘 방어 표면**: [`rag_verifier.py:262/266/269`](../../rag_verifier.py) 의 regex 셋; 공격별 positive 케이스는 [`tests/test_prompt_injection_regression.py`](../../tests/test_prompt_injection_regression.py) + 벡터별 적대 pinning [`tests/test_evidence_boundary_attack_vectors.py`](../../tests/test_evidence_boundary_attack_vectors.py)
- **Marker-bypass / marker-tag confusion** — **issue #830 surgical PR 로 closed**: `rag_verifier.py` 의 `_LITERAL_MARKER_RE` 가 입력의 리터럴 `[INSTRUCTION_LIKE]` / `[/INSTRUCTION_LIKE]` 토큰을 wrap 적용 BEFORE `[INPUT_MARKER]` 로 재작성 — 출력의 모든 marker 토큰은 공격자가 아닌 방어가 작성
- **잔여 미해결 공격 벡터** (tracking [#830](https://github.com/hskim-solv/BidMate-DocAgent/issues/830)):
  - **Chat-token aliasing**: 주위 whitespace(`< |im_start| >`), fullwidth lookalike(`＜｜im_start｜＞`), 부분 매치(`<|im_star`)는 정규화 안 됨. `tests/test_evidence_boundary_attack_vectors.py::TestVector3ChatTokenAliasing` pinning. 수정 경로: regex 매치 전 NFKC unicode 정규화
  - **Role-tag case (fullwidth only)**: ASCII `IGNORECASE` 가 `SyStEm:` 처리; 갭은 fullwidth(`ＳＹＳＴＥＭ:`). `TestVector4RoleTagCaseUnicode::test_4b_fullwidth_role_tag_NOT_defended` pinning. 수정 경로: chat-token aliasing 과 동일 NFKC 정규화
  - **Instruction-override paraphrase**: regex 가 `ignore`/`disregard` 같은 키워드 요구; 의미 paraphrase("reset everything we discussed")는 통과. `TestVector5InstructionOverrideParaphrase` pinning. ADR Alternatives 섹션 따라 deterministic 검증기 범위 외 — LLM classifier 필요
- **regex 변경 결정 규칙**: 새 rule(또는 완화)은 ≥1 신규 공격 벡터 커버 + real-corpus survey set 에 false-positive 회귀 없음(한국어 법률 언어가 regulation-quote 맥락에서 "이전 지시사항 무시" 정당 인용 빈번)
- **적대 corpus 확장 계획**: #830 에서 커버(기존 회귀 set 출발, 위 공격 벡터별 확장)
- **Cross-link**: LLM judge(ADR 0006)는 자체 evaluation 표면 보유; 방어 회귀는 리더보드 `agreement_with_verifier` delta 로 표면화. #830 출하 후 적대 확장 벤치마크 거기 추가

## 검토한 대안

- **패턴 silent strip** — Reject: 근거 파괴 + 인용 audit 가능성 깨짐. 인용 reader 는 source 에 있던 것을 봐야
- **pluggable rule 의 신규 `Sanitizer` 클래스** — Reject: CLAUDE.md "Reuse over invent". 두 번째 consumer 가 다른 rule 필요해질 때까지 한 함수로 충분
- **LLM judge 경계에서만 sanitize** — Reject: defense-in-depth, 검증기가 이미 `evidence_text_for_verification` 호출 — 단일 함수가 자연스러운 choke point
- **시스템이 extractive 라 변경 스킵** — Reject: ADR 0006 LLM judge 가 이미 근거 텍스트 소비, 향후 generative 파이프라인 명시 예상
