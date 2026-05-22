import { FLIGHT_TYPE_STYLES } from "./constants";

export function FlightTypeBadge({ type }: { type: string | null }) {
  if (!type) return <span className="text-gray-600 text-xs">—</span>;
  const style = FLIGHT_TYPE_STYLES[type] ?? {
    label: type,
    cls: "bg-gray-700 text-gray-300",
  };
  return (
    <span
      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${style.cls}`}
    >
      {style.label}
    </span>
  );
}
