import { useState, useMemo, useCallback } from "react";

export type SortDir = "asc" | "desc";

export interface SortState<K extends string> {
  column: K;
  direction: SortDir;
}

export function useSort<K extends string>(defaultColumn: K, defaultDir: SortDir = "asc") {
  const [sort, setSort] = useState<SortState<K>>({ column: defaultColumn, direction: defaultDir });

  const toggle = useCallback(
    (col: K) => {
      setSort((prev) =>
        prev.column === col
          ? { column: col, direction: prev.direction === "asc" ? "desc" : "asc" }
          : { column: col, direction: "asc" },
      );
    },
    [],
  );

  return { sort, toggle };
}

/** Generic comparator for sortable values */
export function compare(a: unknown, b: unknown, dir: SortDir): number {
  const mul = dir === "asc" ? 1 : -1;

  if (a == null && b == null) return 0;
  if (a == null) return mul;
  if (b == null) return -mul;

  if (typeof a === "number" && typeof b === "number") return (a - b) * mul;
  return String(a).localeCompare(String(b)) * mul;
}

/** Sort indicator arrow for column headers */
export function SortArrow<K extends string>({
  column,
  sort,
}: {
  column: K;
  sort: SortState<K>;
}) {
  if (sort.column !== column) return <span className="ml-1 text-gray-600">⇅</span>;
  return <span className="ml-1 text-blue-400">{sort.direction === "asc" ? "▲" : "▼"}</span>;
}
