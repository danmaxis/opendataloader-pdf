"""
Resolution of the bundled native (GraalVM) executable.

The JVM-free distribution ships a standalone native binary built with GraalVM
native-image instead of requiring a Java runtime. Platform-specific wheels
embed the matching binary under ``opendataloader_pdf/bin/``. This module locates
that binary; the runner falls back to the bundled JAR (``java -jar``) when no
native binary is available or when ``OPENDATALOADER_USE_JVM`` is set.
"""
import os
import sys
import importlib.resources as resources

# Single binary per platform wheel, so a fixed name is enough.
_BIN_NAME = "opendataloader-pdf.exe" if sys.platform.startswith("win") else "opendataloader-pdf"


def use_jvm() -> bool:
    """True when the caller forces the legacy JVM path via OPENDATALOADER_USE_JVM."""
    value = os.environ.get("OPENDATALOADER_USE_JVM", "").strip().lower()
    return value not in ("", "0", "false", "no")


def native_binary_ref():
    """
    Return a importlib.resources traversable pointing at the bundled native
    binary, or ``None`` when it is absent (e.g. sdist install) or disabled.

    The caller is expected to wrap the result with ``resources.as_file`` to get
    a concrete filesystem path before spawning.
    """
    if use_jvm():
        return None
    try:
        ref = resources.files("opendataloader_pdf").joinpath("bin", _BIN_NAME)
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    try:
        if not ref.is_file():
            return None
    except OSError:
        return None
    return ref
