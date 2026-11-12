// 校验 mermaid 源码（flowchart / stateDiagram 等），用法: node check.mjs <file.mmd>...
import { JSDOM } from 'jsdom';
import { readFileSync } from 'node:fs';

const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
try { globalThis.navigator = dom.window.navigator; }
catch (e) { Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true }); }
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.Element = dom.window.Element;
globalThis.Node = dom.window.Node;
globalThis.getComputedStyle = dom.window.getComputedStyle;

const mermaid = (await import('mermaid')).default;
mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });

let failed = false;
for (const f of process.argv.slice(2)) {
  const src = readFileSync(f, 'utf8');
  try {
    await mermaid.parse(src, { suppressErrors: false });
    console.log('OK  : ' + f);
  } catch (e) {
    failed = true;
    console.log('FAIL: ' + f);
    console.log(String(e.message || e).split('\n').slice(0, 6).join('\n'));
  }
}
process.exit(failed ? 1 : 0);
