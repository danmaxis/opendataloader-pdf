"""Custom build hook for hatch to copy the native binary (or fallback JAR) and license files.

The JVM-free distribution ships a standalone GraalVM native binary inside
platform-specific wheels. When the environment variable ``ODL_NATIVE_BINARY``
points at a built binary, it is copied into ``src/opendataloader_pdf/bin/`` and
the wheel is self-contained (no Java required). Otherwise the build falls back
to bundling the JAR (used for the sdist and the legacy JVM path).
"""

import glob
import os
import shutil
import stat
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def _bundle_native_binary(self, pkg_dir: Path) -> bool:
        """Copy the native binary into the package when ODL_NATIVE_BINARY is set.

        Returns True when a binary was bundled.
        """
        src = os.environ.get("ODL_NATIVE_BINARY")
        if not src:
            return False
        src_path = Path(src)
        if not src_path.is_file():
            raise RuntimeError(f"ODL_NATIVE_BINARY is set but not a file: {src_path}")
        bin_dir = pkg_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        dest_name = "opendataloader-pdf.exe" if src_path.suffix == ".exe" else "opendataloader-pdf"
        dest = bin_dir / dest_name
        print(f"Bundling native binary {src_path} -> {dest}")
        shutil.copy(src_path, dest)
        # Ensure the executable bit survives into the wheel (POSIX).
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        # native-image ships headless-AWT sidecar libraries (libawt_*, libfontmanager,
        # libjavajpeg, liblcms, ...) next to the binary; the binary loads them via an
        # $ORIGIN rpath, so they must travel together in bin/.
        for lib in src_path.parent.glob("*.so"):
            shutil.copy(lib, bin_dir / lib.name)
        for lib in src_path.parent.glob("*.dll"):
            shutil.copy(lib, bin_dir / lib.name)
        for lib in src_path.parent.glob("*.dylib"):
            shutil.copy(lib, bin_dir / lib.name)
        return True

    def initialize(self, version, build_data):
        root_dir = Path(self.root)
        pkg_dir = root_dir / "src/opendataloader_pdf"
        # Native binary takes priority; when present the wheel is JVM-free.
        bundled_native = self._bundle_native_binary(pkg_dir)
        dest_jar_dir = pkg_dir / "jar"
        dest_jar_path = dest_jar_dir / "opendataloader-pdf-cli.jar"
        license_path = pkg_dir / "LICENSE"
        notice_path = pkg_dir / "NOTICE"
        third_party_dest = pkg_dir / "THIRD_PARTY"

        readme_path = root_dir / "README.md"

        if not bundled_native:
            # sdist-install code path: when users `pip install <sdist>.tar.gz`,
            # the extracted sdist already contains JAR/LICENSE/NOTICE/THIRD_PARTY
            # (force-included via [tool.hatch.build] artifacts in pyproject.toml),
            # and there is no java/ tree to rebuild from. Do not remove — sdist
            # installs would break with a spurious "mvn package" error.
            if (
                dest_jar_path.exists()
                and license_path.exists()
                and notice_path.exists()
                and third_party_dest.exists()
                and readme_path.exists()
            ):
                print("All required files already exist (building from sdist), skipping copy")
                return

            # --- Copy JAR (legacy JVM path / sdist fallback) ---
            print(f"Root DIR: {root_dir}")
            source_jar_glob = str(
                root_dir / "../../java/opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar"
            )
            resolved_glob_path = Path(source_jar_glob).resolve()
            print(f"Searching for JAR file in: {resolved_glob_path}")

            source_jar_paths = glob.glob(source_jar_glob)
            if not source_jar_paths:
                raise RuntimeError(
                    f"Could not find the JAR file. Please run 'mvn package' in the 'java/' directory first. Searched in: {resolved_glob_path}"
                )
            if len(source_jar_paths) > 1:
                raise RuntimeError(f"Found multiple JAR files, expected one: {source_jar_paths}")
            source_jar_path = source_jar_paths[0]
            print(f"Found source JAR: {source_jar_path}")

            dest_jar_dir.mkdir(parents=True, exist_ok=True)
            print(f"Copying JAR to {dest_jar_path}")
            shutil.copy(source_jar_path, dest_jar_path)
        else:
            print("Native binary bundled — JVM-free wheel, skipping JAR copy")

        # --- Copy LICENSE, NOTICE, THIRD_PARTY from the repo ---
        # README is copied by build-python.sh before this hook runs, because
        # hatchling validates [project.readme] during metadata parsing, which
        # happens before build hooks. Do not copy README here. Guard on the
        # source existing so an extracted sdist (no ../../) does not crash.
        license_src = root_dir / "../../LICENSE"
        if license_src.exists():
            shutil.copy(license_src, license_path)
            shutil.copy(root_dir / "../../NOTICE", notice_path)
            third_party_src = root_dir / "../../THIRD_PARTY"
            print(f"Copying THIRD_PARTY directory to {third_party_dest}")
            if third_party_dest.exists():
                shutil.rmtree(third_party_dest)
            shutil.copytree(third_party_src, third_party_dest)
