# 0082: Dual-lane adversarial review with `claude -p` + `--effort`

- **Status**: proposed
- **Date**: 2026-05-28
- **Deciders**: User, Claude Code as implementer
- **Related**: [ADR 0066](./0066-codex-pr-adversarial-review.md), [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md), [claude-code CLI reference](https://code.claude.com/docs/en/cli-reference), [Codex models](https://developers.openai.com/codex/models)

## Context

[ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) 의 lane policy 는 Claude/Codex 두 lane 을 같은 read-only review 작업에 배정하지만, 현재 구현은 **병렬 독립 리뷰** — 두 lane 이 서로의 출력을 참조하지 않는다 ([agent_loop.py:9876-9896](../../scripts/agent_loop.py)). ADR 0066 의 "adversarial" intent 는 codex pre-commit surface 한정이고 agent-loop 안에서는 미구현. 결과적으로 lane policy 의 "두 시점에서 본 review" 가치가 실현되지 않는다.

추가로 두 부담이 동시에 표면화됐다:
1. claude lane 이 `claude -p` CLI subprocess 호출인데 [#1598 F4](https://github.com/anthropics/claude-code/issues/1598) 가정 (claude-code 2.1.3 기준 `--thinking`/`--effort` 미지원) 으로 silent 행동 변화 가능. **그러나 claude-code 2.1.153 으로 업그레이드하면 `--effort low/medium/high/xhigh/max` 지원 확인** ([cli-reference docs](https://code.claude.com/docs/en/cli-reference)) — Pro/Max 구독 OAuth 경로 위에서 모델·effort 명시 가능. Anthropic Messages API 우회 (API key 발급) 불필요.
2. codex 2026 라인업 (GPT-5.5 / GPT-5.4-mini / GPT-5.3-Codex-Spark / GPT-5.1-Codex-Max) 이 등장해 lane 별 변별력/비용 최적화 여지가 생겼지만 현재 `gpt-5-codex` legacy 로 silent 호출 중.

## Decision

claude lane 의 transport 는 **`claude -p` CLI subprocess 그대로 유지** 하되 `--model` + `--effort` 인자를 추가하여 role 별 모델·effort 매트릭스를 명시화하고, 두 lane 이 서로의 직전 출력을 참조해 challenge 하는 adversarial prompt 로 dual lane 을 활용한다. Anthropic Messages API 직접 호출은 채택하지 않는다 (사용자 메모리 `project_claude_sdk_credit_policy` 의 "구독제만 쓰기로 정책" 준수).

핵심 결정:

- **claude lane transport 유지 (subscription OAuth)**: `subprocess.run(["claude", "-p", prompt, "--model", model, "--effort", effort, "--output-format", "json", ...])`. Pro/Max 구독 quota 사용, `ANTHROPIC_API_KEY` 불필요. CLI 설치+인증 = 사용자 명시 동의 (ADR 0066 codex trust contract 와 동일 모델). 외부 페이로드 egress 추가 가드 불필요.
- **role 별 model × effort 대칭 매트릭스** (1차 / 2차 lane 모두 명시 — adversarial challenge 의 추론 강도 정합):

  | Role | 1차 lane | 1차 model / effort | 2차 lane | 2차 model / effort |
  |---|---|---|---|---|
  | Planner / Issue Triage | claude | `claude-opus-4-7` / `xhigh` | codex | `gpt-5.5` / `high` |
  | Eval / Claim / Privacy Auditor | claude | `claude-sonnet-4-6` / `medium` | codex | `gpt-5.4-mini` / `medium` |
  | Experiment Scout | claude | `claude-sonnet-4-6` / `medium` | codex | `gpt-5.4-mini` / `medium` |
  | Reviewer | codex | `gpt-5.5` / `high` | claude | `claude-opus-4-7` / `xhigh` |
  | Deep Reviewer | codex | `gpt-5.5` / `high` | claude | `claude-opus-4-7` / `xhigh` |
  | CI / Regression Auditor | codex | `gpt-5.4-mini` / `medium` | claude | `claude-sonnet-4-6` / `medium` |
  | CI/Eval Auditor | codex | `gpt-5.4-mini` / `medium` | claude | `claude-sonnet-4-6` / `medium` |

  비대칭 fallback 회피 — Reviewer 1차 = codex frontier 인데 2차 = sonnet medium 으로 떨어지면 challenge 가 의미 없음. 대칭 매트릭스는 두 lane 의 reasoning 강도를 매칭하여 adversarial 가치 보존. `xhigh` 는 Opus-4-7 전용 — 다른 모델에 보내면 `_validate_effort_for_model` 가 자동 `high` 로 보정.

  codex `--effort` 는 [codex-companion 1.0.4 의 adversarial-review subcommand 가 미지원](../../../../.claude/plugins/cache/openai-codex/codex/1.0.4/scripts/codex-companion.mjs) (line 684 `valueOptions: ["base", "scope", "model", "cwd"]`) — env 정의만 두고 호출 경로 미주입. companion 표면 확장은 후속 별 PR.
- **adversarial prompt**: `_build_agent_turn_prompt(..., prior_artifact)` 가 1차 lane 의 `{verdict, summary, findings}` 를 2차 lane 의 prompt 끝에 "Prior lane verdict (challenge this) ... Where you disagree, surface counter-examples. Where you agree, state explicitly. Do NOT echo." 블록으로 포함. role-aware header 도 분기 (Reviewer/Deep/CI Auditor 는 adversarial 강조, Planner/Eval/Privacy 는 plan-first synthesis 강조). Codex lane 도 동일하게 sanitized prior finding titles 를 `focus` 문자열로 전달 받음.
- **dual-lane consensus**: 1차 + 2차 lane verdict 를 `_stricter_verdict` 로 합산 (blocked > needs-attention > approved/clear, error 는 가장 strict). final aggregate heartbeat 는 `agent=None` 으로 호출되어 **세션 top-level status 만 변경, 두 lane 의 개별 lane-level verdict 는 보존** — adversarial 이 disagree 했다는 evidence 가 registry 에 살아남는다.
- **env knob (Knobs)**: `BIDMATE_CLAUDE_LANE_PLANNER_MODEL`(`claude-opus-4-7`), `BIDMATE_CLAUDE_LANE_PLANNER_EFFORT`(`xhigh`), `BIDMATE_CLAUDE_LANE_MODEL`(`claude-sonnet-4-6`), `BIDMATE_CLAUDE_LANE_EFFORT`(`medium`), `BIDMATE_CODEX_LANE_REVIEWER_MODEL`(`gpt-5.5`), `BIDMATE_CODEX_LANE_CI_MODEL`(`gpt-5.4-mini` — role 라벨 `CI / Regression Auditor` 의 env token 은 `_role_env_token` 이 `/` 앞 텍스트만 사용해 `CI` 가 됨), `BIDMATE_CODEX_LANE_MODEL`(`gpt-5.5`), `BIDMATE_DUAL_LANE_ADVERSARIAL`(`1`). `--agent codex|claude` 가 명시되면 자동 single-lane 으로 전환 (운영자 lane pinning 시 의도 보존).

**Scope** (의도된 제한):
- 본 ADR 의 dual-lane 분기는 **`agent-turn` CLI 명령 한정** 이다. `active-codex-runner` (assignment 기반 codex spawn) 는 기존 codex-only entry point 로 유지 — assignment 단위 dual-lane 화는 1000+LOC 별 PR 범위라 "one PR, one concern" 영역 밖.
- 사용자 환경의 `claude` CLI 가 **2.1.150 이상** 이어야 `--effort` 인자가 작동. 이전 버전 (2.1.3 같은) 은 `--effort` 가 unknown option 으로 거부 → claude lane 의 verdict=error 회귀. 사용자가 `claude update` 로 업그레이드 필요 (release 시점 2026-05-28 기준 2.1.153).

## Consequences

**이점**:
- ADR 0080 lane policy 가 본래 의도한 "두 시점 review" 가치 실현 — 두 lane 출력이 더 이상 독립이 아니라 상호 검증.
- silent 행동 변화 제거 — `cat reports/agent_loop/active/start.md` 만으로 모델/effort/adversarial 모드 즉시 확인.
- Opus 4.7 의 `xhigh` effort 를 Planner 역할에 활용 (claude-code 2.1.150+ CLI 기능).
- **API key 발급 불필요** — Pro/Max 구독 path 그대로. 사용자 메모리 의 "구독제만 쓰기로 정책" 정합.
- 비용 회수 경로: `BIDMATE_*_EFFORT=low` 또는 `BIDMATE_DUAL_LANE_ADVERSARIAL=0` (호출 횟수 절반화) — env 단일 toggle.

**비용**:
- adversarial 모드에서 한 task 당 lane 호출이 1회 → 2회 (1차 + 2차) 로 증가 — 평균 latency 거의 2배 + 구독 quota 비례 증가. `BIDMATE_DUAL_LANE_ADVERSARIAL=0` 으로 즉시 off 가능.
- 사용자 환경의 claude CLI 가 2.1.150 미만이면 `--effort unknown option` 으로 lane 의 verdict=error 회귀. release notes 에 명시 + 사용자가 `claude update` 로 업그레이드 필요.
- codex effort 명시화는 companion 표면 한계로 이번에 활성화 불가 — env 만 정의되고 미주입. 향후 companion 확장에 종속.

**locked-in contract**:
- claude lane 출력 스키마 `{verdict, summary, findings, next_steps}` 불변 — `claude -p --output-format json` 의 `.result` 필드에서 동일 JSON 추출.
- adversarial 경로의 1차/2차 artifact 모두 `reports/agent_loop/active/artifacts/<task>/<session>/<agent>.json` 에 별 파일 저장 (실제 `_agent_turn_artifact_path` layout). 2차 artifact 의 meta 에 `prior_artifact_ref` 키 추가 (계약).
- start.md 의 lane 섹션에 `claude_lane_planner_model` / `claude_lane_planner_effort` / `claude_lane_model` / `claude_lane_effort` / `codex_lane_reviewer_model` / `codex_lane_ci_auditor_model` / `codex_lane_model` / `dual_lane_adversarial` 줄 노출 (계약).

## Alternatives considered

- **Anthropic Messages API 직접 호출**: claude-code 2.1.3 의 `--thinking`/`--effort` 미지원 우회용으로 한때 시도. ANTHROPIC_API_KEY 필수 + Pro/Max 구독 풀과 별 billing + ADR 0061 ③ egress guard 추가 부담 + ADR 0005 의 codex/claude 비대칭 trust boundary 등 다수 회귀 발견. claude-code 2.1.150+ 의 `--effort` 지원 확인 후 폐기.
- **Option A — 모델·effort env 만 명시화, prompt 미변경**: lane policy 정신은 보존하나 사용자 요구 "역할에 맞는 행동" 미충족. 두 lane 이 여전히 같은 input 으로 같은 출력을 내는 병렬 독립 구조.
- **Option C — role+lane config 매트릭스를 별 YAML 로 외부화**: 운영 surface 증가 + "one PR, one concern" 위반. env knob 으로 시작하고 config 외부화는 사용 패턴 누적 후 별 ADR.
- **codex companion 의 adversarial-review 에 `--effort` 추가**: companion upstream 수정 필요 (이 repo 외 surface) — 별 PR 분리.

## Verification

- 회귀 테스트 `tests/test_agent_loop.py` 의 `test_claude_lane_adapter_subprocess_command_and_core` 가 `--model` / `--effort` 플래그 검증 + `_validate_effort_for_model` / role-aware prompt 가 단위 테스트로 강제. 180 통과.
- `reports/agent_loop/active/start.md` 가 lane 메타 줄 (claude_lane_planner_model 등) 을 노출 — 사용자가 silent 디폴트 즉시 확인.
- `reports/agent_loop/active/events.jsonl` 의 agent-turn 이벤트에 `lane.model` / `lane.effort` / `lane.prior_artifact_ref` 키 노출.

<!-- verifies-key: scripts/agent_loop.py:_CLAUDE_ROLE_PROFILE -->
<!-- verifies-key: scripts/agent_loop.py:_CODEX_ROLE_PROFILE -->
<!-- verifies-key: scripts/agent_loop.py:_validate_effort_for_model -->
<!-- verifies-key: scripts/agent_loop.py:write_dual_agent_turn -->
<!-- verifies-key: scripts/agent_loop_claude_turn.py:--effort -->
<!-- verifies-key: tests/test_agent_loop.py:test_build_agent_turn_prompt_role_aware_header_and_prior_artifact -->
<!-- verifies-key: tests/test_agent_loop.py:test_claude_lane_adapter_subprocess_command_and_core -->
<!-- verifies-key: tests/test_agent_loop.py:test_claude_lane_adapter_xhigh_only_on_opus_47 -->
<!-- verifies-key: tests/test_agent_loop.py:test_stricter_verdict_dual_lane_consensus -->
<!-- verifies-key: tests/test_agent_loop.py:test_role_profile_resolution_env_priority -->
<!-- verifies-key: tests/test_agent_loop.py:test_dual_lane_adversarial_off_via_env -->
