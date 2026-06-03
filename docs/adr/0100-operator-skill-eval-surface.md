# 0100: Operator-Skill Eval (Static Frozen-Playbook Quality) — Per-Task 측정 표면

- **Status**: proposed
- **Date**: 2026-06-03
- **Deciders**: User, Claude Code
- **Related**: [ADR 0064](./0064-self-review-external-judge.md) (self-review external judge — 본 표면이 정면으로 회피하는 self-reference/Goodhart 실패 선례), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (aggregate-only 데이터 경계 — PR1 path-layer 는 README 만 commit, 나머지(code/task.yaml/playbook/splits/report)는 PR2 content 검증까지 denied), [ADR 0055](./0055-claim-validator-as-pr-gate.md) (paired bootstrap / claim-gate 선례), [ADR 0045](./0045-rag-core-leaf-migration-plan.md) (back-edge=0 import 경계 — core↔adapter 격리의 선례), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 데이터 경계 — cross-family oracle payload egress 게이트의 근거), [ADR 0007](./0007-issue-linked-branch-naming.md) (issue-first 브랜치)
- **Issue**: #1844

## Context

이 repo 는 운영자(사람)의 코딩-에이전트 운영 능력 — 같은 모델·repo·budget 에서
task 를 어떻게 쪼개고 context 를 주고 검증기를 만들고 개입하느냐 — 를 측정하는
per-task 표면이 없다. 기존 5축 self-review(`scripts/_self_review.py`,
[ADR 0060](./0060-outcome-telemetry-measurement-surface.md))는 **quarter-aggregate git/hook
telemetry** 라 "같은 task 에서 운영 방식 A vs B" 를 paired 로 비교하는 primitive 가
없다 — 거기에 per-task 실행을 붙이려면 결국 본 하니스가 필요(=확장이 아니라
additive 신규 측정 표면).

[ADR 0064](./0064-self-review-external-judge.md) 는 self-review 가 self-reference/
Goodhart 로 무너지는 실패를 기록했다. 운영자-eval 은 같은 함정에 **더** 취약하다:
운영자가 task·PR·테스트를 직접 저술했으므로 (a) same-family LLM 이 LLM 산출을
채점하면 anchor 가 없고 (b) 운영자의 task 기억이 결과를 부풀린다. 따라서 새 표면은
externally-anchored·report-first·cross-family 여야 한다.

본 ADR 은 **새 측정 표면의 계약을 고정**한다(reviewer 가 의존할 surface 도입 →
CLAUDE.md "ADR 임계값"). 구현(코드·러너·리포트)은 후속 PR2/PR3 가 이 계약을
채운다. 측정 construct 는 좁게 한정한다: **"static frozen-playbook quality under
fixed budget"** — improvised live 개입 timing 은 본 표면이 측정하지 않는 deferred
axis 다.

## Decision

`agent-evals/` 신규 per-task 측정 표면을 도입한다(5축 self-review 상호보완, 대체
아님). 계약:

1. **독립변수 = 운영자의 frozen playbook vN** (v0 naive / v1 spec-first), model·
   repo·budget 고정. playbook 은 versioned·frozen 파일(SHA 기록)로, training split
   에서 freeze → unseen **holdout** 에서 paired 비교. 본 표면은 **절대 solve rate 가
   아니라 paired delta(v1 − v0) 만** 주장한다. **단 paired delta 의 타당성은 운영자-기억
   오염이 v0·v1 에 동등 작용(common-mode)한다는 가정에 의존하므로, 그 균형을 가정이
   아니라 강제 규칙으로 못박는다(PR3 runner/schema + `splits.yaml` 스키마가 구현):**
   - **freshness-exclusion:** holdout task 는 운영자가 cutoff 이전 일정 기간(`splits.yaml`
     기록) engage 하지 않은 것만 — run 시점에 genuinely unseen.
   - **counterbalanced order:** playbook 적용 순서(v0-first / v1-first)를 task 집합에
     걸쳐 randomize·balance → "먼저 돈 playbook 이 task 를 학습"하는 order-effect 오염이
     aggregate 에서 상쇄.
   - **familiarity 메타데이터 기록:** run 마다 last-touch date·운영자가 원 PR 저자인지·
     order index 등 기록.
   - **fail-closed claim gate:** familiarity 가 측정·balance 되지 않으면 paired-delta
     주장 **금지**(정직하게 "confounded/underpowered" 로 보고) — common-mode 상쇄가
     성립하지 않는 run set 에서 delta 를 주장하지 않는다.
