export interface CypherResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
}

export interface KafkaEvent {
  id: string;
  timestamp: string;
  event_type: string;
  topic: string;
  payload: Record<string, unknown>;
}

export interface Snapshot {
  snapshot_id: string;
  name: string;
  filename: string;
  created_at: string;
  sim_time: string;
  day_number: number;
  node_count: number;
  relationship_count: number;
  size_kb: number;
}

export type TabId =
  | "inject"
  | "inspector"
  | "cypher"
  | "kafka"
  | "weather"
  | "snapshots";

export const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "inject", label: "Entity Injection", icon: "💉" },
  { id: "inspector", label: "Inspector", icon: "🔍" },
  { id: "cypher", label: "Cypher Console", icon: "⌨️" },
  { id: "kafka", label: "Kafka Inspector", icon: "📡" },
  { id: "weather", label: "Weather Source", icon: "🌤️" },
  { id: "snapshots", label: "Snapshots", icon: "📸" },
];
