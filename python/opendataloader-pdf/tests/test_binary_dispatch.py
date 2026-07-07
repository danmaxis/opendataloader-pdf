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


def _patch_native(monkeypatch, tmp_path):
    """Wire run_native to a fake binary + fake subprocess; return (fake_bin, captured)."""
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

    def fake_run(command, **_kw):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    return fake_bin, captured


def test_run_native_restores_exec_bit_on_posix(monkeypatch, tmp_path):
    """On non-Windows, run_native chmod +x's the resolved binary before spawning."""
    fake_bin, captured = _patch_native(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux", raising=False)
    chmod_calls = []
    monkeypatch.setattr(runner.os, "chmod", lambda p, mode: chmod_calls.append((p, mode)))

    assert runner.run_native(["a.pdf"], quiet=True) == "ok\n"
    assert chmod_calls and chmod_calls[0][0] == str(fake_bin)
    # The mode keeps the user/group/other execute bits.
    assert chmod_calls[0][1] & 0o111 == 0o111
    assert captured["command"][0] == str(fake_bin)


def test_run_native_survives_chmod_oserror(monkeypatch, tmp_path):
    """An OSError from the exec-bit restore must not stop the binary from running."""
    fake_bin, captured = _patch_native(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux", raising=False)

    def _boom(_p, _mode):
        raise OSError("read-only fs")

    monkeypatch.setattr(runner.os, "chmod", _boom)
    assert runner.run_native(["a.pdf"], quiet=True) == "ok\n"
    assert captured["command"][0] == str(fake_bin)


def test_run_native_skips_chmod_on_windows(monkeypatch, tmp_path):
    """On Windows there is no exec bit to restore; chmod must not be called."""
    fake_bin, captured = _patch_native(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(runner.os, "chmod", lambda *_a: (_ for _ in ()).throw(AssertionError("chmod on win")))
    assert runner.run_native(["a.pdf"], quiet=True) == "ok\n"
