import { useId } from "react";

export function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  unit?: string;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-2">
      <label htmlFor={id} className="text-sm text-gray-300">{label}{unit ? ` (${unit})` : ""}</label>
      <div className="flex items-center gap-1">
        <input
          id={id}
          type="number"
          className="w-20 bg-gray-700 text-white text-right rounded px-2 py-1 text-sm
                     border border-gray-600 focus:border-blue-400 focus:outline-none"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {unit && <span className="text-xs text-gray-400 w-8">{unit}</span>}
      </div>
    </div>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-gray-300">{label}</span>
      <button
        role="switch"
        aria-label={label}
        aria-checked={checked}
        className={`w-12 h-9 rounded-full transition-colors relative ${checked ? "bg-blue-500" : "bg-gray-600"}`}
        onClick={() => onChange(!checked)}
      >
        <span
          className={`block w-4 h-4 rounded-full bg-white absolute top-2.5 transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`}
        />
      </button>
    </div>
  );
}

export function SelectInput({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-2">
      <label htmlFor={id} className="text-sm text-gray-300">{label}</label>
      <select
        id={id}
        className="bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600
                   focus:border-blue-400 focus:outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <span>{icon}</span>
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}
