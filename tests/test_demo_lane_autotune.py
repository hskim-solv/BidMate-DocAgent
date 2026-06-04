from __future__ import annotations

from scripts import demo_lane_autotune as demo


def test_demo_off_prints_inert_contract(capsys):
    demo.demo_off()

    out = capsys.readouterr().out

    assert "AUTOTUNE OFF" in out
    assert "ACTIVE_LANE_AUTOTUNE" in out
    assert "effort_overrides : {}" in out
    assert "recommendations  : []" in out
    assert "cooldown_state   : {}" in out
    assert "컨트롤러 미호출" in out


def test_demo_on_prints_auditor_strengthen_contract(capsys):
    demo.demo_on()

    out = capsys.readouterr().out

    assert "AUTOTUNE ON" in out
    assert "agent=codex  median=10.3s" in out
    assert "role=Auditor  agent=codex" in out
    assert "fail_rate : 1.0 over 3 obs" in out
    assert "direction : strengthen" in out
    assert "effort    : high → xhigh  (actuated=True)" in out
    assert "effort_overrides[('Auditor', 'codex')] = 'xhigh'" in out
    assert "cooldown_state['Auditor||codex'] = 2" in out
    assert "model_reasoning_effort=xhigh" in out


def test_main_prints_off_before_on_demo(capsys):
    demo.main()

    out = capsys.readouterr().out

    assert out.index("AUTOTUNE OFF") < out.index("AUTOTUNE ON")
