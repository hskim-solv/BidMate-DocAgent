# ADR 0066 — Local Codex adversarial pre-commit review loop

- **Status**: Accepted
- **Date**: 2026-05-21 (개정 2026-05-31: Decision #4 를 single-pass approve loop → N-pass union + 빈도 게이트로 교체; 개정 2026-06-01: Decision #4 를 flat-N union → adaptive escalation(START=2 → CAP=8)으로 교체, issue #1728; 개정 2026-06-03: invalid Codex result(미지 verdict/비-dict result/비-list findings)를 error pass 로 분류하고 staged diff snapshot 을 focus 에 embed, issue #1693)
- **Related**: [0007](./0007-issue-linked-branch-naming.md) (issue-first 컨벤션), [0047](./0047-solo-author-adr-governance.md) (30일 SLA), [0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 3조건); issue #1126

## Context

PR 리뷰 시 `/codex:adversarial-review` 슬래시 명령을 수동 호출해 외부 LLM(Codex)의 challenge framing으로 설계 가정·구현 선택을 흔드는 패턴이 자리잡았다. ADR 0066의 초기 형태는 이를 PR-time GitHub Actions workflow로 자동화했다.

그러나 PR open/synchronize마다 self-hosted Codex review가 반복되면 load-bearing 변경 PR에서 새 finding이 push마다 계속 생성된다. 특히 canonical contract 변경처럼 구현과 검증을 함께 조정하는 PR에서는 review가 CI 상태판의 일부가 되어, 실제 blocker와 모델의 후속 선호가 섞인다.

이 표면은 여전히 유용하지만, 실행 위치는 CI가 아니라 commit 전 로컬 반복 점검이 더 적합하다. 작성자는 staged diff를 고친 뒤 다시 commit을 시도할 수 있고, PR CI는 deterministic gate와 public fixture smoke에 집중한다.

## Decision

1. **`.github/workflows/codex-adversarial-review.yml` PR-time workflow를 제거한다.** Codex adversarial review는 더 이상 PR comment나 GitHub Check run을 만들지 않는다.
2. **`.githooks/pre-commit`이 load-bearing staged 변경에 한해 local Codex adversarial review를 실행한다.** 트리거 SSoT는 `scripts/_governance.py LOAD_BEARING_PATHS`이며, private eval path guard(ADR 0005)가 먼저 실행된다.
3. **review 대상은 staged diff다.** `scripts/run_codex_adversarial_precommit.py`는 Codex prompt에 `git diff --cached` / `git diff --cached --name-only`를 사용하라고 명시하고, staged file list와 load-bearing hit를 focus로 전달한다.
4. **adaptive escalation: 기본 2패스(START)로 시작해, 강한(critical/high) finding 이 보이면 CAP(기본 8)까지 escalate 하고, 2회 이상 재현된 강한 finding 이 있으면 commit 을 block 한다.** 단일 패스는 stochastic reviewer 라 강한 결함의 무작위 부분집합만 잡는다(실측: 동일 diff 4패스 union 5개 중 2개는 1/4 패스에서만 검출). 따라서 START 배치에서 강한 finding 이 **freq≥1** 로 한 번이라도 보이면 그 빈도를 확증하기 위해 CAP 까지 추가 패스를 병렬 실행한다(union: 같은 file + line range overlap ≤8줄 클러스터링, severity 는 max 집계). 반대로 START 배치가 강한 finding 없이 깨끗하면 early-stop 으로 통과한다 — ADR Status 전이 같은 noise-free load-bearing 변경은 8패스가 아니라 2패스만에 통과해 평균 비용을 낮춘다. block 판정은 finding 의 **존재** 가 아니라 **재현 빈도**(freq≥`MIN_FREQ`, 기본 2)로 하며 — `frequency < MIN_FREQ` 인 1회성 finding 과 medium/low 는 참고용으로 렌더만 하고 block 하지 않는다 — 이는 매 재commit 마다 새 1회성 트집이 생겨 commit 이 영원히 통과 못하는 왕복 폭주를 구조적으로 막는다(freq≥1 자동 block 은 이 폭주를 재유발하므로 명시적으로 기각). START 에서 이미 freq≥MIN_FREQ 면 escalation 없이 즉시 block 한다(단조성 — 추가 패스는 클러스터 빈도를 더할 뿐 빼지 않으므로 verdict 가 이미 확정). knob: START 는 `BIDMATE_CODEX_ADVERSARIAL_START_ATTEMPTS=<n>`(기본 2), escalation CAP 은 `BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS=<n>`(기본 8 — rate-limit 시 낮추면 상한이 내려감, 기존 계약 유지), 빈도 임계는 `BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY=<n>`(기본 2), per-pass timeout 은 `BIDMATE_CODEX_ADVERSARIAL_TIMEOUT_SEC=<n>`(기본 900). 개별 패스의 parse error / companion 실패 / timeout 은 그 패스만 무효 처리하고 나머지로 게이트를 진행하되, **최종 누적 성공 패스가 `min_frequency` 미만이면**(부분 장애 포함 — 재현을 확인할 수 없음) commit 을 fail-closed 로 block 한다(START 가 깨끗하지만 성공 패스가 부족하면 약한 신호로 통과시키지 않고 escalate 해 신호를 더 모은다). 또한 `START ≤ CAP` 과 `min_frequency ≤ CAP` 를 강제한다(아니면 어떤 finding 도 임계에 도달 못 해 게이트가 조용히 무력화되므로 config 를 거부). `START=CAP` 으로 두면 escalation 이 no-op 이 되어 기존 flat-N 단일 배치 동작과 정확히 동일하다(하위 호환).
5. **artifact는 local-only다.** 각 pass의 raw JSON/stderr 와, union 클러스터 구조(`union.json`) 및 렌더된 markdown(`union.md`, blocking + 참고 findings)은 `git rev-parse --git-dir` 기준 `codex-adversarial-precommit/` 아래에 남기며 commit되지 않는다. emergency bypass는 기존 Git hook 경로와 같이 `git commit --no-verify` 또는 `BIDMATE_SKIP_CODEX_ADVERSARIAL_PRECOMMIT=1`로 가능하다.
6. **기존 수동 `/codex:adversarial-review`와 active-loop Codex lane은 유지한다.** 본 ADR은 PR-time CI surface만 local pre-commit loop로 이동한다.

## Consequences

- **CI noise 감소**: PR synchronize마다 새 adversarial review가 달리지 않으므로 deterministic CI와 LLM critique가 섞이지 않는다.
- **shift-left 유지**: load-bearing 변경자는 commit 전에 Codex challenge를 받는다. 문제를 고친 뒤 commit을 다시 시도하는 local loop가 된다.
- **commit latency 완화 (adaptive)**: noise-free load-bearing 변경(ADR Status 전이 등)은 이제 START=2 패스만에 early-stop 으로 통과해 평균 비용이 8회 → 2회로 내려간다. 강한 finding 이 의심될 때만 CAP=8 까지 escalate 한다. 패스는 배치 내에서 **병렬** 실행하므로 wall-clock 은 1패스 수준(각 패스 900초 timeout)에 그치고, 늘어나는 것은 escalate 시의 동시 API 비용/부하다. 필요 시 START/CAP/timeout 을 낮추거나 emergency bypass 를 명시적으로 사용한다. 동시 호출이 rate-limit 에 걸리면 `BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS`(CAP)를 낮춘다.
- **early-stop 의 수용된 커버리지 한계 (issue #1728 dogfood, 명시 수용)**: 이 escalation 변경을 도입하는 commit 자체에 게이트를 dogfood 한 결과, 게이트가 freq 2/2(high)로 "깨끗한 START 2패스가 CAP 안전망을 영구히 건너뛸 수 있다"를 self-catch 했다. 코드로 검증한 통계도 이를 확증한다 — per-pass 검출률이 위 실측("1/4 패스")처럼 낮은 강한 결함은 START 2패스에 **한 번도** 안 보일 확률이 `P(0/2)=0.75²≈56%` 라, escalation 트리거(freq≥1)가 발동 못 하고 early-stop 으로 통과해 flat-CAP 이었다면 재현·block 했을 결함을 놓칠 수 있다. 트리거가 load-bearing 한정이라 이 잔여 위험은 **가장 중요한 변경에 집중**된다. 그럼에도 평균 비용 절감(8→2)을 위해 이 tradeoff 를 **명시적으로 수용**한다: (a) escalation-on-strong(freq≥1) + block=freq≥2 + 최종 누적 성공<min_freq fail-closed 가 부분 완화하고, (b) high-risk 임을 아는 작성자는 그 commit 만 `BIDMATE_CODEX_ADVERSARIAL_START_ATTEMPTS=8`(=CAP)로 flat 커버리지를 복원할 수 있다. 향후 measured miss-rate 가 쌓이면 START 기본값 재조정 또는 doc-only 변경 한정 early-stop 방향을 재검토한다. (도입 commit 은 이 한계를 문서화한 뒤 `--no-verify` 로 의도적 우회 — 약화의 은폐가 아니라 기록된 수용.)
- **재현성 게이트로 오탐 안정화**: stochastic reviewer 가 패스마다 다른 1회성 트집을 내거나 같은 finding 의 severity 를 다르게 라벨(critical↔high)해도, block 은 `frequency ≥ MIN_FREQ` 인 강한 finding 으로만 발생한다. 이는 commit 왕복 폭주(존재-기반 block 의 실패 모드)를 막고, severity 는 union 클러스터에서 max 로 보수적 집계한다. 1회성 finding 은 버려지지 않고 참고 섹션에 남아 사람이 판단할 수 있다.
- **로컬 Codex 환경 의존**: Claude Codex plugin cache 또는 `CODEX_COMPANION`이 필요하다. 모든 패스가 미설치/실패면 load-bearing commit이 block된다.
- **PR comment evidence 제거**: reviewer-facing artifact는 PR comment/check가 아니라 local hook stderr와 git-dir 내부 `codex-adversarial-precommit/` artifact다. PR 본문에는 필요한 finding만 사람이 요약한다.
- **비공개 데이터 경계 유지**: pre-commit은 ADR 0005 path block 이후에 Codex를 호출한다. private staged file이 있으면 Codex 호출 전에 hook이 중단된다.
- **malformed Codex 출력의 fail-closed 분류 (issue #1693)**: rc=0 이어도 result 가 dict 가 아니거나 verdict 가 `approve`/`needs-attention` 이 아니거나 findings 가 list 가 아니면 `_is_valid_result` 가 그 패스를 error pass 로 분류한다 — 그래야 깨진 패스가 "깨끗한 빈 approve" 로 위장해 게이트를 약화시키지 못한다(누적 성공<min_freq 이면 기존 fail-closed 경로가 block). 렌더러(`render_codex_review.py`)도 비-dict result 에 `(unknown)` 으로 graceful degrade 해 per-pass artifact 작성이 죽지 않는다. 또한 `--base HEAD --scope branch` 호출에서 구조적 branch-diff 가 비어 있으므로(HEAD..HEAD), staged diff snapshot(상한 60KB, truncation 마커)을 focus 프롬프트에 직접 embed 해 변경 집합을 권위 있는 증거로 만든다(모델이 직접 `git diff --cached` 를 돌리는 데 의존하지 않음; 산문 지시도 defense-in-depth 로 유지). 이 변경을 도입하는 commit 을 게이트가 dogfood 한 결과(freq≥2 high) 세 잔여 빈틈을 self-catch 해 함께 보강했다: (a) truncated snapshot 은 authoritative 라벨을 떼고 모델에게 full `git diff --cached` 재확인을 지시(잘린 hunk 은폐 방지), (b) validity 로직 변경이 stale cache 로 우회되지 않도록 `_CACHE_SCHEMA_VERSION` 을 3→4 bump, (c) 렌더러가 findings list 의 비-dict 항목도 drop(중첩 malformed 방어), (d) embed 한 staged diff 는 ```diff 펜스가 아니라 sentinel(`<<<STAGED_DIFF_BEGIN/END>>>`)로 감싼 데이터 채널로 프레이밍하고, diff 본문에 들어 있는 sentinel 문자열(이 파일 자체를 staging 할 때 가장 첨예 — freq 4/8 로 재self-catch)은 embed 전에 inert 형태로 defang 해 diff 내용이 프레임 경계를 위조하지 못하게 한다(프롬프트 인젝션 / 프레임 탈출 방어). 나머지 self-catch(errored pass finding salvage, full-schema 검증, embed scope 축소)는 게이트 위협모델 재설계라는 별개 concern 으로 follow-up 이슈 #1920 에 분리.

## Alternatives considered

- **PR-time workflow 유지**: 호출 누락은 줄지만, push마다 모델 finding이 새로 생기며 CI 상태판이 불안정해진다. 이번 전환의 직접 반례라 기각.
- **Merge gate화**: `needs-attention`을 CI failure로 만들면 오탐이 머지를 막는다. LLM critique는 deterministic CI gate가 아니라 local authoring guard가 맞다.
- **수동 slash command만 유지**: 호출 누락 문제가 재발한다. load-bearing staged 변경에 대해서는 hook이 자동 호출한다.
- **단일 패스 + 존재-기반 block**: stochastic reviewer 한 번에 의존하면 강한 결함의 일부만 잡고, 더 나아가 finding 의 *존재* 만으로 block 하면 매 재commit 마다 새 1회성 트집이 생겨 commit 이 영원히 통과 못하는 왕복 폭주가 발생한다. 본 ADR 의 이전 형태(`2회 approve` loop)도 이 방향의 부분 완화였으나, 재현성을 명시적 빈도 임계(`MIN_FREQ`)로 일반화하고 패스를 8로 늘려 망라성과 폭주 방지를 동시에 확보하는 현재 형태로 교체했다.
- **고정 N + dry-until-no-new loop**: 새 finding 이 안 나올 때까지 라운드를 반복하면 망라성은 최고지만, stochastic generator 가 큰 diff 에서 끝없이 새 트집을 만들어 dry 가 영원히 안 오는 폭주 위험이 있다. 빈도 게이트가 폭주를 이미 막으므로 dry-loop 없이 고정 N 병렬 1회로 충분하다(단순성 + 비용 예측가능).
- **Merge gate화 / verdict 기반 block**: 기각 사유는 위와 동일 — `needs-attention` verdict 는 stochastic 라 deterministic gate 에 부적합하다. 본 형태는 verdict 를 무시하고 finding 재현 빈도만 본다.
- **flat-N 고정(옛 Decision #4) vs adaptive escalation(현재, 2026-06-01)**: 모든 load-bearing commit 에 CAP 패스를 항상 돌리면 비용은 예측 가능하지만 noise-free 변경(ADR Status 전이 등)도 8패스를 치른다. adaptive 는 START=2 로 시작해 강한 finding 이 freq≥1 로 보일 때만 CAP 까지 escalate 하고, 깨끗하면 early-stop — clean diff 의 평균 비용을 START 로 낮추면서 commit-storm 불변식(block=freq≥2)과 fail-closed(최종 누적 성공<min_freq)는 그대로 유지한다. escalation 트리거를 freq≥2(동의)로 두는 변형은 START=2 에서 강한 결함을 freq 1 로만 잡아 놓치므로 freq≥1 로 결정했다(실측 "1/4 패스 검출"). early-block 없이 강한 finding 이 하나라도 있으면 항상 escalate 하는 더 단순한 변형도 고려했으나, START 에서 이미 freq≥min_freq 면 추가 패스가 verdict 를 못 바꾸므로(단조성) redundant escalation 을 피하는 early-block 을 채택. flat default 자체를 낮추는 변형(cascade 8→3, #1709)은 load-bearing-only 트리거 특성상 가장 중요한 변경의 망라성만 골라 희생하므로 철회했고, adaptive 는 그 대신 변경별로 깊이를 조절한다.

## Verification

<!-- verifies-key: .githooks/pre-commit:run_codex_adversarial_precommit.py -->
<!-- verifies-key: scripts/run_codex_adversarial_precommit.py:def main -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_blocks_when_strong_finding_reproduced -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_passes_when_strong_finding_is_one_off -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_cluster_findings_same_pass_duplicate_counts_once -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_env_start_attempts_default_is_two -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_early_stops_when_start_clean -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_escalates_when_strong_finding_subthreshold_in_start -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_early_blocks_when_strong_reproduced_in_start -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_resolve_start_attempts_clamps_implicit_start_to_lowered_cap -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_malformed_result_counts_as_error_pass -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_unknown_verdict_counts_as_error_pass -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_valid_empty_approve_still_successful -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_runner_receives_staged_diff_in_focus -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_old_v3_cache_entry_is_rejected -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_build_focus_truncated_diff_is_not_labeled_authoritative -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_build_focus_defangs_sentinel_injected_from_diff -->

- Hook wiring: `.githooks/pre-commit`이 staged load-bearing hit를 `scripts/_governance.py --any-match`로 찾은 뒤 `scripts/run_codex_adversarial_precommit.py`를 호출한다.
- Local runner: `scripts/run_codex_adversarial_precommit.py`는 staged file list를 focus에 포함해 N패스를 병렬 실행하고, pass별 raw + union artifact를 git-dir 내부 `codex-adversarial-precommit/`에 쓴다.
- Regression tests: `tests/test_codex_adversarial_precommit.py`가 load-bearing reuse, staged diff focus, N-pass union/dedup 클러스터링, adaptive escalation(START 깨끗→early-stop, 강한 finding 서브임계→CAP 까지 escalate, START 에서 freq≥min_freq→early-block), 빈도 게이트(재현된 강한 finding block / 1회성·약한 finding 통과), staged fail-closed(START 후 성공 패스 부족→escalate, 최종 누적 성공 부족→block), policy-aware cache(start/cap/min_freq/timeout 변경→cache miss), entrypoint start-clamp(암묵 START 가 낮춰진 CAP 을 따라 내려가 `ATTEMPTS=1` 이 훅을 hard-fail 시키지 않음 — issue #1728 dogfood informational)을 검증한다.
