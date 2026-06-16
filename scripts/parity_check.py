#!/usr/bin/env python3
"""
Parity harness: prove the native (GraalVM) binary produces the same output as
the JVM jar across every sample PDF and output format.

For each (sample, format) it runs both the native binary and `java -jar`, then
compares the produced files:

  * .json            -> parsed, canonicalized (sorted keys) and compared, with a
                        configurable set of volatile keys scrubbed.
  * .md/.html/.txt   -> compared byte-for-byte.
  * .png             -> compared byte-for-byte (the deterministic PngEncoder
                        yields identical bytes on JVM and native).
  * .pdf             -> compared by size + a structural text marker (PDFs embed
                        timestamps/ids, so exact bytes are not expected).

Exit code is non-zero if any mismatch is found.

Usage:
  scripts/parity_check.py --native ./opendataloader-pdf \
                          --jar path/to/opendataloader-pdf-cli.jar \
                          --samples samples/pdf [--formats json,markdown,html,text]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

# Keys whose values legitimately differ run-to-run (none known yet for the
# deterministic local pipeline, but kept configurable for safety).
VOLATILE_KEYS = set()

DEFAULT_FORMATS = ["json", "markdown", "html", "text", "pdf"]


def scrub(obj):
    """Recursively drop volatile keys so canonical comparison is stable."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def canonical_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(scrub(data), sort_keys=True, ensure_ascii=False, indent=0)


def run_cli(cmd_prefix, pdf: Path, out_dir: Path, fmt: str, image_output: str = "external"):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*cmd_prefix, str(pdf), "--output-dir", str(out_dir), "--format", fmt,
           "--image-output", image_output]
    # nosec B603 — this is a developer parity harness: argv is a fixed list (no
    # shell), the binary/jar come from trusted CLI args, and the only variable
    # inputs are local sample paths under our control. Not a command-injection sink.
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stderr or "")


def _pdf_structural_marker(path: Path) -> bytes:
    """Return a lightweight structural marker for a PDF, for parity checking.

    Avoids full PDF parsing: grabs a stable slice around common structural
    tokens (unaffected by timestamps/object ids alone), falling back to the
    header+trailer bytes. Lets the .pdf comparison detect structural drift even
    when two files happen to have similar sizes.
    """
    data = path.read_bytes()
    for marker in (b"/Type /Catalog", b"/Type /Page", b"/Outlines", b"/StructTreeRoot"):
        idx = data.find(marker)
        if idx != -1:
            return data[max(0, idx - 64):idx + 64]
    head = data[:128]
    tail = data[-128:] if len(data) > 128 else data
    return head + b"||" + tail


def compare_dir(jvm_dir: Path, nat_dir: Path, problems: list):
    jvm_files = {p.relative_to(jvm_dir) for p in jvm_dir.rglob("*") if p.is_file()}
    nat_files = {p.relative_to(nat_dir) for p in nat_dir.rglob("*") if p.is_file()}

    only_jvm = jvm_files - nat_files
    only_nat = nat_files - jvm_files
    for f in sorted(only_jvm):
        problems.append(f"MISSING in native: {f}")
    for f in sorted(only_nat):
        problems.append(f"EXTRA in native:   {f}")

    for rel in sorted(jvm_files & nat_files):
        a, b = jvm_dir / rel, nat_dir / rel
        suffix = rel.suffix.lower()
        if suffix == ".json":
            if canonical_json(a) != canonical_json(b):
                problems.append(f"JSON differs: {rel}")
        elif suffix == ".pdf":
            # PDFs embed timestamps/object ids; compare size within tolerance
            # plus a lightweight structural marker (so similar sizes don't mask
            # structural drift).
            sa, sb = a.stat().st_size, b.stat().st_size
            if abs(sa - sb) > max(64, sa * 0.02):
                problems.append(f"PDF size differs >2%: {rel} ({sa} vs {sb})")
            elif _pdf_structural_marker(a) != _pdf_structural_marker(b):
                problems.append(f"PDF structural marker differs: {rel}")
        else:
            if a.read_bytes() != b.read_bytes():
                problems.append(f"Bytes differ: {rel}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", required=True, help="Path to the native binary")
    ap.add_argument("--jar", required=True, help="Path to the CLI jar")
    ap.add_argument("--samples", required=True, help="Directory of sample PDFs")
    ap.add_argument("--formats", default=",".join(DEFAULT_FORMATS))
    ap.add_argument("--workdir", default="/tmp/odl-parity")
    ap.add_argument("--image-output", dest="image_output", default="external",
                    choices=["external", "embedded", "off"],
                    help="Image output mode for both sides; use 'off' on platforms "
                         "without a native AWT backend to compare text/data only.")
    args = ap.parse_args()

    native_cmd = [args.native]
    jvm_cmd = ["java", "-Djava.awt.headless=true", "-jar", args.jar]
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]

    samples = sorted(Path(args.samples).glob("*.pdf"))
    if not samples:
        print(f"No sample PDFs found in {args.samples}", file=sys.stderr)
        return 2

    work = Path(args.workdir)
    problems: list = []
    checked = 0

    for pdf in samples:
        for fmt in formats:
            tag = f"{pdf.stem}/{fmt}"
            jvm_dir = work / "jvm" / pdf.stem / fmt
            nat_dir = work / "native" / pdf.stem / fmt
            rc_jvm, _ = run_cli(jvm_cmd, pdf, jvm_dir, fmt, args.image_output)
            rc_nat, err_nat = run_cli(native_cmd, pdf, nat_dir, fmt, args.image_output)
            if rc_jvm != rc_nat:
                problems.append(f"Exit code differs ({tag}): jvm={rc_jvm} native={rc_nat}")
                # Surface the native error so CI logs explain the crash.
                tail = "\n      ".join(err_nat.strip().splitlines()[-12:])
                if tail:
                    problems.append(f"  native stderr ({tag}):\n      {tail}")
            compare_dir(jvm_dir, nat_dir, problems)
            checked += 1
            print(f"  checked {tag}: {'OK' if not problems else 'see report'}")

    print(f"\n{checked} (sample,format) combinations compared.")
    if problems:
        print(f"\nFAIL — {len(problems)} mismatch(es):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("PASS — native output matches the JVM jar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
