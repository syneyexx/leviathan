export function Sparkline({ samples, color, chart = "line" }: { samples: Array<number | null>; color: string; chart?: "line" | "bars" }) {
  const values = samples.filter((value): value is number => typeof value === "number");
  if (values.length < 2) return <div className="spark" aria-label="UNMEASURED" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  if (chart === "bars") {
    const gap = 0.7;
    const width = (100 - gap * (samples.length - 1)) / samples.length;
    return (
      <div className="spark">
        <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
          {samples.map((value, index) => {
            if (typeof value !== "number") return null;
            const height = 4 + ((value - min) / span) * 26;
            return <rect key={index} x={index * (width + gap)} y={32 - height} width={width} height={height} fill={color} />;
          })}
        </svg>
      </div>
    );
  }
  const step = 100 / (samples.length - 1);
  const points = samples
    .map((value, index) => {
      if (typeof value !== "number") return null;
      const x = index * step;
      const y = 28 - ((value - min) / span) * 24;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
  return (
    <div className="spark">
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
        <polyline fill="none" stroke={color} strokeWidth="1.6" points={points} />
        <polyline fill={`${color}22`} stroke="none" points={`0,32 ${points} 100,32`} />
      </svg>
    </div>
  );
}
