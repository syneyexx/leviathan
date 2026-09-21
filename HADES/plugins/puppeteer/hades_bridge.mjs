import dns from "node:dns/promises";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const cmd = args[0];

function argValue(flag, fallback = "") {
  const idx = args.indexOf(flag);
  if (idx === -1) return fallback;
  const value = args[idx + 1];
  if (!value || value.startsWith("--")) return fallback;
  return value;
}

async function withBrowser(fn) {
  const puppeteer = await import("puppeteer");
  // Do not disable Chromium's process sandbox. If a host cannot launch the
  // sandbox, surface that as an operational error instead of silently dropping
  // a core browser security boundary.
  const browser = await puppeteer.default.launch({ headless: true });
  try {
    return await fn(browser);
  } finally {
    await browser.close();
  }
}

function blockedIpv4(address) {
  const parts = address.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return true;
  const [a, b, c] = parts;
  if (a === 0 || a === 10 || a === 127) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 0 && c === 0) return true;
  if (a === 192 && b === 0 && c === 2) return true;
  if (a === 192 && b === 88 && c === 99) return true;
  if (a === 192 && b === 168) return true;
  if (a === 198 && (b === 18 || b === 19)) return true;
  if (a === 198 && b === 51 && c === 100) return true;
  if (a === 203 && b === 0 && c === 113) return true;
  if (a >= 224) return true;
  return false;
}

function blockedIpv6(address) {
  const value = address.toLowerCase().split("%", 1)[0];
  if (value === "::" || value === "::1") return true;
  if (value.startsWith("::ffff:")) {
    const mapped = value.slice("::ffff:".length);
    return net.isIP(mapped) !== 4 || blockedIpv4(mapped);
  }

  // Be conservative: ordinary globally routed IPv6 unicast lives in 2000::/3.
  // Reject deprecated IPv4-compatible forms (::x.x.x.x), ULA/link-local,
  // multicast and other non-global families by rejecting anything outside it.
  const pieces = value.split(":");
  const first = Number.parseInt(pieces[0] || "0", 16);
  const second = Number.parseInt(pieces[1] || "0", 16);
  if (!Number.isFinite(first) || !Number.isFinite(second)) return true;
  if (first < 0x2000 || first > 0x3fff) return true;

  // Transition/benchmark/documentation address space must not become a route
  // around the public-only browser boundary. 2001:0..2f includes IETF special
  // assignments such as Teredo/benchmark/ORCHID; normal public 2001 prefixes
  // (e.g. 2001:4860::) remain available.
  if (first === 0x2001 && second <= 0x002f) return true;
  if (first === 0x2001 && second === 0x0db8) return true; // documentation
  if (first === 0x2002) return true; // deprecated 6to4 embeds an IPv4 route
  if (first === 0x3fff) return true; // documentation/special-use allocation
  return false;
}

function blockedAddress(address) {
  const family = net.isIP(address);
  if (family === 4) return blockedIpv4(address);
  if (family === 6) return blockedIpv6(address);
  return true;
}

async function ensurePublicUrl(rawUrl) {
  let parsed;
  try {
    parsed = new URL(String(rawUrl || "").trim());
  } catch {
    throw new Error("Invalid URL");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Only http/https URLs are allowed");
  }
  const host = (parsed.hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
  if (!host || host === "localhost" || host === "metadata.google.internal" || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".internal")) {
    throw new Error(`Private/local host blocked: ${host || "<empty>"}`);
  }

  let addresses;
  if (net.isIP(host)) {
    addresses = [{ address: host }];
  } else {
    try {
      addresses = await dns.lookup(host, { all: true, verbatim: true });
    } catch (error) {
      throw new Error(`Host resolution failed: ${host}`, { cause: error });
    }
  }
  if (!addresses.length) throw new Error(`Host resolved to no usable addresses: ${host}`);
  const blocked = addresses.map((item) => String(item.address || "")).filter((address) => blockedAddress(address));
  if (blocked.length) {
    throw new Error(`Private/non-public address blocked for ${host}: ${blocked.sort().join(", ")}`);
  }
  return parsed.toString();
}

