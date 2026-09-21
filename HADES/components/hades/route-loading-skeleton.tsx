export function RouteLoadingSkeleton() {
  return (
    <div className="route-loading-skeleton" role="status" aria-live="polite" aria-label="Pagina laden">
      <span className="route-skeleton-title" />
      <span className="route-skeleton-line" />
      <div className="route-skeleton-grid">
        <span /><span /><span />
      </div>
      <span className="visually-hidden">Pagina laden…</span>
    </div>
  );
}
