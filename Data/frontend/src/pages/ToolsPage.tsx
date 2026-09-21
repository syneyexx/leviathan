import { useMemo, useState, type ReactNode } from "react";
import { SubMenu } from "../components/SubMenu";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type ToolRow = {
  id: string;
  name: string;
  type: "Built-in" | "Integration";
  category: string;
  status: "Active" | "Idle" | "Not Configured";
  description: string;
  lastUsed: string;
  icon: ReactNode;
};

const TABS = [
  "All Tools",
  "Core Tools",
  "MCP Servers",
  "Integrations",
  "Custom Tools",
  "Installed",
  "Templates",
] as const;

const TOOLS: ToolRow[] = [
  {
    id: "fs",
    name: "File System",
    type: "Built-in",
    category: "System",
    status: "Active",
    description: "Read, write, search and manage files and directories",
    lastUsed: "2 min ago",
    icon: <path d="M4 8h6l2 2h8v8H4z" />,
  },
  {
    id: "web",
    name: "Web Search",
    type: "Built-in",
    category: "Research",
    status: "Active",
    description: "Search the web with ranked results",
    lastUsed: "5 min ago",
    icon: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3-3" />
      </>
    ),
  },
  {
    id: "code",
    name: "Code Execution",
    type: "Built-in",
    category: "Development",
    status: "Active",
    description: "Run sandboxed Python and shell snippets",
    lastUsed: "12 min ago",
    icon: <path d="M8 8l-4 4 4 4M16 8l4 4-4 4" />,
  },
  {
    id: "browser",
    name: "Browser",
    type: "Built-in",
    category: "Automation",
    status: "Active",
    description: "Navigate pages and extract structured content",
    lastUsed: "28 min ago",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M4 12h16M12 4c2.5 2.8 2.5 13.2 0 16M12 4c-2.5 2.8-2.5 13.2 0 16" />
      </>
    ),
  },
  {
    id: "terminal",
    name: "Terminal",
    type: "Built-in",
    category: "System",
    status: "Active",
    description: "Execute approved local shell commands",
    lastUsed: "41 min ago",
    icon: <path d="M5 8l5 4-5 4M12 16h7" />,
  },
  {
    id: "db",
    name: "Database",
    type: "Built-in",
    category: "Data",
    status: "Active",
    description: "Query connected SQL and document stores",
    lastUsed: "1h ago",
    icon: (
      <>
        <ellipse cx="12" cy="6" rx="7" ry="3" />
        <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
      </>
    ),
  },
  {
    id: "memory",
    name: "Memory",
    type: "Built-in",
    category: "Memory",
    status: "Active",
    description: "Store and recall durable working memory",
    lastUsed: "2h ago",
    icon: (
      <>
        <path d="M8 7h8l1 4H7l1-4z" />
        <path d="M7 11v7h10v-7" />
      </>
    ),
  },
  {
    id: "knowledge",
    name: "Knowledge Search",
    type: "Built-in",
    category: "Knowledge",
    status: "Active",
    description: "Retrieve local knowledge and evidence",
    lastUsed: "3h ago",
    icon: <path d="M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-3z" />,
  },
  {
    id: "youtube",
    name: "YouTube",
    type: "Integration",
    category: "Media",
    status: "Active",
    description: "Search and summarize video content",
    lastUsed: "5h ago",
    icon: <path d="M6 8h12v8H6zM10 10l5 2-5 2z" />,
  },
  {
    id: "github",
    name: "Github",
    type: "Integration",
    category: "Development",
    status: "Active",
    description: "Repos, issues, PRs and code search",
    lastUsed: "6h ago",
    icon: <path d="M9 19c-4 1.5-4-2-6-2m12 4v-3.5a3 3 0 00-.7-2C16.5 17 20 16 20 11a4 4 0 00-1-2.9" />,
  },
  {
    id: "hf",
    name: "HuggingFace",
    type: "Integration",
    category: "AI/ML",
    status: "Active",
    description: "Browse models and datasets",
    lastUsed: "8h ago",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M8 14c1.2 1.4 2.6 2 4 2s2.8-.6 4-2" />
      </>
    ),
  },
  {
    id: "slack",
    name: "Slack",
    type: "Integration",
    category: "Communication",
    status: "Idle",
    description: "Send messages and read channels",
    lastUsed: "3 days ago",
    icon: <path d="M8 8h3v3H8zM13 8h3v3h-3M8 13h3v3H8M13 13h3v3h-3" />,
  },
  {
    id: "notion",
    name: "Notion",
    type: "Integration",
    category: "Productivity",
    status: "Idle",
    description: "Read and write workspace pages",
    lastUsed: "4 days ago",
    icon: <path d="M6 5h10l2 2v12H6z" />,
  },
  {
    id: "discord",
    name: "Discord",
    type: "Integration",
    category: "Communication",
    status: "Not Configured",
    description: "Connect Discord bots and channels",
    lastUsed: "Never",
    icon: (
      <>
        <circle cx="9" cy="12" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="15" cy="12" r="1.2" fill="currentColor" stroke="none" />
        <path d="M7 8c2-2 8-2 10 0M6 15c1.5 2 10.5 2 12 0" />
      </>
    ),
  },
  {
    id: "gdrive",
    name: "Google Drive",
    type: "Integration",
    category: "Storage",
    status: "Not Configured",
    description: "Access Drive files and folders",
    lastUsed: "Never",
    icon: <path d="M8 18h8l4-7-4-7H8L4 11z" />,
  },
];

