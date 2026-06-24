import { useCallback, useEffect, useRef } from "react";

type Props = {
  width: number;
  height: number;
  points: [number, number][];
  onPointsChange: (pts: [number, number][]) => void;
  closed: boolean;
  onClose: () => void;
};

export default function PolygonSvg({ width, height, points, onPointsChange, closed, onClose }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  // Defer single-click point-adds so a dblclick (which also fires two click
  // events) can cancel them before they land. Without this the close
  // double-click leaks two stray vertices into the polygon.
  const pendingClickRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pendingClickRef.current !== null) {
        clearTimeout(pendingClickRef.current);
      }
    };
  }, []);

  const toNorm = useCallback((evt: React.MouseEvent) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const x = (evt.clientX - rect.left) / rect.width;
    const y = (evt.clientY - rect.top) / rect.height;
    return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))] as [number, number];
  }, []);

  const handleSvgClick = useCallback(
    (e: React.MouseEvent) => {
      if (closed) return;
      const p = toNorm(e);
      if (!p) return;
      // Drop any in-flight pending add — the user is starting a new
      // single-click sequence (or a double-click).
      if (pendingClickRef.current !== null) {
        clearTimeout(pendingClickRef.current);
        pendingClickRef.current = null;
      }
      const snapshot = points;
      pendingClickRef.current = window.setTimeout(() => {
        pendingClickRef.current = null;
        onPointsChange([...snapshot, p]);
      }, 220);
    },
    [closed, onPointsChange, points, toNorm]
  );

  const handleSvgDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      // Cancel both pending single-clicks from this double-click sequence
      // (they're the would-be stray vertices).
      if (pendingClickRef.current !== null) {
        clearTimeout(pendingClickRef.current);
        pendingClickRef.current = null;
      }
      if (!closed && points.length >= 3) onClose();
    },
    [closed, onClose, points.length]
  );

  const dragVertex = useCallback(
    (idx: number, e: React.PointerEvent) => {
      e.stopPropagation();
      const target = e.currentTarget as SVGCircleElement;
      target.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent) => {
        const svg = svgRef.current;
        if (!svg) return;
        const rect = svg.getBoundingClientRect();
        const x = (ev.clientX - rect.left) / rect.width;
        const y = (ev.clientY - rect.top) / rect.height;
        const clamped: [number, number] = [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))];
        const next = points.slice();
        next[idx] = clamped;
        onPointsChange(next);
      };
      const up = () => {
        target.releasePointerCapture(e.pointerId);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    },
    [onPointsChange, points]
  );

  const pathD =
    points.length === 0
      ? ""
      : points
          .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x * width},${y * height}`)
          .join(" ") + (closed ? " Z" : "");

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      onClick={handleSvgClick}
      onDoubleClick={handleSvgDoubleClick}
      style={{ cursor: closed ? "default" : "crosshair" }}
    >
      {pathD && (
        <path
          d={pathD}
          fill={closed ? "rgba(78, 161, 255, 0.18)" : "none"}
          stroke="#4ea1ff"
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {points.map(([x, y], i) => (
        <circle
          key={i}
          cx={x * width}
          cy={y * height}
          r={6}
          fill="#0f1115"
          stroke="#4ea1ff"
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
          onPointerDown={(e) => dragVertex(i, e)}
          style={{ cursor: "grab" }}
        />
      ))}
    </svg>
  );
}
