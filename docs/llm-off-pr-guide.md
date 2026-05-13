# LLM-off PR Guide

BidMate-DocAgent ownership 4축 중 **#4 확장 자력성** 측정 도구. 다음 small follow-up PR 1건을 *의도적으로* "LLM 은 타이핑/문법 보조만, 설계·디버깅·리뷰는 나" 모드로 진행하는 self-imposed 룰셋 + 회고 템플릿.

[`adr-self-interview-checklist.md`](adr-self-interview-checklist.md) (#1·#2) + [`adr-debugging-scenarios.md`](adr-debugging-scenarios.md) (#3) 의 자매 문서.

## 사용법

1. *다음 small PR 1건* 만 선택 (전체 PR 에 강제 ❌, 측정 PR 1건만 ⭕).
2. PR 작업 시작 전 "본 PR 은 LLM-off 모드" 라고 PR description 상단에 명시 (회피 incentive 제거).
3. 작업 진행 — 아래 6 룰 모두 준수. 위반 시 *즉시* memory log 에 1줄.
4. PR merge 후 5분 안에 회고 5문항을 [`memory/llm_off_pr_log.md`](file:///Users/hskim/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/llm_off_pr_log.md) 에 작성. **답을 외부에 적지 않고 본인 머릿속만으로** — 회고 자체도 LLM 도움 없이.

**이 가이드는 *모든 PR* 에 적용하지 않는다.** 매 PR 마다 본 룰을 강제하면 cycle time 이 비현실적으로 늘어남. *측정 PR 1건* 으로 한정해 baseline 을 만든 뒤, 회고를 통해 *어느 룰이 일상 PR 에 incorporate 할 가치 있나* 를 판단.

## Ownership 4축 #4 정의

**확장 자력성** — 새 컴포넌트(또는 follow-up 변경)를 본인이 *leading* 하는가, LLM 이 leading 하고 본인이 *검수만* 하는가. 둘은 코드 결과물이 같아도 *얼마나 본인의 작품인가* 가 다르다.

- 설계 의사결정 (어디 break ? 어떤 trade-off ? 어떤 anchor ?) 을 본인이 *외부 도움 없이* 산출했는가.
- LLM 이 짠 코드 라인을 본인이 *라인별* 설명 가능한가.
- 디버깅/리뷰 시점에 LLM 의존도가 0 인 구간이 있는가.

## 자가 룰셋 6개

### 룰 1. Hand-written trade-off bullet 1개 첨부

PR description §3 Risks **첫 줄**에 본인이 *손으로 쓴* trade-off 1쌍 (`선택한 것 vs 거부한 것`) 의 사진/스캔을 첨부. LLM 은 §3 *나머지* 만 보강 가능. 드래프트는 손.

- *왜*: 설계 의도가 *물리적으로* 본인 작품임을 강제. 손글씨는 LLM 이 흉내 못함.
- *위반 신호*: 사진 없이 typed bullet 만 → 룰 1 위반. log 에 기록.

### 룰 2. 설명 못 하는 LLM 라인은 commit 금지

`git add -p` / staging 직전 30초 **verbal-walk** 셀프테스트 — 추가 hunk 한 줄씩 입으로 *왜 이 모양인가* 말해본다. 막히면 그 hunk 만 `git restore --staged <file>`.

- *왜*: LLM 생성 코드가 black box 로 commit 되는 흔한 함정. verbal-walk 가 본인 이해 게이트.
- *위반 신호*: hunk 1개 이상 설명 못 한 채 commit → 룰 2 위반.

### 룰 3. Anchor 는 LLM 이 아닌 `grep -n` 직접

verifier 위치, `EVIDENCE_BOUNDARY` 상수, `ANSWER_SCHEMA_VERSION` 위치, `LOAD_BEARING_PATHS` SSoT 등 anchor 를 LLM 에게 "어디 있나" 묻지 않고 본인이 `grep -rn "EVIDENCE_BOUNDARY" rag_*.py` 로 찾기. PR body 에 anchor 인용 시 본인이 직접 본 line:N 형식으로.

- *왜*: anchor 위치를 LLM 에게 매번 묻는 패턴이 4축 #2 (의도추적성) 회귀의 root.
- *위반 신호*: LLM 답변에 의존해 anchor 인용 → 룰 3 위반.

### 룰 4. Regression test 의 setUp 은 본인 작성, fixture 만 LLM

`tests/test_*_regression.py` 새 guard 추가 시 `setUp` / `_base_summary()` / assertion 본문은 본인이 작성 — LLM 비참조. fixture data (`{"key": "value", ...}` 같은 dict literal) 만 LLM 가능. assertion 의 *왜 이 값이 이 값과 같아야 하나* 의 논리는 본인.

- *왜*: regression test 의 *논리* 는 시스템 invariant 의 코드화. 그 부분 LLM 위임 = invariant 본인 이해 0.
- *위반 신호*: assertion 본문이 LLM 출력 그대로 → 룰 4 위반.

### 룰 5. Real-eval delta 본인 한 줄 요약 *먼저*

load-bearing PR 에서 `make real-eval-delta` 출력 표를 LLM 에게 "읽어달라/요약해달라" 하기 전에 본인이 *한 줄 요약* 을 PR body §5 Eval impact 에 적기. 그 다음에야 LLM 으로 보강.

- *왜*: real-eval 표 해석 능력이 4축 #3 (디버깅 자력성) 의 핵심. LLM 에게 위임하면 헤드라인 metric 의 *silent regression* (abstention -0.30 + incorrect_answer +6 같은 ) 못 잡음.
- *위반 신호*: 본인 요약 0줄, LLM 요약만 → 룰 5 위반.

### 룰 6. CI fail 5분 룰

CI red 시 처음 **5분** 은 LLM 호출 금지. 그 시간 안에 [디버깅 시나리오 워크북](adr-debugging-scenarios.md) 형식으로 가설 1개 + 검증 명령 1개를 본인이 작성. 5분 후에야 LLM 호출 가능.

- *왜*: CI fail 시 반사적 LLM 호출이 #3 디버깅 자력성 회귀의 가장 흔한 함정. 5분 timer 가 그 반사를 끊는다.
- *위반 신호*: CI fail 5분 내 LLM 호출 → 룰 6 위반.

## 빨간불 기준 (per-PR)

1. **룰 위반 3개 이상** — 본 PR 은 *LLM-off* 가 아니라 *LLM-assisted* 였음. 회고에서 *왜 위반했나* 를 솔직히.
2. **회고 Q5 자가 점수 ≤ 2/5** — "LLM 이 leading" 으로 본인이 평가. 다음 라운드에 룰 1개 추가/조정.
3. **PR cycle time 이 LLM-on 대비 5배 이상** — 룰셋이 *비현실* 하거나 본 PR 의 scope 가 너무 크다. scope 조정.
4. **회고 Q1 ("가장 묻고 싶었던 순간")이 공란** — 본인이 LLM 의존 의식이 안 됨. self-awareness 회귀 신호.

## 회고 템플릿 (PR merge 후 5문항, `memory/llm_off_pr_log.md` 에 append)

```
## PR #<N> (<YYYY-MM-DD>)

- Q1. 가장 LLM 에게 묻고 싶었던 순간 (구체 라인/시점, 1~2줄): ___
- Q2. 30분 이상 막힌 시점은 어디였나? 무엇이 잠금을 풀었나? ___
- Q3. cycle time 이 평소 대비 × ___ 배. 그 N 을 줄일 방법? (혹은 못 줄여도 되는가?): ___
- Q4. 다음 라운드 룰 add/remove 1개: ___
- Q5. 자가 점수 1~5 ("나 leading" vs "LLM leading"): ___ / 5 ·  근거 1줄: ___
- 룰 위반: 룰 ___ / ___ (어느 룰, 몇 번)
```

회고 자체도 LLM 도움 없이. 막히면 빈칸으로 두고 1일 후 재시도.

## First target PR 후보

작고 docs-only, 비-load-bearing, 룰 6개 모두 자연스럽게 강제될 수 있는 PR 후보:

- **A**: ADR self-interview checklist ([#508](https://github.com/hskim-solv/BidMate-DocAgent/pull/508)) 머지 후 follow-up — ADR 0031 (kiwipiepy BM25, #490) stub row 를 30-row tracker 에 추가. ~5줄 변경. 룰 3 (`grep` 으로 ADR 0031 파일/PR 위치 찾기) 자연스러움.
- **B**: Phase 2 stub 카드 1개를 fully form ([#508](https://github.com/hskim-solv/BidMate-DocAgent/pull/508) 의 0001/0003/0005/0008/0023 외 1개) — 룰 1·3·4 강제. 사용자가 *본인 시스템 본문* 을 직접 grep 해야 함.
- **C**: 디버깅 시나리오 워크북 ([#513](https://github.com/hskim-solv/BidMate-DocAgent/pull/513)) Phase 2 stub 1개를 fully form — 룰 4·5 자연스러움. 시나리오 본문이 *본인이 한 번 풀어본* 후 작성되어야.
- **D** (대안): `docs/` 의 작은 정정 PR (typo, broken link, ADR cross-reference 오류) — load-bearing 0, scope 최소. 룰 1·2·3 만 적용.

추천: **A** 또는 **B** — ownership 도구 시리즈의 일부로 자연스러운 흐름. **D** 는 너무 작아서 룰셋 운동 효과 낮음.

## Phase / Status

- **Phase 1 (이 PR)**: 가이드 문서 자체 land. 다음 1주 안에 사용자가 first target PR 1건 골라 룰셋 적용 + 회고.
- **Phase 2 (회고 1회 후)**: 룰셋 add/remove. 첫 회고 데이터로 룰 6개 중 1~2개가 너무 강하거나 약함이 드러나면 본 가이드 자체를 update.

## Related

- [`adr-self-interview-checklist.md`](adr-self-interview-checklist.md) — ownership #1·#2 audit
- [`adr-debugging-scenarios.md`](adr-debugging-scenarios.md) — ownership #3 audit, 룰 6 (CI fail 5분) fallback
- [`engineering-governance.md`](engineering-governance.md) — PR workflow 규칙 (PR template / hook / CI gate)
- [`docs/auto-ship.md`](auto-ship.md) — Stop-hook auto-ship pipeline (이 가이드의 *반대* 표면; 가이드는 *수동 leading* 강제)
- `~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/llm_off_pr_log.md` — 사적 회고 log
