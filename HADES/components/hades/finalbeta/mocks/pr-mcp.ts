/** FINALBETA MCP page — mock/demo data only (pixel-lock to mcp.jpg). */

export const MCP_TABS = [
  "Overzicht",
  "Servers",
  "Tools",
  "Testen",
  "Logs",
  "Instellingen",
] as const;

export type McpTab = (typeof MCP_TABS)[number];

export const MCP_KPIS = [
  {
    id: "servers",
    label: "MCP servers",
    value: "3 verbonden",
    hint: "1 inactief",
    icon: "link",
    tone: "cyan" as const,
    valueTone: "cyan" as const,
  },
  {
    id: "tools",
    label: "Beschikbare tools",
    value: "28 tools",
    hint: "uit 4 servers",
    icon: "wrench",
    tone: "green" as const,
    valueTone: "white" as const,
  },
  {
    id: "perms",
    label: "Actieve permissies",
    value: "6 scopes",
    hint: "veilig geconfigureerd",
    icon: "shield",
    tone: "teal" as const,
    valueTone: "teal" as const,
  },
  {
    id: "health",
    label: "Systeemhealth",
    value: "3 / 4 online",
    hint: "75% operationeel",
    icon: "line",
    tone: "green" as const,
    valueTone: "white" as const,
    trend: "down" as const,
    hintTone: "green" as const,
  },
];

export type McpServerStatus = "Online" | "Offline";
export type McpAuthTone = "ok" | "warn" | "none";

export type McpServer = {
  id: string;
  name: string;
  summary: string;
  status: McpServerStatus;
  transport: string;
  tools: number;
  auth: string;
  authTone: McpAuthTone;
  lastActive: string;
  icon: string;
  endpoint?: string;
  transportDetail?: string;
  lastActiveFull?: string;
  avgResponse?: string;
  scopes?: string[];
};

export const MCP_SERVERS: McpServer[] = [
  {
    id: "filesystem",
    name: "Filesystem",
    summary: "Lokale bestandssysteem toegang",
    status: "Online",
    transport: "stdio",
    tools: 8,
    auth: "Geen",
    authTone: "none",
    lastActive: "17 nov 2024 16:12",
    icon: "folder",
  },
  {
    id: "brave",
    name: "Brave Search",
    summary: "Web search en realtime informatie",
    status: "Online",
    transport: "HTTP",
    tools: 7,
    auth: "API key",
    authTone: "ok",
    lastActive: "17 nov 2024 16:08",
    icon: "search",
    endpoint: "https://mcp.brave.com/sse",
    transportDetail: "HTTP (SSE)",
    lastActiveFull: "17 nov 2024 16:08:24",
    avgResponse: "842 ms",
    scopes: ["search", "web", "news", "domains"],
  },
  {
    id: "github",
    name: "GitHub",
    summary: "Repository beheer en code analyse",
    status: "Online",
    transport: "HTTP",
    tools: 9,
    auth: "OAuth 2.0",
    authTone: "ok",
    lastActive: "17 nov 2024 15:55",
    icon: "code",
  },
  {
    id: "postgres",
    name: "PostgreSQL",
    summary: "Database query en analyse",
    status: "Offline",
    transport: "stdio",
    tools: 4,
    auth: "API key",
    authTone: "warn",
    lastActive: "16 nov 2024 22:14",
    icon: "database",
  },
];

