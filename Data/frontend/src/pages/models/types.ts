export type FilterKey =
  | "all"
  | "local"
  | "remote"
  | "api"
  | "loaded"
  | "available"
  | "active"
  | "offline"
  | "error"
  | string;

export type SortKey = "name" | "provider" | "recent" | "size" | "parameters" | "context" | "status";
