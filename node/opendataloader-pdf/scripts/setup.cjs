const fs = require('fs');
const path = require('path');
const { globSync } = require('glob');

const rootDir = path.resolve(__dirname, '..');
const javaDir = path.resolve(rootDir, '../../java');

const libDir = path.join(rootDir, 'lib').replace(/\\/g, '/');
if (!fs.existsSync(libDir)) {
  fs.mkdirSync(libDir, { recursive: true });
}

// JVM-free path: when ODL_NATIVE_BINARY points at a built GraalVM binary, bundle
// it under lib/bin/ so the package runs without Java. Otherwise fall back to the
// JVM jar (legacy path / source checkout).
const nativeBinary = process.env.ODL_NATIVE_BINARY;
if (nativeBinary) {
  if (!fs.existsSync(nativeBinary)) {
    console.error(`ODL_NATIVE_BINARY is set but not found: ${nativeBinary}`);
    process.exit(1);
  }
  const binDir = path.join(libDir, 'bin');
  if (!fs.existsSync(binDir)) {
    fs.mkdirSync(binDir, { recursive: true });
  }
  const destName = nativeBinary.endsWith('.exe') ? 'opendataloader-pdf.exe' : 'opendataloader-pdf';
  const destBin = path.join(binDir, destName).replace(/\\/g, '/');
  console.log(`Bundling native binary ${nativeBinary} -> ${destBin}`);
  fs.copyFileSync(nativeBinary, destBin);
  if (!destName.endsWith('.exe')) {
    fs.chmodSync(destBin, 0o755);
  }
  // native-image ships headless-AWT sidecar libraries next to the binary
  // (libawt_*, libfontmanager, libjavajpeg, liblcms, ...); the binary loads
  // them via an $ORIGIN rpath, so they must travel together in lib/bin/.
  const srcDir = path.dirname(nativeBinary);
  for (const f of fs.readdirSync(srcDir)) {
    if (f.endsWith('.so') || f.endsWith('.dll') || f.endsWith('.dylib')) {
      fs.copyFileSync(path.join(srcDir, f), path.join(binDir, f));
    }
  }
} else {
  const sourceJarGlob = path
    .join(javaDir, 'opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar')
    .replace(/\\/g, '/');

  console.log(`Searching for JAR file in: ${sourceJarGlob}`);

  const sourceJarPaths = globSync(sourceJarGlob);
  if (sourceJarPaths.length === 0) {
    console.error(
      "Could not find the JAR file. Please run 'mvn package' in the 'java/' directory first.",
    );
    process.exit(1);
  }
  if (sourceJarPaths.length > 1) {
    console.error(`Found multiple JAR files, expected one: ${sourceJarPaths}`);
    process.exit(1);
  }

  const sourceJarPath = sourceJarPaths[0];
  console.log(`Found source JAR: ${sourceJarPath}`);

  const destJarPath = path.join(libDir, 'opendataloader-pdf-cli.jar').replace(/\\/g, '/');
  console.log(`Copying JAR to ${destJarPath}`);
  fs.copyFileSync(sourceJarPath, destJarPath);
}

// Copy README.md, LICENSE, NOTICE, and THIRD_PARTY
const readmeSrc = path.resolve(rootDir, '../../README.md');
const licenseSrc = path.resolve(rootDir, '../../LICENSE');
const noticeSrc = path.resolve(rootDir, '../../NOTICE');
const thirdPartySrc = path.resolve(rootDir, '../../THIRD_PARTY');

const readmeDest = path.join(rootDir, 'README.md').replace(/\\/g, '/');
const licenseDest = path.join(rootDir, 'LICENSE').replace(/\\/g, '/');
const noticeDest = path.join(rootDir, 'NOTICE').replace(/\\/g, '/');
const thirdPartyDest = path.join(rootDir, 'THIRD_PARTY').replace(/\\/g, '/');

console.log(`Copying README.md to ${readmeDest}`);
fs.copyFileSync(readmeSrc, readmeDest);

console.log(`Copying LICENSE to ${licenseDest}`);
fs.copyFileSync(licenseSrc, licenseDest);

console.log(`Copying NOTICE to ${noticeDest}`);
fs.copyFileSync(noticeSrc, noticeDest);

console.log(`Copying THIRD_PARTY directory to ${thirdPartyDest}`);
if (fs.existsSync(thirdPartyDest)) {
  fs.rmSync(thirdPartyDest, { recursive: true, force: true });
}
fs.cpSync(thirdPartySrc, thirdPartyDest, { recursive: true });

console.log('Package preparation complete.');
