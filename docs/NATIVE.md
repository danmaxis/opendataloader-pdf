# JVM-free native build

This fork compiles the existing Java core into a **standalone native executable**
with [GraalVM native-image](https://www.graalvm.org/reference-manual/native-image/),
so it runs with **no Java runtime installed**. The primary motivation is running
the library inside a slim Python pod/container that has no Java layer.

Nothing about the parser was rewritten — the benchmark-leading veraPDF + WCAG
algorithms are compiled as-is, so output is identical to the JVM build (enforced
by the parity harness).

## What changed vs. upstream

| Area | Change |
|------|--------|
| `java/opendataloader-pdf-cli/pom.xml` | Added a `native` Maven profile using `native-maven-plugin`. |
| `…/META-INF/native-image/**` | Committed GraalVM reachability metadata + `native-image.properties` build args. |
| `utils/PngEncoder.java` | Dependency-free, deterministic PNG encoder (replaces `ImageIO` PNG *writes*) so image bytes are identical on JVM and native and the native build avoids the `ImageIO` writer `ServiceLoader`. JPEG and PNG *decoding* still use `ImageIO`. |
| Python/Node wrappers | Spawn the native binary by default; fall back to `java -jar` when no binary is bundled or `OPENDATALOADER_USE_JVM=1`. |
| `.github/workflows/native-build.yml` | Per-OS/arch native build matrix + parity gate + release assets. |

AWT is **not** removed — veraPDF's `ContrastRatioConsumer` renders pages to
`BufferedImage`. The binary ships headless AWT; on Linux it needs `fontconfig` +
a font at runtime (see the slim-pod image).

### Non-ASCII / accented paths

native-image freezes `sun.jnu.encoding` — the charset used to decode
command-line arguments and filesystem paths — at **build time** from the build
machine's locale, and never re-reads the runtime locale (unlike stock HotSpot).
A `C`/POSIX build locale (the CI/Docker default) would bake it to ASCII, so a
path like `Dimensões.pdf` fails with `File or folder ... not found` regardless of
the runtime `LANG`/`LC_ALL`. The build pins `-Dsun.jnu.encoding=UTF-8` (plus
`-Dfile.encoding=UTF-8` and `-H:+AddAllCharsets`) in `native-image.properties` so
UTF-8 argv/paths always work **on Linux and macOS**; the CI build locale is also
set to `C.UTF-8` as a backstop. The `native-build.yml` smoke test converts an
accented filename to guard against regressions. **Windows is the exception** — its
`argv` arrives through the ANSI code page, so non-ASCII input paths are not
supported there (details under *Platform status → Non-ASCII paths on Windows*).

## Building locally

Requires a **GraalVM JDK 21** and ~6–8 GB free RAM for the build (native-image's
whole-program (closed-world) static analysis over veraPDF + PDFBox is
memory-hungry; the final image-write phase
peaks around 4 GB).

```bash
# 1. build the shaded jar (embeds the reachability metadata)
mvn -f java/pom.xml -DskipTests package

# 2. (re)generate reachability metadata if you changed code paths
build-scripts/native/trace-metadata.sh

# 3. build the native image
mvn -f java/pom.xml -Pnative -pl opendataloader-pdf-cli -am -DskipTests package
# -> java/opendataloader-pdf-cli/target/opendataloader-pdf
```

On a RAM-constrained machine, build in a memory-capped container instead (the
official image bundles native-image):

```bash
JAR=java/opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar
docker run --rm -v "$PWD/$JAR":/app.jar:ro -v "$PWD/out":/out \
  ghcr.io/graalvm/native-image-community:21 \
  -jar /app.jar -o /out/opendataloader-pdf -Ob --parallelism=2
```

CI (`native-build.yml`) builds all platforms on GitHub runners (16 GB) and is the
recommended path for release binaries.

## Verifying parity

```bash
python3 scripts/parity_check.py \
  --native java/opendataloader-pdf-cli/target/opendataloader-pdf \
  --jar    java/opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar \
  --samples samples/pdf
```

## Slim Python pod proof (no Java in the image)

```bash
docker build -f build-scripts/native/Dockerfile.slim-pod \
  --build-arg NATIVE_BINARY=java/opendataloader-pdf-cli/target/opendataloader-pdf \
  -t odl-slim-pod .
docker run --rm -v "$PWD/samples:/samples" odl-slim-pod \
  /samples/pdf/lorem.pdf --output-dir /tmp/out --format json,markdown
```

The image build asserts there is no `java` on `PATH`.

## Install via requirements.txt (no Java, no git)

The CI `linux-wheels` job builds JVM-free wheels for linux **x86_64** and **arm64**
and attaches them to a moving [`latest`](https://github.com/danmaxis/opendataloader-pdf/releases/tag/latest)
GitHub Release. The wheel bundles the native binary + its headless-AWT `.so`
sidecars, so a slim Python pod needs **no Java and no `git`** — just `pip`.

Add these lines to `requirements.txt` (pip auto-selects the right arch via the
environment markers; the `manylinux_2_XX` number is whatever glibc floor the
build runner reports — read it off the published asset names):

```text
# linux only — JVM-free native wheels from the fork's `latest` release
opendataloader-pdf @ https://github.com/danmaxis/opendataloader-pdf/releases/download/latest/opendataloader_pdf-0.1.0-py3-none-manylinux_2_34_x86_64.whl ; sys_platform == "linux" and platform_machine == "x86_64"
opendataloader-pdf @ https://github.com/danmaxis/opendataloader-pdf/releases/download/latest/opendataloader_pdf-0.1.0-py3-none-manylinux_2_34_aarch64.whl ; sys_platform == "linux" and platform_machine == "aarch64"
```

```bash
pip install --no-cache-dir -r requirements.txt
```

`latest` is a **moving tag at a fixed version (`0.1.0`)**, so pip may serve a
cached copy of the wheel; use `--no-cache-dir` (or bump the version) when a
refreshed `latest` must be picked up. Pin to an immutable `v*` release tag
instead if you need byte-for-byte reproducibility.

## Packaging

* **Python**: platform wheels embed the matching binary under
  `opendataloader_pdf/bin/`. Set `ODL_NATIVE_BINARY=/path/to/binary` before
  `hatch build` to produce a JVM-free wheel; without it the build falls back to
  bundling the jar.
* **Node**: per-platform optional-dependency packages
  (`@opendataloader/pdf-<os>-<arch>`) each ship one binary; the main package
  resolves the right one at runtime. Set `ODL_NATIVE_BINARY` for `setup.cjs` to
  bundle a binary under `lib/bin/`.

Set `OPENDATALOADER_USE_JVM=1` to force the legacy `java -jar` path.

## Platform status

| Target | Status |
|--------|--------|
| linux-x64 | ✅ Full parity with the JVM jar — **all** formats (JSON/Markdown/HTML/text/annotated-PDF/tagged-PDF) + image extraction. Validated incl. a JVM-free `python:3.12-slim` wheel. |
| linux-arm64 | ✅ Builds successfully. |
| win-x64 | ✅ **JSON / Markdown / text** fully supported. AWT-dependent outputs (HTML, annotated PDF, tagged PDF, image extraction) are **gracefully skipped** — see below. **Non-ASCII input paths are not supported** — see below. |
| darwin-arm64 / darwin-x64 | ✅ Same as Windows, **but non-ASCII paths work** (only Windows is affected). |

**AWT on Windows/macOS.** Several outputs touch AWT: image extraction and
hidden-text rasterize pages (veraPDF `ContrastRatioConsumer` → `BufferedImage`),
HTML color-manages text colors (`java.awt.Color`), and the annotated/tagged PDF
writers go through PDFBox. native-image's AWT backend is solid on Linux but
incomplete on Windows/macOS — the first AWT call throws
`NoSuchMethodError: java.awt.Toolkit.getDefaultToolkit()`. Rather than crash, the
binary **catches this per output format, logs one warning, and skips that format**
(image extraction + hidden-text too), while the AWT-free formats
(**JSON / Markdown / text**, with tables, lists and reading order) complete
normally (exit 0). **Linux is full-featured.** Restoring HTML/PDF/images on
Windows/macOS needs a non-AWT raster/color path or improved GraalVM AWT support.

**Non-ASCII paths on Windows.** The `-Dsun.jnu.encoding=UTF-8` pin (see above)
fixes accented/non-ASCII input paths on **Linux and macOS**, but **not on
Windows**: a Windows native image receives its command-line `argv` through the
system **ANSI code page** rather than UTF-16, so the UTF-8 path bytes are already
replaced with `?`/`�` before the JVM decodes them — the build-time pin cannot
recover what the OS layer dropped. A path like `Dimensões.pdf` therefore still
fails with `File or folder ... not found` on the Windows binary. This is a known
GraalVM native-image limitation (it would need a `wmain`/UTF-16 argv entry point);
the CI accented-path smoke test is scoped to Linux/macOS for this reason. The
JVM-free **linux wheels are unaffected** — they are the primary distribution and
handle non-ASCII paths correctly.
