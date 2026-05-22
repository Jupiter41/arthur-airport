export interface TrainingRun {
  id: string;
  model_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  progress_pct: number;
  total_timesteps: number;
  current_timesteps: number;
  metrics: Record<string, unknown>;
  error: string | null;
  output_path: string | null;
}

export interface ModelFile {
  path: string;
  size_bytes: number;
  modified_at: string;
}

export interface TrainingStatus {
  active_run: TrainingRun | null;
  history: TrainingRun[];
  available_models: ModelFile[];
}

export interface TrainingConfig {
  rl_model_path: string;
  rl_model_exists: boolean;
  rl_model_loaded: boolean;
  models_dir: string;
  models_dir_exists: boolean;
  model_files: string[];
  env: Record<string, string>;
}
