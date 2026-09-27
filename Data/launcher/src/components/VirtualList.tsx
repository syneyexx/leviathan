import { useEffect, useRef, useState, type ReactNode } from "react";

export function VirtualList<T>({
  items,
  rowHeight,
  render,
}: {
  items: T[];
  rowHeight: number;
  render: (item: T, index: number) => ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState(0);
  const [height, setHeight] = useState(180);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => setHeight(node.clientHeight || 180);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const start = Math.max(0, Math.floor(scroll / rowHeight) - 6);
  const count = Math.ceil(height / rowHeight) + 12;
  const slice = items.slice(start, start + count);
  return (
    <div ref={ref} className="console" onScroll={(event) => setScroll(event.currentTarget.scrollTop)}>
      <div className="vlist" style={{ height: items.length * rowHeight }}>
        {slice.map((item, index) => (
          <div key={start + index} style={{ position: "absolute", top: (start + index) * rowHeight, left: 0, right: 0, height: rowHeight }}>
            {render(item, start + index)}
          </div>
        ))}
      </div>
    </div>
  );
}
