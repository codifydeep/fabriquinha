// Build-stage only. Export Node and its C++ runtime, not a second system root.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const destination = '/quality-node-runtime';
function copy(source, target) {
  fs.mkdirSync(path.dirname(destination + target), { recursive: true });
  fs.copyFileSync(source, destination + target);
}
copy('/usr/local/bin/node', '/usr/local/bin/node');
copy('/usr/local/LICENSE', '/usr/local/share/licenses/quality-node/LICENSE');
const packages = new Map([
  ['libstdc++.so.6', 'libstdc++6'],
  ['libgcc_s.so.1', 'libgcc-s1'],
  ['libatomic.so.1', 'libatomic1']
]);
const copied = [];
const linked = execFileSync('/usr/bin/ldd', ['/usr/local/bin/node'],
  { encoding: 'utf8', timeout: 10000, maxBuffer: 65536 });
for (const line of linked.split('\n')) {
  const match = /^\s*(\S+) => (\/\S+) /.exec(line);
  if (!match || !packages.has(match[1])) continue;
  const source = match[2];
  if (!source.startsWith('/lib/') && !source.startsWith('/usr/lib/')) throw Error('unexpected runtime path');
  if (source.split('/').some(part => part === '..') || path.basename(source) !== match[1]) throw Error('runtime path mismatch');
  // Debian's /lib is a symlink to /usr/lib. Export the canonical destination
  // so Docker COPY merges directories instead of replacing that base symlink.
  copy(source, source.startsWith('/lib/') ? '/usr' + source : source);
  const pkg = packages.get(match[1]);
  copy('/usr/share/doc/' + pkg + '/copyright',
    '/usr/local/share/licenses/quality-node/' + pkg + '.copyright');
  copied.push(match[1]);
}
if (!copied.includes('libstdc++.so.6')) throw Error('C++ dependency not observed');
console.log(JSON.stringify({ node: process.versions.node, libraries: copied.sort() }));