2. **Acceptance oracle = externally-anchored + cross-family fail-closed.** 원래 merge PR
   의 테스트 + repo pytest CI + regression = *necessary-not-sufficient* gate; 최종
   "accepted" 판정의 primary arbiter 는 **candidate 와 다른 family 의 fresh-context
   reviewer**(issue+patch 만 제공해 운영자 framing 차단) — same-family LLM-judges-LLM
   ([ADR 0064](./0064-self-review-external-judge.md) pathology) 봉쇄. **운영자가 구동한
   agent family(`candidate_family`)를 run 메타에 기록하고, runner/schema 는
   `reviewer_family != candidate_family` 일 때만 진행(fail closed)** — candidate 가
   Claude 면 reviewer = codex, candidate 가 codex 면 reviewer = 비-codex(예: Claude/
   Gemini). Codex 도 동시 구동 가능한 family 이므로 reviewer 를 codex 로 하드코딩하지
   않는다(이 강제는 PR3 runner/schema 가 구현). hard gate(build/secret/destructive/
   unrelated-rewrite/instruction-violation/무단 migration) 강제.
   **payload privacy gate(외부 egress 경계, [ADR 0005](./0005-eval-split-public-synthetic-private-local.md)/[ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md)):**
   external-family reviewer 는 *외부 서비스 호출*이므로, 넘기는 reviewer payload(issue
   +patch)는 **public 으로 증명(attestation)된 데이터일 때만** 외부로 나간다 — 아니면
   **fail closed**(외부 호출 차단, local/stub reviewer 로 강등). **redaction/scanner 는
   외부 egress 허가 조건이 아니다** — content scanner 는 commit/content 경계(PR2)용이고,
   불완전 redaction 이 private 데이터를 외부로 흘리는 경로([ADR 0005](./0005-eval-split-public-synthetic-private-local.md)
   위반)를 차단하기 위해 egress 는 오직 public-data attestation 으로만 연다. redacted
   private egress 가 정말 필요하면 sanitizer 계약 + 테스트를 갖춘 별도 ADR 0005/0061
   **superseding** 결정이 선행해야 하며, 이 ADR 로 데이터 경계를 우회 확장하지 않는다.
   commit 경계(.gitignore)와 별개의 egress 경계이며, 이 게이트는 PR3 가 wire 한다.
3. **데이터 경계 = aggregate-only([ADR 0005](./0005-eval-split-public-synthetic-private-local.md)), 2-layer.
   PR1 은 *path* 경계만 주장한다 — *content* aggregate-only 강제는 아직 없다(PR2).**
   **(path layer — PR1 이 enforce)** `.gitignore` deny-by-default(`agent-evals/**` 차단
   후 **`README.md`(curated 표면 정의, in-PR 리뷰) 단 하나만 exact-path unignore**;
   code·`*.py`·`__init__.py`·task.yaml·playbook·splits·report 예외 **전부 없음** — shallow
   `.py` 도 raw string literal 을 담을 수 있어 exact-match README-only 가 "코드 경로가 raw
   sink" 우회를 봉쇄) + **index-aware 가드**(`tests/test_agent_evals_gitignore.py` 가
   `git ls-files agent-evals/` ⊆ 명시 committable allowlist 강제 — `.gitignore` advisory 라
   `git add -f`/이미-tracked 못 막지만 index 가드가 막음) + **local pre-commit mirror**
   (`.githooks/pre-commit` 의 BLOCKED/ALLOWED 가 같은 deny-all-but-README 규칙을 미러 →
   force-add 를 commit 시점 로컬에서 차단). **(content layer — PR2 가 enforce)** code,
   `task.yaml`(merge PR mined)·playbook·`splits.yaml`·report 는 모두 raw issue/PR/RFP
   본문을 담을 수 있는 free-form 텍스트라, 내용 미포함 스캐너(`core/report.py` + per-file
   privacy test)가 들어오기 **전까지 commit 금지** — path-only allowlist 로 raw 텍스트를
   commit-가능하게 만들면 거짓 aggregate-only 주장이 되므로. PR2 가 그 스캐너와 함께
   unignore 규칙(code 모듈 경로 + `tasks/*/task.yaml`·`playbooks/*.md`·`splits.yaml`·
   `reports/*.aggregate.json`)을 추가한다. 즉 **PR1 은 *경로* 경계만(README only) 주장하고
   *내용* aggregate-only 는 PR2 가 완성**한다.
4. **추출 경계.** `agent-evals/core/` 는 repo-무관 모듈만(`rag_*`·BidMate 경로/
   휴리스틱 import 0, [ADR 0045](./0045-rag-core-leaf-migration-plan.md) back-edge=0
   패턴을 AST import guard 로 강제); BidMate 특화(task mining, `human_baseline_minutes`)
   는 `adapters/bidmate/` 한정. plugin 시스템 등 premature generality 금지.
