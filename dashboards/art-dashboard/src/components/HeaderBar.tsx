import { NavLink } from "react-router-dom";
import { SimClock } from "./SimClock";
import { WeatherStrip } from "./WeatherStrip";
import { IncidentBadge } from "./IncidentBadge";
import { SimControls } from "./SimControls";

const NAV_ITEMS = [
  { path: "/", label: "Flights" },
  { path: "/baggage", label: "Baggage" },
  { path: "/passengers", label: "Passengers" },
  { path: "/incidents", label: "Incidents" },
  { path: "/ground-ops", label: "Ground Ops" },
];

export function HeaderBar() {
  return (
    <header className="bg-gray-800 border-b border-gray-700">
      {/* Top row */}
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-blue-400">KART</span>
            <span className="text-sm text-gray-400">
              Arthur International Airport
            </span>
          </div>
          <WeatherStrip />
        </div>

        <div className="flex items-center gap-4">
          <IncidentBadge />
          <SimClock />
          <SimControls />
        </div>
      </div>

      {/* Nav row */}
      <nav className="flex gap-1 px-4 pb-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `text-xs font-medium px-3 py-1.5 rounded-t transition-colors ${
                isActive
                  ? "bg-gray-900 text-white border-t-2 border-blue-400"
                  : "text-gray-400 hover:text-white hover:bg-gray-700"
              }`
            }
            end={item.path === "/"}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
