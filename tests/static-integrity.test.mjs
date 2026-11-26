import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = ['test', 'tests'].includes(path.basename(here)) ? path.resolve(here, '..') : here;
const read = (rel) => readFileSync(path.join(root, rel), 'utf8');

function printBlocks(css) {
  const blocks = [];
  const re = /@media\s+(?:only\s+)?print\b[^{]*\{/gi;
  for (const match of css.matchAll(re)) {
    const start = match.index + match[0].length;
    let depth = 1;
    let end = start;
    while (end < css.length && depth > 0) {
      if (css[end] === '{') depth += 1;
      if (css[end] === '}') depth -= 1;
      end += 1;
    }
    blocks.push(css.slice(start, end - 1));
  }
  return blocks.join('\n');
}

test('static accessibility and print integrity', () => {
  const sources = [
  "dashboard.html",
  "docs/index.html",
  "dashboard.py"
  ].map(read);
  const printCss = printBlocks(sources.join('\n'));
  assert.notEqual(printCss, '', 'an @media print block is present');
  assert.match(printCss, /@page/, 'print block defines page margins');
  assert.match(printCss, /background:\s*(?:#fff|#ffffff|white)\b/, 'print resets ink-heavy surfaces to white paper');
  assert.match(printCss, /color:\s*(?:#111|#111111|black)\b/, 'print resets text to dark ink');
  assert.match(printCss, /button[\s\S]*display:\s*none !important/, 'print hides interactive buttons');
  assert.match(printCss, /max-height:\s*none !important/, 'print keeps scrollable content unclipped');
  assert.match(printCss, /overflow:\s*visible !important/, 'print makes clipped overflow visible');
  assert.match(read('dashboard.py'), /@media print/, 'the dashboard generator keeps the print rules');
});
