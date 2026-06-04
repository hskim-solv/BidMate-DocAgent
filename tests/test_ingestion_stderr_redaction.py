"""Unit coverage for ingestion._safe_process_tail HWP 변환 stderr redaction (issue #2340).

``_safe_process_tail`` 은 HWP→PDF 변환 서브프로세스 stderr 의 tail 을 진단
메시지로 남기되 비공개 경로/파일명을 redaction 하는 import-safe leaf
(torch/chromadb/rag_core 미로드)인데 직접 단위 테스트가 0건이었다(test-only,
소스 무수정). ADR 0005 데이터 경계와 정합.

핵심 변별:
- None/빈/공백 → "".
- bytes → utf-8(errors="replace") decode 후 strip.
- ``str(source_path)``→``<source_path>``, ``source_path.name``→``<source_file>``.
- 절대경로 prefix / Windows drive → ``<path>``.
- tail 은 마지막 ``_HWP_TO_PDF_STDERR_TAIL_CHARS``(=400)자만.
"""
from __future__ import annotations

from pathlib import Path

from ingestion import _HWP_TO_PDF_STDERR_TAIL_CHARS, _safe_process_tail

_SP = Path("/Users/foo/secret/공고문서.hwp")


def test_empty_or_whitespace_stderr_returns_empty() -> None:
    # None / 빈 / 공백뿐 → "".
    assert _safe_process_tail(None, _SP) == ""
    assert _safe_process_tail("", _SP) == ""
    assert _safe_process_tail("   ", _SP) == ""


def test_bytes_are_decoded_and_stripped() -> None:
    # bytes → utf-8 decode + 양끝 strip(decode 누락 시 bytes 그대로/타입에러 KILL).
    assert _safe_process_tail(b"error at end\n", _SP) == "error at end"
    # invalid utf-8 → errors="replace"(크래시 대신 U+FFFD 치환).
    assert _safe_process_tail(b"\xff fail", _SP) == "� fail"


def test_source_path_and_name_are_redacted() -> None:
    # 전체 경로 → <source_path>.
    assert _safe_process_tail(f"failed: {_SP}", _SP) == "failed: <source_path>"
    # 파일명만 등장 → <source_file>(원문 파일명 유출 시 KILL).
    out = _safe_process_tail("opening 공고문서.hwp now", _SP)
    assert out == "opening <source_file> now"
    assert "공고문서" not in out


def test_generic_absolute_paths_redacted_to_path() -> None:
    # source_path 와 무관한 6개 절대경로 prefix 가 모두 <path>(로컬 디렉터리
    # 구조 유출 차단). prefix 하나라도 regex alternative 에서 빠지면 그 경로가
    # leak 돼 KILL — 특히 /Users/ 는 source-path replace 가 먼저 잡는 케이스와
    # 달리 무관 경로라 generic regex 만으로 가려져야 한다.
    for pfx in ("/Users/", "/private/", "/tmp/", "/var/", "/home/", "/Volumes/"):
        assert _safe_process_tail(f"err at {pfx}a/b.log here", _SP) == "err at <path> here"
    # Windows drive 경로.
    assert _safe_process_tail(r"load C:\Users\x\f.dll fail", _SP) == "load <path> fail"


def test_clean_message_unchanged() -> None:
    # PII/경로 없는 메시지는 그대로(과잉 redaction 시 KILL).
    assert _safe_process_tail("just a message", _SP) == "just a message"


def test_only_last_tail_chars_kept() -> None:
    # tail 은 마지막 _HWP_TO_PDF_STDERR_TAIL_CHARS 자만 — 그 앞 내용은 버린다.
    n = _HWP_TO_PDF_STDERR_TAIL_CHARS
    out = _safe_process_tail("X" * 50 + "Y" * n, _SP)
    # 앞부분(X)은 잘려나가고 마지막 n 자(전부 Y)만 남는다.
    assert out == "Y" * n
    assert "X" not in out
