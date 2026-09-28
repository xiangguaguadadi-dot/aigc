import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client.ts";
import type { AlgorithmService, ArtifactRef, Job, JobLog } from "../../api/types.ts";
import { useJobPolling } from "../../hooks/useJobPolling.ts";
import { ArtifactPreview } from "../../components/ArtifactPreview.tsx";
import { LogView } from "../../components/LogView.tsx";
import { MeshPreview } from "../../components/MeshPreview.tsx";
import { ParameterForm } from "../../components/ParameterForm.tsx";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "timeout"]);

interface JobListItemProps {
  job: Job;
  selected: boolean;
  onSelect: () => void;
}

function JobListItem({ job, selected, onSelect }: JobListItemProps) {
  const progress = job.progress?.percent ?? 0;
  return (
    <button type="button" className={`job-item${selected ? " selected" : ""}`} onClick={onSelect}>
      <span className="job-title">{job.job_id}</span>
      <span className={`status ${job.status}`}>{job.status}</span>
      <span className="progress-value">{progress}%</span>
    </button>
  );
}

export function ServiceWorkbench() {
  const [services, setServices] = useState<AlgorithmService[]>([]);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null);
  const [inputFile, setInputFile] = useState<File | null>(null);
  const [uploadedArtifact, setUploadedArtifact] = useState<ArtifactRef | null>(null);
  const [uploading, setUploading] = useState(false);
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [logs, setLogs] = useState<JobLog[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const selectedService = useMemo(
    () => services.find((service) => service.service_id === selectedServiceId) ?? null,
    [services, selectedServiceId],
  );

  const { job, setJob, refresh } = useJobPolling(null);

  const loadRecentJobs = async () => {
    const jobs = await api.listJobs(20);
    setRecentJobs(jobs);
    if (!selectedJobId && jobs.length > 0) setSelectedJobId(jobs[0].job_id);
  };

  useEffect(() => {
    api.listServices()
      .then((list) => {
        setServices(list);
        const online = list.find((service) => service.status === "online" && service.enabled);
        setSelectedServiceId((current) => current ?? online?.service_id ?? null);
      })
      .catch((error) => setActionError(error instanceof Error ? error.message : String(error)));

    loadRecentJobs().catch((error) => setActionError(error instanceof Error ? error.message : String(error)));
  }, []);

  useEffect(() => {
    if (!selectedService) return;
    const defaults: Record<string, unknown> = {};
    for (const definition of selectedService.capabilities.parameter_schema) {
      defaults[definition.key] = definition.default ?? null;
    }
    setParameters(defaults);
  }, [selectedServiceId, services]);

  useEffect(() => {
    if (!selectedJobId) return;
    let active = true;
    api.getJob(selectedJobId)
      .then((loaded) => { if (active) setJob(loaded); })
      .catch((error) => setActionError(error instanceof Error ? error.message : String(error)));
    api.getLogs(selectedJobId)
      .then((loadedLogs) => { if (active) setLogs(loadedLogs); })
      .catch(() => setLogs([]));
    return () => { active = false; };
  }, [selectedJobId]);

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return;
    let cancelled = false;
    const poll = window.setInterval(async () => {
      try {
        const refreshed = await refresh(job.job_id);
        if (cancelled) return;
        const lastSeq = logs.at(-1)?.seq ?? -1;
        const newLogs = await api.getLogs(job.job_id, lastSeq);
        if (!cancelled && newLogs.length > 0) setLogs((current) => [...current, ...newLogs]);
        setRecentJobs((current) => current.map((item) => (item.job_id === refreshed.job_id ? refreshed : item)));
      } catch {
      }
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [job?.job_id, job?.status, logs, refresh]);

  const handleUpload = async () => {
    if (!inputFile) return;
    setUploading(true);
    setActionError(null);
    try {
      const artifactType = inputFile.type.startsWith("image/") ? "image" : "report";
      const uploaded = await api.uploadArtifact(inputFile, artifactType);
      setUploadedArtifact({
        artifact_id: uploaded.artifact_id,
        type: uploaded.type,
        name: uploaded.name,
        uri: uploaded.uri,
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  };

  const handleRun = async () => {
    if (!selectedService || !uploadedArtifact) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const created = await api.createJob(selectedService.service_id, parameters, [uploadedArtifact]);
      setJob(created);
      setSelectedJobId(created.job_id);
      setRecentJobs((current) => [created, ...current].slice(0, 20));
      setLogs([]);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (!job) return;
    try {
      const cancelled = await api.cancelJob(job.job_id);
      setJob(cancelled);
      await refresh(job.job_id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const handleRerun = async () => {
    if (!job) return;
    try {
      const rerun = await api.rerunJob(job.job_id);
      setJob(rerun);
      setSelectedJobId(rerun.job_id);
      setRecentJobs((current) => [rerun, ...current].slice(0, 20));
      setLogs([]);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const glbArtifact = job?.output_artifacts.find((artifact) => artifact.type === "glb") ?? null;

  return (
    <main className="workbench">
      <header>
        <h1>Single-Module Debugging Workbench</h1>
        <p>Image → Job → Logs → GLB → Interactive 3D Preview</p>
      </header>

      <div className="workbench-grid">
        <aside className="panel service-panel">
          <h2>Services</h2>
          <div className="service-list">
            {services.map((service) => (
              <button
                key={service.service_id}
                type="button"
                className={`service-item${service.service_id === selectedServiceId ? " selected" : ""}`}
                onClick={() => setSelectedServiceId(service.service_id)}
              >
                <strong>{service.name}</strong>
                <span>{service.status} · {service.module_key}</span>
                <small>{service.service_id}</small>
              </button>
            ))}
          </div>

          <h2>Recent Jobs</h2>
          <div className="job-list">
            {recentJobs.map((item) => (
              <JobListItem
                key={item.job_id}
                job={item}
                selected={item.job_id === selectedJobId}
                onSelect={() => setSelectedJobId(item.job_id)}
              />
            ))}
          </div>
        </aside>

        <section className="panel detail-panel">
          {selectedService ? (
            <>
              <h2>{selectedService.name}</h2>
              <div className="metadata-grid">
                <div><span>Status</span><strong>{selectedService.status}</strong></div>
                <div><span>Version</span><strong>{selectedService.version}</strong></div>
                <div><span>Inputs</span><strong>{selectedService.capabilities.input_artifact_types.join(", ")}</strong></div>
                <div><span>Outputs</span><strong>{selectedService.capabilities.output_artifact_types.join(", ")}</strong></div>
              </div>

              <div className="run-grid">
                <section>
                  <h3>Input</h3>
                  <input type="file" accept="image/*" onChange={(event) => setInputFile(event.target.files?.[0] ?? null)} />
                  <button type="button" onClick={handleUpload} disabled={!inputFile || uploading}>
                    {uploading ? "Uploading..." : "Upload Input"}
                  </button>
                  {uploadedArtifact ? (
                    <div className="input-preview">
                      <ArtifactPreview artifact={uploadedArtifact} />
                      <small>{uploadedArtifact.artifact_id}</small>
                    </div>
                  ) : null}
                </section>

                <section>
                  <h3>Parameters</h3>
                  <ParameterForm
                    definitions={selectedService.capabilities.parameter_schema}
                    values={parameters}
                    disabled={submitting || Boolean(job && !TERMINAL_STATUSES.has(job.status))}
                    onChange={(key, value) => setParameters((current) => ({ ...current, [key]: value }))}
                  />
                  <div className="actions">
                    <button type="button" className="primary" onClick={handleRun} disabled={!uploadedArtifact || submitting}>Run</button>
                    <button
                      type="button"
                      onClick={handleCancel}
                      disabled={!job || !["queued", "running"].includes(job.status)}
                    >
                      Cancel
                    </button>
                    <button type="button" onClick={handleRerun} disabled={!job || job.status !== "succeeded"}>Rerun</button>
                  </div>
                </section>
              </div>
            </>
          ) : (
            <p className="muted">选择一个可用 Service。</p>
          )}

          {job ? (
            <div className="job-details">
              <h3>Job Details</h3>
              <div className="metadata-grid">
                <div><span>Job ID</span><strong>{job.job_id}</strong></div>
                <div><span>Status</span><strong className={`status ${job.status}`}>{job.status}</strong></div>
                <div><span>Progress</span><strong>{job.progress?.percent ?? 0}% · {job.progress?.phase ?? "unknown"}</strong></div>
                <div><span>Updated</span><strong>{new Date(job.updated_at).toLocaleString()}</strong></div>
              </div>
              <div className="progress-bar"><div style={{ width: `${job.progress?.percent ?? 0}%` }} /></div>
              <pre className="parameters-json">{JSON.stringify(job.parameters, null, 2)}</pre>
              <LogView logs={logs} error={job.error} />

              <h3>Output Artifacts</h3>
              {job.output_artifacts.length === 0 ? <p className="muted">暂无输出。</p> : (
                <div className="output-grid">
                  {job.output_artifacts.map((artifact) => (
                    <div key={artifact.artifact_id} className="artifact-card">
                      <strong>{artifact.type}</strong>
                      <span>{artifact.name ?? artifact.artifact_id}</span>
                      <a href={api.artifactFileUrl(artifact.artifact_id)} target="_blank" rel="noreferrer">Download</a>
                    </div>
                  ))}
                </div>
              )}
              {glbArtifact ? <MeshPreview artifact={glbArtifact} /> : null}
            </div>
          ) : null}
        </section>
      </div>
      {actionError ? <div className="toast error">{actionError}</div> : null}
    </main>
  );
}
