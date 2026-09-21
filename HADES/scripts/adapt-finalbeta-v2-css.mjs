/**
 * Scope mockup CSS under .fb-root so FINALBETA doesn't leak into Lux.
 */
import fs from "node:fs";
import path from "node:path";

const srcDir = path.join("docs/mockups/finalbeta-v2/css");
const dstDir = path.join("components/hades/styles/finalbeta/v2");
fs.mkdirSync(dstDir, { recursive: true });

function scopeCss(css) {
  css = css.replaceAll('url("../assets/mountain-scene.png")', 'url("/finalbeta/mountain-scene.png")');
  css = css.replaceAll('url("../assets/login-hero.png")', 'url("/finalbeta/login-hero.png")');
  css = css.replace(/:root\s*\{/g, ".fb-root {");
  css = css.replace(/html,\s*body\s*\{/g, ".fb-root {");

  const lines = css.split("\n");
  const out = [];
  let inKeyframes = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("@keyframes") || trimmed.startsWith("@-webkit-keyframes")) {
      inKeyframes = true;
      out.push(line);
      continue;
    }
    if (inKeyframes) {
      out.push(line);
      if (trimmed === "}") inKeyframes = false;
      continue;
    }

    if (trimmed.endsWith("{") && !trimmed.startsWith("@") && !/^(from|to|\d+%)/.test(trimmed)) {
      const openIdx = line.lastIndexOf("{");
      const selPart = line.slice(0, openIdx).trim();
      const indent = line.slice(0, line.length - line.trimStart().length);
      const rest = line.slice(openIdx);
      if (selPart && !selPart.startsWith(".fb-root")) {
        const scoped = selPart
          .split(",")
          .map((raw) => {
            const t = raw.trim();
            if (!t) return t;
            if (t.startsWith(".fb-root")) return t;
            if (t === ".login-page") return ".fb-root.login-page";
            if (t.startsWith(".login-page")) return `.fb-root.login-page${t.slice(".login-page".length)}`;
            return `.fb-root ${t}`;
          })
          .join(", ");
        out.push(`${indent}${scoped} ${rest}`);
        continue;
      }
    }
    out.push(line);
  }

  let result = out.join("\n");
  result = result.replace(
    /\.fb-root \.app\s*\{/,
    `.fb-root .app {\n  position: fixed;\n  inset: 0;\n  z-index: 40;`
  );
  result = result.replace(
    /\.fb-root \.dash-app\s*\{/,
    `.fb-root .dash-app {\n  position: fixed;\n  inset: 0;\n  z-index: 40;`
  );
  result = result.replace(
    /\.fb-root\.login-page\s*\{/,
    `.fb-root.login-page {\n  position: fixed;\n  inset: 0;\n  z-index: 40;`
  );
  return result;
}

for (const name of ["hades.css", "dashboard.css", "login.css"]) {
  const raw = fs.readFileSync(path.join(srcDir, name), "utf8");
  const scoped = scopeCss(raw);
  fs.writeFileSync(path.join(dstDir, name), scoped);
  console.log("scoped", name, scoped.length);
}
