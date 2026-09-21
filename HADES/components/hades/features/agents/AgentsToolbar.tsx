import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";

type AgentsToolbarProps = {
  query: string;
  status: string;
  role: string;
  provider: string;
  model: string;
  activeOnly: boolean;
  errorOnly: boolean;
  roles: string[];
  providers: string[];
  models: string[];
  onQueryChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onRoleChange: (value: string) => void;
  onProviderChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onActiveOnlyChange: (value: boolean) => void;
  onErrorOnlyChange: (value: boolean) => void;
};

export function AgentsToolbar({
  query,
  status,
  role,
  provider,
  model,
  activeOnly,
  errorOnly,
  roles,
  providers,
  models,
  onQueryChange,
  onStatusChange,
  onRoleChange,
  onProviderChange,
  onModelChange,
  onActiveOnlyChange,
  onErrorOnlyChange,
}: AgentsToolbarProps) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <label className="inline-search min-w-[16rem] flex-1">
        <Search />
        <Input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Zoek op naam, id, taak of fout…" aria-label="Agents zoeken" />
      </label>
      <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={status} onChange={(event) => onStatusChange(event.target.value)} aria-label="Filter op status">
        <option value="all">Alle statussen</option>
        <option value="idle">Idle</option>
        <option value="running">Running</option>
        <option value="busy">Busy</option>
        <option value="error">Error</option>
        <option value="disabled">Disabled</option>
        <option value="unavailable">Unavailable</option>
      </select>
      <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={role} onChange={(event) => onRoleChange(event.target.value)} aria-label="Filter op type">
        <option value="all">Alle types</option>
        {roles.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={provider} onChange={(event) => onProviderChange(event.target.value)} aria-label="Filter op provider">
        <option value="all">Alle providers</option>
        {providers.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={model} onChange={(event) => onModelChange(event.target.value)} aria-label="Filter op model">
        <option value="all">Alle modellen</option>
        {models.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <label className="flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 text-xs text-muted-foreground">
        <input type="checkbox" checked={activeOnly} onChange={(event) => onActiveOnlyChange(event.target.checked)} />
        Alleen actief
      </label>
      <label className="flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 text-xs text-muted-foreground">
        <input type="checkbox" checked={errorOnly} onChange={(event) => onErrorOnlyChange(event.target.checked)} />
        Alleen fouten
      </label>
    </div>
  );
}
