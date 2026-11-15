const paths: Record<string, string> = {
  "/": "M3 10 12 3l9 7v11h-6v-7H9v7H3Z",
  "/flights": "M12 3v18M3 11l9-4 9 4M7 21l5-3 5 3",
  "/ground-ops": "M5 3v18M19 3v18M12 4v3m0 3v4m0 3v3",
  "/atc": "M9 21h6M10 21l1-12h2l1 12M7 9h10V4H7ZM5 4h14",
  "/passengers":
    "M16 21v-2a4 4 0 0 0-8 0v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M20 21v-2a4 4 0 0 0-3-4",
  "/baggage": "M4 7h16v13H4ZM9 7V3h6v4M8 7v13M16 7v13",
  "/accessibility": "M12 4h.01M12 8v6h6l3 6M12 11H7M9 13a5 5 0 1 0 6 6",
  "/incidents": "m12 3 10 18H2ZM12 9v5M12 17h.01",
  "/decisions": "M5 3h14v18H5ZM8 8h8M8 12h8M8 16h4",
  "/planning": "M4 4h16v16H4ZM4 10h16M10 10v10",
  "/whatif": "M4 7h10a5 5 0 0 1 0 10H6M4 7l4-4M4 7l4 4",
  "/history": "M3 11a9 9 0 1 1 2 7M3 5v6h6M12 7v5l3 2",
  "/costs": "M19 6H9a6 6 0 0 0 0 12h10M4 10h12M4 14h12",
  "/carbon": "M5 19C0 5 13 2 21 3c0 12-7 19-16 16ZM5 19 16 8",
  "/world":
    "M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18",
  "/settings": "M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6",
  "/scenarios": "M5 3v18l16-9Z",
  "/lab": "M8 3h8M10 3v6L4 19v2h16v-2L14 9V3M7 15h10",
  "/data-sources":
    "M3 6c0-4 18-4 18 0s-18 4-18 0M3 6v12c0 4 18 4 18 0V6M3 12c0 4 18 4 18 0",
  "/ml":
    "M5 5h14v14H5ZM9 9h6v6H9ZM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M19 9h3M2 15h3M19 15h3",
  "/debug": "M4 8h16M4 16h16M8 3v18M16 3v18",
  "/help": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M9 9a3 3 0 1 1 4 3v2M12 17h.01",
};

export function NavigationIcon({ path }: { path: string }) {
  return (
    <svg
      aria-hidden="true"
      className="w-4 h-4 shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={paths[path] ?? paths["/"]} />
    </svg>
  );
}
