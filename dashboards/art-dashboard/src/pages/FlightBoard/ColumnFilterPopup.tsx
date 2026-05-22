import { useState, useEffect, useRef } from "react";

export function FilterIcon({ active }: { active: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill={active ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`inline-block ml-1 ${active ? "text-blue-400" : "text-gray-500"}`}
    >
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}

export function ColumnFilterPopup({
  type,
  value,
  onChange,
  options,
  placeholder,
}: {
  type: "text" | "select";
  value: string;
  onChange: (v: string) => void;
  options?: { value: string; label: string }[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const isActive = value !== "";

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className={`p-0.5 rounded transition-colors ${
          isActive
            ? "text-blue-400 hover:text-blue-300"
            : "text-gray-500 hover:text-gray-300"
        }`}
        title={isActive ? `Filtered: ${value}` : "Filter this column"}
      >
        <FilterIcon active={isActive} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-2 min-w-[140px]">
          {type === "text" ? (
            <input
              type="text"
              placeholder={placeholder ?? "Filter…"}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              autoFocus
              className="text-xs bg-gray-700 text-gray-200 border border-gray-600 rounded px-2 py-1.5 w-full focus:outline-none focus:ring-1 focus:ring-blue-500/50 placeholder-gray-500"
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false);
                if (e.key === "Enter") setOpen(false);
              }}
            />
          ) : (
            <select
              value={value}
              onChange={(e) => {
                onChange(e.target.value);
                setOpen(false);
              }}
              autoFocus
              className="text-xs bg-gray-700 text-gray-200 border border-gray-600 rounded px-2 py-1.5 w-full focus:outline-none focus:ring-1 focus:ring-blue-500/50"
            >
              {options?.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          )}
          {isActive && (
            <button
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
              className="mt-1.5 text-[10px] text-gray-400 hover:text-white w-full text-center py-0.5 rounded hover:bg-gray-700 transition-colors"
            >
              Clear filter
            </button>
          )}
        </div>
      )}
    </div>
  );
}
