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
        <span className="font-bold text-white">{flight.flight_number}</span>
        <span className="ml-2 text-xs bg-gray-700 text-gray-300 px-1.5 rounded">
          {flight.airline_code}
        </span>
      </td>
      <td className="px-3 py-2">
        <FlightTypeBadge type={flight.flight_type} />
      </td>
      <td className="px-3 py-2 text-sm text-gray-300">
        {flight.direction === "departure"
          ? flight.destination_iata
          : flight.origin_iata}
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
        <StatusBadge status={flight.status} delay={flight.delay_minutes} direction={flight.direction} />
      </td>
      <td className="px-3 py-2">
        {flight.status === "boarding" && (
          <div className="flex items-center gap-2">
            <div className="w-20 bg-gray-700 rounded-full h-2">
              <div
                className="bg-green-500 h-2 rounded-full transition-all duration-700"
                style={{
                  width: `${flight.pax_count > 0 ? Math.round((flight.pax_boarded / flight.pax_count) * 100) : 0}%`,
                }}
              />
            </div>
            <span className="text-xs text-gray-400">
              {flight.pax_boarded}/{flight.pax_count}
            </span>
          </div>
        )}
        {flight.direction === "arrival" &&
          ["approach", "landed", "taxiing", "at_gate", "arrived"].includes(
            flight.status,
          ) && (
            <span className="text-xs text-gray-400">
              {flight.pax_count > 0 ? `${flight.pax_count} pax` : "—"}
            </span>
          )}
        {flight.direction === "departure" &&
          ["airborne", "arrived"].includes(flight.status) &&
          flight.arrival_estimated_time && (
            <span className="text-xs text-gray-400">
              ETA {formatTime(flight.arrival_estimated_time)}
              {flight.status === "arrived" && (
                <span className="ml-1 text-green-400">✓</span>
              )}
            </span>
          )}
      </td>
    </tr>
  );
});
