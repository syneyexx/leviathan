export type FilesTab = "Verkenner" | "Recente activiteit" | "Gedeeld met mij" | "Favorieten" | "Prullenbak";

export type FileKind = "folder" | "file";

export type FileTagTone = "gold" | "green" | "blue" | "cyan" | "purple" | "orange" | "gray" | "teal";

export type FinalBetaFileTag = {
  label: string;
  tone: FileTagTone;
};

export type FinalBetaFileRow = {
  id: string;
  name: string;
  kind: FileKind;
  typeLabel: string;
  size: string;
  modified: string;
  owner: string;
  tags: FinalBetaFileTag[];
  favorite: boolean;
  iconTone: "gold" | "red" | "blue" | "green" | "cyan" | "gray" | "purple" | "orange";
  iconGlyph: string;
  location?: string;
  checksum?: string;
  previewType?: string;
};

export type FinalBetaFileVersion = {
  id: string;
  label: string;
  when: string;
  by: string;
  active?: boolean;
};

export type FinalBetaFolderNode = {
  id: string;
  label: string;
  icon?: "folder" | "shared" | "archive" | "trash";
  expandable?: boolean;
  children?: FinalBetaFolderNode[];
};

export const FILES_TABS: FilesTab[] = [
  "Verkenner",
  "Recente activiteit",
  "Gedeeld met mij",
  "Favorieten",
  "Prullenbak",
];

export const FILES_FOLDER_TREE: FinalBetaFolderNode[] = [
  {
    id: "hades",
    label: "HADES",
    expandable: true,
    children: [
      { id: "projecten", label: "Projecten", expandable: true },
      { id: "llm-modellen", label: "LLM modellen", expandable: true },
      { id: "datasets", label: "Datasets", expandable: true },
      { id: "training-runs", label: "Training runs" },
      { id: "evaluaties", label: "Evaluaties" },
      { id: "experimenten", label: "Experimenten", expandable: true },
      { id: "media", label: "Media" },
      {
        id: "documenten",
        label: "Documenten",
        expandable: true,
        children: [
          { id: "onderzoek", label: "Onderzoek" },
          { id: "notities", label: "Notities" },
          { id: "presentaties", label: "Presentaties" },
          { id: "rapporten", label: "Rapporten" },
        ],
      },
      { id: "exports", label: "Exports", expandable: true },
      { id: "imports", label: "Imports", expandable: true },
      { id: "gedeeld", label: "Gedeeld", icon: "shared", expandable: true },
      { id: "archief", label: "Archief", icon: "archive", expandable: true },
      { id: "prullenbak", label: "Prullenbak", icon: "trash" },
    ],
  },
];

export const FILES_QUICK_FILTERS = [
  { id: "all", label: "Alle bestanden", count: "12.481", icon: "file" },
  { id: "images", label: "Afbeeldingen", count: "842", icon: "image" },
  { id: "docs", label: "Documenten", count: "3.204", icon: "file" },
  { id: "video", label: "Video's", count: "612", icon: "play" },
  { id: "archives", label: "Archieven", count: "421", icon: "folder" },
  { id: "code", label: "Code", count: "1.186", icon: "code" },
  { id: "favorites", label: "Favorieten", count: "94", icon: "bolt" },
] as const;

export const FILES_STORAGE = {
  used: "142.6 GB",
  total: "1.0 TB",
  percent: 14,
  slices: [
    { id: "modellen", label: "Modellen", color: "#38bdf8", share: 38 },
    { id: "datasets", label: "Datasets", color: "#7dd3fc", share: 28 },
    { id: "projecten", label: "Projecten", color: "#eab94f", share: 22 },
    { id: "overig", label: "Overig", color: "#64748b", share: 12 },
  ],
} as const;

export const FILES_QUOTE = "Data is de brandstof voor een slimmere morgen.";

export const FILES_VERSIONS: FinalBetaFileVersion[] = [
  { id: "v2", label: "v2.0", when: "17 feb 2025 14:20", by: "jij", active: true },
  { id: "v13", label: "v1.3", when: "12 feb 2025 09:44", by: "jij" },
  { id: "v12", label: "v1.2", when: "4 feb 2025 16:18", by: "team" },
  { id: "v11", label: "v1.1", when: "28 jan 2025 11:02", by: "jij" },
  { id: "v10", label: "v1.0", when: "15 jan 2025 08:30", by: "jij" },
];

