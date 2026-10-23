// Fixed full-suite reporter, outside the product snapshot and not agent-editable.
// Test stdout/diagnostics are hashed, never forwarded as protocol records.
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

export default async function* reporter(source) {
  const files = new Set();
  const counts = Object.create(null);
  const duplicates = new Set();
  const output = createHash('sha256');
  let bytes = 0;
  for await (const event of source) {
    const data = event.data || {};
    if (typeof data.file === 'string' &&
        ['test:enqueue', 'test:dequeue', 'test:pass', 'test:fail'].includes(event.type)) {
      files.add(resolve(data.file));
    }
    if (typeof data.message === 'string') {
      output.update(data.message);
      bytes += Buffer.byteLength(data.message);
      if (event.type === 'test:diagnostic' && data.nesting === 0) {
        const match = /^(tests|pass|fail|cancelled|skipped|todo) ([0-9]+)$/.exec(data.message);
        if (match) {
          if (Object.hasOwn(counts, match[1])) duplicates.add(match[1]);
          counts[match[1]] = Number(match[2]);
        }
      }
    }
  }
  yield JSON.stringify({ operation: 'frozen_node_suite_report_v1',
    node_version: process.versions.node, files: [...files].sort(), counts,
    duplicate_summary_fields: [...duplicates].sort(),
    captured_output_sha256: output.digest('hex'), captured_output_bytes: bytes }) + '\n';
}
