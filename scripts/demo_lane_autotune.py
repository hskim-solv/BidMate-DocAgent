"""Demo: compute_lane_autotune — 합성 데이터로 opt-in lane autotune 재현.

Lane A/B는 정상(~10 s), Lane C는 느리고(~100 s) 반복 실패한다.
OFF 경로(autotune 미적용)와 ON 경로(compute_lane_autotune 호출)를 비교해
컨트롤러가 C 를 감지해 effort 를 high → xhigh 로 높이는 과정을 보여준다.

실행:
    python3 scripts/demo_lane_autotune.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# scripts/ 디렉터리를 경로에 추가 (직접 실행 지원).
sys.path.insert(0, str(Path(__file__).parent))
import agent_loop  # noqa: E402 (side-effect-free import)


# ---------------------------------------------------------------------------
# 합성 lane 데이터 구성
# ---------------------------------------------------------------------------

# 시나리오:
#   - Lane A (codex, Implementer) : 정상  ~10 s, completed
#   - Lane B (codex, Reviewer)    : 정상  ~10 s, completed
#   - Lane C (codex, Auditor)     : 느림 ~100 s, 반복 failed

FAIL_ITER_1 = [
    {"role": "Implementer", "agent": "codex", "elapsed_s": 10.2, "status": "completed"},
    {"role": "Reviewer",    "agent": "codex", "elapsed_s":  9.8, "status": "completed"},
    {"role": "Auditor",     "agent": "codex", "elapsed_s": 97.3, "status": "failed"},
]
FAIL_ITER_2 = [
    {"role": "Implementer", "agent": "codex", "elapsed_s": 10.5, "status": "completed"},
    {"role": "Reviewer",    "agent": "codex", "elapsed_s": 10.1, "status": "completed"},
    {"role": "Auditor",     "agent": "codex", "elapsed_s": 102.7, "status": "failed"},
]
NEWEST = [
    {"role": "Implementer", "agent": "codex", "elapsed_s": 10.3, "status": "completed"},
    {"role": "Reviewer",    "agent": "codex", "elapsed_s":  9.9, "status": "completed"},
    {"role": "Auditor",     "agent": "codex", "elapsed_s": 98.6, "status": "failed"},
]

PRIOR_LANE_STATS = [FAIL_ITER_1, FAIL_ITER_2, NEWEST]

# baseline effort 리졸버: 운영자가 Auditor lane 에 high 를 설정했다고 가정.
def _high_baseline(agent: str, role: str) -> str:  # noqa: ARG001
    return "high"


# LaneAutotuneConfig: 기본값(k=2.0, fail_window=3, fail_min_sample=2,
# fail_threshold=0.5, cooldown=2) 사용.
CFG = agent_loop.LaneAutotuneConfig()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _banner(title: str) -> None:
    line = "=" * 60
    print(f"\n{line}")
    print(f"  {title}")
    print(line)


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# OFF 경로: autotune 미적용
# ---------------------------------------------------------------------------

def demo_off() -> None:
    _banner("AUTOTUNE OFF  (ACTIVE_LANE_AUTOTUNE 미설정)")
    print(textwrap.dedent("""\
        ACTIVE_LANE_AUTOTUNE 환경변수가 빈값이면 _resolve_lane_autotune_config()
        가 None 을 반환한다. 루프는 config=None 인 경우 compute_lane_autotune 을
        호출하지 않으며, effort 오버라이드·권고·cooldown 를 생성하지 않는다.
        runner 산출물은 byte-identical 로 유지된다 (ADR 0087 (d)).
    """))
    print("  effort_overrides : {}")
    print("  recommendations  : []")
    print("  cooldown_state   : {}")
    print("  (컨트롤러 미호출 — lane 데이터 감지 없음)")


# ---------------------------------------------------------------------------
# ON 경로: compute_lane_autotune 호출
# ---------------------------------------------------------------------------

def demo_on() -> None:
    _banner("AUTOTUNE ON  (ACTIVE_LANE_AUTOTUNE=1)")

    _section("입력 lane 데이터 (3 iteration, 최신이 마지막)")
    for i, batch in enumerate(PRIOR_LANE_STATS, 1):
        print(f"  Iteration {i}:")
        for obs in batch:
            print(f"    {obs['role']:14s}  agent={obs['agent']}  "
                  f"elapsed={obs['elapsed_s']:.1f}s  status={obs['status']}")

    _section("Config (env 기본값)")
    print(f"  k                  = {CFG.k}   (within-agent median 배수)")
    print(f"  fail_window        = {CFG.fail_window}   (fail_rate 계산 window)")
    print(f"  fail_min_sample    = {CFG.fail_min_sample}   (최소 관측 횟수)")
    print(f"  fail_threshold     = {CFG.fail_threshold}  (fail_rate 임계값)")
    print(f"  cooldown           = {CFG.cooldown}   (조정 후 동결 iteration 수)")

    # 실제 함수 호출 (effort_resolver=_high_baseline: Auditor 기준 effort = high)
    effort_overrides, recommendations, new_cooldown_state, events = agent_loop.compute_lane_autotune(
        PRIOR_LANE_STATS,
        None,          # 이전 cooldown 없음 (첫 번째 actuation)
        CFG,
        effort_resolver=_high_baseline,
    )

    _section("elapsed 감지 이벤트 (newest batch, codex 그룹)")
    for ev in events:
        if ev.get("decision") == "evaluated":
            print(f"  agent={ev['agent']}  median={ev['median_elapsed_s']:.1f}s  "
                  f"k={ev['k']}  flag_threshold={ev['flag_threshold_s']:.1f}s  "
                  f"timed_lanes={ev['timed_lane_count']}")
        elif ev.get("decision") == "no-op":
            print(f"  agent={ev['agent']}  no-op: {ev['reason']}")

    _section("권고 (flagged lane)")
    for rec in recommendations:
        print(
            f"  lane      : role={rec['role']}  agent={rec['agent']}\n"
            f"  elapsed   : {rec['elapsed_s']:.1f}s  (median {rec['median_elapsed_s']:.1f}s,  "
            f"threshold {rec['flag_threshold_s']:.1f}s)\n"
            f"  fail_rate : {rec['fail_rate']} over {rec['fail_sample']} obs  "
            f"(min_sample={rec['fail_min_sample']}  threshold={rec['fail_threshold']})\n"
            f"  signal    : {rec['fail_signal']}\n"
            f"  direction : {rec['direction']}  (fail_rate > threshold → strengthen)\n"
            f"  effort    : {rec['effort_from']} → {rec['effort_to']}  "
            f"(actuated={rec['actuated']})\n"
            f"  note      : {rec['note']}"
        )

    _section("결과 요약")
    if effort_overrides:
        for (role, agent), effort in effort_overrides.items():
            print(f"  effort_overrides[({role!r}, {agent!r})] = {effort!r}")
        print()
        print("  다음 iteration: Auditor codex lane 에 '-c model_reasoning_effort=xhigh' 주입")
    else:
        print("  effort_overrides = {}  (오버라이드 없음)")

    print()
    if new_cooldown_state:
        for key, remaining in new_cooldown_state.items():
            role, _, agent = key.partition("||")
            print(f"  cooldown_state[{key!r}] = {remaining}  "
                  f"→ {remaining} iteration 동안 {role}/{agent} 재조정 억제")
    else:
        print("  cooldown_state = {}")

    _section("auto_loop_state.json 읽는 법")
    print(textwrap.dedent("""\
        reports/agent_loop/active/auto_loop_state.json
          cycles[-1].lane_stats          — 각 lane 의 role/agent/elapsed_s/status
          cycles[-1].lane_autotune_recommendations
            .role / .agent              — 감지된 lane
            .direction                  — "strengthen" | "accelerate"
            .effort_from / .effort_to   — 조정 전후 effort 단계
            .actuated                   — True 면 다음 iteration 에 실제 주입
            .cooldown_remaining         — 조정 억제 남은 횟수
    """))


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main() -> None:
    demo_off()
    demo_on()
    print()


if __name__ == "__main__":
    main()
