# 번역 용어집

PR-A~E (가독성 개선 5-PR stacked, issue [#916](https://github.com/hskim-solv/BidMate-DocAgent/issues/916)~[#920](https://github.com/hskim-solv/BidMate-DocAgent/issues/920)) 에서 영문→한국어 번역 시 일관성을 위한 단일 출처. PR-D (ADR 50개 번역) 시 LLM system prompt 로 강제 주입.

## 영문 유지 (번역 금지)

- **코드/식별자**: 함수명, 변수, 클래스, 파일·디렉터리명 (`rag_core.py`, `run_rag_query`, `naive_baseline`, `EVIDENCE_BOUNDARY`)
- **CLI/명령어**: `make smoke`, `git push`, `gh pr create`, `pytest`, `bash scripts/test.sh`
- **컨벤션 키워드**: `Closes #N`, `<type>/issue-<N>-<slug>`, `BREAKING CHANGE`
- **약어**: RFP, RAG, ADR, BM25, RRF, HyDE, LLM, CI/CD, PR, API, CLI, OCR, MLOps, MiniLM, KURE, LoRA, JSON, YAML, regex
- **URL / anchor**: `#key-technical-contribution-*`, badge 이미지, 외부 링크
- **메트릭 단위 / 수치**: `p50 1.7ms`, `0.718±0.10`, `95% CI`, `n=100`

## 한국어 매핑 (도메인 용어)

| 영문 | 한국어 | 비고 |
|---|---|---|
| evidence | 근거 | "지지하는 증거" 의 의미. citation 과 짝 |
| grounded answer | 근거 기반 답변 | extractive grounding 결과 |
| grounding | 근거 연결 | claim ↔ evidence ↔ source 연결 |
| abstention | 보류 | ADR 0003 `status: insufficient`. "회피"·"기권" 아님 |
| verifier | 검증기 | rag_verifier.py |
| claim | 주장 | answer dict 의 `claims` 배열 |
| citation | 인용 | `citations` 배열, evidence 출처 |
| baseline | 기준선 | naive_baseline preset |
| retrieval | 검색 | document retrieval |
| ranking | 순위 매기기 / 순위 | retrieval ranking |
| reranking | 재순위 | cross-encoder reranker |
| ablation | 분석 변형 | "절제" 아님. preset 단위 비교 |
| top-k | top-k | 영문 유지 (수치 의미) |
| starvation | 누락 | retrieval starvation |
| balanced | 균등 | balanced top-k |
| pipeline | 파이프라인 | |
| preset | 프리셋 | eval/config.yaml |
| ingestion | 수집 | 문서 수집 단계 |
| chunking | 청킹 | 청크 분할 |
| metadata-first | 메타데이터 우선 | ADR 0002 |
| extractive | 추출형 | 추출 기반 답변 |
| generative | 생성형 | LLM 합성 답변 |
| synthesis | 합성 | LLM synthesis |
| evaluation / eval | 평가 / eval | "eval" 은 디렉터리·CLI 명칭이므로 영문 |
| judge | 평가자 | LLM-as-judge |
| leaderboard | 리더보드 | |
| stacked PR | stacked PR | 영문 유지 (관용어) |
| retry | 재시도 | |
| load-bearing | load-bearing | 영문 유지 (관용어) |
| worktree | worktree | 영문 유지 (git 개념) |
| hook | 훅 | pre-commit hook, PreToolUse hook |
| invariant | invariant | 영문 유지 |
| follow-up | follow-up | |
| stale | stale | 라벨명 |

## 문체 규약

- **본문**: "~다/~한다/~된다" 종결. "~합니다/~입니다" 금지 (장황)
- **헤더**: 명사구 또는 짧은 동사구
- **표 / 리스트**: 한 줄 한 문장. 마침표 생략 가능
- **TL;DR**: 2-3 줄 bullet. 매 문서 최상단에 배치
- **수치 / 메트릭**: 영문 형식 유지 (`+57.1pp`, `n=100`, `p95 3.1ms`)

## 압축 원칙

- **유지**: 표, 코드 블록, mermaid 다이어그램, 결정 사유, 식별자
- **제거**: 같은 내용 반복, 영어 원문 보존용 paraphrase, 외부 reviewer 가 링크 따라가면 알 수 있는 배경 설명
- **링크 위임**: 자세한 설명은 ADR / 별도 docs 로 링크하고 본문은 요점만
