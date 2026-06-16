"""
Low-level CLI runner for opendataloader-pdf.

By default this spawns the bundled standalone native (GraalVM) executable, so
no Java runtime is required. It transparently falls back to the bundled JAR
(``java -jar``) when no native binary is available (e.g. an sdist install) or
when ``OPENDATALOADER_USE_JVM`` is set.
"""
import os
import subprocess
import sys
import importlib.resources as resources
from typing import List

from . import binary

# The consistent name of the JAR file bundled with the (fallback) package
_JAR_NAME = "opendataloader-pdf-cli.jar"


def run(args: List[str], quiet: bool = False) -> str:
    """Run the opendataloader-pdf CLI, preferring the native binary."""
    if binary.native_binary_ref() is not None:
        return run_native(args, quiet)
    return run_jar(args, quiet)


def run_native(args: List[str], quiet: bool = False) -> str:
    """Run the bundled native executable directly (no JVM)."""
    ref = binary.native_binary_ref()
    if ref is None:
        # Native explicitly requested but unavailable; fall back to the JVM jar.
        return run_jar(args, quiet)
    with resources.as_file(ref) as bin_path:
        bin_path = str(bin_path)
        # The wheel should preserve the executable bit; restore it defensively
        # in case packaging/extraction dropped it (POSIX only).
        if not sys.platform.startswith("win"):
            try:
                os.chmod(bin_path, os.stat(bin_path).st_mode | 0o111)
            except OSError:
                pass
        return _execute([bin_path, *args], quiet)


def run_jar(args: List[str], quiet: bool = False) -> str:
    """Run the opendataloader-pdf JAR with the given arguments (legacy JVM path)."""
    try:
        # Access the embedded JAR inside the package
        jar_ref = resources.files("opendataloader_pdf").joinpath("jar", _JAR_NAME)
        with resources.as_file(jar_ref) as jar_path:
            # Force headless AWT so macOS doesn't surface a Dock icon (and
            # steal focus) every time the JVM touches ImageIO/PDFBox
            # rendering. Safe on all OSes — the CLI never opens a UI window,
            # only manipulates BufferedImages.
            command = [
                "java",
                "-Djava.awt.headless=true",
                "-Dapple.awt.UIElement=true",
                "-jar",
                str(jar_path),
                *args,
            ]
            return _execute(command, quiet)

    except FileNotFoundError:
        print(
            "Error: 'java' command not found. Please ensure Java is installed and in your system's PATH.",
            file=sys.stderr,
        )
        raise


def _execute(command: List[str], quiet: bool) -> str:
    """Spawn ``command`` and relay its output, identically for the native and JVM paths."""
    try:
        if quiet:
            # Quiet mode → suppress the CLI's log stream (stderr) but relay its
            # stdout to the caller: --to-stdout content and the folder summary
            # line arrive on stdout, and swallowing them breaks pipe consumers
            # (`... --quiet --to-stdout | jq`).
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.stdout:
                if hasattr(sys.stdout, "buffer"):
                    sys.stdout.buffer.write(
                        result.stdout.encode("utf-8", errors="replace")
                    )
                    sys.stdout.buffer.flush()
                else:
                    sys.stdout.write(result.stdout)
            return result.stdout

        # Streaming mode → live output
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            output_lines: List[str] = []
            for line in process.stdout:
                if hasattr(sys.stdout, "buffer"):
                    sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
                    sys.stdout.buffer.flush()
                else:
                    sys.stdout.write(line)
                output_lines.append(line)

            return_code = process.wait()
            captured_output = "".join(output_lines)

            if return_code:
                raise subprocess.CalledProcessError(
                    return_code, command, output=captured_output
                )
            return captured_output

    except subprocess.CalledProcessError as error:
        print("Error running opendataloader-pdf CLI.", file=sys.stderr)
        print(f"Return code: {error.returncode}", file=sys.stderr)
        # Streaming mode already wrote the CLI's output live to stdout, so
        # re-printing the captured copy would duplicate it. Only surface the
        # captured streams in quiet mode, where the caller has not seen them.
        # Note: CalledProcessError.output and .stdout are aliases for the same
        # attribute — printing both produces the same content twice.
        if quiet:
            if error.stdout:
                print(f"Stdout: {error.stdout}", file=sys.stderr)
            if error.stderr:
                print(f"Stderr: {error.stderr}", file=sys.stderr)
        raise
