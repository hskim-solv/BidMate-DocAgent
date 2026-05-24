---
name: eval-baseline-regen
description: |
  Regenerate the committed private real-100 eval baseline (`reports/real100/baseline.aggregate.json` + `history/*.aggregate.json`) after PRs merge. Owns the provenance + regression-decision + commit-convention layer on top of the mechanical `make real-eval-baseline-update`: verifies the local eval_summary was produced at HEAD (#160/#414 guard), computes the `post-#N` intervening-PR list, gates `[ALLOW_REGRESSION]` on explicit user confirmation, drafts the tracking issue + `chore(eval): regen ...` commit, then hands off to `ship-pr`. No helper code — orchestrates existing make targets / scripts only.

  Trigger phrases: "real100 baseline regen", "eval baseline 재생성", "베이스라인 갱신 PR", "chore(eval) regen", "post-#N baseline 갱신", "real-eval baseline 업데이트해줘". Trigger when the user wants to refresh the committed real100 baseline after merges. Trigger even if the user does not say "skill".

  Do NOT trigger for: retrieval measurement (use `retrieval-eval`), eval-framework gap audit (use `eval-framework-progressive-audit`), drafting an ADR from eval results (use the `eval-to-adr-bridge` agent), generic PR shipping (use `ship-pr`), removed public-eval artifact freshness (former leaderboard / cost_frontier / judge aggregate / README freshness), or running the eval itself (`make real-eval` — that produces the local eval_summary this skill consumes).
---

# /eval-baseline-regen — real100 baseline 재생성 (provenance·판단·컨벤션 레이어)

private real-100 eval 베이스라인(`reports/real100/baseline.aggregate.json` + `history/*.aggregate.json`)을 머지 이후 재생성하는 chore. **기계적 재생성은 이미 [`make real-eval-baseline-update`](../../../Makefile)([`scripts/write_real_eval_baseline.py`](../../../scripts/write_real_eval_baseline.py))가 처리** — 이 skill 은 그 위에서 매번 손으로 재구성하던 4가지를 담당한다: (1) provenance 자기일관성 검증, (2) `post-#N` 산출, (3) regression 정당화 판단, (4) 트래킹 이슈 + 컨벤션 커밋. 코드 helper 작성 금지 — 기존 타깃·스크립트만 호출. 로컬·가역 작업(regen → commit)까지만 하고 push/PR/merge 는 `ship-pr` 에 위임.

## Scope

- `reports/real100/baseline.aggregate.json` + `reports/real100/history/*.aggregate.json` regen 한정. **삭제된 public-eval 산출물(구 leaderboard / cost_frontier / judge aggregate / README freshness) 재생성은 out of scope** — 이 skill 은 private/internal baseline 만 다룬다.
- One regen per invocation. 여러 베이스라인 표면(예: `failure_distribution`, `distinguishing_power`)을 한 번에 묶지 않음 — 각각 별도 호출.
- Helper code inline 작성 금지. 새 측정 로직·스크립트가 필요하면 별개 PR 로 선행.
- ADR 초안 / push / PR / merge 안 함. eval→ADR 는 `eval-to-adr-bridge` agent, remote shipping 은 `ship-pr` 담당.

## Workflow

각 단계는 (gate) 통과 후 다음으로. STOP gate(1·4)는 사용자 명시 승인 전 진행 금지.

1. **Prerequisite gate — provenance 자기일관성 (가장 중요한 guard, 절대 우회 금지)**
   - `reports/real100/eval_summary.json` 존재 확인. 없으면 **STOP**: "private 100-doc 데이터라 skill 이 생성 못 함. `make real-eval` 를 HEAD 에서 먼저 실행" 안내 ([`write_real_eval_baseline.py`](../../../scripts/write_real_eval_baseline.py) `main` — 부재 시 exit 2).
   - eval_summary 의 `provenance.git_commit` 와 `git rev-parse HEAD` 비교. **skew 시 STOP** = 이것이 #160 실패모드(eval 은 commit X, baseline 작성은 commit Y → metric/provenance 불일치). 권고: `make real-eval` 를 HEAD 에서 재실행. 그대로 진행해야 하면 **`make real-eval-baseline-update STRICT=1`** 사용 — 스크립트가 skew 에 hard-fail(exit 2)하여 침묵 오염을 차단([`write_real_eval_baseline.py`](../../../scripts/write_real_eval_baseline.py) `_warn_if_stale`).
   - **dirty-state gate (#1148, SHA 일치만으로 부족)**: `provenance.git_dirty` 또는 `run_manifest.git_dirty` 중 하나라도 `true` 면 **STOP**. eval 을 dirty worktree(uncommitted scorer/config/code)에서 돌리면 SHA 가 HEAD 와 같아도 baseline 이 재현 불가능한 metric 을 박제한다 — skew check 가 못 잡는 #160 잔여 구멍. `make real-eval` 와 baseline-update **둘 다 clean worktree 에서** 실행. `STRICT=1` 이 dirty 에도 hard-fail(exit 2). 의도된 dirty baseline 만 `make real-eval-baseline-update STRICT=1 ALLOW_DIRTY=1`(또는 스크립트 `--allow-dirty` / `BIDMATE_BASELINE_ALLOW_DIRTY=1`)로 명시 override([`write_real_eval_baseline.py`](../../../scripts/write_real_eval_baseline.py) `_warn_if_dirty`).

2. **`post-#N` 산출 (intervening PR provenance)**
   - 현재 *committed* baseline 의 anchor commit 추출 후 squash-aware 로 PR 번호 열거:
     ```
     ANCHOR=$(python3 -c "import json;print(json.load(open('reports/real100/baseline.aggregate.json'))['provenance']['git_commit'])")
     # 이 repo 는 squash merge(gh pr merge --squash, docs/operations/auto-ship.md) →
     # true merge commit 이 없다. --merges 는 0건을 반환하므로 절대 사용 금지(#1148).
     # first-parent 스캔으로 squash commit subject 의 (#N) 을 추출:
     git log ${ANCHOR}..HEAD --first-parent --oneline | grep -oE '\(#[0-9]+\)'
     ```
   - **복구된 PR 번호가 0건이면 STOP** — anchor..HEAD 사이 PR 식별 실패(anchor SHA 가 origin/main 에 reachable 하지 않거나, ANCHOR==HEAD). `make real-eval-delta` / [`scripts/check_baseline_provenance.py`](../../../scripts/check_baseline_provenance.py) 로 anchor reachability 재확인 후 진행. post-#N 을 빈 채로 커밋하면 regen 을 정당화한 바로 그 eval-surface PR 을 누락한다.
   - 열거된 PR 을 분류: **(a) eval-surface 변경**(scorer / `eval/config.yaml` / preset / load-bearing 경로 — regen 을 *필요로* 한 PR) vs **(b) intervening variance**(infra / orthogonal 머지지만 metric 을 흔든 PR). 커밋 subject 의 `post-#X/#Y` 는 주로 (a), 본문에 (b) 를 변동 사유로 기록.

3. **기계적 regen 실행**
   - `make real-eval-baseline-update`(skew 우려 시 `STRICT=1`) → baseline + `history/<ts>_<sha>.aggregate.json` 작성.
   - `git diff reports/real100/baseline.aggregate.json` 로 구(committed) → 신(working) 메트릭 델타 표시. 이 diff 가 곧 regression 판단 입력.

4. **Regression 판단 gate (ALLOW_REGRESSION)**
   - step 3 diff 에서 핵심 aggregate 수치(accuracy / citation_precision / distinguishing_power / abstention 등 top-level)의 방향 확인.
   - 하락이 있으면: **하락폭 + step 2 (b) intervening PR 후보원인**을 제시하고 사용자에게 **명시 확인**을 요구.
     - 예상된 회귀(측정 프로토콜 진화·orthogonal infra 변동) → subject 에 `[ALLOW_REGRESSION]` + 본문에 사유.
     - 실제 버그 의심 → **STOP, 커밋하지 않음**. regen 이 문제를 표면화한 것이므로 별도 디버깅으로 전환.
   - **`[ALLOW_REGRESSION]` 자동 태깅 절대 금지** — 항상 사용자 확인 후.

5. **이슈 + 커밋 작성**
   - 트래킹 이슈(`gh issue create`, 전역 CLAUDE.md 사전승인): 제목 `chore(eval): regen real100 baseline post-#X/#Y`, 본문 = "베이스라인이 왜 갈렸나"(eval-surface 트리거 PR + intervening variance + 회귀 정당화).
   - `git add reports/real100/` (allowlist: baseline.aggregate.json + history/*.aggregate.json 만 ADR 0005 차단 통과, [`.githooks/pre-commit:29-31`](../../../.githooks/pre-commit)).
   - commit subject: `chore(eval): regen baseline.aggregate.json post-#X/#Y + <reason> (closes #N)` — 회귀 시 `[ALLOW_REGRESSION]` 포함.

6. **ship-pr 핸드오프**
   - "로컬 regen 커밋 완료. `/ship-pr` 호출로 push + PR(브랜치 컨벤션 체크 · push/merge gate · stacked-dependent audit 담당)" 안내.
   - 참고: `reports/real100/` baseline 변경은 §5b real-data 델타 자체이므로 PR 의 §5b 에 `make real-eval-delta` 출력을 채운다(`ship-pr` step 9). skill 신설 PR 과 달리 regen PR 은 baseline 변경 = load-bearing 산출이므로 §5b 필수.

## Approval-gate language

go-ahead(진행): "진행" / "ㄱㄱ" / "ㅇㅋ" / "ok" / "go". 질문(답변만, 실행 금지): "?" / "머지?" / "갱신할까?" / "ready?". 불확실하면 묻고 실행하지 않음. STOP gate(1·4) · `gh issue create` · commit 은 모두 명시 승인 후.

## When the user pushes back

- **"regression 그냥 통과시켜"** → 비용 명시: 잘못된 `[ALLOW_REGRESSION]` 은 변별력(distinguishing power) 측정을 오염시켜 이후 모든 델타 비교의 기준선을 흐린다. 1회만 명시 확인 후 진행.
- **"real-eval 생략하고 베이스라인만 갱신"** → 거부. `eval_summary.json` 없이는 baseline 작성 불가([`write_real_eval_baseline.py`](../../../scripts/write_real_eval_baseline.py) `main`), private 데이터(ADR 0005)라 skill 이 대신 생성 못 함.
- **"provenance skew 무시"** → `STRICT` 끄면 가능하나 #160 사유(metric/provenance 불일치 침묵 오염) 경고 후 사용자 선택. 기본은 `STRICT=1` 권장.
- **"dirty 인데 그냥 baseline 떠"** → 비용 명시: dirty eval 은 SHA 가 HEAD 와 같아도 uncommitted 변경의 metric 을 박제 → 재현 불가, 이후 모든 델타 비교의 기준선 오염(#1148, skew check 가 못 잡는 #160 잔여 구멍). 권고는 commit/stash 후 clean 재실행. 의도적이면 1회 명시 확인 후 `ALLOW_DIRTY=1`.
- **"legacy public eval artifacts 도 같이 갱신"** → out of scope. public eval leaderboard / public judge aggregate 는 제거된 표면이므로 재생성하지 않고, private/internal baseline regen 과 묶지 않음.

## References

- [Makefile](../../../Makefile) `real-eval-baseline-update` (`STRICT` 지원), `real-eval-delta`.
- [scripts/write_real_eval_baseline.py](../../../scripts/write_real_eval_baseline.py) — baseline + history 작성, provenance skew 가드(`_warn_if_stale`) + dirty-state 가드(`_warn_if_dirty`, #1148), `STRICT`/`--allow-dirty` 해석, eval_summary 부재 처리(`main`), `provenance` 기록.
- [scripts/check_baseline_provenance.py](../../../scripts/check_baseline_provenance.py) — committed baseline 의 `provenance.git_commit` reachability(origin/main).
- [.githooks/pre-commit](../../../.githooks/pre-commit) — ADR 0005 allowlist(real100 baseline / history 만 통과).
- ADR 0005(eval public/private 분리), #160 / #414 / #1148(provenance 자기일관성 + dirty 가드), ADR 0054(aggregate semantics).
- [.claude/skills/ship-pr/SKILL.md](../ship-pr/SKILL.md) — push/PR/merge + stacked-audit + approval-gate 컨벤션(핸드오프 대상).
- [.claude/skills/retrieval-eval/SKILL.md](../retrieval-eval/SKILL.md) — "no helper code" + STOP gate 패턴.

## What this skill does NOT do

- Does NOT write helper code — 기존 make 타깃 / 스크립트만 오케스트레이션.
- Does NOT regen or recreate removed public-eval artifacts (former leaderboard / cost_frontier / judge aggregate / README freshness).
- Does NOT run `make real-eval` — private 데이터 필요, 사용자가 HEAD 에서 실행. skill 은 결과(`eval_summary.json`)를 소비.
- Does NOT draft an ADR — `eval-to-adr-bridge` agent 담당.
- Does NOT push / open PR / merge — `ship-pr` 담당.
- Does NOT auto-tag `[ALLOW_REGRESSION]` — 항상 사용자 명시 확인.
- Does NOT bypass the provenance skew/dirty gate silently — skew·dirty 시 STOP 또는 `STRICT=1` hard-fail. dirty override 는 명시 `ALLOW_DIRTY=1` / `--allow-dirty` 만(#1148).
