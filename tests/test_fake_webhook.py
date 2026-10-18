# SPDX-License-Identifier: GPL-2.0-or-later
"""fake-webhook certificate lookup, including hosts whose OpenSSL cafile is unset."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "fake-webhook.py"
    spec = importlib.util.spec_from_file_location("fake_webhook", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ssl_cert_file_is_used_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load()
    chosen = tmp_path / "chosen.pem"
    chosen.write_bytes(b"chosen-ca\n")
    monkeypatch.setenv("SSL_CERT_FILE", str(chosen))
    assert module.system_ca_file() == chosen


def test_missing_default_cafile_uses_a_distro_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load()
    fedora = tmp_path / "tls-ca-bundle.pem"
    fedora.write_bytes(b"fedora-ca\n")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    class Paths:
        cafile = None
        capath = None

    monkeypatch.setattr(module.ssl, "get_default_verify_paths", lambda: Paths())
    monkeypatch.setattr(module, "_CA_FILES", (str(fedora), "/no/such/ca.pem"))
    assert module.system_ca_file() == fedora


def test_capath_pem_files_are_concatenated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load()
    cap = tmp_path / "certs"
    cap.mkdir()
    pem = b"-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----\n"
    (cap / "one.pem").write_bytes(pem)
    (cap / "skip.txt").write_bytes(b"nope\n")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    class Paths:
        cafile = None
        capath = str(cap)

    monkeypatch.setattr(module.ssl, "get_default_verify_paths", lambda: Paths())
    monkeypatch.setattr(module, "_ca_candidates", lambda: [tmp_path / "missing.pem"])
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    found = module.system_ca_file()
    assert found is not None
    data = found.read_bytes()
    assert b"BEGIN CERTIFICATE" in data
    assert b"nope" not in data


def test_bundle_being_written_is_not_its_own_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load()
    bundle = tmp_path / "bundle.pem"
    bundle.write_bytes(b"self\n")
    real = tmp_path / "real.pem"
    real.write_bytes(b"real\n")
    monkeypatch.setattr(module, "_ca_candidates", lambda: [bundle, real])
    monkeypatch.setattr(module, "_bundle_capath", lambda: None)
    assert module.system_ca_file(exclude=bundle) == real


def test_startup_lines_flush(tmp_path: Path):
    del tmp_path
    module = _load()

    class Stream:
        def __init__(self) -> None:
            self.writes: list[str] = []
            self.flushes = 0

        def write(self, data: str) -> int:
            self.writes.append(data)
            return len(data)

        def flush(self) -> None:
            self.flushes += 1

    stream = Stream()
    module._say(stream, "URL: https://127.0.0.1:8765/hook")
    assert stream.flushes == 1
    assert stream.writes[0].startswith("URL:")
