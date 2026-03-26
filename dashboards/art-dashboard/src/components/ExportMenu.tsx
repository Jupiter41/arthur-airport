import { useState, useRef, useEffect } from "react";
import type { ExportFormat } from "../utils/exportData";

export function ExportMenu({
  onExport,
}: {
  onExport: (format: ExportFormat) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-2.5 py-1.5 rounded transition-colors"
        onClick={() => setOpen(!open)}
        title="Export page data"
      >
        ⬇ Export
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 bg-gray-800 border border-gray-600 rounded shadow-lg z-50 min-w-[100px]">
          <button
            className="block w-full text-left text-xs text-gray-300 hover:bg-gray-700 px-3 py-2"
            onClick={() => {
              onExport("csv");
              setOpen(false);
            }}
          >
            Export CSV
          </button>
          <button
            className="block w-full text-left text-xs text-gray-300 hover:bg-gray-700 px-3 py-2"
            onClick={() => {
              onExport("json");
              setOpen(false);
            }}
          >
            Export JSON
          </button>
        </div>
      )}
    </div>
  );
}
