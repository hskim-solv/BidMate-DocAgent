from __future__ import annotations

import hashlib
import unicodedata

from ingestion import _KORDOC_MANIFEST_SCHEMA_VERSION, _KORDOC_POSTPROCESS_VERSION
from scripts.build_kordoc_manifest import build_manifest


def test_build_manifest_matches_nfc_stems_and_skips_stale_cache(tmp_path, capsys):
    source_dir = tmp_path / "files"
    cache_dir = tmp_path / "files_kordoc"
    source_dir.mkdir()
    cache_dir.mkdir()

    nfc_stem = unicodedata.normalize("NFC", "cafe\u0301")
    nfd_stem = unicodedata.normalize("NFD", nfc_stem)
    source_path = source_dir / f"{nfc_stem}.pdf"
    source_bytes = b"private bytes are represented only by digest metadata"
    source_path.write_bytes(source_bytes)
    (cache_dir / f"{nfd_stem}.md").write_text("converted markdown", encoding="utf-8")
    (cache_dir / "stale.md").write_text("stale markdown", encoding="utf-8")

    manifest = build_manifest(source_dir, cache_dir)

    stderr = capsys.readouterr().err
    assert "cached .md had no matching source" in stderr
    assert "stale.md" in stderr
    assert manifest["schema_version"] == _KORDOC_MANIFEST_SCHEMA_VERSION
    assert manifest["postprocess_version"] == _KORDOC_POSTPROCESS_VERSION
    assert set(manifest["entries"]) == {nfc_stem}
    assert manifest["entries"][nfc_stem] == {
        "source_relpath": source_path.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_size": len(source_bytes),
    }