async function installRequestGuard(page) {
  await page.setRequestInterception(true);
  page.on("request", async (request) => {
    const requestUrl = request.url();
    let parsed;
    try {
      parsed = new URL(requestUrl);
    } catch {
      try { await request.abort("blockedbyclient"); } catch {}
      return;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      try { await request.continue(); } catch {}
      return;
    }
    try {
      await ensurePublicUrl(requestUrl);
      await request.continue();
    } catch {
      try { await request.abort("blockedbyclient"); } catch {}
    }
  });
}

async function guardedGoto(page, url, options) {
  const safeUrl = await ensurePublicUrl(url);
  await installRequestGuard(page);
  const response = await page.goto(safeUrl, options);
  const finalUrl = await ensurePublicUrl(page.url());
  return { response, finalUrl };
}

if (cmd === "doctor") {
  const pkgPath = path.join(__dirname, "package.json");
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  let puppeteerOk = false;
  try {
    await import("puppeteer");
    puppeteerOk = true;
  } catch {
    puppeteerOk = false;
  }
  const payload = {
    ok: puppeteerOk,
    name: pkg.name,
    version: pkg.version,
    dependency: pkg.dependencies?.puppeteer || null,
    puppeteer_importable: puppeteerOk,
  };
  if (!puppeteerOk) payload.error = "puppeteer_not_importable";
  console.log(JSON.stringify(payload, null, 2));
  process.exit(puppeteerOk ? 0 : 2);
}

if (cmd === "fetch") {
  const url = argValue("--url");
  const maxChars = Number(argValue("--max-chars", "20000"));
  if (!url) {
    console.error("url is required");
    process.exit(1);
  }
  try {
    await ensurePublicUrl(url);
  } catch (error) {
    console.log(JSON.stringify({ url, ok: false, error: String(error?.message || error), status: 0 }, null, 2));
    process.exit(2);
  }
  const result = await withBrowser(async (browser) => {
    const page = await browser.newPage();
    let response;
    let finalUrl;
    try {
      ({ response, finalUrl } = await guardedGoto(page, url, { waitUntil: "domcontentloaded", timeout: 60000 }));
    } catch (error) {
      return { url, ok: false, error: String(error?.message || error), status: 0 };
    }
    const status = response ? response.status() : 0;
    if (!response || status >= 400) {
      return { url: finalUrl || url, ok: false, error: `HTTP ${status || "no response"}`, status };
    }
    const title = await page.title();
    const text = await page.evaluate(() => document.body?.innerText || "");
    const html = await page.content();
    return {
      url: finalUrl,
      title,
      ok: Boolean(String(text || "").trim()),
      status,
      chars: text.length,
      truncated: text.length > maxChars,
      text: text.slice(0, maxChars),
      html_chars: html.length,
      ...(String(text || "").trim() ? {} : { error: "empty page text" }),
    };
  });
  console.log(JSON.stringify(result, null, 2));
  if (result.ok === false) process.exit(1);
  if (!String(result.text || "").trim()) process.exit(2);
  process.exit(0);
}

if (cmd === "screenshot") {
  const url = argValue("--url");
  const output = argValue("--output", "screenshot.png");
  if (!url) {
    console.error("url is required");
    process.exit(1);
  }
  try {
    await ensurePublicUrl(url);
  } catch (error) {
    console.log(JSON.stringify({ url, ok: false, error: String(error?.message || error), status: 0, bytes: 0 }, null, 2));
    process.exit(2);
  }
  const result = await withBrowser(async (browser) => {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 720 });
    let response;
    let finalUrl;
    try {
      ({ response, finalUrl } = await guardedGoto(page, url, { waitUntil: "networkidle2", timeout: 60000 }));
    } catch (error) {
      return { url, ok: false, error: String(error?.message || error), status: 0, bytes: 0 };
    }
    const status = response ? response.status() : 0;
    if (!response || status >= 400) {
      return { url: finalUrl || url, ok: false, error: `HTTP ${status || "no response"}`, status, bytes: 0 };
    }
    const outPath = path.resolve(output);
    await page.screenshot({ path: outPath, fullPage: true });
    const bytes = fs.statSync(outPath).size;
    return {
      url: finalUrl,
      output: outPath,
      bytes,
      status,
      ok: bytes > 0,
      ...(bytes > 0 ? {} : { error: "empty screenshot" }),
    };
  });
  console.log(JSON.stringify(result, null, 2));
  if (result.ok === false) process.exit(1);
  if (!result.bytes) process.exit(2);
  process.exit(0);
}

console.error(`unknown command: ${cmd}`);
process.exit(1);