export const MCP_TOOLS = [
  {
    id: "search",
    name: "search",
    description: "Zoek op het web met Brave",
    serverId: "brave",
    server: "Brave Search",
    category: "Zoeken",
    categoryTone: "green" as const,
    icon: "search" as const,
  },
  {
    id: "get_web_content",
    name: "get_web_content",
    description: "Haal inhoud op van een URL",
    serverId: "brave",
    server: "Brave Search",
    category: "Web",
    categoryTone: "blue" as const,
    icon: "globe" as const,
  },
  {
    id: "list_directory",
    name: "list_directory",
    description: "Lijst bestanden in directory",
    serverId: "filesystem",
    server: "Filesystem",
    category: "Bestanden",
    categoryTone: "teal" as const,
    icon: "folder" as const,
  },
  {
    id: "read_file",
    name: "read_file",
    description: "Lees de inhoud van een bestand",
    serverId: "filesystem",
    server: "Filesystem",
    category: "Bestanden",
    categoryTone: "teal" as const,
    icon: "file" as const,
  },
  {
    id: "create_file",
    name: "create_file",
    description: "Maak een nieuw bestand aan",
    serverId: "filesystem",
    server: "Filesystem",
    category: "Bestanden",
    categoryTone: "teal" as const,
    icon: "squareplus" as const,
  },
  {
    id: "list_repos",
    name: "list_repos",
    description: "Lijst repositories van een user/org",
    serverId: "github",
    server: "GitHub",
    category: "Code",
    categoryTone: "green" as const,
    icon: "code" as const,
  },
];

export const MCP_TEST_PARAMS = `{
  "query": "Laatste AI ontwikkelingen 2024",
  "count": 5,
  "safe_search": "moderate"
}`;

export const MCP_TEST_RESULT = `{
  "query": "Laatste AI ontwikkelingen 2024",
  "results": [
    {
      "title": "OpenAI deelt GPT-5 research preview",
      "url": "https://example.com/ai/gpt-5-preview",
      "snippet": "Nieuwe multimodaliteit en langere contextvensters."
    },
    {
      "title": "Anthropic Claude 3.5 productupdate",
      "url": "https://example.com/ai/claude-3-5",
      "snippet": "Snellere coding agents en verbeterde tool use."
    },
    {
      "title": "Lokale LLM runtimes in 2024",
      "url": "https://example.com/ai/local-runtimes",
      "snippet": "Offline-first werkruimten en MCP-toolbruggen."
    }
  ],
  "count": 5,
  "took_ms": 2304
}`;

export const MCP_STATUS = [
  { id: "total", label: "Servers totaal", value: "4", icon: "database", tone: "" },
  { id: "online", label: "Online", value: "3", icon: "checkcircle", tone: "green" },
  { id: "offline", label: "Offline", value: "1", icon: "stop", tone: "red" },
  { id: "tools", label: "Tools totaal", value: "28", icon: "wrench", tone: "" },
  { id: "calls", label: "Actieve calls", value: "2", icon: "target", tone: "" },
  { id: "latency", label: "Gem. responstijd", value: "842 ms", icon: "clock", tone: "" },
  { id: "success", label: "Succesratio", value: "98.7%", icon: "checkcircle", tone: "green" },
];

export const MCP_RECENT_CALLS = [
  { id: "c1", tool: "brave_search.search", server: "Brave Search", duration: "2.3s", ok: true },
  { id: "c2", tool: "github.list_repos", server: "GitHub", duration: "1.1s", ok: true },
  { id: "c3", tool: "filesystem.list_directory", server: "Filesystem", duration: "0.4s", ok: true },
  { id: "c4", tool: "brave_search.search", server: "Brave Search", duration: "3.2s", ok: true },
  { id: "c5", tool: "postgresql.query", server: "PostgreSQL", duration: "12.4s", ok: false },
];

export const MCP_QUICK_ACTIONS = [
  { id: "test", label: "Test verbindingen", icon: "line" },
  { id: "new", label: "Nieuwe MCP server", icon: "plus" },
  { id: "refresh", label: "Tools vernieuwen", icon: "refresh" },
  { id: "logs", label: "Logs bekijken", icon: "list" },
  { id: "docs", label: "Open documentatie", icon: "book" },
];

export const MCP_PERMISSIONS = [
  { id: "allowed", label: "Toegestane scopes", value: "6", tone: "" },
  { id: "blocked", label: "Geblokkeerde scopes", value: "1", tone: "red" },
  { id: "mode", label: "Gebruiker modus", value: "Lokaal (volledig)", tone: "green" },
];
