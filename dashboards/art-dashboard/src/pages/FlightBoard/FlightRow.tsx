import { memo } from "react";
import type { Flight } from "../../types";
import { StatusBadge } from "../../components/StatusBadge";
import { FlightTypeBadge } from "./FlightTypeBadge";
import { formatTime } from "./helpers";

export const FlightRow = memo(function FlightRow({
  flight,
  isFlashing,
  onClick,
}: {
  flight: Flight;
  isFlashing: boolean;
  onClick: () => void;
}) {
  const statusFlash = isFlashing ? "ring-2 ring-blue-400 bg-gray-700" : "";

  return (
    <tr
      className={`border-b border-gray-800 hover:bg-gray-800/60 cursor-pointer transition-all duration-500 ${statusFlash}`}
      onClick={onClick}
    >
      <td className="px-3 py-2">
        <button
          className="font-semibold text-accent"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
          aria-label={`Inspect ${flight.flight_number}`}
        >
          {flight.flight_number}
        </button>
        <span className="ml-2 text-xs bg-gray-700 text-gray-300 px-1.5 rounded">
          {flight.airline_code}
        </span>
      </td>
      <td className="px-3 py-2">
        <FlightTypeBadge type={flight.flight_type} />
      </td>
      <td className="px-3 py-2 text-sm text-gray-300">
        {flight.origin_iata} → {flight.destination_iata}
      </td>
      <td className="px-3 py-2 text-sm text-gray-400 font-mono">
        {flight.gate_id ?? "—"}
      </td>
      <td className="px-3 py-2 text-sm font-mono">
        {flight.delay_minutes > 0 &&
        flight.estimated_time &&
        formatTime(flight.estimated_time) !==
          formatTime(flight.scheduled_time) ? (
          <>
            <span className="line-through text-gray-500">
              {formatTime(flight.scheduled_time)}
            </span>
            <span
              className={`ml-2 ${
                flight.delay_minutes >= 30
                  ? "text-red-400"
                  : flight.delay_minutes >= 10
                    ? "text-amber-400"
                    : "text-amber-400"
              }`}
            >
              {formatTime(flight.estimated_time)}
            </span>
          </>
        ) : (
          <span
            className={
              flight.status === "airborne" || flight.status === "departed"
                ? "text-green-400"
                : "text-gray-300"
            }
          >
            {formatTime(flight.scheduled_time)}
          </span>
        )}
      </td>
      <td className="px-3 py-2">
        <StatusBadge
          status={flight.status}
          delay={flight.delay_minutes}
          direction={flight.direction}
        />
      </td>
      <td className="px-3 py-2 tabular-nums">
        {flight.delay_minutes > 0 ? (
          <span className="text-amber-300">+{flight.delay_minutes} min</span>
        ) : (
          <span className="text-gray-400">On time</span>
        )}
      </td>
    </tr>
  );
});
