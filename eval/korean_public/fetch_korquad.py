#!/usr/bin/env python3
"""Fetch + deterministically sample a KorQuAD 2.x dev subset.

Single-purpose fetcher that downloads ONE chunk of the KorQuAD 2.1 dev
split, deterministically samples ``--sample-size`` (default 150)
question–article pairs, and writes the result to
``data/korean_public/korquad_dev_sample.json``.

Design constraints (ADR 0018 spirit):

* **Deterministic** — fixed seed; same input file → same sample. Two
  runs on different hosts produce byte-identical sample files.
* **Offline-capable** — pre-downloaded file can be passed via
  ``--input``; network not required for re-sampling.
* **No redistribution** — the script fetches the dataset on demand;
  the raw dataset never enters the repo.

KorQuAD 2.1 license: CC BY-ND 2.0 KR. Attribution required when
publishing derived metrics — see ``eval/korean_public/README.md``.

Usage:
  # Default — fetches dev_00 from the official mirror, samples 150.
  python eval/korean_public/fetch_korquad.py

  # Offline — use a pre-downloaded JSON file.
  python eval/korean_public/fetch_korquad.py --input ~/downloads/KorQuAD_2.1_dev_00.json

  # Bigger sample.
  python eval/korean_public/fetch_korquad.py --sample-size 300

Output schema (matches what ``run.py`` expects):
  {
    "version": "KorQuAD_2.1_dev_sample",
    "source": "KorQuAD 2.1 dev chunk 00",
    "seed": 17,
    "sample_size": 150,
    "articles": [{"title": "...", "context": "..."}, ...],
    "questions": [{"id": "...", "title": "...", "question": "...",
                   "answer_text": "..."}],
  }
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# KorQuAD 2.x contexts are HTML-formatted Wikipedia dumps (with <table>,
# <ul>, etc.). Our pipeline takes plain text, and the answer-substring
# metric needs to compare against the same view the model sees, so we
# strip HTML tags + decode entities + collapse whitespace on the
# context BEFORE sampling. Answers that don't survive that round-trip
# get dropped (they're typically formatting-bound and unscoreable
# without a richer normalizer).
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_WS_RE = re.compile(r"\s+")


def _normalize_context(raw_html: str) -> str:
    no_tags = _HTML_TAG_RE.sub(" ", raw_html)
    decoded = html.unescape(no_tags)
    return _MULTI_WS_RE.sub(" ", decoded).strip()

DEFAULT_SEED = 17
DEFAULT_SAMPLE_SIZE = 150
# Official KorQuAD 2.1 dev split (split into multiple zips by file size).
# dev_00 alone has thousands of articles — plenty for a 150-question
# sample. License: CC BY-ND 2.0 KR; we fetch on demand and never commit
# the raw archive.
DEFAULT_URL = (
    "https://raw.githubusercontent.com/korquad/korquad.github.io/"
    "master/dataset/KorQuAD_2.1/dev/KorQuAD_2.1_dev_00.zip"
)
DEFAULT_CACHE_DIR = Path("data/korean_public")
DEFAULT_OUTPUT_NAME = "korquad_dev_sample.json"
DEFAULT_RAW_NAME = "korquad_dev_00.zip"


def _read_json_from_zip_or_path(path: Path) -> dict[str, Any]:
    """Parse the KorQuAD dev source whether it's a raw .json or a .zip.

    Official distribution is a .zip with a single .json inside (file size
    in source-control terms); local cache + ``--input`` should accept
    either form so an operator who downloaded the raw JSON manually
    doesn't have to re-zip.
    """
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".json")]
            if not names:
                raise SystemExit(f"{path}: zip has no .json member")
            with zf.open(names[0]) as inner:
                return json.loads(inner.read().decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def _download(url: str, dest: Path) -> Path:
    """Fetch ``url`` to ``dest`` unless already present."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] downloading {url} → {dest}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=300) as resp:  # noqa: S310 - trusted host
        dest.write_bytes(resp.read())
    return dest


def _extract_first_answer(qa: dict[str, Any]) -> str | None:
    """KorQuAD 2.x ``qa`` may carry ``answer`` (single) or ``answers`` (list).

    Return the first non-empty answer text, or None for unanswerable.
    """
    single = qa.get("answer")
    if isinstance(single, dict):
        text = single.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    plural = qa.get("answers")
    if isinstance(plural, list):
        for entry in plural:
            if isinstance(entry, dict):
                text = entry.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return None


def sample_korquad(
    raw: dict[str, Any],
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Sample ``sample_size`` answerable questions deterministically.

    Each sampled question keeps its article ``title`` so the runner can
    rebuild the corpus + ground-truth mapping. Articles that none of
    the sampled questions reference are dropped from ``articles`` so
    the corpus stays minimal.
    """
    articles_raw = raw.get("data") or []
    rng = random.Random(seed)

    # Flatten (title, context, qa) candidates; skip qa without an answer.
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for article in articles_raw:
        title = str(article.get("title") or "").strip()
        raw_html_context = str(article.get("context") or "")
        context = _normalize_context(raw_html_context)
        if not title or not context:
            continue
        for qa in article.get("qas") or []:
            answer_text = _extract_first_answer(qa)
            qid = str(qa.get("id") or "").strip()
            question = str(qa.get("question") or "").strip()
            if not (qid and question and answer_text):
                continue
            # Skip cases where the answer string isn't a substring of the
            # normalized context. Many KorQuAD answers carry HTML or
            # formatting that doesn't survive the strip + whitespace
            # collapse — those are unscoreable for our substring metric
            # without a richer normalizer, so we drop them here.
            if answer_text not in context:
                continue
            candidates.append((title, context, qa))

    if len(candidates) < sample_size:
        raise SystemExit(
            f"Not enough scoreable candidates: got {len(candidates)}, "
            f"need {sample_size}. Pull a bigger raw file or lower --sample-size."
        )

    sampled = rng.sample(candidates, sample_size)

    # Build the unique-article corpus (only the articles referenced by
    # the sample stay).
    seen_titles: dict[str, str] = {}
    for title, context, _ in sampled:
        seen_titles.setdefault(title, context)
    articles = [{"title": t, "context": c} for t, c in seen_titles.items()]

    questions = [
        {
            "id": str(qa["id"]),
            "title": title,
            "question": str(qa["question"]),
            "answer_text": _extract_first_answer(qa) or "",
        }
        for title, _, qa in sampled
    ]

    return {
        "version": "KorQuAD_2.1_dev_sample",
        "source": "KorQuAD 2.1 dev (sampled)",
        "seed": seed,
        "sample_size": sample_size,
        "articles": articles,
        "questions": questions,
    }


def write_sample(payload: dict[str, Any], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def sample_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL, help="Source JSON URL.")
    ap.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Pre-downloaded JSON file (skips network).",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Directory for the cached raw + sample files.",
    )
    ap.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    cache_dir: Path = args.cache_dir
    if args.input is not None:
        raw_path = args.input
    else:
        raw_path = _download(args.url, cache_dir / DEFAULT_RAW_NAME)
    raw = _read_json_from_zip_or_path(raw_path)

    payload = sample_korquad(raw, sample_size=args.sample_size, seed=args.seed)
    out_path = cache_dir / DEFAULT_OUTPUT_NAME
    write_sample(payload, out_path)

    sha = sample_sha256(payload)
    print(f"[fetch] wrote {out_path}", file=sys.stderr)
    print(f"[fetch] sample sha256: {sha}", file=sys.stderr)
    print(
        f"[fetch] questions={len(payload['questions'])} "
        f"articles={len(payload['articles'])} seed={payload['seed']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
