import { describe, expect, it } from "vitest";
import { isSafeHref, parseSafeMarkdown } from "./safeMarkdown";

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
});
