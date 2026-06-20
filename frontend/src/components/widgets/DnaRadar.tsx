import type { DnaResponse } from "../../api/dna";
import { SourcesFooter, dnaSourceToDisplaySource } from "./SourcesFooter";

const N = 5;
const CX = 180;
const CY = 130;
const R = 100;
const LABEL_R = 118;
const RINGS = [0.25, 0.5, 0.75, 1.0];
const LABELS = ["Values", "Exclusions", "Tilts", "Life Events", "Promises"];

function axisAngle(i: number): number {
  return (2 * Math.PI * i) / N - Math.PI / 2;
}

function point(i: number, r: number): { x: number; y: number } {
  const θ = axisAngle(i);
  return { x: CX + r * Math.cos(θ), y: CY + r * Math.sin(θ) };
}

function toPoints(coords: { x: number; y: number }[]): string {
  return coords.map((p) => `${p.x},${p.y}`).join(" ");
}

function labelAnchor(i: number): "start" | "middle" | "end" {
  const cosθ = Math.cos(axisAngle(i));
  if (Math.abs(cosθ) < 0.05) return "middle";
  return cosθ > 0 ? "start" : "end";
}

interface DnaRadarProps {
  dna: DnaResponse;
}

export function DnaRadar({ dna }: DnaRadarProps) {
  const counts = [
    dna.values?.length ?? 0,
    dna.exclusions?.length ?? 0,
    dna.tilts?.length ?? 0,
    dna.life_events?.length ?? 0,
    dna.promises?.length ?? 0,
  ];
  const maxCount = Math.max(...counts, 1);

  const dataCoords = counts.map((c, i) => point(i, (c / maxCount) * R));

  return (
    <div className="w-full max-w-[360px] mx-auto">
      <svg
        width="100%"
        viewBox="0 0 360 260"
        aria-label="DNA value-axis radar"
      >
        {/* Grid rings */}
        {RINGS.map((f) => (
          <polygon
            key={f}
            points={toPoints(Array.from({ length: N }, (_, i) => point(i, f * R)))}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth="1"
          />
        ))}

        {/* Axis lines */}
        {Array.from({ length: N }, (_, i) => {
          const outer = point(i, R);
          return (
            <line
              key={i}
              x1={CX}
              y1={CY}
              x2={outer.x}
              y2={outer.y}
              stroke="var(--color-border)"
              strokeWidth="1"
            />
          );
        })}

        {/* Data polygon */}
        <polygon
          points={toPoints(dataCoords)}
          fill="var(--color-blue)"
          fillOpacity="0.2"
          stroke="var(--color-blue)"
          strokeWidth="2"
        />

        {/* Vertex dots */}
        {dataCoords.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="4" fill="var(--color-blue)" />
        ))}

        {/* Axis labels */}
        {LABELS.map((label, i) => {
          const { x, y } = point(i, LABEL_R);
          return (
            <text
              key={i}
              x={x}
              y={y}
              fontSize="10"
              textAnchor={labelAnchor(i)}
              dominantBaseline="middle"
              fill="var(--color-muted)"
            >
              {label}
            </text>
          );
        })}
      </svg>
      {dna.sources.length > 0 && (
        <SourcesFooter sources={dna.sources.map(dnaSourceToDisplaySource)} />
      )}
    </div>
  );
}
