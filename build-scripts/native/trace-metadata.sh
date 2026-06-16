#!/usr/bin/env bash
#
# Copyright 2025-2026 Hancom Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Generates GraalVM native-image reachability metadata by running the CLI jar
# under the native-image tracing agent across a representative matrix of sample
# PDFs, output formats and flags. The merged config is written into the CLI
# module resources so the `-Pnative` build picks it up automatically.
#
# Usage:  build-scripts/native/trace-metadata.sh [path-to-cli-jar]
#
# Requires a GraalVM JDK on PATH (java with the native-image-agent shipped).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JAR="${1:-$(ls "$REPO_ROOT"/java/opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar 2>/dev/null | grep -v original | head -1)}"
SAMPLES="$REPO_ROOT/samples/pdf"
META_DIR="$REPO_ROOT/java/opendataloader-pdf-cli/src/main/resources/META-INF/native-image/org.opendataloader/opendataloader-pdf-cli"
WORK="$(mktemp -d)"

if [[ -z "$JAR" || ! -f "$JAR" ]]; then
  echo "CLI jar not found. Build it first: (cd java && mvn -DskipTests package)" >&2
  exit 1
fi

mkdir -p "$META_DIR"
echo "Jar:       $JAR"
echo "Metadata:  $META_DIR"
echo "Scratch:   $WORK"

run() {
  # run <label> <args...>
  local label="$1"; shift
  echo "  trace: $label"
  java -agentlib:native-image-agent="config-merge-dir=$META_DIR" \
       -Djava.awt.headless=true -Dfile.encoding=UTF-8 \
       -jar "$JAR" "$@" >/dev/null 2>&1 || echo "    (non-zero exit for '$label' — still traced)"
}

# --- no-input paths (help / option export) ---
run "help"            --help
run "export-options"  --export-options

# --- every output format on a tagged + an untagged document ---
for pdf in lorem.pdf 2408.02509v1.pdf; do
  base="$SAMPLES/$pdf"; out="$WORK/${pdf%.pdf}"
  run "$pdf:json"             "$base" -o "$out-json"     --format json
  run "$pdf:markdown"         "$base" -o "$out-md"       --format markdown
  run "$pdf:markdown+html"    "$base" -o "$out-mdh"      --format markdown --markdown-with-html
  run "$pdf:html"             "$base" -o "$out-html"     --format html
  run "$pdf:text"             "$base" -o "$out-text"     --format text
  run "$pdf:pdf"              "$base" -o "$out-pdf"      --format pdf
  run "$pdf:tagged-pdf"       "$base" -o "$out-tagged"   --format tagged-pdf
done

# --- image output: external + embedded, png + jpeg (jpeg pulls the ImageIO JPEG writer) ---
img="$SAMPLES/1901.03003.pdf"
run "img:external-png"  "$img" -o "$WORK/img-ext-png"  --format markdown --image-output external --image-format png
run "img:external-jpeg" "$img" -o "$WORK/img-ext-jpg"  --format markdown --image-output external --image-format jpeg
run "img:embedded-png"  "$img" -o "$WORK/img-emb-png"  --format markdown --image-output embedded --image-format png
run "scan:image"        "$SAMPLES/chinese_scan.pdf" -o "$WORK/scan" --format markdown --image-output external

# --- feature flags (each once is enough to reach the code) ---
fin="$SAMPLES/issue-336-conto-economico-bialetti.pdf"
run "sanitize"          "$fin" -o "$WORK/san"     --format json --sanitize
run "struct-tree"       lorem.pdf "$SAMPLES/lorem.pdf" -o "$WORK/st" --format json --use-struct-tree || true
run "use-struct-tree"   "$SAMPLES/lorem.pdf" -o "$WORK/st2"  --format json --use-struct-tree
run "strikethrough"     "$fin" -o "$WORK/strike"  --format markdown --detect-strikethrough
run "header-footer"     "$fin" -o "$WORK/hf"      --format json --include-header-footer
run "keep-breaks"       "$fin" -o "$WORK/kb"      --format markdown --keep-line-breaks
run "table-cluster"     "$fin" -o "$WORK/tc"      --format json --table-method cluster
run "pages-threads"     "$img" -o "$WORK/pt"      --format json --pages 1-2 --threads 4

# --- whole PDF/UA reference suite (exercises tagged-PDF reading paths) ---
if [[ -d "$SAMPLES/pdfua-1-reference-suite-1-1" ]]; then
  run "pdfua-suite" "$SAMPLES/pdfua-1-reference-suite-1-1" -o "$WORK/ua" --format json,tagged-pdf
fi

# --- hybrid mode: unreachable backend with fallback, to trace OkHttp + TLS init ---
run "hybrid-fallback" "$SAMPLES/2408.02509v1.pdf" -o "$WORK/hy" \
    --format json --hybrid hancom-ai --hybrid-url http://127.0.0.1:1 --hybrid-fallback

echo
echo "Done. Generated config files:"
ls -la "$META_DIR"
rm -rf "$WORK"
