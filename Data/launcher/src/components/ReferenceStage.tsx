import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export const REFERENCE_WIDTH = 1672;
export const REFERENCE_HEIGHT = 941;

export function ReferenceStage({ children }: { children: ReactNode }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: REFERENCE_WIDTH, height: REFERENCE_HEIGHT });

  useLayoutEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const measure = () => setBox({ width: node.clientWidth, height: node.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const scale = Math.min(box.width / REFERENCE_WIDTH, box.height / REFERENCE_HEIGHT);
  const exact = Math.abs(box.width - REFERENCE_WIDTH) <= 1 && Math.abs(box.height - REFERENCE_HEIGHT) <= 1;
  const style = exact
    ? { width: REFERENCE_WIDTH, height: REFERENCE_HEIGHT, transform: "none", left: 0, top: 0 }
    : {
        width: REFERENCE_WIDTH,
        height: REFERENCE_HEIGHT,
        transform: `translate(-50%, -50%) scale(${scale})`,
      };

  return (
    <div className="viewport" ref={viewport}>
      <div className={exact ? "reference-stage is-exact" : "reference-stage"} style={style} data-scale={exact ? "1" : scale.toFixed(4)}>
        {children}
      </div>
    </div>
  );
}
