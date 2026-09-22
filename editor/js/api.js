/**
 * LEVIATHAN STUDIO — fetch wrappers for the local editor API.
 * Session token + Origin headers on mutating requests.
 */

async function parse(res) {
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = new Error(data?.error || data?.notes || `Fout ${res.status}`);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

export function createApi(origin) {
  const root = String(origin || "").replace(/\/$/, "");
  let sessionToken = "";

  function headers(extra = {}) {
    const h = { ...extra };
    if (sessionToken) h["X-LVB-Session"] = sessionToken;
    return h;
  }

  function send(path, options = {}) {
    return fetch(`${root}${path}`, {
      ...options,
      headers: headers(options.headers || {}),
      credentials: "same-origin",
    }).then(parse);
  }

  const json = (method, path, body) =>
    send(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  return {
    origin: root,
    get sessionToken() {
      return sessionToken;
    },
    setSessionToken(token) {
      sessionToken = String(token || "");
    },
    async boot() {
      const data = await send("/api/session");
      sessionToken = data.token || "";
      return data;
    },
    health: () => send("/api/health"),
    getFile: (name) => send(`/api/file?name=${encodeURIComponent(name)}`),
    putFile: (name, content, meta = {}) =>
      json("PUT", `/api/file?name=${encodeURIComponent(name)}`, { content, ...meta }),
    getContent: () => send("/api/content"),
    putContent: (content, meta = {}) => json("PUT", "/api/content", { content, ...meta }),
    saveTransaction: (payload) => json("POST", "/api/save", payload),
    replaceText: () => Promise.reject(Object.assign(new Error("Bronvervanging uitgeschakeld"), { status: 410 })),
    upload: (filename, data) => json("POST", "/api/upload", { filename, data }),
    assets: () => send("/api/assets"),
    editorAi: (body) => json("POST", "/api/editor-ai", body),
  };
}
