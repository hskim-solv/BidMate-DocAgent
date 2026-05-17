# 기여 가이드 (한국어)

이 저장소는 한국어 화자 reviewer 와 LLM 협업을 모두 가정한다. **자연어 본문은
한국어, 기술 텍스트는 영문 유지** 가 단일 규칙.

## TL;DR

- PR 본문/issue 본문/문서 본문 → **한국어**
- 코드/식별자/CLI/커밋 메시지/`Closes #N`/브랜치명 → **영문**
- 용어는 [`docs/translation-glossary.md`](translation-glossary.md) 따름

## 영문 유지 (번역 금지)

- **코드/식별자**: 함수명, 변수, 클래스, 파일·디렉터리명 (`rag_core.py`,
  `run_rag_query`, `naive_baseline`, `EVIDENCE_BOUNDARY`)
- **CLI/명령어**: `make smoke`, `git push`, `gh pr create`, `pytest`,
  `bash scripts/test.sh`
- **컨벤션 키워드** (ADR 0007, CI 강제):
  - `Closes #N` — PR 본문 내 issue 링크
  - `<type>/issue-<N>[-<slug>]` — 브랜치명. type ∈ {feat, fix, docs, refactor, chore}
  - `BREAKING CHANGE` — 답변 계약 깨짐 표시 (ADR 0003)
- **커밋 메시지 전체** — `feat(scope): subject (closes #N)` 형식. 본문 영문
  (git 도구·외부 reviewer 와의 일관성)
- **약어**: RFP, RAG, ADR, BM25, RRF, HyDE, LLM, CI/CD, PR, API, CLI, OCR
- **메트릭/수치**: `p50 1.7ms`, `0.718±0.10`, `n=100`

## 한국어 본문

- PR/Issue 본문, `docs/*.md`, `README.md` prose 영역
- 핵심 도메인 용어 매핑 ([`docs/translation-glossary.md`](translation-glossary.md)):
  evidence→근거, abstention→보류, verifier→검증기, claim→주장, citation→인용,
  baseline→기준선, ablation→분석 변형
- 문체: "~다/~한다/~된다" 종결. "~합니다/~입니다" 회피 (장황)
- TL;DR 2-3 bullet 을 매 문서 최상단 배치

## PR 작성 순서

1. issue 먼저 (`gh issue create --template feature.md` 또는 `bug.md`)
2. 브랜치: `git switch -c <type>/issue-<N>-<slug>`
3. 작업 + `make smoke` + `bash scripts/test.sh`
4. Stacked PR 이면 `gh pr create --base <parent-head-branch>`, 독립이면 `--base main`
5. PR 본문은 한국어, `Closes #N` 필수, [.github/pull_request_template.md](../.github/pull_request_template.md) 각 섹션 채움
6. Load-bearing 파일 변경 시 **5b (real-data delta)** 필수

자세한 lifecycle 은 [`docs/engineering-governance.md`](engineering-governance.md).

## 검증

- `make check-branch` — 브랜치 컨벤션 ad-hoc 확인
- `make install-hooks` — clone 직후 1회 (pre-commit ADR 0005 boundary +
  pre-push branch/eval check 활성화)
- CI gate: [pr-eval.yml](../.github/workflows/pr-eval.yml),
  [branch-and-issue-check.yml](../.github/workflows/branch-and-issue-check.yml)

## 참고

- [`CLAUDE.md`](../CLAUDE.md) — 저장소 컨벤션
- [`docs/translation-glossary.md`](translation-glossary.md) — 번역 용어집
- [`docs/multi-agent-ownership.md`](multi-agent-ownership.md) — 다중 agent 협업 모델
