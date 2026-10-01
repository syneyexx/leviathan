/**
 * Safe markdown renderer — no raw HTML, blocks javascript:/data: URLs,
 * supports headings, lists, tables, code fences (with copy), inline code,
 * bold/italic/links, blockquotes, hr.
 */

import {
  createElement,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const DANGEROUS_SCHEME = /^(javascript|data|vbscript|file):/i;

export function isSafeHref(href: string): boolean {
  const trimmed = href.trim();
  if (!trimmed) return false;
  if (DANGEROUS_SCHEME.test(trimmed)) return false;
  // Allow relative, hash, http(s), mailto
  if (/^(https?:|mailto:|#|\/|\.\/|\.\.\/)/i.test(trimmed)) return true;
  // Plain paths without scheme
  if (!/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) return true;
  return false;
}

/** Returns sanitized href or null when blocked. */
export function sanitizeHref(href: string): string | null {
  return isSafeHref(href) ? href.trim() : null;
}

export type MdBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: 1 | 2 | 3 | 4; text: string }
  | { type: "code"; lang: string; code: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "blockquote"; text: string }
  | { type: "hr" }
  | { type: "table"; headers: string[]; rows: string[][] };

/** Parse a markdown string into safe block structures (no HTML). */
export function parseSafeMarkdown(source: string): MdBlock[] {
  const lines = source.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const blocks: MdBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      const lang = fence[1] || "";
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence
      blocks.push({ type: "code", lang, code: body.join("\n") });
      continue;
    }

    // HR
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    // Heading
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      blocks.push({
        type: "heading",
        level: Math.min(4, heading[1].length) as 1 | 2 | 3 | 4,
        text: heading[2].trim(),
      });
      i += 1;
      continue;
    }

    // Table (simple GFM): header | --- | rows
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      /^\s*\|?[\s-:|]+\|?\s*$/.test(lines[i + 1]) &&
      lines[i + 1].includes("-")
    ) {
      const headers = splitTableRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(splitTableRow(lines[i]));
        i += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      const parts: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        parts.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      blocks.push({ type: "blockquote", text: parts.join("\n") });
      continue;
    }

    // Blank
    if (!line.trim()) {
      i += 1;
      continue;
    }

    // Paragraph — gather until blank / structural
    const parts: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^```/.test(lines[i]) &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i]) &&
      !/^(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i])
    ) {
      // Don't swallow table starts mid-paragraph
      if (
        lines[i].includes("|") &&
        i + 1 < lines.length &&
        /^\s*\|?[\s-:|]+\|?\s*$/.test(lines[i + 1])
      ) {
        break;
      }
      parts.push(lines[i]);
      i += 1;
    }
    blocks.push({ type: "paragraph", text: parts.join("\n") });
  }

  return blocks;
}

function splitTableRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

/** Render inline markdown: `code`, **bold**, *italic*, [links](url). Escapes HTML text nodes via React. */
export function renderInlineMarkdown(text: string, keyPrefix = "i"): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Tokenize: code | link | bold | italic | plain
  const re =
    /(`[^`]+`)|(\[[^\]]+\]\([^)]+\))|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*]+\*)|(_[^_]+_)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let k = 0;
  while ((match = re.exec(text)) != null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(
        createElement("code", { key: `${keyPrefix}-c-${k++}` }, token.slice(1, -1)),
      );
    } else if (token.startsWith("[")) {
      const m = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (m && isSafeHref(m[2])) {
        nodes.push(
          createElement(
            "a",
            {
              key: `${keyPrefix}-a-${k++}`,
              href: m[2],
              target: "_blank",
              rel: "noopener noreferrer",
            },
            m[1],
          ),
        );
      } else {
        nodes.push(m ? m[1] : token);
      }
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(
        createElement("strong", { key: `${keyPrefix}-b-${k++}` }, token.slice(2, -2)),
      );
    } else {
      nodes.push(
        createElement("em", { key: `${keyPrefix}-e-${k++}` }, token.slice(1, -1)),
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.length ? nodes : [text];
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore clipboard failures */
    }
  }, [code]);

  return (
    <div className="lv-v2-md-code">
      <div className="lv-v2-md-code__bar">
        <span className="lv-v2-md-code__lang">{lang || "code"}</span>
        <button type="button" className="lv-v2-md-code__copy" onClick={() => void onCopy()}>
          {copied ? "Gekopieerd" : "Kopiëren"}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export type SafeMarkdownProps = {
  content: string;
  className?: string;
};

export function SafeMarkdown({ content, className }: SafeMarkdownProps) {
  const blocks = useMemo(() => parseSafeMarkdown(content || ""), [content]);

  return (
    <div className={className ? `lv-v2-md ${className}` : "lv-v2-md"}>
      {blocks.map((block, index) => {
        const key = `b-${index}`;
        switch (block.type) {
          case "heading":
            return createElement(
              `h${block.level}`,
              { key, className: "lv-v2-md__heading" },
              renderInlineMarkdown(block.text, key),
            );
          case "code":
            return <CodeBlock key={key} lang={block.lang} code={block.code} />;
          case "ul":
            return (
              <ul key={key} className="lv-v2-md__list">
                {block.items.map((item, j) => (
                  <li key={`${key}-${j}`}>{renderInlineMarkdown(item, `${key}-${j}`)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={key} className="lv-v2-md__list">
                {block.items.map((item, j) => (
                  <li key={`${key}-${j}`}>{renderInlineMarkdown(item, `${key}-${j}`)}</li>
                ))}
              </ol>
            );
          case "blockquote":
            return (
              <blockquote key={key} className="lv-v2-md__quote">
                {renderInlineMarkdown(block.text, key)}
              </blockquote>
            );
          case "hr":
            return <hr key={key} className="lv-v2-md__hr" />;
          case "table":
            return (
              <div key={key} className="lv-v2-md__table-wrap">
                <table className="lv-v2-md__table">
                  <thead>
                    <tr>
                      {block.headers.map((h, j) => (
                        <th key={`${key}-h-${j}`}>{renderInlineMarkdown(h, `${key}-h-${j}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={`${key}-r-${r}`}>
                        {row.map((cell, c) => (
                          <td key={`${key}-r-${r}-c-${c}`}>
                            {renderInlineMarkdown(cell, `${key}-r-${r}-c-${c}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "paragraph":
          default:
            return (
              <p key={key} className="lv-v2-md__p">
                {block.text.split("\n").map((line, li) => (
                  <span key={`${key}-l-${li}`}>
                    {li > 0 ? <br /> : null}
                    {renderInlineMarkdown(line, `${key}-l-${li}`)}
                  </span>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
