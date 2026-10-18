const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const markdownit = require('../src/company/web/markdown-it.min.js');
const source = fs.readFileSync(path.join(__dirname, '../src/company/web/markdown.js'), 'utf8');

function renderer(parser = markdownit) {
  const context = vm.createContext({markdownit:parser, URL, location:{href:'http://127.0.0.1:8765/'}});
  vm.runInContext(source, context);
  return context.renderMarkdown;
}

test('renders headings, nested lists, emphasis, quotes, and literal fenced code', () => {
  const html = renderer()('## Result\n\n**Passed** and *reviewed* with `commit()`.\n\n1. Check\n   - Nested\n\n> Verified\n\n```python\nprint("<script>not HTML</script>")\n```');
  for (const fragment of ['<h2>Result</h2>', '<strong>Passed</strong>', '<em>reviewed</em>',
    '<code>commit()</code>', '<ol>', '<ul>', '<blockquote>', '<pre><code class="language-python">']) {
    assert.ok(html.includes(fragment), fragment);
  }
  assert.ok(html.includes('&lt;script&gt;not HTML&lt;/script&gt;'));
  assert.ok(!html.includes('<script>'));
});

test('renders wide tables with CSP-compatible alignment classes', () => {
  const html = renderer()('| Name | Result |\n| :--- | ---: |\n| commit | pass |');
  assert.ok(html.includes('class="markdown-table"'));
  assert.ok(html.includes('<th class="align-right">Result</th>'));
  assert.ok(html.includes('<td class="align-right">pass</td>'));
  assert.ok(!html.includes('style='));
});

test('escapes raw HTML and prevents script, data, and local file links', () => {
  const render = renderer();
  for (const source of ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>', '<iframe src="https://example.com"></iframe>']) {
    const html = render(source);
    assert.ok(!/<(?:script|img|svg|iframe)\b/i.test(html));
    assert.ok(html.includes('&lt;'));
  }
  for (const href of ['javascript:alert(1)', 'java&#x73;cript:alert(1)', 'vbscript:run',
    'data:text/html,test', 'file:///etc/passwd', 'custom:command']) {
    assert.ok(!renderer()(`[unsafe](${href})`).includes('<a '), href);
  }
});

test('keeps useful links and never loads model-supplied images', () => {
  const render = renderer();
  for (const href of ['https://example.com/docs', 'http://example.com', 'mailto:user@example.com', '/notes']) {
    const html = render(`[source](${href})`);
    assert.ok(html.includes('<a '), href);
    assert.ok(html.includes('target="_blank"'));
    assert.ok(html.includes('rel="noopener noreferrer"'));
  }
  const image = render('![Review diagram](https://example.com/pixel.png)');
  assert.ok(image.includes('Review diagram'));
  assert.ok(!image.includes('<img') && !image.includes('src='));
});

test('falls back to escaped readable output when the parser is missing or fails', () => {
  const failingParser = () => {
    const md = markdownit();
    md.render = () => {throw new Error('unexpected');};
    return md;
  };
  for (const render of [renderer(null), renderer(failingParser)]) {
    assert.equal(render('<img>\n**Answer**'), '<div class="markdown-fallback">&lt;img&gt;\n**Answer**</div>');
  }
});
