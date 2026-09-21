/** Outline icons copied from the canonical hades-pixel-ui-v3 reference. */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

const paths: Record<string, string> = {
  chat: '<path d="M4 5h16v11H9l-5 4V5Z"/>',
  check: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 12 3 3 5-6"/>',
  code: '<path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  brain: '<path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 3 3 3 0 0 0 2 3v1a3 3 0 0 0 3 3M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 3 3 3 0 0 1-2 3v1a3 3 0 0 1-3 3M9 4v16M15 4v16M9 8h3M12 12h3M9 16h3"/>',
  wrench: '<path d="M14 6a4 4 0 0 0-5 5L3 17l4 4 6-6a4 4 0 0 0 5-5l-3 2-3-3 2-3Z"/>',
  more: '<circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/>',
  folder: '<path d="M3 6h7l2 2h9v10H3V6Z"/>',
  paperclip: '<path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 1 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
  squareplus: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 8v8M8 12h8"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 4V2M20 12h2"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/>',
  upload: '<path d="M12 16V4m0 0-4 4m4-4 4 4M5 13v7h14v-7"/>',
  download: '<path d="M12 4v12m0 0 4-4m-4 4-4-4M5 20h14"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 9a7 7 0 0 1 12-2l2 5M18 15a7 7 0 0 1-12 2l-2-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  file: '<path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  sliders: '<path d="M4 7h8M16 7h4M4 17h4M12 17h8M12 4v6M8 14v6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1-2-4-2 1.2A7 7 0 0 0 15 6l-.3-2h-5L9.4 6a7 7 0 0 0-1.8 1.1L5.5 6 3 10l2 1a7 7 0 0 0 0 2l-2 1 2.5 4 2-1.2A7 7 0 0 0 9.4 18l.3 2h5l.3-2a7 7 0 0 0 1.9-1.1L19 18l2-4-2.1-1a7 7 0 0 0 .1-1Z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
  database: '<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3 3 7 3s7-1.3 7-3v-6"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m5 18 5-5 3 3 2-2 4 4"/>',
  book: '<path d="M4 5a3 3 0 0 1 3-2h5v17H7a3 3 0 0 0-3 2V5ZM20 5a3 3 0 0 0-3-2h-5v17h5a3 3 0 0 1 3 2V5Z"/>',
  chart: '<path d="M4 20V9M10 20V4M16 20v-7M22 20H2"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM17 11a3 3 0 0 0 0-6M22 21v-2a4 4 0 0 0-3-3.8"/>',
  play: '<path d="m9 7 8 5-8 5V7Z"/>',
  save: '<path d="M5 3h12l2 2v16H5V3Z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/>',
  copy: '<rect x="8" y="8" width="11" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M19 13v7H4V5h7"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  send: '<path d="m3 11 18-8-8 18-2-8-8-2Z"/><path d="m11 13 5-5"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
  terminal: '<path d="m4 6 5 5-5 5M11 18h9"/>',
  shield: '<path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  trident: '<path d="M12 22V9"/><path d="M8 5 12 2.5 16 5"/><path d="M5 9h14"/><path d="M6.5 9v2.5c0 2.2 2.2 3.8 5.5 3.8s5.5-1.6 5.5-3.8V9"/><path d="M9 9v2M15 9v2"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  grid: '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/>',
  line: '<path d="M3 17 9 11l4 3 8-8"/>',
  candle: '<path d="M6 4v16M4 8h4v6H4V8ZM14 3v18M12 6h4v8h-4V6ZM21 7v10M19 10h4v5h-4v-5Z"/>',
  checkcircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  flask: '<path d="M9 3h6M10 3v6l-5 9h14l-5-9V3"/><path d="M8.5 14h7"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  bolt: '<path d="m13 2-8 12h7l-1 8 8-12h-7l1-8Z"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
};

export type FinalBetaIconName = keyof typeof paths;

export function FbIcon({ name, size = 20, ...rest }: IconProps & { name: FinalBetaIconName | string }) {
  const d = paths[name] || '<circle cx="12" cy="12" r="8"/>';
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      dangerouslySetInnerHTML={{ __html: d }}
      {...rest}
    />
  );
}

export function moreMenuIcon(page: string): FinalBetaIconName {
  if (page === "files") return "folder";
  if (page === "media") return "image";
  if (page === "trading") return "chart";
  if (page === "agents") return "users";
  if (page === "workflows") return "list";
  if (page === "memory" || page === "knowledge") return "book";
  if (page === "evidence") return "shield";
  if (page === "models") return "database";
  if (page === "mcp") return "link";
  if (page === "performance") return "chart";
  return "settings";
}
