from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.propose_private_real100_v2_questions import (  # noqa: E402
    PROFILE_TYPE,
    generate_question_set,
    main,
    write_outputs,
)


def _chunk(doc: str, chunk: str, text: str, page: int) -> dict:
    return {
        "doc_id": doc,
        "chunk_id": chunk,
        "text": text,
        "metadata": {"page_span": [page, page], "text_source": "pdf_pymupdf4llm"},
    }


def _index() -> dict:
    return {
        "schema_version": 2,
        "chunks": [
            _chunk(
                "SECRET-DOC-A",
                "SECRET-CHUNK-A1",
                "요구사항 본문입니다. 사업비는 1억원이며 납품은 계약 후 3개월 이내입니다.",
                1,
            ),
            _chunk(
                "SECRET-DOC-A",
                "SECRET-CHUNK-A2",
                "운영 조건은 SLA 99.5% 이상이며 장애 대응은 2시간 이내 임시 조치입니다.",
                2,
            ),
            _chunk(
                "SECRET-DOC-B",
                "SECRET-CHUNK-B1",
                "| 항목 | 배점 |\\n| 기술평가 | 80점 |\\n| 가격평가 | 20점 |",
                3,
            ),
            _chunk(
                "SECRET-DOC-C",
                "SECRET-CHUNK-C1",
                "제안서 제출 마감은 2026년 7월 15일 17:00이며 발표 일정은 별도 통지합니다.",
                4,
            ),
        ],
    }


def test_tier_generation_contract_covers_easy_standard_and_hard() -> None:
    cases = generate_question_set(_index(), targets={"easy_sanity": 1, "standard_real": 2, "hard_stress": 6})
    tiers = {case["difficulty_tier"] for case in cases}
    assert {"easy_sanity", "standard_real", "hard_stress"} <= tiers
    assert any(case["question_type"] == "multi_chunk_same_doc" for case in cases)
    assert any(case["question_type"] == "unanswerable_absence" for case in cases)


def test_aggregate_only_output_excludes_raw_private_content(tmp_path: Path) -> None:
    cases = generate_question_set(_index(), targets={"easy_sanity": 1, "standard_real": 1, "hard_stress": 2})
    aggregate = write_outputs(
        cases,
        out_dir=tmp_path / "private_questions",
        aggregate_path=tmp_path / "question_distribution.aggregate.json",
        eval_config_path=tmp_path / "real_config_v2.local.yaml",
        index_dir_label="data/index/real100_v2",
        targets={"easy_sanity": 1, "standard_real": 1, "hard_stress": 2},
    )

    rendered = json.dumps(aggregate, ensure_ascii=False, sort_keys=True)
    assert aggregate is not None
    assert aggregate["schema_version"] == 1
    assert aggregate["profile_type"] == PROFILE_TYPE
    assert "SECRET-DOC" not in rendered
    assert "SECRET-CHUNK" not in rendered
    assert "사업비는 1억원" not in rendered
    assert "questions" not in aggregate
    assert (tmp_path / "private_questions" / "questions.jsonl").is_file()
    assert (tmp_path / "private_questions" / "gold_evidence.jsonl").is_file()


def test_cli_writes_private_draft_and_public_safe_aggregate(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index(), ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "private_questions"
    out_aggregate = tmp_path / "question_distribution.aggregate.json"

    rc = main(
        [
            "--index",
            str(index_path),
            "--out-dir",
            str(out_dir),
            "--out-aggregate",
            str(out_aggregate),
            "--easy",
            "1",
            "--standard",
            "1",
            "--hard",
            "2",
        ]
    )

    assert rc == 0
    aggregate = json.loads(out_aggregate.read_text(encoding="utf-8"))
    assert aggregate["comparison_protocol"]["interpretation_not_cherry_picking"] is True
