/**
 * Leviathan Visual Builder — fetch wrappers for the local editor API.
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

  function send(path, options) {
    return fetch(`${root}${path}`, options).then(parse);
  }

  const json = (method, path, body) =>
    send(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  return {
    origin: root,
    health: () => send("/api/health"),
    getFile: (name) => send(`/api/file?name=${encodeURIComponent(name)}`),
    putFile: (name, content) => json("PUT", `/api/file?name=${encodeURIComponent(name)}`, { content }),
    getContent: () => send("/api/content"),
    putContent: (content) => json("PUT", "/api/content", { content }),
    replaceText: (oldText, newText) => json("POST", "/api/replace-text", { old: oldText, new: newText }),
    upload: (filename, data) => json("POST", "/api/upload", { filename, data }),
    assets: () => send("/api/assets"),
    editorAi: (body) => json("POST", "/api/editor-ai", body),
  };
}
