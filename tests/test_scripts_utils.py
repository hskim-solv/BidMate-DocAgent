"""Unit coverage for scripts/_utils.py helpers (issue #2143).

scripts/_utils.py exports 17 shared I/O / git / metric helpers but had no
direct unit tests. These lock the provenance-tracking determinism
(``json_hash`` key-order invariance, ``make_run_id`` normalization), the two
intentionally-distinct missing-value formatting conventions (``fmt_rate``
"N/A" vs ``fmt_cell`` "—"), and the file I/O round-trips that aggregate
artifact writers depend on.

``render_history_table`` / ``metric_snapshot`` and the git-state-dependent
paths of ``build_provenance`` / ``git_dirty`` are out of scope (follow-up) —
only ``git_output``'s never-raise default-fallback contract is exercised.

Import idiom mirrors ``tests/test_eval_artifact_privacy_regression.py``
(``from scripts._governance import ...``): scripts/ is an implicit
namespace package reachable from the repo root that pytest puts on sys.path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts._utils import (
    append_jsonl,
    fmt_cell,
    fmt_rate,
    git_output,
    json_hash,
    load_json,
    load_yaml,
    make_run_id,
    rel_path,
    repo_path,
    stable_json,
    write_json,
)


# --- json_hash: sort_keys 결정성 (provenance hash 안정성 계약) ---


def test_json_hash_is_key_order_invariant() -> None:
    """``sort_keys=True`` 이므로 동일 내용·다른 키 삽입 순서 → 동일 hash.
    provenance/aggregate hash 가 dict 순서에 흔들리면 안 된다."""
    a = json_hash({"alpha": 1, "beta": 2, "gamma": 3})
    b = json_hash({"gamma": 3, "alpha": 1, "beta": 2})
    assert a == b


def test_json_hash_distinguishes_content() -> None:
    """내용이 다르면 hash 도 다르다 (해시가 trivial 하게 충돌하지 않음)."""
    assert json_hash({"x": 1}) != json_hash({"x": 2})


def test_json_hash_is_sha256_hex() -> None:
    """반환은 64자 hex (sha256) — 다운스트림이 길이/문자셋을 가정한다."""
    digest = json_hash({"x": 1})
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_json_hash_handles_non_ascii_deterministically() -> None:
    """``ensure_ascii=False`` — 한글 payload 도 결정적으로 해시된다."""
    assert json_hash({"기관": "행정안전부"}) == json_hash({"기관": "행정안전부"})


# --- make_run_id: provenance → YYYYMMDDTHHMMSSZ_<sha12> 정규화 ---


def test_make_run_id_normalizes_timestamp_and_truncates_sha() -> None:
    """ISO 타임스탬프의 ``-``/``:`` 제거 + 소수점 drop, sha 12자 truncate."""
    prov: dict[str, object] = {
        "generated_at": "2026-06-03T22:15:00.123456Z",
        "git_commit": "abcdef0123456789",
    }
    assert make_run_id(prov) == "20260603T221500Z_abcdef012345"


def test_make_run_id_appends_z_when_missing() -> None:
    """타임스탬프에 ``Z`` 가 없으면 보강한다."""
    rid = make_run_id({"generated_at": "20260603T221500", "git_commit": "a" * 12})
    assert rid.startswith("20260603T221500Z_")


def test_make_run_id_defaults_missing_commit_to_unknown() -> None:
    """``git_commit`` 부재 → 'unknown' (str(None or 'unknown') 분기)."""
    rid = make_run_id({"generated_at": "2026-06-03T22:15:00Z"})
    assert rid.endswith("_unknown")


# --- fmt_rate vs fmt_cell: 의도적으로 다른 missing-value 컨벤션 ---


def test_fmt_rate_numeric_three_decimals() -> None:
    assert fmt_rate(0.5) == "0.500"
    assert fmt_rate(1) == "1.000"


def test_fmt_rate_non_numeric_is_na() -> None:
    """fmt_rate 의 missing 은 'N/A' (README ablation 테이블 컨벤션)."""
    assert fmt_rate(None) == "N/A"
    assert fmt_rate("x") == "N/A"


def test_fmt_cell_none_is_em_dash_distinct_from_fmt_rate() -> None:
    """fmt_cell 의 missing 은 '—' em dash (history 테이블) — fmt_rate 와 갈린다.
    두 컨벤션이 실제로 다른 문자열을 내는지 한 곳에서 못 박는다."""
    assert fmt_cell(None) == "—"
    assert fmt_rate(None) != fmt_cell(None)


def test_fmt_cell_float_three_decimals_but_int_str_passthrough() -> None:
    """float 만 3소수, int/str 은 ``str()`` passthrough (fmt_rate 와 또 다른 분기).
    int 3 은 '3' 이지 '3.000' 이 아니다."""
    assert fmt_cell(0.5) == "0.500"
    assert fmt_cell(3) == "3"
    assert fmt_cell("hybrid") == "hybrid"


# --- stable_json: ensure_ascii=False + trailing newline ---


def test_stable_json_preserves_non_ascii_and_trailing_newline() -> None:
    out = stable_json({"기관": "행안부"})
    assert "기관" in out  # \uXXXX 로 escape 되지 않음
    assert out.endswith("\n")
    assert json.loads(out) == {"기관": "행안부"}


# --- repo_path / rel_path: ROOT_DIR 경계 ---


def test_repo_path_absolute_passthrough_relative_joined() -> None:
    abs_p = Path("/tmp/x")
    assert repo_path(abs_p) == abs_p  # 절대경로 그대로
    joined = repo_path("eval/config.yaml")
    assert joined.is_absolute() and joined.name == "config.yaml"


def test_rel_path_inside_root_relative_outside_absolute() -> None:
    inside = repo_path("scripts/_utils.py")
    assert rel_path(inside) == "scripts/_utils.py"
    # ROOT_DIR 밖 경로는 relative_to ValueError → 절대경로 fallback
    outside = rel_path("/tmp")
    assert Path(outside).is_absolute()


# --- load_yaml: non-mapping → ValueError ---


def test_load_yaml_rejects_non_mapping(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_yaml(p)


def test_load_yaml_returns_mapping(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text("key: 값\n", encoding="utf-8")
    assert load_yaml(p) == {"key": "값"}


# --- write_json / load_json / append_jsonl round-trip ---


def test_write_json_round_trip_creates_parent_and_preserves_unicode(
    tmp_path: Path,
) -> None:
    target = tmp_path / "nested" / "out.json"  # 부모 디렉터리 미존재
    payload = {"기관": "행안부", "n": 3}
    write_json(target, payload)
    assert target.exists()  # mkdir(parents=True, exist_ok=True)
    assert load_json(target) == payload
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")  # trailing newline
    assert "기관" in text  # ensure_ascii=False


def test_append_jsonl_accumulates_one_object_per_line(tmp_path: Path) -> None:
    p = tmp_path / "log" / "events.jsonl"  # 부모 디렉터리 미존재
    append_jsonl(p, {"i": 1})
    append_jsonl(p, {"i": 2, "한글": "값"})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # append mode, 누적
    assert json.loads(lines[0]) == {"i": 1}
    assert json.loads(lines[1]) == {"i": 2, "한글": "값"}


# --- git_output: subprocess 실패 시 default fallback (never-raise) ---


def test_git_output_returns_default_on_failure() -> None:
    """존재하지 않는 git 서브커맨드 → CalledProcessError → default 반환.
    provenance 수집이 git 오류로 crash 하지 않는다 (except → default)."""
    assert git_output(["definitely-not-a-git-command"], default="FB") == "FB"


def test_git_output_strips_and_returns_real_output() -> None:
    """정상 명령은 ``stdout.strip()`` 반환 (이 repo HEAD SHA, 개행 없음)."""
    sha = git_output(["rev-parse", "HEAD"], default="")
    assert sha and "\n" not in sha and len(sha) >= 7
