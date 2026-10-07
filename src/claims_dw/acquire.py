"""Download CMS archives with checksum verification and atomic promotion into data/raw."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import fixtures
from .config import Settings, sources
from .db import TransientError


class AcquisitionError(RuntimeError):
    """Downloaded bytes do not match the recorded source (not retryable)."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_entries(settings: Settings) -> list[dict[str, Any]]:
    """Source files for the configured source (CMS or the deterministic fixture)."""
    if settings.source == "fixture":
        return fixtures.source_entries()
    return [dict(e) for e in sources()["files"]]


def dataset_version(settings: Settings) -> str:
    return (
        fixtures.DATASET_VERSION if settings.source == "fixture" else sources()["dataset_version"]
    )


def _verify_archive(path: Path, entry: dict[str, Any]) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            if entry["member"] not in zf.namelist():
                raise AcquisitionError(f"{path.name}: member {entry['member']} not found")
            bad = zf.testzip()
            if bad is not None:
                raise AcquisitionError(f"{path.name}: corrupt member {bad}")
    except zipfile.BadZipFile as exc:
        raise AcquisitionError(f"{path.name}: not a valid zip archive") from exc


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "claims-dw/0.1 (portfolio project)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as out:
            for block in iter(lambda: response.read(1 << 20), b""):
                out.write(block)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise TransientError(f"download failed for {url}: {exc}") from exc


def acquire(settings: Settings) -> dict[str, Any]:
    """Ensure every source archive is present and verified; write data/manifest/sources.json."""
    raw_dir = settings.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.manifest_dir / "sources.json"
    previous = {}
    if manifest_path.exists():
        previous = {f["archive"]: f for f in json.loads(manifest_path.read_text())["files"]}

    if settings.source == "fixture":
        fixtures.write_source_archives(raw_dir)

    records = []
    for entry in source_entries(settings):
        target = raw_dir / entry["archive"]
        status = "present"
        if settings.source == "cms":
            if not (target.exists() and sha256_file(target) == entry["sha256"]):
                partial_dir = raw_dir / ".partial"
                partial_dir.mkdir(exist_ok=True)
                tmp = partial_dir / f"{entry['archive']}.part"
                _download(entry["url"], tmp)
                actual = sha256_file(tmp)
                if actual != entry["sha256"]:
                    tmp.unlink(missing_ok=True)
                    raise AcquisitionError(
                        f"{entry['archive']}: sha256 {actual} != recorded {entry['sha256']}"
                    )
                _verify_archive(tmp, entry)
                os.replace(tmp, target)  # atomic promotion on the same filesystem
                status = "downloaded"
            if target.stat().st_size != entry["size_bytes"]:
                raise AcquisitionError(f"{entry['archive']}: unexpected size")
        _verify_archive(target, entry)
        sha = sha256_file(target)
        prior = previous.get(entry["archive"], {})
        retrieved = prior.get("retrieved_at") if prior.get("sha256") == sha else None
        records.append(
            {
                "dataset": entry["dataset"],
                "year": entry.get("year"),
                "url": entry["url"],
                "archive": entry["archive"],
                "member": entry["member"],
                "sha256": sha,
                "size_bytes": target.stat().st_size,
                "retrieved_at": retrieved or datetime.now(UTC).isoformat(timespec="seconds"),
                "status": status,
            }
        )

    manifest = {
        "source": settings.source,
        "dataset_version": dataset_version(settings),
        "files": records,
    }
    settings.manifest_dir.mkdir(parents=True, exist_ok=True)
    tmp_manifest = manifest_path.with_suffix(".json.tmp")
    tmp_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(tmp_manifest, manifest_path)
    return manifest
