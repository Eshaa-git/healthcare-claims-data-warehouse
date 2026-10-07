import io
import zipfile

import pytest

from claims_dw import acquire
from claims_dw.config import DbSettings, Settings


def make_zip(member: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, text)
    return buf.getvalue()


@pytest.fixture
def cms_settings(tmp_path):
    db = DbSettings("x", 1, "x", "a", "a", "l", "t", "d")
    return Settings(db=db, data_dir=tmp_path, source="cms", cohort_size=10, chunk_rows=10)


def patch_sources(monkeypatch, payload: bytes, sha: str):
    entry = {
        "dataset": "drug_events",
        "url": "https://example.invalid/x.zip",
        "archive": "x.zip",
        "member": "x.csv",
        "sha256": sha,
        "size_bytes": len(payload),
    }
    monkeypatch.setattr(acquire, "sources", lambda: {"dataset_version": "t", "files": [entry]})

    def fake_download(url, dest):
        dest.write_bytes(payload)

    monkeypatch.setattr(acquire, "_download", fake_download)


def test_download_is_verified_and_promoted(monkeypatch, cms_settings):
    payload = make_zip("x.csv", "a,b\n1,2\n")
    import hashlib

    patch_sources(monkeypatch, payload, hashlib.sha256(payload).hexdigest())
    manifest = acquire.acquire(cms_settings)
    assert manifest["files"][0]["status"] == "downloaded"
    assert (cms_settings.raw_dir / "x.zip").read_bytes() == payload
    assert not list((cms_settings.raw_dir / ".partial").iterdir())
    # second call finds the verified file and does not download again
    assert acquire.acquire(cms_settings)["files"][0]["status"] == "present"


def test_checksum_mismatch_never_reaches_raw(monkeypatch, cms_settings):
    payload = make_zip("x.csv", "tampered\n")
    patch_sources(monkeypatch, payload, "0" * 64)
    with pytest.raises(acquire.AcquisitionError, match="sha256"):
        acquire.acquire(cms_settings)
    assert not (cms_settings.raw_dir / "x.zip").exists()
