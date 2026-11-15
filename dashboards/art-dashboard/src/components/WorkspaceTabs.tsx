import { NavLink, useLocation } from "react-router-dom";

export function WorkspaceTabs() {
  const { pathname, search } = useLocation();
  const params = new URLSearchParams(search);
  const groups = [
    [
      ["/history", "History"],
      ["/costs", "Costs"],
      ["/carbon", "Carbon"],
    ],
    [
      ["/planning", "Build & compare"],
      ["/whatif", "Replay interventions"],
    ],
    [
      ["/settings", "Controls"],
      ["/scenarios", "Shared scenarios"],
      ["/lab", "Incident lab"],
    ],
  ];
  const group = groups.find((items) =>
    items.some(([path]) => path === pathname),
  );
  if (!group) return null;
  return (
    <nav
      aria-label="Workspace views"
      className="flex flex-wrap border-b border-panel-border px-4 bg-surface-card"
    >
      {group
        .filter(
          ([path]) =>
            import.meta.env.VITE_PUBLIC_DEPLOYMENT !== "true" ||
            !["/planning", "/whatif", "/scenarios", "/lab"].includes(path),
        )
        .map(([path, label]) => (
          <NavLink
            className="view-tab"
            key={path}
            to={`${path}${params.has("scenario") ? `?scenario=${encodeURIComponent(params.get("scenario")!)}` : ""}`}
          >
            {label}
          </NavLink>
        ))}
    </nav>
  );
}
