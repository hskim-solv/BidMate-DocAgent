"""ADR 번역 시 식별자 보존 검증.

번역 PR(예: PR-D, issue #919)이 ADR 본문의 자연어 prose만 한국어로 교체하고
load-bearing 식별자(파일 경로, ADR 번호, PR/issue 번호, `make` 타깃, env var,
verifies-key 마커, schema_version 등)는 변경하지 않았는지 확인한다.

사용:
    python3 scripts/check_translation_identifier_parity.py docs/adr/
    python3 scripts/check_translation_identifier_parity.py --base-ref HEAD~1 docs/adr/

종료 코드 0 = 모든 식별자 before ⊆ after. 1 = 일부 ADR 에서 식별자 소실.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

PATTERNS: list[tuple[str, str]] = [
    (r"ADR\s+0\d{3}", "ADR"),
    (r"(?<![\w/])\d{4}-[a-z][a-z0-9-]+\.md", "ADR-file"),
    (r"#\d{3,}", "issue/PR"),
    (r"`[a-zA-Z_./][a-zA-Z0-9_./-]*\.(py|sh|md|yaml|yml|json|jsonl|toml)`", "file"),
    (r"`make\s+[a-z][a-z-]*`", "make"),
    (r"BIDMATE_[A-Z_]+", "env"),
    (r"<!--\s*verifies-key:[^>]+-->", "verifies-key"),
    (r"schema_version", "schema_version"),
    (r"(?<![\w-])(naive_baseline|agentic_full)(?![\w-])", "preset"),
]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract(text: str) -> dict[str, set[str]]:
    return {
        name: {_normalize(m) for m in re.findall(pat, text)}
        for pat, name in PATTERNS
    }


def read_git(ref: str, path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def check_pair(before: str, after: str) -> list[str]:
    b = extract(before)
    a = extract(after)
    issues: list[str] = []
    for name in b:
        missing = b[name] - a[name]
        if missing:
            sample = sorted(missing)[:5]
            extra = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
            issues.append(f"{name}: missing {sample}{extra}")
    return issues


EXCLUDE_NAMES = {"README.md", "_template.md"}


def iter_adr_files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_file() and p.suffix == ".md":
            yield p
        elif p.is_dir():
            yield from (f for f in sorted(p.glob("*.md")) if f.name not in EXCLUDE_NAMES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="ADR file(s) or directory")
    parser.add_argument("--base-ref", default="HEAD~1", help="git ref to diff against")
    args = parser.parse_args()

    files = list(iter_adr_files(args.paths))
    if not files:
        print("No .md files found.", file=sys.stderr)
        return 1

    failed = 0
    for path in files:
        before = read_git(args.base_ref, path)
        if not before:
            continue
        after = path.read_text(encoding="utf-8")
        issues = check_pair(before, after)
        if issues:
            failed += 1
            print(f"FAIL {path}:")
            for line in issues:
                print(f"  {line}")
        else:
            print(f"OK   {path}")

    print(f"\nTotal {len(files)} files, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