5. **초기 등급 = supporting(비 load-bearing).** `scripts/_governance.py:LOAD_BEARING_PATHS`
   에 추가하지 않는다. load-bearing 승격은 별도 ADR.

## Drivers

1. **anti-Goodhart / externally-anchored** — [ADR 0064](./0064-self-review-external-judge.md)
   의 self-reference 실패를 cross-family reviewer + common-mode cancellation +
   freshness-exclusion 다층 방어로 정면 회피.
2. **self-authored task bank 활용** — repo 의 merge PR 이력이 자산. 단 self-reference
   누수는 oracle 설계로 봉쇄.
3. **정직한 포트폴리오 신뢰도** — paired holdout + 정직 CI + frozen-playbook 서사;
   과소표본이면 "underpowered" 명시.

## Alternatives considered

- **(a) 5축 self-review 확장.** 기각: 5축은 quarter-aggregate telemetry 로 per-task
  paired 비교 primitive 가 없어, 붙이려면 본 하니스가 그대로 필요(=확장이 아님).
- **(b) 모델 benchmark(SWE-bench / LiveCodeBench).** 기각: 그것들은 *모델* 을
  측정한다. 본 표면의 독립변수는 운영자 playbook(모델은 고정 상수).
- **(c) 지금 별도 generic repo 로 분리.** 기각: self-authored task bank 를 잃고 첫
  리포트가 지연된다. 추출은 thin slice 가 리포트를 낸 뒤(core↔adapter 경계는 지금
  확보).
- **(d) fully-improvised live-intervention hand-run.** 기각: seed/variance/paired-
  bootstrap 무의미하고 hand-run = operator-as-oracle 로 self-reference 재유입.
  intervention-timing 은 별도 후속 axis.

## Consequences

- **+** 운영자(playbook)의 첫 정직한 per-task 리포트 + 포트폴리오 시그널; cross-
  family anchor 로 [ADR 0064](./0064-self-review-external-judge.md) 함정 회피.
- **+** core↔adapter 경계로 나중 generic 추출 준비(premature generality 없이).
- **−** 측정 construct 가 **"static frozen-playbook quality under fixed budget"** 로
  한정됨 — live intervention timing 은 미측정(deferred axis).
- **−** **thin slice 는 "유의한 v1 > v0 차이" 를 주장하지 않는다(명시적 비목표).**
  목표는 파이프라인 확립 + directional signal; v1 ≤ v0(CI 내)이면 "이 운영자의
  spec-first scaffolding 은 고정 budget 에서 accepted output 을 못 올린다" 가 정직한
  reportable finding 이다(falsifiable).
- **−** 유지 표면 추가. mitigation = thin slice(ADR 1 + mined task + playbook 2버전)
  + aggregate-only 경계(PR1 path-layer, content 강제는 PR2) + ADR-gated 승격 +
  report-before-expansion(PR2 에 3-task smoke report 를 박아 인프라>리포트 함정 회피).

## Follow-ups

- v2–v4 playbook · task-bank 표본/검정력 확장 · live-intervention axis · 12지표
  dashboard · Pareto frontier · public-benchmark(SWE-bench/LiveCodeBench) calibration
  · generic 별도 repo 추출 — 각 별도 issue/ADR.

## Verification

```bash
# PR1(이 ADR)이 확립하는 계약은 agent-evals/README 의 표면 정의 + ADR↔README parity.
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0100-operator-skill-eval-surface.md
test -f agent-evals/README.md
python3 -m pytest -q tests/test_agent_evals_gitignore.py    # path 가드: deny-by-default 패턴 + index-aware(git ls-files ⊆ allowlist)
git check-ignore --no-index -q agent-evals/runs/x/run-log.json    # raw run-log → denied
git check-ignore --no-index -q agent-evals/tasks/T-1/task.yaml    # task.yaml → PR1 denied (PR2 content scanner 후 허용)
! git check-ignore --no-index -q agent-evals/README.md           # README(표면 정의) → committable
git diff --check
# 측정 로직(import 격리 / mining floor / cross-family oracle / min-N 가드 /
# aggregate-only)의 코드 검증은 후속 PR2/PR3 의 tests/test_agent_evals_*.py 가 wire.
```

<!-- verifies-key: agent-evals/README.md:static frozen-playbook quality under fixed budget -->
<!-- verifies-key: agent-evals/README.md:cross-family -->
