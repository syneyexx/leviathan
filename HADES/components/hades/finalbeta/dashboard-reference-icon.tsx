import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement> & {
  name: string;
  size?: number;
};

/** Dashboard-only glyph set traced against the canonical 1672x941 reference. */
const pathMap: Record<string, string> = {
  dashboard: '<rect x="5" y="4" width="14" height="16" rx="2"/><path d="M8 8h3M8 12l2-2 2 2 4-4M8 16h8"/>',
  chat: '<path d="M4 5.5h16v11H9.5L5 20v-3.5H4z"/><path d="M8 9h8M8 12h5"/>',
  coding: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m9 9-3 3 3 3m6-6 3 3-3 3m-2-8-2 10"/>',
  mission: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2M12 3V1.8M12 22.2V21"/>',
  tasks: '<circle cx="6" cy="7" r="1.5"/><circle cx="18" cy="6" r="1.5"/><circle cx="10" cy="17" r="1.5"/><path d="M7.5 7h4.5c3 0 4.5-1 4.5-1M6 8.5v3c0 3 2 4 4 4M11.5 17H18v-4"/>',
  research: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.8 3.8 5.8 3.8 9S14.6 18.2 12 21M12 3C9.4 5.8 8.2 8.8 8.2 12s1.2 6.2 3.8 9"/>',
  media: '<path d="M5 20V8l7 3 7-3v12"/><path d="M4 20h16M7 7l5-3 5 3M7 4.6 12 7l5-2.4M9 16h6"/>',
  trading: '<path d="M4 20v-6h4v6m3 0v-9h4v9m3 0V7h2v13"/><path d="m4 10 5-4 4 2 7-6M17 2h3v3"/>',
  training: '<rect x="6" y="6" width="12" height="12" rx="1.5"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',
  agents: '<circle cx="12" cy="8" r="3"/><path d="M6.5 18c.8-3.3 2.7-5 5.5-5s4.7 1.7 5.5 5"/><path d="M8 19h8"/>',
  plugins: '<path d="m5 4 15 15M19 4 4 19"/><circle cx="5" cy="4" r="1.5"/><circle cx="19" cy="4" r="1.5"/><circle cx="4" cy="19" r="1.5"/><path d="m17.5 17.5 2.5 2.5"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1-2-4-2 1.2A7 7 0 0 0 15 6l-.3-2h-5L9.4 6a7 7 0 0 0-1.8 1.1L5.5 6 3 10l2 1a7 7 0 0 0 0 2l-2 1 2.5 4 2-1.2A7 7 0 0 0 9.4 18l.3 2h5l.3-2a7 7 0 0 0 1.9-1.1L19 18l2-4-2.1-1a7 7 0 0 0 .1-1Z"/>',
  status: '<path d="M7.2 13.8c.8-4.7 3.7-7.2 8.4-7.1-1.1 4.2-3.8 6.7-8.4 7.1Z" fill="currentColor" stroke="none"/><path d="M16.8 10.2c-.3 4.2-2.7 7-7 7.6.4-3.9 2.8-6.4 7-7.6Z" fill="currentColor" stroke="none"/>',
  runtime: '<rect x="6" y="6" width="12" height="12" rx="1.5"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3"/>',
  check: '<path d="m6 12 4 4 8-9"/>',
  gpu: '<path d="m12 6 5 3.4-1.9 6.2H8.9L7 9.4 12 6Z" fill="currentColor" fill-opacity=".92" stroke="none"/><path d="m9.6 10.2 2.2 1.5 2.7-2M10 15.6l-1.6 2.1M14 15.6l1.6 2.1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
  sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M5 5l1.8 1.8M17.2 17.2 19 19M19 5l-1.8 1.8M6.8 17.2 5 19"/>',
  power: '<circle cx="12" cy="12" r="8.2"/><path d="M12 6v6"/><path d="M8.6 8.4a5.2 5.2 0 1 0 6.8 0"/>',
  activity: '<path d="m12 3 1.5 4.6 4.8.1-3.8 2.9 1.4 4.7-3.9-2.8-3.9 2.8 1.4-4.7-3.8-2.9 4.8-.1L12 3Z" fill="currentColor" stroke="none"/>',
  results: '<path d="M5 8h14v11H5z"/><path d="M8 8V5.5h8V8M9 12h6M9 15h4"/>',
  performance: '<rect x="5" y="5" width="14" height="14" rx="2"/><circle cx="12" cy="12" r="2.2"/><path d="M12 7.5v1.2M12 15.3v1.2M7.5 12h1.2M15.3 12h1.2"/>',
  distribution: '<path d="m12 3.5 6.5 3.7L12 11 5.5 7.2 12 3.5Z"/><path d="m5.5 11.3 6.5 3.8 6.5-3.8M5.5 15.4l6.5 3.8 6.5-3.8"/>',
  warning: '<path d="M12 4 3.5 19h17L12 4Z"/><path d="M12 9v4M12 16h.01"/>',
  codeagent: '<path d="m8 9-3 3 3 3m8-6 3 3-3 3M14 5l-4 14"/>',
  researchagent: '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4M8 11h6M11 8v6"/>',
  mediaagent: '<path d="M5 7h14v10H5z"/><path d="m10 10 5 2.5-5 2.5z"/>',
  tradingagent: '<path d="M4 19V9m5 10v-6m5 6V7m5 12V4"/><path d="m4 12 5-3 5 2 6-6"/>',
  modelresult: '<path d="M5 6h14v12H5z"/><path d="M8 9h8M8 12h8M8 15h5"/>',
  datasetresult: '<rect x="6" y="5" width="12" height="14" rx="1.5"/><path d="M9 9h6M9 12h6M9 15h4"/>',
  coderesult: '<circle cx="12" cy="12" r="9"/><path d="m9 9-3 3 3 3m6-6 3 3-3 3"/>',
  webresult: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.4 2.8 3.5 5.8 3.5 9S14.4 18.2 12 21M12 3C9.6 5.8 8.5 8.8 8.5 12s1.1 6.2 3.5 9"/>',
  videoresult: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
  coreagent: '<path d="M12 4 6 7v5c0 4 2.5 6.5 6 8 3.5-1.5 6-4 6-8V7l-6-3Z"/><path d="M9 12h6M12 9v6"/>',
  knowledgeagent: '<path d="M5 6 12 3l7 3v12l-7 3-7-3V6Z"/><path d="M9 10h6M9 13h6M9 16h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  magnify: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4.5 4.5"/>',
};

export function DashboardReferenceIcon({ name, size = 20, ...props }: Props) {
  const markup = pathMap[name] ?? '<circle cx="12" cy="12" r="8"/>';
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      dangerouslySetInnerHTML={{ __html: markup }}
      {...props}
    />
  );
}
