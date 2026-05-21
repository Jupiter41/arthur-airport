import type { Gate, Flight, Runway } from "../../types";

/* ──────── Gate Cell ──────── */
export function GateCell({ gate }: { gate: Gate }) {
  const gateColors: Record<string, string> = {
    available: "fill-gray-700",
    occupied: "fill-blue-800",
    boarding: "fill-green-700",
    departing: "fill-green-600",
    delayed: "fill-amber-700",
    incident: "fill-red-700",
    maintenance: "fill-gray-600",
  };

  return (
    <g>
      <rect
        width={28}
        height={22}
        rx={3}
        className={`${gateColors[gate.status] ?? "fill-gray-700"} transition-all duration-500`}
      />
      <text
        x={14}
        y={12}
        textAnchor="middle"
        className="fill-white text-[7px] font-bold"
      >
        {gate.gate_id}
      </text>
      {gate.flight_number && (
        <text
          x={14}
          y={20}
          textAnchor="middle"
          className="fill-gray-300 text-[5px]"
        >
          {gate.flight_number}
        </text>
      )}
    </g>
  );
}

/* ──────── Terminal Block ──────── */
export function TerminalBlock({
  terminal,
  gates,
  x,
  y,
}: {
  terminal: string;
  gates: Gate[];
  x: number;
  y: number;
}) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect
        width={440}
        height={40}
        rx={4}
        className="fill-gray-800/80 stroke-gray-600"
        strokeWidth={0.5}
      />
      <text x={10} y={15} className="fill-gray-400 text-[9px] font-bold">
        Terminal {terminal}
      </text>
      {gates.slice(0, 14).map((g, i) => (
        <g key={g.gate_id} transform={`translate(${10 + i * 30}, 18)`}>
          <GateCell gate={g} />
        </g>
      ))}
    </g>
  );
}

/* ──────── Runway Strip ──────── */
export function RunwayStripSVG({
  runway,
  y,
  flights,
  hasIncident,
}: {
  runway: Runway;
  y: number;
  flights: Flight[];
  hasIncident: boolean;
}) {
  const bgColor = hasIncident
    ? "fill-red-900/60"
    : runway.status === "restricted"
      ? "fill-amber-900/30"
      : "fill-gray-700/50";

  const activeFlights = flights.filter(
    (f) =>
      f.runway_id === runway.runway_id &&
      ["approach", "landed", "taxiing", "departed", "airborne"].includes(
        f.status,
      ),
  );

  return (
    <g transform={`translate(30, ${y})`}>
      {/* Runway background */}
      <rect width={500} height={30} rx={2} className={bgColor} />
      {/* Runway markings */}
      <line
        x1={20}
        y1={15}
        x2={480}
        y2={15}
        stroke="#6b7280"
        strokeWidth={1}
        strokeDasharray="8 4"
      />
      {/* Runway ID */}
      <text x={5} y={20} className="fill-white text-[10px] font-bold">
        {runway.runway_id}
      </text>
      <text x={460} y={20} className="fill-gray-400 text-[8px]">
        {runway.status === "open" ? "OPEN" : runway.status?.toUpperCase()}
      </text>

      {/* Aircraft arrows */}
      {activeFlights.slice(0, 4).map((f, i) => {
        const xPos = 80 + i * 100;
        const isLanding = ["approach", "landed"].includes(f.status);
        return (
          <g key={f.id} transform={`translate(${xPos}, 5)`}>
            <polygon
              points={isLanding ? "20,10 0,5 0,15" : "0,10 20,5 20,15"}
              className={isLanding ? "fill-teal-400" : "fill-blue-400"}
            >
              <animateTransform
                attributeName="transform"
                type="translate"
                values={isLanding ? "10,0;-5,0;10,0" : "-5,0;10,0;-5,0"}
                dur="3s"
                repeatCount="indefinite"
              />
            </polygon>
            <text
              x={10}
              y={25}
              textAnchor="middle"
              className="fill-white text-[7px] font-bold"
            >
              {f.flight_number}
            </text>
          </g>
        );
      })}

      {/* Incident overlay */}
      {hasIncident && (
        <>
          <rect width={500} height={30} rx={2} className="fill-red-600/20" />
          <text
            x={250}
            y={12}
            textAnchor="middle"
            className="fill-red-400 text-[9px] font-bold"
          >
            ⚠ INCURSION
          </text>
        </>
      )}
    </g>
  );
}
