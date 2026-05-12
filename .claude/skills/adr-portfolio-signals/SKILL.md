---
name: adr-portfolio-signals
description: |
  Map a single ADR (e.g. 0023) to the 5 senior-engineering signals defined in docs/senior-positioning.md and produce a draft checklist for portfolio / interview prep.

  Trigger whenever the user references an ADR by number AND wants portfolio framing — phrases like "0023번 ADR 시니어 시그널 정리", "ADR 23으로 면접 ammo 뽑아줘", "ADR 0005 senior signal checklist", "0001 포트폴리오 매핑", "이 ADR로 뭘 어필할 수 있나". Trigger even if the user does not explicitly say "checklist" — extracting senior signal mapping from one ADR is exactly this skill's job. Do NOT trigger for: multi-ADR comparisons, PR-level storytelling, README copy generation, full STAR paragraphs / blog drafts (different scope).
---

# ADR → Senior Signal Checklist

Given an ADR number, produce a markdown table mapping that ADR to the 5 senior-engineering signals in [`docs/senior-positioning.md`](../../../docs/senior-positioning.md). Each row = one signal × yes/partial/no judgment × citation evidence × **1-line claim bullet** the user can polish into final copy.

## Scope

- Single-ADR input only (`0023`, `23`, `0001` — all resolve to `docs/adr/<zero-padded>-*.md`).
- Output = markdown table to **stdout**. No file writes.
- Claim cells = **1-line bullet drafts** (factual hook + 1 concrete tie-in). Not paragraph narrative.
- If the user asks for a paragraph, STAR story, blog draft, or multi-ADR comparison, decline politely and explain this skill is single-ADR checklist only.

## Workflow

1. **Resolve input.** Zero-pad N to 4 digits and find `docs/adr/<NNNN>-*.md` via `ls docs/adr/ | grep -E "^0*${N}-"` (or equivalent). On miss, print the result of `ls docs/adr/` and stop — ask the user to pick a valid number.
2. **Load signal definitions.** Read `references/senior-signals.md` end-to-end (5 signals × definition × probe questions × common partial cases). Use this as the rubric — do not invent additional signals.
3. **Read the ADR end-to-end.** Capture Status, Related/Date, Context, Decision, Consequences, Alternatives. Extract supersession metadata explicitly (Supersedes / Superseded by / Extends / Refines / reuses pattern from).
4. **Cross-reference (depth-1 only — do not chase further hops).**
   - Other ADR numbers mentioned in body → note as `ADR #NNNN` in evidence. Status lookup optional.
   - PR / issue numbers → cite as `PR #NNN` / `issue #NN`. No `gh` fetch needed.
   - Code file paths the ADR points to → cite as `path:Lstart-Lend` using the line ranges the ADR itself mentions, or the relevant section (e.g. function definition line).
   - `tests/test_*_regression.py` references in the ADR → strong evidence for signal 3 (failure handling).
   - `Makefile`, `eval/config.yaml`, `scripts/_governance.py` references → evidence for signal 4 (governance-as-code) and/or signal 5 (reproducibility).
