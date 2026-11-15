import { NavigationIcon } from "./NavigationIcon";
import { useEffect, useState, useId } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { availableDestinations, type Workspace } from "./navigation";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const workspaceId = useId();
  const current =
    availableDestinations.find((d) => d.path === location.pathname)
      ?.workspace ?? "Operations";
  const [workspace, setWorkspace] = useState<Workspace>(current);
  useEffect(() => setWorkspace(current), [current]);
  const items = availableDestinations.filter((d) => d.workspace === workspace);
  return (
    <aside className="sidebar">
      <NavLink
        to="/"
        onClick={onNavigate}
        className="flex items-center gap-3 px-3 py-4 mb-3"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 32 32"
          className="w-8 h-8 text-accent"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M16 3v26M5 14l11-4 11 4M10 27l6-3 6 3" />
          <path d="M3 18h26" />
        </svg>
        <span>
          <strong className="block text-base tracking-wide">ARTHUR</strong>
          <span className="text-xs text-gray-400">International · KART</span>
        </span>
      </NavLink>
      <label className="block px-3 text-xs text-gray-400" htmlFor={workspaceId}>
        Workspace
      </label>
      <select
        id={workspaceId}
        className="m-3 mt-2 w-[calc(100%-1.5rem)]"
        value={workspace}
        onChange={(e) => {
          const value = e.target.value as Workspace;
          setWorkspace(value);
          const first = availableDestinations.find(
            (d) => d.workspace === value,
          );
          if (first) navigate(first.path);
          onNavigate?.();
        }}
      >
        <option>Operations</option>
        <option>Planning</option>
        <option>System</option>
      </select>
      <nav
        aria-label={`${workspace} navigation`}
        className="space-y-4 px-2 pb-6"
      >
        {[...new Set(items.map((i) => i.group))].map((group) => (
          <div key={group}>
            <p className="px-3 pb-1 text-xs text-gray-400">{group}</p>
            {items
              .filter((i) => i.group === group)
              .map((item) => (
                <NavLink
                  key={item.path}
                  end={item.path === "/"}
                  to={item.path}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `nav-link ${isActive ? "is-active" : ""}`
                  }
                >
                  <NavigationIcon path={item.path} />
                  {item.label}
                </NavLink>
              ))}
          </div>
        ))}
      </nav>
      <p className="mt-auto px-5 pb-4 text-xs text-gray-400">
        Digital twin
        <br />
        Synthetic operational data
      </p>
    </aside>
  );
}
