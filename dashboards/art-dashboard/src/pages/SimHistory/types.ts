export interface DaySummary {
  day_number: number;
  sim_date: string;
  flights_total: number;
  flights_cancelled: number;
  flights_delayed: number;
  avg_delay_minutes: number;
  passengers_total: number;
  incidents_total: number;
  max_severity: string | null;
}

export interface HistoryResponse {
  current_day: number;
  days: DaySummary[];
}

export interface WeatherHistoryEntry {
  category: string;
  from: string;
  to: string;
  duration_minutes: number;
}

export interface TimelineEvent {
  time: string;
  type: "weather" | "incident" | "flight";
  severity?: string;
  message: string;
}

export const DAYS_PER_PAGE = 20;
