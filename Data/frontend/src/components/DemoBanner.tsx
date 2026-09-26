/** Honest DEMO marker — never present hardcoded KPI/state as live production data. */
export function DemoBanner({ children }: { children?: string }) {
  return (
    <p className="lv-demo-banner" role="status" data-demo="true">
      <strong>DEMO</strong>
      {" — "}
      {children ?? "Decorative / sample content. Not live production data."}
    </p>
  );
}
