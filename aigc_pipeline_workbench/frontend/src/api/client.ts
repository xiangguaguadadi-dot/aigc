import type { AlgorithmService, ArtifactMetadata, ArtifactRef, Job, JobLog, ModuleCompatibility, ModuleDefinition } from "./types.js";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      try {
        message = await response.text();
      } catch {
      }
    }
    throw new Error(message);
  }
  return await response.json() as T;
}

export const api = {
  health: () =>
    requestJson<{ status: string; version: string; contract_version: string }>("/api/v1/health"),

  listServices: () => requestJson<AlgorithmService[]>("/api/v1/services"),

  listModules: () => requestJson<ModuleDefinition[]>("/api/v1/modules"),

  createModule: (payload: Omit<ModuleDefinition, "module_id" | "status" | "created_at" | "updated_at">) =>
    requestJson<ModuleDefinition>("/api/v1/modules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateModule: (moduleId: string, payload: Partial<ModuleDefinition>) =>
    requestJson<ModuleDefinition>(`/api/v1/modules/${encodeURIComponent(moduleId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  moduleServices: (moduleId: string) =>
    requestJson<ModuleCompatibility[]>(`/api/v1/modules/${encodeURIComponent(moduleId)}/services`),

  checkService: (serviceId: string) =>
    requestJson<AlgorithmService>(`/api/v1/services/${encodeURIComponent(serviceId)}/check`, {
      method: "POST",
    }),

  uploadArtifact: async (file: File, artifactType: string): Promise<ArtifactMetadata> => {
    const body = new FormData();
    body.append("file", file);
    body.append("artifact_type", artifactType);
    body.append("retention", "temporary");
    return await requestJson<ArtifactMetadata>("/api/v1/artifacts", { method: "POST", body });
  },

  createJob: (serviceId: string, parameters: Record<string, unknown>, inputArtifacts: ArtifactRef[], moduleId?: string | null) =>
    requestJson<Job>("/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        service_id: serviceId,
        parameters: JSON.stringify(parameters),
        input_artifacts: JSON.stringify(inputArtifacts),
        ...(moduleId ? { module_id: moduleId } : {}),
      }),
    }),

  listJobs: (limit = 20, moduleId?: string) => requestJson<Job[]>(`/api/v1/jobs?limit=${limit}${moduleId ? `&module_id=${encodeURIComponent(moduleId)}` : ""}`),

  getJob: (jobId: string) => requestJson<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),

  cancelJob: (jobId: string) =>
    requestJson<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),

  rerunJob: (jobId: string) =>
    requestJson<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}/rerun`, { method: "POST" }),

  syncJob: (jobId: string) =>
    requestJson<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}/sync`, { method: "POST" }),

  getLogs: (jobId: string, afterSeq?: number) => {
    const query = new URLSearchParams();
    if (afterSeq !== undefined) query.set("after_seq", String(afterSeq));
    return requestJson<JobLog[]>(`/api/v1/jobs/${encodeURIComponent(jobId)}/logs?${query.toString()}`);
  },

  artifactFileUrl: (artifactId: string) => `/api/v1/artifacts/${encodeURIComponent(artifactId)}/file`,
};
