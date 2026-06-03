# agent-evals/ — Operator-Skill Eval

**무엇을 측정하나:** 모델 성능이 아니라 **운영자(사람)의 코딩-에이전트 운영 능력**.
같은 모델·같은 repo·같은 budget 에서, task 를 어떻게 쪼개고 context 를 주고 검증기를
만들고 개입하느냐에 따라 *accepted* 산출이 얼마나 달라지는가.

측정 construct 는 좁게 한정한다 — **static frozen-playbook quality under fixed budget**. 즉 운영 능력을 versioned·frozen "playbook" 으로 조작화(operationalize)해 고정 budget 에서 채점한다. improvised live 개입 timing 은 이 표면이 측정하지 않는
**deferred axis** 다.

> 계약 출처: [ADR 0100](../docs/adr/0100-operator-skill-eval-surface.md). 데이터
> 경계 = [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md)
> (aggregate-only). 이 표면은 5축 self-review([ADR 0060](../docs/adr/0060-outcome-telemetry-measurement-surface.md))를
> **대체하지 않고 상호보완**한다(per-task paired primitive 추가).

## 핵심 설계

| 축 | 결정 |
|---|---|
| **독립변수** | 운영자의 **frozen playbook vN**(v0 naive / v1 spec-first). model·repo·budget 은 고정 상수. |
| **비교 방식** | playbook 을 training split 에서 freeze → unseen **holdout** 에서 **paired**(v1 − v0). 주장은 paired **delta** 뿐, 절대 solve rate 아님. |
| **왜 delta 만** | 운영자-기억 오염이 v0·v1 에 **동등 작용**(common-mode)할 때만 paired delta 에서 상쇄 → 그 균형을 강제: **freshness-exclusion**(unseen holdout) + **counterbalanced order**(v0/v1 적용 순서 balance) + **familiarity 메타** 기록, 측정·balance 안 되면 **paired-delta 주장 금지**(fail-closed, PR3 강제). 절대율은 inflated 가능 → 비주장. |
| **Acceptance oracle** | 원래 PR 테스트 + repo pytest CI + regression = *necessary* gate. 최종 "accepted" primary arbiter = **candidate 와 다른 family** 의 fresh-context reviewer(issue+patch 만, 운영자 framing 차단) → same-family LLM-judges-LLM([ADR 0064](../docs/adr/0064-self-review-external-judge.md)) 회피. `candidate_family` 기록 + `reviewer_family != candidate_family` fail-closed (codex 도 candidate 가능 → reviewer codex 하드코딩 금지; PR3 runner/schema 강제). **payload privacy gate(외부 egress):** external-family reviewer 호출은 외부 서비스 egress 이므로 넘기는 reviewer payload(issue+patch)는 **public 증명(attestation)된 데이터일 때만** 외부로 나간다 — 아니면 **fail-closed**(외부 호출 차단, local/stub reviewer 강등). redaction/scanner 는 외부 egress 허가 조건이 아니라 commit/content 경계(PR2)용 — 불완전 redaction 의 private 누출 경로를 막기 위해 egress 는 public-data attestation 으로만 연다(commit 경계와 별개, [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md)/[ADR 0061](../docs/adr/0061-external-and-paid-api-dependencies-allowed.md)). |
| **데이터 경계 (2-layer)** | **path (PR1 enforce):** `.gitignore` deny-by-default + **index-aware 가드**(`git ls-files agent-evals/` ⊆ allowlist — `git add -f`/이미-tracked 차단) + **local pre-commit mirror**(`.githooks/pre-commit`) 로 README-only 경계를 먼저 고정했다. **content (PR2 enforce):** `core/report.py --check-staged` 가 exact PR2 surface(code·`task.yaml`·playbook·`splits.yaml`·`*.aggregate.json`)를 commit 전 검사한다. Raw run-log/captured patch/reviewer input/worktree/non-aggregate report/unanticipated path 는 계속 denied. |
| **추출 경계** | `core/` = repo-무관(import guard); BidMate 특화는 `adapters/bidmate/` 한정. |

## Falsifiability (anti-Goodhart)

이 thin slice 는 **"유의한 v1 > v0 차이" 를 주장하지 않는다(명시적 비목표)**. 목표는
파이프라인 확립 + directional signal. v1 ≤ v0(CI 내)이면 *"이 운영자의 spec-first
scaffolding 은 고정 budget 에서 accepted output 을 못 올린다"* 가 정직한 reportable
finding 이다 — eval 실패가 아니다.

## 레이아웃 (PR2 현재)

```
agent-evals/
├── README.md                 # 표면 정의
├── core/                     # repo-무관: schema/metrics/report content scanner
├── adapters/bidmate/         # sanitized task mining (runner/oracle wrapper는 PR3)
├── tasks/T-*/task.yaml       # scanner-backed sanitized task contracts
├── playbooks/                # v0_naive.md · v1_spec_first.md (frozen)
├── splits.yaml               # train/holdout 배정 + freshness-exclusion
├── runs/                     # ⛔ gitignored — per-run run-log/캡처 diff/reviewer 입력 (raw 본문)
└── reports/                  # scanner-backed *.aggregate.json only
```

## 상태 (thin slice, 3 PR)

- **PR1 (완료):** ADR 0100 + 이 README + queue 항목 + CLAUDE.md 맵 — 계약 고정만(코드 없음).
- **PR2 (현재):** `core/`(import 격리) + content scanner + task mining(merge PR ~#1336–1820, hidden-test gate) +
  playbook 2버전 + split + **3-task smoke report**(report-before-expansion).
- **PR3:** full runner(`git worktree add --detach`, ≥3 seed) + cross-family oracle(`reviewer_family != candidate_family` fail-closed) +
  paired bootstrap CI(min-N 가드) + holdout v0-vs-v1 report.

## 실행 (PR3 에서 Makefile wire 예정)

```bash
# PR3+
make agent-eval-mine     # merge PR → task.yaml (hidden-test gate, mineable floor 경고)
make agent-eval-run      # (playbook × holdout task × seed) → run-log
make agent-eval-report   # holdout v0 vs v1 aggregate (paired bootstrap, min-N 가드)
```
