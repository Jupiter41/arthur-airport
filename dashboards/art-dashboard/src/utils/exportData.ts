/** Utility for exporting dashboard data as CSV or JSON */

type ExportFormat = "csv" | "json";

function toCsv(data: Record<string, unknown>[]): string {
  if (data.length === 0) return "";
  const headers = Object.keys(data[0]);
  const rows = data.map((row) =>
    headers
      .map((h) => {
        const val = row[h];
        const str =
          val == null
            ? ""
            : typeof val === "object"
              ? JSON.stringify(val)
              : String(val);
        return str.includes(",") || str.includes('"') || str.includes("\n")
          ? `"${str.replace(/"/g, '""')}"`
          : str;
      })
      .join(","),
  );
  return [headers.join(","), ...rows].join("\n");
}

function downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function exportData(
  data: Record<string, unknown>[],
  filename: string,
  format: ExportFormat,
) {
  if (format === "json") {
    downloadBlob(
      JSON.stringify(data, null, 2),
      `${filename}.json`,
      "application/json",
    );
  } else {
    downloadBlob(toCsv(data), `${filename}.csv`, "text/csv");
  }
}

export function exportRaw(data: unknown, filename: string) {
  downloadBlob(
    JSON.stringify(data, null, 2),
    `${filename}.json`,
    "application/json",
  );
}

export type { ExportFormat };
