#!/usr/bin/env node
/*
 * Generates a per-platform npm package that ships a single native binary
 * (plus its sidecar shared libraries). The main @opendataloader/pdf package
 * lists these as optionalDependencies with matching `os`/`cpu`, so npm installs
 * only the one matching the host — the esbuild/swc distribution pattern.
 *
 * Usage:
 *   node scripts/build-platform-package.cjs \
 *     --target linux-x64 \
 *     --binary-dir path/to/graalvm/output \   # contains opendataloader-pdf + *.so
 *     --version 2.4.7 \
 *     --out dist-platform
 */
const fs = require('fs');
const path = require('path');

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
}

const target = arg('target'); // e.g. linux-x64, darwin-arm64, win32-x64
const binaryDir = arg('binary-dir');
const version = arg('version', '0.0.0');
const outRoot = arg('out', 'dist-platform');

if (!target || !binaryDir) {
  console.error('Required: --target <os-arch> --binary-dir <dir>');
  process.exit(1);
}

const [os, cpu] = target.split('-');
const isWin = os === 'win32' || os === 'win';
const exe = isWin ? 'opendataloader-pdf.exe' : 'opendataloader-pdf';
const npmOs = os === 'win' ? 'win32' : os;

const pkgName = `@opendataloader/pdf-${npmOs}-${cpu}`;
const pkgDir = path.join(outRoot, `${npmOs}-${cpu}`);
const binDir = path.join(pkgDir, 'bin');
fs.mkdirSync(binDir, { recursive: true });

// Copy the binary and every sidecar shared library next to it.
fs.copyFileSync(path.join(binaryDir, exe), path.join(binDir, exe));
if (!isWin) fs.chmodSync(path.join(binDir, exe), 0o755);
for (const f of fs.readdirSync(binaryDir)) {
  if (/\.(so|dll|dylib)$/.test(f)) {
    fs.copyFileSync(path.join(binaryDir, f), path.join(binDir, f));
  }
}

const pkgJson = {
  name: pkgName,
  version,
  description: `opendataloader-pdf native binary for ${npmOs}/${cpu}`,
  license: 'Apache-2.0',
  os: [npmOs],
  cpu: [cpu],
  files: ['bin'],
};
fs.writeFileSync(path.join(pkgDir, 'package.json'), JSON.stringify(pkgJson, null, 2) + '\n');
for (const f of ['LICENSE', 'NOTICE']) {
  const src = path.resolve(__dirname, '../../../', f);
  if (fs.existsSync(src)) fs.copyFileSync(src, path.join(pkgDir, f));
}

console.log(`Created ${pkgName} -> ${pkgDir}`);
