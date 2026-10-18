# Bundled browser dependencies

The viewer serves its scripts locally; it does not load dependencies from a CDN.

## markdown-it 15.0.3

- Upstream: https://github.com/markdown-it/markdown-it
- Published archive: https://registry.npmjs.org/markdown-it/-/markdown-it-15.0.3.tgz
- Archive integrity (SHA-512, base64): `+Az7Ojz3iRGu8KYMvJ6xVhvrxP3eE+vEtJX75Ow88XBpcQNV/0lGX5ZynIIBftREo4DC2jsveAMDaeltmm8QvQ==`
- `package/dist/browser/markdown-it.umd.min.js` is copied unchanged to `src/company/web/markdown-it.min.js`. Source maps are not bundled.
- MIT license: [markdown-it.LICENSE](../src/company/web/markdown-it.LICENSE), included in Python package data.

The wrapper in `src/company/web/markdown.js` disables raw HTML, permits only
HTTP(S), mail, and relative links, adds `noopener noreferrer` to links, and
renders image descriptions without loading images. Tables use CSS classes
instead of inline styles to preserve the viewer's Content Security Policy.

Run the formatting and untrusted-content regression checks with
`node --test tests/test_markdown.cjs`.