const CATEGORIES = [
  { label: "All Tools", count: 15 },
  { label: "System", count: 4 },
  { label: "Research", count: 2 },
  { label: "Development", count: 3 },
  { label: "Communication", count: 2 },
  { label: "AI/ML", count: 1 },
  { label: "Storage", count: 1 },
  { label: "Other", count: 2 },
] as const;

const SERVERS = [
  { name: "LEVIATHAN Core Tools", status: "Online", meta: "12 tools" },
  { name: "MCP Browser Server", status: "Online", meta: "6 tools" },
  { name: "MCP File System Server", status: "Online", meta: "4 tools" },
  { name: "MCP GitHub Server", status: "Degraded", meta: "3 tools" },
] as const;

const ACTIVITY = [
  { text: 'File read: config.json', time: "2 min ago" },
  { text: 'Web search: "Qwen2.5 benchmarks"', time: "5 min ago" },
  { text: "Python execution (3.2s)", time: "12 min ago" },
  { text: "Browser navigate → docs.leviathan.ai", time: "28 min ago" },
  { text: "Memory write: session summary", time: "1h ago" },
] as const;

const TAGS = ["Built-in", "System", "File I/O", "Search", "Edit", "Secure"] as const;

function statusDot(status: ToolRow["status"]) {
  if (status === "Active") return "ready";
  if (status === "Idle") return "running";
  return "failed";
}

