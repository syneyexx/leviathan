export type ErrorStateProps = {
  title: string;
  detail?: string;
  className?: string;
};

export function ErrorState({ title, detail, className = "" }: ErrorStateProps) {
  const classes = ["lv-v2-error", className].filter(Boolean).join(" ");

  return (
    <div className={classes} role="alert">
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}
