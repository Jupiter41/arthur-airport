export type Workspace = "Operations" | "Planning" | "System";
export interface Destination { path: string; label: string; group: string; workspace: Workspace; restricted?: boolean }
export const destinations: Destination[] = [
  { path: "/", label: "Overview", group: "Airport", workspace: "Operations" },
  { path: "/flights", label: "Flights", group: "Airport", workspace: "Operations" },
  { path: "/ground-ops", label: "Ground operations", group: "Airfield", workspace: "Operations" },
  { path: "/atc", label: "Air traffic control", group: "Airfield", workspace: "Operations" },
  { path: "/passengers", label: "Passengers", group: "Terminal", workspace: "Operations" },
  { path: "/baggage", label: "Baggage", group: "Terminal", workspace: "Operations" },
  { path: "/accessibility", label: "Special assistance", group: "Terminal", workspace: "Operations" },
  { path: "/incidents", label: "Incidents", group: "Response", workspace: "Operations" },
  { path: "/decisions", label: "Decisions", group: "Response", workspace: "Operations" },
  { path: "/planning", label: "Experiments", group: "Isolated experiments", workspace: "Planning", restricted: true },
  { path: "/whatif", label: "Replay & compare", group: "Isolated experiments", workspace: "Planning", restricted: true },
  { path: "/history", label: "History", group: "Performance", workspace: "Planning" },
  { path: "/costs", label: "Costs", group: "Performance", workspace: "Planning" },
  { path: "/carbon", label: "Carbon", group: "Performance", workspace: "Planning" },
  { path: "/world", label: "Network", group: "Network", workspace: "Planning" },
  { path: "/settings", label: "Simulation controls", group: "Shared airport", workspace: "System" },
  { path: "/scenarios", label: "Scenarios", group: "Shared airport", workspace: "System", restricted: true },
  { path: "/lab", label: "Incident lab", group: "Shared airport", workspace: "System", restricted: true },
  { path: "/data-sources", label: "Data sources", group: "Tools", workspace: "System", restricted: true },
  { path: "/ml", label: "Model training", group: "Tools", workspace: "System", restricted: true },
  { path: "/debug", label: "Diagnostics", group: "Tools", workspace: "System", restricted: true },
  { path: "/help", label: "Help & teaching lab", group: "Guide", workspace: "System" },
];
export const availableDestinations = destinations.filter(d => !d.restricted || import.meta.env.VITE_PUBLIC_DEPLOYMENT !== "true");
