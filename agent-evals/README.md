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

## 레이아웃 (shipped)

```
agent-evals/
├── README.md                 # 표면 정의
├── core/                     # repo-무관: schema/metrics/report content scanner/oracle 결정표
├── adapters/bidmate/         # sanitized task mining + runner.py(detached-worktree matrix) + oracle_bidmate.py(gate·cross-family egress)
├── tasks/T-*/task.yaml       # scanner-backed sanitized task contracts
├── playbooks/                # v0_naive.md · v1_spec_first.md (frozen)
├── splits.yaml               # train/holdout 배정 + freshness-exclusion
├── runs/                     # ⛔ gitignored — per-run run-log/캡처 diff/reviewer 입력 (raw 본문)
└── reports/                  # scanner-backed *.aggregate.json only
```

> 오케스트레이션 CLI(`scripts/agent_evals_run.py` · `scripts/agent_evals_report.py`)는
> agent-evals allowlist 밖의 일반 repo 도구이므로 `scripts/` 에 있다 (hyphen 디렉터리는
> import 불가 → 둘 다 path-load). `core/` ↔ `adapters/` 는 import 격리(back-edge 0).

## 상태 (thin slice 완료 — 3 PR 전부 머지)

- **PR1 (#1964, 머지):** ADR 0100 + 이 README + queue 항목 + CLAUDE.md 맵 — 계약 고정만(코드 없음).
- **PR2 (#2343, 머지):** `core/`(import 격리) + content scanner + task mining(merge PR ~#1336–1820, hidden-test gate) +
  playbook 2버전 + split + **3-task smoke report**(report-before-expansion).
- **PR3 (#2411, 머지):** full runner(`git worktree add --detach`, ≥3 seed) + cross-family oracle(`reviewer_family != candidate_family` fail-closed) +
  paired bootstrap CI(min-N 가드) + holdout v0-vs-v1 report.

> **Cross-family 리뷰 수렴 (thesis 자기증명).** PR3 머지 후 외부-family(codex) 리뷰
> 3라운드가 real 결함을 점감(漸減)시키며 수렴했다 — round1(3) → round2 #2446(6) →
> round3 #2455(2 real+live; 1 latent defer, 1 contrived decline). fail-closed 규율은
> 모든 경계(decide_verdict + adapter/runner/egress/report)에서 strict `is True`. committed
> holdout aggregate 의 byte-identical 재현은 회귀 테스트(#2471)로 잠갔다. **실제 holdout
> 측정(real candidate)·external-reviewer 실 egress 는 deferred axis** — 따라서 ADR 0100 은
> 여전히 `proposed`(실측 e2e 전 승격 금지).

## 실행 (stub 합성 표면)

```bash
# 1) (playbook × holdout task × seed) 매트릭스 → gitignored run-log + run_manifest.json
#    기본 후보 = 결정적 stub(repo 무변경·고정 게이트); --real 은 NotImplemented(실 코딩-에이전트는 후속 PR)
python3 scripts/agent_evals_run.py --public-attestation
#    --public-attestation 없으면 egress 게이트가 닫혀 전 trial 이 NECESSARY_GATE_ONLY 로 캡(ACCEPTED 0)

# 2) run-log → paired v0-vs-v1 aggregate (manifest 스코핑 + paired bootstrap min-N 가드)
python3 scripts/agent_evals_report.py
#    → agent-evals/reports/holdout-v0-vs-v1.aggregate.json (content scanner 통과 시에만 write)
```

> task mining 은 adapter-internal(`adapters/bidmate/`)이라 별도 CLI 가 없다 — sanitized
> `tasks/T-*/task.yaml` 은 PR2 에 이미 commit 됐다. Makefile 타겟은 아직 wire 되지 않았고
> 위 두 스크립트가 오케스트레이션 SSoT 다. 합성 stub 표면의 byte-identical aggregate 는
> 회귀 테스트(`tests/test_agent_evals_runner.py::test_committed_holdout_aggregate_reproduced_by_stub_pipeline`)가 잠근다.
