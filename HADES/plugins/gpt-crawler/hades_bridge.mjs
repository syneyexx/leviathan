import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const cmd = args[0];

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

if (cmd === "doctor") {
  const pkgPath = path.join(__dirname, "package.json");
  if (!fs.existsSync(pkgPath)) {
    console.log(JSON.stringify({
      ok: false,
      error: "package.json missing",
    }, null, 2));
    process.exit(2);
  }
  const pkg = readJson(pkgPath);
  const scripts = pkg.scripts || {};
  const startScript = String(scripts.start || "");
  const stubStart = /pack upstream/i.test(startScript);
  const hasConfigExample =
    fs.existsSync(path.join(__dirname, "config.ts")) ||
    fs.existsSync(path.join(__dirname, "config.example.ts"));
  const ok = Boolean(pkg.name) && !stubStart;
  const payload = {
    ok,
    name: pkg.name,
    version: pkg.version,
    scripts: Object.keys(scripts),
    hasConfigExample,
    stubStart,
  };
  if (!ok) {
    payload.error = stubStart
      ? "upstream not packed; start script is a stub"
      : "package.json incomplete";
  }
  console.log(JSON.stringify(payload, null, 2));
  process.exit(ok ? 0 : 2);
}

if (cmd === "write-config") {
  const url = args[args.indexOf("--url") + 1];
  const match = args[args.indexOf("--match") + 1] || `${url.replace(/\/$/, "")}/**`;
  const maxPages = Number(args[args.indexOf("--max-pages") + 1] || 50);
  const out = args[args.indexOf("--out") + 1] || path.join(__dirname, "hades-config.json");
  if (!url || url.startsWith("--")) {
    console.error("url is required");
    process.exit(1);
  }
  const config = {
    url,
    match,
    maxPagesToCrawl: maxPages,
    outputFileName: "hades-output.json",
  };
  fs.writeFileSync(out, JSON.stringify(config, null, 2));
  console.log(JSON.stringify({ wrote: out, config }, null, 2));
  process.exit(0);
}

console.error(`unknown command: ${cmd}`);
process.exit(1);
