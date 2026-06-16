"""Tests for native-binary resolution and runner dispatch (JVM-free path)."""
import subprocess
from unittest.mock import MagicMock

from opendataloader_pdf import binary, runner


def _fake_ref(is_file=True):
    ref = MagicMock()
    ref.is_file.return_value = is_file
    return ref


def test_use_jvm_env_toggle(monkeypatch):
    monkeypatch.delenv("OPENDATALOADER_USE_JVM", raising=False)
    assert binary.use_jvm() is False
    for truthy in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv("OPENDATALOADER_USE_JVM", truthy)
        assert binary.use_jvm() is True
    for falsy in ("0", "false", "no", ""):
        monkeypatch.setenv("OPENDATALOADER_USE_JVM", falsy)
        assert binary.use_jvm() is False


def test_native_ref_none_when_jvm_forced(monkeypatch):
    monkeypatch.setattr(binary, "use_jvm", lambda: True)
    assert binary.native_binary_ref() is None


def test_native_ref_none_when_binary_absent(monkeypatch):
    monkeypatch.setattr(binary, "use_jvm", lambda: False)
    monkeypatch.setattr(
        binary.resources, "files", lambda _pkg: MagicMock(joinpath=lambda *_a: _fake_ref(is_file=False))
    )
    assert binary.native_binary_ref() is None


def test_run_dispatches_to_native_when_available(monkeypatch):
    monkeypatch.setattr(runner.binary, "native_binary_ref", lambda: _fake_ref(True))
    called = {}
    monkeypatch.setattr(runner, "run_native", lambda args, quiet=False: (called.update(native=(args, quiet)), "ok")[1])
    monkeypatch.setattr(runner, "run_jar", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("jar must not run")))
    assert runner.run(["doc.pdf"], quiet=True) == "ok"
    assert called["native"] == (["doc.pdf"], True)


def test_run_falls_back_to_jar_when_no_binary(monkeypatch):
    monkeypatch.setattr(runner.binary, "native_binary_ref", lambda: None)
    called = {}
    monkeypatch.setattr(runner, "run_jar", lambda args, quiet=False: (called.update(jar=(args, quiet)), "ok")[1])
    assert runner.run(["doc.pdf"]) == "ok"
    assert called["jar"] == (["doc.pdf"], False)


def test_run_native_spawns_binary_directly(monkeypatch, tmp_path):
    fake_bin = tmp_path / "opendataloader-pdf"
    fake_bin.write_bytes(b"")
    ref = MagicMock()
    ref.is_file.return_value = True
    monkeypatch.setattr(runner.binary, "native_binary_ref", lambda: ref)

    class _AsFile:
        def __enter__(self):
            return fake_bin

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(runner.resources, "as_file", lambda _r: _AsFile())

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="done\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    out = runner.run_native(["a.pdf", "--format", "json"], quiet=True)
    assert out == "done\n"
    # First arg is the binary itself, NOT 'java', and no -jar flag.
    assert captured["command"][0] == str(fake_bin)
    assert "java" not in captured["command"]
    assert "-jar" not in captured["command"]
    assert captured["command"][1:] == ["a.pdf", "--format", "json"]
