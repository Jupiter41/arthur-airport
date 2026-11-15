import { useEffect, useState, useRef, type RefObject } from "react";
import { useLocation, Link } from "react-router-dom";
import { SimClock } from "./SimClock";
import { ConnectionStatus } from "./ConnectionStatus";
import { AccessBar } from "./AccessBar";
import { availableDestinations } from "./navigation";
import { CommandPalette } from "./CommandPalette";

export function HeaderBar({
  onMenu,
  menuRef,
}: {
  onMenu: () => void;
  menuRef?: RefObject<HTMLButtonElement>;
}) {
  const searchTrigger = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const destination = availableDestinations.find(
    (d) => d.path === location.pathname,
  );
  const [search, setSearch] = useState(false);
  const [theme, setTheme] = useState(() =>
    localStorage.getItem("airport-theme") === "light" ? "light" : "dark",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("airport-theme", theme);
  }, [theme]);
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearch((v) => !v);
      }
    };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);
  return (
    <header className="app-header">
      <div className="flex items-center gap-3 min-w-0">
        <button
          className="btn-secondary lg:hidden"
          onClick={onMenu}
          aria-label="Open navigation"
          ref={menuRef}
        >
          Menu
        </button>
        <div>
          <p className="text-xs text-gray-400">
            {destination?.workspace ?? "Operations"}
          </p>
          <p className="font-medium">{destination?.label ?? "Airport"}</p>
        </div>
      </div>
      <div className="flex items-center flex-wrap gap-2">
        <button
          className="btn-secondary text-sm"
          ref={searchTrigger}
          onClick={() => setSearch(true)}
        >
          Search{" "}
          <kbd className="hidden xl:inline text-xs text-gray-400">Ctrl K</kbd>
        </button>
        <button
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          className="btn-secondary text-sm"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        <AccessBar />
      </div>
      <div className="basis-full flex flex-wrap items-center justify-between gap-2 text-xs border-t border-panel-border pt-2">
        <SimClock />
        <div className="flex gap-3 items-center">
          <ConnectionStatus />
          <Link className="text-gray-300" to="/settings">
            Simulation controls
          </Link>
        </div>
      </div>
      {search && (
        <CommandPalette
          returnFocus={searchTrigger.current}
          onClose={() => setSearch(false)}
        />
      )}
    </header>
  );
}