5. **Evaluate each of the 5 signals.** For each, judge `yes` / `partial — <≤30자 사유>` / `no — <≤30자 사유>` using the probe questions in `references/senior-signals.md`. Always include the short factual reason for partial/no — never bare "partial" or "no".
6. **Write the claim bullet** for each `yes` and `partial` row. **≤80 chars** (path/code 포함), 1 line, passive(`-된다`) voice 우선, factual hook + 1 concrete tie-in. For `no` rows, write `(해당 없음)`. See "Claim bullet style" for the verb allow-list / deny-list.
7. **Render the table** using the template below. Output to stdout. Do NOT write the output to a file — the user pastes it manually where useful.
8. **Self-check before returning.** Quickly scan the rendered output:
   - Every Evidence cell contains only citations (file:line / ADR# / PR# / issue# / make targets) — no paraphrased summaries.
   - Every Claim cell ≤80 chars, 1 line, passive voice, contains no deny-list verb (`강제`, `잠금`, `보장`, `입증`, `보여준다`, `디자인되어`, `탄탄히`, `잘 ~`).
   - Every partial/no verdict carries a factual reason ≤30 chars after the dash.
   - If any check fails, rewrite the offending cell before returning.

## Output template

````markdown
# ADR <N> — Senior Signal Checklist

- Source: `docs/adr/<NNNN>-<slug>.md`
- Status: <accepted | proposed | superseded by ADR #...>
- Supersedes / Extends / Refines / Reuses: <list, or "none">

| # | Senior signal | Applies? | Evidence (citations only) | Claim (1-line draft) |
|---|---|---|---|---|
| 1 | 아키텍처 결정의 추적성 | yes | `docs/adr/<NNNN>-...md:L1-L7`, ADR #0001, ADR #0011 | <1-line bullet> |
| 2 | 측정의 엄격성 | partial — <≤30자 사유> | `docs/adr/<NNNN>-...md:L99-L108` | <1-line bullet> |
| 3 | 실패를 시스템적으로 다룬다 | no — <≤30자 사유> | (없음) | (해당 없음) |
| 4 | 거버넌스가 코드와 같이 진화한다 | yes | `docs/adr/<NNNN>-...md:L73-L83`, `eval/config.yaml` | <1-line bullet> |
| 5 | 재현성을 갖춘 시연 | yes | `docs/adr/<NNNN>-...md:L99-L102`, `Makefile` (`make smoke`) | <1-line bullet> |

## Primary sources (re-read before defending)
- <2-3 load-bearing citation lines, no commentary>
````

## Claim bullet style

각 claim은 사용자가 자기 톤으로 1-2번 손대면 면접·블로그·issue 코멘트에 그대로 쓰일 수 있는 draft. 형식: **하나의 factual hook + 하나의 구체적 tie-in**.

### Hard rules

- **Length**: claim bullet ≤ 80 chars (path / code 포함). verdict 사유는 `partial —` / `no —` dash 이후 ≤ 30 chars.
- **Voice**: passive(`-된다`) 또는 중립 description voice 우선. 자기평가 형용사(`잘 ~`, `탄탄한`, `뛰어난`) 금지.
- **Compression 금지**: 1줄에 아이디어 1개만. 세미콜론 / 콤마로 2개 절 압축 금지.

### 선호 동사 (passive / sterile)

`정의된다`, `분리된다`, `유지된다`, `포함된다`, `명시된다`, `표시된다`, `등록된다`, `잠긴다`, `검출된다`, `재현된다`, `작동한다`, `발생한다`, `~이다`

### 회피 동사 (selling / active-strong)

`강제(한다)`, `잠금(처리)`, `보장(한다)`, `입증(한다)`, `보여준다`, `디자인되어 ~`, `탄탄히`, `잘 ~한`

### Good examples

(passive, factual hook + concrete tie-in, ≤80자)

- `deferred decision도 ADR로 잠긴다 — re-open 조건(env 업그레이드 + full ≥+5pp) 명시`
- `IdentityExpander 디폴트로 ADR 0001 golden이 byte-equal로 유지된다`
- `공개 합성과 비공개 real-data가 분리 표면으로 정의된다 — failure mode가 surface된다`
- `naive baseline은 후속 retrieval 변경 효과 측정의 reference column이다`

### Bad examples

- `이 ADR은 아키텍처 결정의 추적성을 잘 보여줍니다.` — 자기평가 narrative, signal 매핑이 아님
- `eval/config.yaml과 SSoT가 ADR을 코드로 강제한다` — deny-list 동사(`강제`)
- `HyDE 쿼리 확장을 additive ablation으로 도입하여 ADR 0001 invariant을 보존하면서 retrieval 표면을 확장한다` — 2 아이디어 압축 + 80자 초과
- `partial — proposed 단계, public CI에서는 fallback byte-equal로 동작하지만 실측은 별도 표면` — verdict 사유 30자 초과

면접 talking point를 통째로 ghost-write하지 않는다. 사용자가 그 1줄을 출발점으로 자기 단락을 만든다.

## What this skill does NOT do

- Does NOT produce STAR paragraphs, blog drafts, or 5-minute demo scripts — those are different scopes.
- Does NOT compare two or more ADRs side-by-side (single-ADR only).
- Does NOT write output to files — stdout only. The user pastes / discards freely.
- Does NOT cite paraphrased summaries in Evidence — only `file:line` / `ADR #N` / `PR #N` / `issue #N` / `make` target / config key.
- Does NOT chase cross-references deeper than one hop. The skill reads the target ADR + `references/senior-signals.md` only.
