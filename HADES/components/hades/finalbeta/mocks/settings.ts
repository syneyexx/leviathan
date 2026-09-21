/** FINALBETA Instellingen — visual-first mock content. */

export const SETTINGS_GENERAL_FIELDS = [
  { id: "name", label: "Systeemnaam", type: "text" as const, value: "HADES" },
  {
    id: "lang",
    label: "Taal",
    type: "select" as const,
    value: "Nederlands",
    options: ["Nederlands", "English"],
  },
  {
    id: "tz",
    label: "Tijdzone",
    type: "select" as const,
    value: "Europe/Amsterdam",
    options: ["Europe/Amsterdam", "UTC", "America/New_York"],
  },
  {
    id: "date",
    label: "Datumformaat",
    type: "select" as const,
    value: "DD-MM-YYYY",
    options: ["DD-MM-YYYY", "MM-DD-YYYY", "YYYY-MM-DD"],
  },
  {
    id: "start",
    label: "Startpagina",
    type: "select" as const,
    value: "Dashboard",
    options: ["Dashboard", "Chat", "Taken"],
  },
] as const;

export const SETTINGS_GENERAL_TOGGLES = [
  { id: "autostart", label: "Start HADES automatisch bij opstarten", on: true },
  { id: "tray", label: "Minimaliseren naar system tray", on: true },
  { id: "welcome", label: "Toon welkomstscherm", on: false },
] as const;

export const SETTINGS_THEMES = [
  { id: "dark", label: "HADES Dark", hint: "Standaard", icon: "image", selected: true },
  { id: "nebula", label: "Nebula Blue", hint: "Rustig en helder", icon: "globe", selected: false },
  { id: "solar", label: "Solar Light", hint: "Licht thema", icon: "bolt", selected: false },
] as const;

export const SETTINGS_INTERFACE_FIELDS = [
  {
    id: "density",
    label: "Interface density",
    value: "Comfort (standaard)",
    options: ["Comfort (standaard)", "Compact", "Ruim"],
  },
  {
    id: "accent",
    label: "Accentkleur",
    value: "HADES Gold",
    options: ["HADES Gold", "Cyan", "Emerald"],
    swatch: true,
  },
  {
    id: "anim",
    label: "Animaties",
    value: "Normaal",
    options: ["Normaal", "Verminderd", "Uit"],
  },
] as const;

export const SETTINGS_INTERFACE_TOGGLES = [
  { id: "bg", label: "Toon achtergrondafbeelding", on: true },
  { id: "motion", label: "Reduceer beweging (accessibility)", on: false },
] as const;

export const SETTINGS_NOTIFICATIONS = [
  { id: "system", label: "Systeemmeldingen", icon: "bolt", on: true },
  { id: "tasks", label: "Taak voltooid", icon: "check", on: true },
  { id: "agents", label: "Agent meldingen", icon: "users", on: true },
  { id: "plugins", label: "Plugin updates", icon: "wrench", on: true },
  { id: "warnings", label: "Waarschuwingen", icon: "shield", on: true },
  { id: "marketing", label: "Marketing & tips", icon: "globe", on: false },
] as const;

export const SETTINGS_PRIVACY = [
  { id: "telemetry", label: "Telemetrie en diagnostiek", on: false },
  { id: "crash", label: "Crash reports (anoniem)", on: true },
  { id: "stats", label: "Anonieme gebruiksstatistieken", on: false },
  { id: "local", label: "Lokale data alleen (geen cloud)", on: true },
  { id: "confirm", label: "Bevestig gevoelige acties", on: true },
] as const;

export const SETTINGS_RUNTIME_FIELDS = [
  {
    id: "runtime",
    label: "Standaard runtime",
    value: "Local HADES Runtime",
    options: ["Local HADES Runtime", "LM Studio", "Custom"],
  },
  {
    id: "agents",
    label: "Maximale gelijktijdige agents",
    value: "4",
    options: ["2", "4", "8", "16"],
  },
  {
    id: "gpu",
    label: "GPU gebruik",
    value: "Automatisch (CUDA)",
    options: ["Automatisch (CUDA)", "Alleen CPU", "Forceer GPU"],
  },
] as const;

export const SETTINGS_RUNTIME_SLIDERS = [
  { id: "vram", label: "VRAM limiet", value: 75, display: "75%", min: 0, max: 100 },
  { id: "cpu", label: "CPU threads", value: 8, display: "8", min: 1, max: 32 },
  { id: "mem", label: "Geheugen limiet", value: 24, display: "24 GB", min: 4, max: 64 },
] as const;

export const SETTINGS_POLICIES = [
  { id: "safe", label: "Veilig & ethisch", tone: "green" as const },
  { id: "nopii", label: "Geen persoonlijke data", tone: "green" as const },
  { id: "sources", label: "Transparante bronnen", tone: "green" as const },
  { id: "filter", label: "Content filtering", tone: "gold" as const },
  { id: "code", label: "Code veiligheid", tone: "green" as const },
  { id: "rate", label: "Rate limiting", tone: "green" as const },
] as const;

export const SETTINGS_AUTOSAVE = [
  { id: "autosave", label: "Automatisch opslaan", on: true },
  { id: "daily", label: "Dagelijkse back-up", on: true },
  { id: "check", label: "Automatisch controleren op updates", on: true },
  { id: "install", label: "Updates automatisch installeren", on: false },
] as const;

export const SETTINGS_SHORTCUTS = [
  { keys: "Ctrl + K", action: "Open HADES AI" },
  { keys: "Ctrl + N", action: "Nieuwe taak" },
  { keys: "Ctrl + P", action: "Command Palette" },
  { keys: "Ctrl + ,", action: "Instellingen openen" },
] as const;

export const SETTINGS_INTEGRATIONS = [
  { id: "github", name: "GitHub", status: "Verbonden", connected: true },
  { id: "docker", name: "Docker", status: "Verbonden", connected: true },
  { id: "openai", name: "OpenAI", status: "Niet verbonden", connected: false },
  { id: "hf", name: "Hugging Face", status: "Verbonden", connected: true },
  { id: "yt", name: "YouTube API", status: "Verbonden", connected: true },
] as const;

export const SETTINGS_CORE = [
  { k: "Status", v: "Online", tone: "green" },
  { k: "Mode", v: "Local" },
  { k: "Host", v: "DESKTOP-HADES" },
  { k: "OS", v: "Windows 11" },
  { k: "Uptime", v: "2d 14h 37m" },
] as const;

export const SETTINGS_PROFILE = [
  { k: "E-mail", v: "hades@local" },
  { k: "Rollen", v: "Admin, Developer" },
  { k: "Organisatie", v: "Personal" },
  { k: "Lid sinds", v: "12 aug 2025" },
] as const;

export const SETTINGS_SECURITY = [
  { k: "Status", v: "Beschermd", tone: "green" },
  { k: "Firewall", v: "Actief", tone: "green" },
  { k: "Encryptie", v: "AES-256", tone: "green" },
  { k: "Laatste scan", v: "17 sep 2026, 11:02" },
] as const;

export const SETTINGS_QUICK_ACTIONS = [
  { id: "save", label: "Opslaan", icon: "save" },
  { id: "reset", label: "Resetten", icon: "refresh" },
  { id: "export", label: "Profiel exporteren", icon: "upload" },
  { id: "import", label: "Profiel importeren", icon: "download" },
  { id: "folder", label: "Open config map", icon: "folder" },
] as const;