export function ToolsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("All Tools");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("fs");
  const [recursive, setRecursive] = useState(true);
  const [createFiles, setCreateFiles] = useState(true);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [confirm, setConfirm] = useState(true);
  const [maxSize, setMaxSize] = useState("100");
  const [allowedPath, setAllowedPath] = useState("D:\\HADES");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return TOOLS.filter((tool) => {
      if (tab === "Core Tools" && tool.type !== "Built-in") return false;
      if (tab === "Integrations" && tool.type !== "Integration") return false;
      if (tab === "MCP Servers") return tool.id === "browser" || tool.id === "fs" || tool.id === "github";
      if (tab === "Installed" && tool.status === "Not Configured") return false;
      if (tab === "Custom Tools") return false;
      if (tab === "Templates") return false;
      if (!q) return true;
      return `${tool.name} ${tool.category} ${tool.description}`.toLowerCase().includes(q);
    });
  }, [query, tab]);

  const selected = TOOLS.find((tool) => tool.id === selectedId) ?? TOOLS[0];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Modules Mode"
      searchPlaceholder="Search modules, integrations, functions..."
      systemItems={["LLM", "Neural", "Memory", "Modules"]}
      layout="wide"
      pageClass="lv-app--tools"
    >
      <main className="lv-main lv-tools-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src="/assets/hero-tools.jpg" alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <h1 className="lv-hero-title">Modules</h1>
            <p className="lv-hero-kicker" style={{ marginTop: 6 }}>
              Extend Capabilities. Execute Reality.
            </p>
            <p className="lv-page-quote">“More than a model. A working intelligence.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Connect</span>
            <span>Automate</span>
            <span>Execute</span>
            <span>Integrate</span>
            <span>Transcend</span>
          </div>
        </section>

        <SubMenu />

        <div className="lv-tools-toolbar">
          <div className="lv-tabs" role="tablist">
            {TABS.map((item) => (
              <button
                key={item}
                className={`lv-tab${tab === item ? " is-active" : ""}`}
                type="button"
                onClick={() => setTab(item)}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="lv-toolbar" style={{ marginLeft: "auto" }}>
            <input
              className="lv-input"
              style={{ minWidth: 180 }}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search tools..."
              aria-label="Search tools"
            />
            <button className="lv-btn" type="button" onClick={() => toast("Filters")}>
              Filters
            </button>
            <button className="lv-btn lv-btn-gold" type="button" onClick={() => toast("Add Tool")}>
              + Add Tool
            </button>
          </div>
        </div>

        <div className="lv-tools-split">
          <div className="lv-models-table-wrap">
            <table className="lv-models-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Description</th>
                  <th>Last Used</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((tool) => (
                  <tr
                    key={tool.id}
                    className={selectedId === tool.id ? "is-selected" : undefined}
                    onClick={() => setSelectedId(tool.id)}
                  >
                    <td>
                      <div className="lv-tool-name-cell">
                        <span className="lv-tool-glyph">
                          <svg className="lv-icon" viewBox="0 0 24 24">
                            {tool.icon}
                          </svg>
                        </span>
                        <strong>{tool.name}</strong>
                      </div>
                    </td>
                    <td>{tool.type}</td>
                    <td>{tool.category}</td>
                    <td>
                      <span className="lv-model-status">
                        <span className={`lv-status-dot ${statusDot(tool.status)}`} />
                        {tool.status}
                      </span>
                    </td>
                    <td>{tool.description}</td>
                    <td>{tool.lastUsed}</td>
                    <td>
                      <button
                        className="lv-icon-btn"
                        type="button"
                        aria-label="More"
                        onClick={(event) => {
                          event.stopPropagation();
                          toast(`${tool.name} options`);
                        }}
                      >
                        <svg className="lv-icon" viewBox="0 0 24 24">
                          <circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none" />
                          <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
                          <circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <article className="lv-panel lv-panel-premium lv-tool-detail">
            <div className="lv-tool-detail-head">
              <div>
                <div className="lv-tool-detail-title">
                  <span className="lv-tool-glyph large">
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      {selected.icon}
                    </svg>
                  </span>
                  <div>
                    <h2>{selected.name}</h2>
                    <span className="lv-model-status">
                      <span className={`lv-status-dot ${statusDot(selected.status)}`} />
                      {selected.status}
                    </span>
                  </div>
                </div>
                <p className="lv-node-desc">{selected.description} on the local system.</p>
              </div>
            </div>

            <div className="lv-toolbar">
              {TAGS.map((tag) => (
                <span key={tag} className="lv-tag gold">
                  {tag}
                </span>
              ))}
            </div>

            <div className="lv-section-label">Configuration</div>
            <div className="lv-form-grid">
              <label className="lv-form-field full">
                <span>Allowed Paths</span>
                <input
                  className="lv-input"
                  value={allowedPath}
                  onChange={(event) => setAllowedPath(event.target.value)}
                />
              </label>
              <label className="lv-form-field">
                <span>Access Mode</span>
                <select className="lv-select" defaultValue="rw">
                  <option value="rw">Read & Write</option>
                  <option value="ro">Read Only</option>
                </select>
              </label>
              <label className="lv-form-field">
                <span>Max File Size (MB)</span>
                <input
                  className="lv-input"
                  value={maxSize}
                  onChange={(event) => setMaxSize(event.target.value)}
                />
              </label>
            </div>

            <div className="lv-toggle-stack">
              {(
                [
                  ["Enable Recursive Search", recursive, setRecursive],
                  ["Allow File Creation", createFiles, setCreateFiles],
                  ["Allow File Deletion", deleteFiles, setDeleteFiles],
                  ["Require Confirmation for Destructive Actions", confirm, setConfirm],
                ] as const
              ).map(([label, on, setOn]) => (
                <button
                  key={label}
                  className="lv-toggle"
                  type="button"
                  onClick={() => setOn(!on)}
                >
                  <span className={`lv-switch${on ? " is-on" : ""}`} />
                  {label}
                </button>
              ))}
            </div>

            <div className="lv-section-label">Usage Statistics (30 Days)</div>
            <div className="lv-job-metrics">
              <div className="lv-metric">
                <span>Executions</span>
                <strong>1,482</strong>
              </div>
              <div className="lv-metric">
                <span>Files Read</span>
                <strong>856</strong>
              </div>
              <div className="lv-metric">
                <span>Files Written</span>
                <strong>231</strong>
              </div>
              <div className="lv-metric">
                <span>Files Deleted</span>
                <strong>12</strong>
              </div>
            </div>

            <div className="lv-detail-actions" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
              <button className="lv-btn lv-btn-gold" type="button" onClick={() => toast("Test Tool")}>
                Test Tool
              </button>
              <button className="lv-btn" type="button" onClick={() => toast("Documentation")}>
                View Documentation
              </button>
              <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Disable Tool")}>
                Disable Tool
              </button>
            </div>
          </article>
        </div>

        <div className="lv-tools-bottom">
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Tool Categories</div>
            <div className="lv-process-list">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.label}
                  className="lv-process-row"
                  type="button"
                  onClick={() => toast(cat.label)}
                >
                  <span className="lv-process-icon gold" />
                  <span>{cat.label}</span>
                  <b>{cat.count}</b>
                </button>
              ))}
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Active Tool Servers</div>
            <div className="lv-server-list">
              {SERVERS.map((server) => (
                <div key={server.name} className="lv-server-row">
                  <span
                    className={`lv-status-dot ${server.status === "Online" ? "ready" : "running"}`}
                  />
                  <div>
                    <strong>{server.name}</strong>
                    <small>
                      {server.status} · {server.meta}
                    </small>
                  </div>
                </div>
              ))}
            </div>
            <button className="lv-btn" type="button" onClick={() => toast("Manage Servers")}>
              Manage Servers
            </button>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Recent Tool Activity</div>
            <div className="lv-recent-list">
              {ACTIVITY.map((item) => (
                <button
                  key={item.text}
                  className="lv-recent-row"
                  type="button"
                  onClick={() => toast(item.text)}
                >
                  <span>{item.text}</span>
                  <time>{item.time}</time>
                </button>
              ))}
            </div>
            <button className="lv-btn" type="button" onClick={() => toast("View All Activity")}>
              View All Activity
            </button>
          </article>

          <div className="lv-tools-actions-col">
            <article className="lv-panel lv-card">
              <div className="lv-section-label">Quick Actions</div>
              <div className="lv-quick-actions" style={{ gridTemplateColumns: "1fr 1fr" }}>
                {[
                  "Add Custom Tool",
                  "Connect MCP Server",
                  "Browse Templates",
                  "Import from Registry",
                ].map((label) => (
                  <button
                    key={label}
                    className="lv-quick-action"
                    type="button"
                    onClick={() => toast(label)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </article>
            <article className="lv-panel lv-card lv-danger-zone">
              <div className="lv-section-label">Danger Zone</div>
              <div className="lv-danger-row">
                <span>Reset All Tool Configurations</span>
                <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Reset All")}>
                  Reset All
                </button>
              </div>
              <small className="lv-muted">
                This disables custom settings and restores factory defaults for every tool.
              </small>
            </article>
          </div>
        </div>

        <p className="lv-footer-quote">“Tools turn thought into action.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
