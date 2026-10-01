import { describe, expect, it } from "vitest";
import { isSafeHref, parseSafeMarkdown, sanitizeHref } from "./safeMarkdown";

describe("safeMarkdown", () => {
  it("blocks javascript: and data: hrefs", () => {
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
    expect(isSafeHref("data:text/html,hi")).toBe(false);
    expect(isSafeHref("https://example.com")).toBe(true);
    expect(isSafeHref("/relative")).toBe(true);
    expect(isSafeHref("mailto:a@b.c")).toBe(true);
  });

  it("parses headings, lists, code, tables without raw HTML", () => {
    const md = [
      "# Title",
      "",
      "Hello **world**",
      "",
      "- one",
      "- two",
      "",
      "```ts",
      "const x = 1;",
      "```",
      "",
      "| A | B |",
      "| --- | --- |",
      "| 1 | 2 |",
      "",
      '<script>alert(1)</script>',
    ].join("\n");

    const blocks = parseSafeMarkdown(md);
    expect(blocks.some((b) => b.type === "heading")).toBe(true);
    expect(blocks.some((b) => b.type === "ul")).toBe(true);
    expect(blocks.some((b) => b.type === "code")).toBe(true);
    expect(blocks.some((b) => b.type === "table")).toBe(true);

    // Raw HTML is treated as plain paragraph text — never as executable markup.
    const htmlPara = blocks.find(
      (b) => b.type === "paragraph" && b.text.includes("<script>"),
    );
    expect(htmlPara).toBeTruthy();
    expect(JSON.stringify(blocks)).not.toMatch(/dangerouslySetInnerHTML/);
  });

  it("does not treat javascript links as safe in source text", () => {
    const blocks = parseSafeMarkdown("[x](javascript:alert(1))");
    expect(blocks[0]?.type).toBe("paragraph");
    // isSafeHref is the gate used by the renderer
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
  });

  it("blocks adversarial scheme variants and nested markdown html", () => {
    expect(isSafeHref("JAVASCRIPT:alert(1)")).toBe(false);
    expect(isSafeHref("  javascript:alert(1)")).toBe(false);
    expect(isSafeHref("vbscript:msgbox(1)")).toBe(false);
    expect(isSafeHref("file:///etc/passwd")).toBe(false);
    expect(isSafeHref("data:text/html,<img src=x onerror=alert(1)>")).toBe(false);
    expect(sanitizeHref("javascript:alert(1)")).toBeNull();
    expect(sanitizeHref("https://ok.example/a")).toBe("https://ok.example/a");

    const blocks = parseSafeMarkdown(
      [
        '[click](JaVaScRiPt:alert(1))',
        "",
        '<img src=x onerror="alert(1)">',
        "",
        "[ok](https://example.com)",
      ].join("\n"),
    );
    const serialized = JSON.stringify(blocks);
    expect(serialized).not.toMatch(/dangerouslySetInnerHTML/);
    expect(serialized.toLowerCase()).toContain("javascript:alert");
    // Safe https link remains parseable as paragraph text / inline target.
    expect(blocks.some((b) => b.type === "paragraph")).toBe(true);
    expect(isSafeHref("https://example.com")).toBe(true);
  });
});
