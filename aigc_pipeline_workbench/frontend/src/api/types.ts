export interface InputSlot {
  name: string;
  artifact_type: string;
  required: boolean;
  accepted_mime_types: string[];
  accepted_extensions: string[];
  description?: string | null;
}

export interface OutputSlot {
  name: string;
  artifact_type: string;
  required: boolean;
  expected_mime_types: string[];
  expected_extensions: string[];
  description?: string | null;
}

export interface ModuleDefinition {
  module_id: string;
  module_key: string;
  name: string;
  description?: string | null;
  version: string;
  status: string;
  input_slots: InputSlot[];
  output_slots: OutputSlot[];
  parameter_schema: ParameterDefinition[];
  created_at: string;
  updated_at: string;
}

export interface ModuleCompatibility {
  service_id: string;
  compatible: boolean;
  reasons: string[];
}

export interface ServiceCapabilities {
  input_artifact_types: string[];
  output_artifact_types: string[];
  parameter_schema: ParameterDefinition[];
  supports_cancel: boolean;
  supports_progress: boolean;
  estimated_duration_seconds?: number | null;
  max_concurrent_jobs?: number | null;
}

export interface AlgorithmService {
  service_id: string;
  module_key: string;
  name: string;
  base_url: string;
  instance_label?: string | null;
  enabled: boolean;
  status: string;
  version: string;
  capabilities: ServiceCapabilities;
  last_error?: string | null;
}

export interface ParameterOption {
  value: string;
  label: string;
}

export interface ParameterDefinition {
  key: string;
  label: string;
  value_type: string;
  required: boolean;
  default?: unknown;
  minimum?: number | null;
  maximum?: number | null;
  options: ParameterOption[];
  description?: string | null;
}

export interface ArtifactRef {
  artifact_id: string;
  type: string;
  name?: string | null;
  uri: string;
  metadata?: Record<string, unknown>;
}

export interface JobError {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface JobProgress {
  percent?: number | null;
  phase?: string | null;
  message?: string | null;
}

export interface Job {
  module_id?: string | null;
  job_id: string;
  service_id: string;
  module_key: string;
  status: string;
  parameters: Record<string, unknown>;
  input_artifacts: ArtifactRef[];
  output_artifacts: ArtifactRef[];
  progress?: JobProgress | null;
  error?: JobError | null;
  created_at: string;
  submitted_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at: string;
  rerun_of_job_id?: string | null;
  consecutive_poll_failures: number;
  last_sync_error?: string | null;
}

export interface JobLog {
  log_id: string;
  job_id: string;
  service_id?: string | null;
  seq: number;
  source: string;
  level: string;
  message: string;
  created_at: string;
}

export interface ArtifactMetadata {
  artifact_id: string;
  type: string;
  name: string;
  mime_type?: string | null;
  size_bytes?: number | null;
  uri: string;
  metadata: Record<string, unknown>;
}
