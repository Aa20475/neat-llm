"use strict";

// Markdown is untrusted model output. Raw HTML stays disabled and images never
// trigger requests. No plugins or syntax highlighter may inject arbitrary HTML.
(() => {
  const escape = text => text.replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const md = typeof markdownit === "function" ? markdownit({html:false, breaks:true, linkify:true}) : null;
  if (md) {
    const validateLink = md.validateLink.bind(md);
    md.validateLink = href => {
      if (!validateLink(href)) return false;
      try {return ["http:", "https:", "mailto:"].includes(new URL(href, location.href).protocol);}
      catch {return false;}
    };
    md.renderer.rules.link_open = (tokens, index, options, env, self) => {
      tokens[index].attrSet("target", "_blank");
      tokens[index].attrSet("rel", "noopener noreferrer");
      return self.renderToken(tokens, index, options);
    };
    md.renderer.rules.image = (tokens, index) => `<span class="markdown-image">${escape(tokens[index].content || "Image")}</span>`;
    md.renderer.rules.table_open = () => '<div class="markdown-table" tabindex="0" role="region" aria-label="Table"><table>\n';
    md.renderer.rules.table_close = () => '</table></div>\n';
    // Keep table alignment compatible with the viewer's no-inline-style CSP.
    for (const type of ["th_open", "td_open"]) {
      md.renderer.rules[type] = (tokens, index, options, env, self) => {
        const token = tokens[index], style = token.attrGet("style");
        const alignment = /^text-align:(left|center|right)$/.exec(style || "");
        if (style !== null) token.attrs.splice(token.attrIndex("style"), 1);
        if (alignment) token.attrSet("class", `align-${alignment[1]}`);
        return self.renderToken(tokens, index, options);
      };
    }
  }
  globalThis.renderMarkdown = value => {
    const text = String(value ?? "");
    try {if (md) return md.render(text);}
    catch { /* Keep the response readable even if parsing fails. */ }
    return `<div class="markdown-fallback">${escape(text)}</div>`;
  };
})();
