# ADR 0066 — Local Codex adversarial pre-commit review loop

- **Status**: Proposed
- **Date**: 2026-05-21 (개정 2026-05-31: Decision #4 를 single-pass approve loop → N-pass union + 빈도 게이트로 교체)
- **Related**: [0007](./0007-issue-linked-branch-naming.md) (issue-first 컨벤션), [0047](./0047-solo-author-adr-governance.md) (30일 SLA), [0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 3조건); issue #1126

## Context

PR 리뷰 시 `/codex:adversarial-review` 슬래시 명령을 수동 호출해 외부 LLM(Codex)의 challenge framing으로 설계 가정·구현 선택을 흔드는 패턴이 자리잡았다. ADR 0066의 초기 형태는 이를 PR-time GitHub Actions workflow로 자동화했다.

그러나 PR open/synchronize마다 self-hosted Codex review가 반복되면 load-bearing 변경 PR에서 새 finding이 push마다 계속 생성된다. 특히 canonical contract 변경처럼 구현과 검증을 함께 조정하는 PR에서는 review가 CI 상태판의 일부가 되어, 실제 blocker와 모델의 후속 선호가 섞인다.

이 표면은 여전히 유용하지만, 실행 위치는 CI가 아니라 commit 전 로컬 반복 점검이 더 적합하다. 작성자는 staged diff를 고친 뒤 다시 commit을 시도할 수 있고, PR CI는 deterministic gate와 public fixture smoke에 집중한다.

## Decision

1. **`.github/workflows/codex-adversarial-review.yml` PR-time workflow를 제거한다.** Codex adversarial review는 더 이상 PR comment나 GitHub Check run을 만들지 않는다.
2. **`.githooks/pre-commit`이 load-bearing staged 변경에 한해 local Codex adversarial review를 실행한다.** 트리거 SSoT는 `scripts/_governance.py LOAD_BEARING_PATHS`이며, private eval path guard(ADR 0005)가 먼저 실행된다.
3. **review 대상은 staged diff다.** `scripts/run_codex_adversarial_precommit.py`는 Codex prompt에 `git diff --cached` / `git diff --cached --name-only`를 사용하라고 명시하고, staged file list와 load-bearing hit를 focus로 전달한다.
4. **기본 8패스를 병렬 실행해 findings 를 union 으로 수집하고, 2회 이상 재현된 강한(critical/high) finding 이 있으면 commit 을 block 한다.** 단일 패스는 stochastic reviewer 라 강한 결함의 무작위 부분집합만 잡는다(실측: 동일 diff 4패스 union 5개 중 2개는 1/4 패스에서만 검출). 그래서 N패스를 병렬로 모아 union(같은 file + line range overlap ≤8줄 클러스터링, severity 는 max 집계)으로 망라성을 높인다. block 판정은 finding 의 **존재** 가 아니라 **재현 빈도** 로 한다 — `frequency < MIN_FREQ` 인 1회성 finding 과 medium/low 는 참고용으로 렌더만 하고 block 하지 않는다. 이는 매 재commit 마다 새 1회성 트집이 생겨 commit 이 영원히 통과 못하는 왕복 폭주를 구조적으로 막는다(본 ADR 초기 형태의 '2회 approve' 재현성 장치를 빈도 임계로 일반화). 패스 수는 `BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS=<n>`(기본 8), 빈도 임계는 `BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY=<n>`(기본 2), per-pass timeout 은 `BIDMATE_CODEX_ADVERSARIAL_TIMEOUT_SEC=<n>`(기본 900)으로 조정한다. 개별 패스의 parse error / companion 실패 / timeout 은 그 패스만 무효 처리하고 나머지로 게이트를 진행하되, **성공 패스가 `min_frequency` 미만이면**(부분 장애 포함 — 재현을 확인할 수 없음) commit 을 fail-closed 로 block 한다. 또한 `min_frequency ≤ attempts` 를 강제한다(아니면 어떤 finding 도 임계에 도달 못 해 게이트가 조용히 무력화되므로 config 를 거부).
5. **artifact는 local-only다.** 각 pass의 raw JSON/stderr 와, union 클러스터 구조(`union.json`) 및 렌더된 markdown(`union.md`, blocking + 참고 findings)은 `git rev-parse --git-dir` 기준 `codex-adversarial-precommit/` 아래에 남기며 commit되지 않는다. emergency bypass는 기존 Git hook 경로와 같이 `git commit --no-verify` 또는 `BIDMATE_SKIP_CODEX_ADVERSARIAL_PRECOMMIT=1`로 가능하다.
6. **기존 수동 `/codex:adversarial-review`와 active-loop Codex lane은 유지한다.** 본 ADR은 PR-time CI surface만 local pre-commit loop로 이동한다.

## Consequences

- **CI noise 감소**: PR synchronize마다 새 adversarial review가 달리지 않으므로 deterministic CI와 LLM critique가 섞이지 않는다.
- **shift-left 유지**: load-bearing 변경자는 commit 전에 Codex challenge를 받는다. 문제를 고친 뒤 commit을 다시 시도하는 local loop가 된다.
- **commit latency 증가, 비용은 병렬화로 완화**: load-bearing staged 변경 commit은 기본 8회 Codex 호출 비용을 치른다. 단 패스를 **병렬** 실행하므로 wall-clock은 1패스 수준(각 패스 900초 timeout)에 그치고, 늘어나는 것은 동시 API 비용/부하다. 필요 시 패스 수/timeout을 낮추거나 emergency bypass를 명시적으로 사용한다. 동시 호출이 rate-limit에 걸리면 `BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS`를 낮춘다.
- **재현성 게이트로 오탐 안정화**: stochastic reviewer 가 패스마다 다른 1회성 트집을 내거나 같은 finding 의 severity 를 다르게 라벨(critical↔high)해도, block 은 `frequency ≥ MIN_FREQ` 인 강한 finding 으로만 발생한다. 이는 commit 왕복 폭주(존재-기반 block 의 실패 모드)를 막고, severity 는 union 클러스터에서 max 로 보수적 집계한다. 1회성 finding 은 버려지지 않고 참고 섹션에 남아 사람이 판단할 수 있다.
- **로컬 Codex 환경 의존**: Claude Codex plugin cache 또는 `CODEX_COMPANION`이 필요하다. 모든 패스가 미설치/실패면 load-bearing commit이 block된다.
- **PR comment evidence 제거**: reviewer-facing artifact는 PR comment/check가 아니라 local hook stderr와 git-dir 내부 `codex-adversarial-precommit/` artifact다. PR 본문에는 필요한 finding만 사람이 요약한다.
- **비공개 데이터 경계 유지**: pre-commit은 ADR 0005 path block 이후에 Codex를 호출한다. private staged file이 있으면 Codex 호출 전에 hook이 중단된다.

## Alternatives considered

- **PR-time workflow 유지**: 호출 누락은 줄지만, push마다 모델 finding이 새로 생기며 CI 상태판이 불안정해진다. 이번 전환의 직접 반례라 기각.
- **Merge gate화**: `needs-attention`을 CI failure로 만들면 오탐이 머지를 막는다. LLM critique는 deterministic CI gate가 아니라 local authoring guard가 맞다.
- **수동 slash command만 유지**: 호출 누락 문제가 재발한다. load-bearing staged 변경에 대해서는 hook이 자동 호출한다.
- **단일 패스 + 존재-기반 block**: stochastic reviewer 한 번에 의존하면 강한 결함의 일부만 잡고, 더 나아가 finding 의 *존재* 만으로 block 하면 매 재commit 마다 새 1회성 트집이 생겨 commit 이 영원히 통과 못하는 왕복 폭주가 발생한다. 본 ADR 의 이전 형태(`2회 approve` loop)도 이 방향의 부분 완화였으나, 재현성을 명시적 빈도 임계(`MIN_FREQ`)로 일반화하고 패스를 8로 늘려 망라성과 폭주 방지를 동시에 확보하는 현재 형태로 교체했다.
- **고정 N + dry-until-no-new loop**: 새 finding 이 안 나올 때까지 라운드를 반복하면 망라성은 최고지만, stochastic generator 가 큰 diff 에서 끝없이 새 트집을 만들어 dry 가 영원히 안 오는 폭주 위험이 있다. 빈도 게이트가 폭주를 이미 막으므로 dry-loop 없이 고정 N 병렬 1회로 충분하다(단순성 + 비용 예측가능).
- **Merge gate화 / verdict 기반 block**: 기각 사유는 위와 동일 — `needs-attention` verdict 는 stochastic 라 deterministic gate 에 부적합하다. 본 형태는 verdict 를 무시하고 finding 재현 빈도만 본다.

## Verification

<!-- verifies-key: .githooks/pre-commit:run_codex_adversarial_precommit.py -->
<!-- verifies-key: scripts/run_codex_adversarial_precommit.py:def main -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_blocks_when_strong_finding_reproduced -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_gate_passes_when_strong_finding_is_one_off -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_cluster_findings_same_pass_duplicate_counts_once -->

- Hook wiring: `.githooks/pre-commit`이 staged load-bearing hit를 `scripts/_governance.py --any-match`로 찾은 뒤 `scripts/run_codex_adversarial_precommit.py`를 호출한다.
- Local runner: `scripts/run_codex_adversarial_precommit.py`는 staged file list를 focus에 포함해 N패스를 병렬 실행하고, pass별 raw + union artifact를 git-dir 내부 `codex-adversarial-precommit/`에 쓴다.
- Regression tests: `tests/test_codex_adversarial_precommit.py`가 load-bearing reuse, staged diff focus, N-pass union/dedup 클러스터링, 빈도 게이트(재현된 강한 finding block / 1회성·약한 finding 통과), 부분 패스 실패 허용 + 전체 패스 실패 block을 검증한다.
