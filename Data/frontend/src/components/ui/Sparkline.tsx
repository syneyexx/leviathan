export type SparklineProps = {
  values: Array<number | null>;
  width?: number;
  height?: number;
  className?: string;
  stroke?: string;
};

export function Sparkline({
  values,
  width = 56,
  height = 36,
  className = "",
  stroke = "currentColor",
}: SparklineProps) {
  const points = values.filter((v): v is number => v !== null && Number.isFinite(v));

  if (points.length < 2) {
    return <svg className={className} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" />;
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const padY = 2;

  const polyline = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - padY - ((value - min) / range) * (height - padY * 2);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={polyline}
        fill="none"
        stroke={stroke}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
