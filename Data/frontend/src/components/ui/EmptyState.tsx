export type EmptyStateProps = {
  title: string;
  detail?: string;
  className?: string;
};

export function EmptyState({ title, detail, className = "" }: EmptyStateProps) {
  const classes = ["lv-v2-empty", className].filter(Boolean).join(" ");

  return (
    <div className={classes} role="status">
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}
