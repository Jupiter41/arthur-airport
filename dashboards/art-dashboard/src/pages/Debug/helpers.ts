export function inferTopic(eventType: string): string {
  if (eventType.startsWith("Flight")) return "flights.events";
  if (eventType.startsWith("Passenger")) return "passengers.events";
  if (eventType.startsWith("Baggage")) return "baggage.events";
  if (eventType.startsWith("Weather") || eventType.startsWith("METAR"))
    return "weather.events";
  if (eventType.startsWith("Incident")) return "incidents.events";
  if (eventType.startsWith("Sim") || eventType.startsWith("Snapshot"))
    return "sim.clock";
  return "unknown";
}

export const CATEGORY_COLORS: Record<string, string> = {
  CAVOK: "#22c55e",
  VMC: "#3b82f6",
  IMC: "#f59e0b",
  LIFR: "#ef4444",
};