export const mockFileRows: FinalBetaFileRow[] = [
  {
    id: "f-alpha",
    name: "Alpha-Trader",
    kind: "folder",
    typeLabel: "Map",
    size: "—",
    modified: "17 feb 2025 14:22",
    owner: "jij",
    tags: [{ label: "trading", tone: "teal" }],
    favorite: false,
    iconTone: "gold",
    iconGlyph: "folder",
  },
  {
    id: "f-brain",
    name: "Brain-Nodes",
    kind: "folder",
    typeLabel: "Map",
    size: "—",
    modified: "16 feb 2025 09:11",
    owner: "jij",
    tags: [{ label: "llm", tone: "green" }],
    favorite: false,
    iconTone: "gold",
    iconGlyph: "folder",
  },
  {
    id: "f-dataset",
    name: "Dataset-Research",
    kind: "folder",
    typeLabel: "Map",
    size: "—",
    modified: "15 feb 2025 19:43",
    owner: "jij",
    tags: [{ label: "onderzoek", tone: "blue" }],
    favorite: true,
    iconTone: "gold",
    iconGlyph: "folder",
  },
  {
    id: "f-demos",
    name: "Klant-Demos",
    kind: "folder",
    typeLabel: "Map",
    size: "—",
    modified: "14 feb 2025 11:05",
    owner: "jij",
    tags: [{ label: "demo", tone: "purple" }],
    favorite: false,
    iconTone: "gold",
    iconGlyph: "folder",
  },
  {
    id: "f-prod",
    name: "Productie",
    kind: "folder",
    typeLabel: "Map",
    size: "—",
    modified: "12 feb 2025 08:37",
    owner: "jij",
    tags: [{ label: "release", tone: "orange" }],
    favorite: false,
    iconTone: "gold",
    iconGlyph: "folder",
  },
  {
    id: "f-temp",
    name: "Temp",
    kind: "folder",
    typeLabel: "Map",
    size: "—",
    modified: "10 feb 2025 16:21",
    owner: "jij",
    tags: [],
    favorite: false,
    iconTone: "gold",
    iconGlyph: "folder",
  },
  {
    id: "f-arch",
    name: "hades_architectuur_v2.pdf",
    kind: "file",
    typeLabel: "PDF",
    size: "4.8 MB",
    modified: "17 feb 2025 14:20",
    owner: "jij",
    tags: [
      { label: "architectuur", tone: "gold" },
      { label: "v2", tone: "gray" },
    ],
    favorite: true,
    iconTone: "red",
    iconGlyph: "pdf",
    location: "/Projecten",
    checksum: "a3f2…9c7d",
    previewType: "PDF Document",
  },
  {
    id: "f-json",
    name: "training_results_qwen25.json",
    kind: "file",
    typeLabel: "JSON",
    size: "12.4 MB",
    modified: "17 feb 2025 13:02",
    owner: "jij",
    tags: [{ label: "training", tone: "green" }],
    favorite: false,
    iconTone: "blue",
    iconGlyph: "json",
  },
  {
    id: "f-csv",
    name: "marktdata_2025.csv",
    kind: "file",
    typeLabel: "CSV",
    size: "86.1 MB",
    modified: "17 feb 2025 11:48",
    owner: "jij",
    tags: [{ label: "trading", tone: "teal" }],
    favorite: false,
    iconTone: "green",
    iconGlyph: "csv",
  },
  {
    id: "f-mp4",
    name: "demo_video.mp4",
    kind: "file",
    typeLabel: "MP4",
    size: "320.5 MB",
    modified: "16 feb 2025 18:03",
    owner: "jij",
    tags: [{ label: "media", tone: "purple" }],
    favorite: false,
    iconTone: "red",
    iconGlyph: "video",
  },
  {
    id: "f-md",
    name: "readme.md",
    kind: "file",
    typeLabel: "MD",
    size: "12 KB",
    modified: "16 feb 2025 12:11",
    owner: "jij",
    tags: [{ label: "docs", tone: "cyan" }],
    favorite: false,
    iconTone: "gray",
    iconGlyph: "md",
  },
  {
    id: "f-yaml",
    name: "config.yaml",
    kind: "file",
    typeLabel: "YAML",
    size: "3 KB",
    modified: "15 feb 2025 21:37",
    owner: "jij",
    tags: [{ label: "config", tone: "blue" }],
    favorite: false,
    iconTone: "gray",
    iconGlyph: "yaml",
  },
  {
    id: "f-xlsx",
    name: "resultaten_analyse.xlsx",
    kind: "file",
    typeLabel: "XLSX",
    size: "2.1 MB",
    modified: "15 feb 2025 16:09",
    owner: "jij",
    tags: [{ label: "analyse", tone: "gold" }],
    favorite: false,
    iconTone: "green",
    iconGlyph: "xlsx",
  },
  {
    id: "f-txt",
    name: "prompt_library.txt",
    kind: "file",
    typeLabel: "TXT",
    size: "48 KB",
    modified: "14 feb 2025 10:52",
    owner: "jij",
    tags: [{ label: "prompts", tone: "cyan" }],
    favorite: false,
    iconTone: "gray",
    iconGlyph: "txt",
  },
  {
    id: "f-safe",
    name: "model_checkpoint.safetensors",
    kind: "file",
    typeLabel: "SAFETENSORS",
    size: "6.8 GB",
    modified: "12 feb 2025 22:14",
    owner: "jij",
    tags: [
      { label: "llm", tone: "green" },
      { label: "checkpoint", tone: "blue" },
    ],
    favorite: true,
    iconTone: "purple",
    iconGlyph: "model",
  },
];

export const FILES_SELECTION_ACTIONS = [
  { id: "open", label: "Openen", tone: "outline" },
  { id: "download", label: "Downloaden", tone: "outline" },
  { id: "share", label: "Delen", tone: "outline", chevron: true },
  { id: "move", label: "Verplaatsen", tone: "outline" },
  { id: "copy", label: "Kopiëren", tone: "outline" },
  { id: "delete", label: "Verwijderen", tone: "danger" },
] as const;
