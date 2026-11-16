/** Owner observation time. Missing evidence must never fall back to the live clock. */
export function ObservationTime({ value }: { value?: string | null }) {
  // Legacy owner timestamps without an offset follow the documented UTC clock.
  const normalized = value && (/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  const date = normalized ? new Date(normalized) : null;
  const valid = date && Number.isFinite(date.getTime());
  return (
    <p className="text-xs text-gray-400 mt-2">
      Observed: {valid ? <time dateTime={date.toISOString()}>{date.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC")}</time> : "simulation time unavailable"}
    </p>
  );
}
