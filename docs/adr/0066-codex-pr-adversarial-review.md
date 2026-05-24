# ADR 0066 — PR-time Codex adversarial review 자동화 표면

- **Status**: Proposed
- **Date**: 2026-05-21
- **Related**: [0007](./0007-issue-linked-branch-naming.md) (issue-first 컨벤션), [0047](./0047-solo-author-adr-governance.md) (30일 SLA), [0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 3조건); issue #1126

## Context

PR 리뷰 시 `/codex:adversarial-review` 슬래시 명령을 수동 호출해 외부 LLM(Codex) 의 challenge framing 으로 설계 가정·구현 선택을 흔드는 패턴이 자리잡았다. 그러나:

- 호출 누락이 reviewer attention budget 한정 때문에 일관성 없음. Load-bearing 변경 PR 도 잊고 머지된 사례 다수.
- 단일 reviewer 가 같은 코드에 대해 challenge framing + 기능 검토 + 규약 점검을 동시에 하기 어렵다.
- Codex 의 adversarial verdict + finding 은 reviewer 가 결정에 의존할 정도로 신호값이 있다 — 즉 **새 reviewer-facing measurement surface** 로 격상해야 한다.

기존 자동화 표면 (`pr-eval.yml` fixture smoke eval, `aggregate report.yml` portfolio signal) 은 PR-time 또는 reviewer-facing evidence 경로로 진화했다. Codex adversarial review 도 같은 자리로 옮긴다.

## Decision

1. **PR open/synchronize/reopen 시 load-bearing path 변경 PR 에 한해 Codex adversarial review 를 자동 트리거한다.** 트리거 SSoT 는 `scripts/_governance.py LOAD_BEARING_PATHS` (regex 새로 안 만듦). 추가 가드: `additions+deletions > 5000 LOC` skip.
2. **결과는 PR comment (marker upsert) + Check run (informational) 로만 표현한다.** Check run conclusion 은 `success` (verdict=approve) 또는 `neutral` (verdict=needs-attention 또는 codex 호출 실패) — **절대 `failure` 안 함**. 머지 게이트 아님.
3. **Runner 는 self-hosted macOS arm64, `~/.codex` 공유로 ChatGPT 로그인 (`times21c@gmail.com`) 재사용** — OpenAI API key 비용을 회피. ephemeral 모드, labels `self-hosted,macOS,ARM64,codex`.
4. **Public repo 보안 다중 가드**: workflow `if: head.repo.full_name == repository && user.login == 'hskim-solv'` + Repo Settings → Actions 의 "Require approval for outside collaborators" + GitHub 의 fork PR token read-only 강등.
5. **외부/유료 API 의존 (ADR 0061 3조건) 명시적 부합**:
   - **opt-in**: workflow 가 load-bearing 변경 + 본인 PR + non-fork 모두 충족 시만 fire. 다른 경로 (eval pipeline, baseline) 에 영향 X.
   - **baseline byte-identical**: ADR 0001 baseline 은 codex 호출과 무관. `reports/` 산출물에 codex output 들어가지 않음.
   - **데이터 경계**: codex 가 받는 prompt = PR diff (public repo 의 git history) + PR title + LOAD_BEARING_PATHS hit. 공개 fixture 는 smoke 재현성 확인용이며, private/internal eval data 는 커밋하지 않는다.
6. **소유는 단일 PR + 단일 ADR**. follow-up 자동화 (다른 codex review surface, API-key 경로, fork PR 지원) 는 별도 issue/ADR 로 분리.

## Consequences

- **Reviewer 가 codex verdict 를 PR signal 로 의존 가능** — Goodhart risk: reviewer 가 verdict=approve 로 자기 review 를 스킵할 수 있다. ADR 표면화 + comment 에 "informational" 명시 + Check run name 에 동일 표현으로 완화.
- **Self-hosted runner 단일점**: 본인 머신 오프라인 시 PR review 신호 끊김. timeout 25min + 코멘트가 "Waiting for runner..." 표시하지 않으므로 reviewer 가 runner 상태를 직접 확인해야 함. follow-up 으로 runner heartbeat 모니터링 추가 검토.
- **ChatGPT 로그인 의존**: 토큰 만료·갱신·rotation 시 PR review 가 silent fail. render 가 rc!=0 케이스를 PR comment 로 표면화하므로 reviewer 는 알 수 있으나, 갱신 책임은 본인.
- **Codex usage limit hit**: 일일·월 한도 초과 시 PR review 가 "Codex usage limit reached" 로 보고. PR 자체는 fail 안 함 (informational).
- **Self-hosted runner 보안 노출**: Public repo + self-hosted 의 fork PR 공격 surface 는 다중 가드로 차단. Runner Groups 설정에서 "Allow public repositories" 활성 필요 여부는 smoke 단계에서 측정.
- **Workflow file (`codex-companion.mjs` 경로) 가 plugin 버전 `1.0.4` 하드코딩**: codex plugin 업데이트 시 workflow 도 같이 갱신 필요. follow-up 으로 symlink 또는 glob resolve 검토.
- **`/codex:adversarial-review` 슬래시 (수동 호출) 는 살아있음** — load-bearing 외 path 또는 인증 만료 시 fallback 경로. 본 ADR 은 추가, 대체 아님.

## Alternatives considered

- **OpenAI API key 경로**: 비용 별도 청구 (월 N PR × ~$1) + key rotation 관리. ChatGPT 로그인 보존 + self-hosted runner 가 cost-zero 라 1차 안으로 기각.
- **모든 PR 자동 트리거**: docs-only / dependabot PR 까지 codex 깨움 → 의미 없는 노이즈 + usage limit 빠르게 소진. Load-bearing 한정으로 ~95% 노이즈 차단.
- **Merge gate 화 (verdict=needs-attention → CI fail)**: 오탐 시 머지 막힘. 본 ADR 단계는 informational 우선, 신뢰도 측정 후 향후 옵션으로 검토.
- **수동 label trigger 패턴**: 수동 label 의존 → 호출 누락 동일 문제 재현. 자동 트리거로 직행.
- **Self-hosted runner 대신 GitHub-hosted + OpenAI API key**: cost + key rotation + secrets noise. 본인 머신 idle 자원 활용이 ROI 우위.

## Verification

<!-- verifies-key: .github/workflows/codex-adversarial-review.yml:codex-companion.mjs -->
<!-- verifies-key: scripts/render_codex_review.py:def render_markdown -->
<!-- verifies-key: scripts/_governance.py:--any-match -->

- Workflow trigger + 가드 검증: `.github/workflows/codex-adversarial-review.yml` 의 `if:` 조건 + `triage` job 의 `should_run` 분기. Smoke phase 2 의 fork PR / 큰 diff / docs-only PR 시나리오.
- Render 정확성: `scripts/render_codex_review.py` 의 4 분기 (approve / needs-attention / parseError / rc!=0) → `tests/test_render_codex_review.py` fixture 기반 단위 테스트.
- SSoT 재사용: `scripts/_governance.py --any-match` CLI (이미 `--check-5b` CI gate / pre-push hook 가 쓰는 동일 표면). LOAD_BEARING_PATHS 추가 시 본 workflow 도 자동 반영.
