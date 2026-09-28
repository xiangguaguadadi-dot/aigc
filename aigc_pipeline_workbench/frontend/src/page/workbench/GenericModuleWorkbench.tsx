import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client.ts";
import type { AlgorithmService, ArtifactRef, Job, JobLog, ModuleDefinition } from "../../api/types.ts";
import { useJobPolling } from "../../hooks/useJobPolling.ts";
import { LogView } from "../../components/LogView.tsx";
import { MeshPreview } from "../../components/MeshPreview.tsx";
import { ParameterForm } from "../../components/ParameterForm.tsx";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "timeout"]);

interface JobListItemProps { job: Job; selected: boolean; onSelect: () => void; }
function JobListItem({ job, selected, onSelect }: JobListItemProps) {
  return (
    <button type="button" className={`job-item${selected ? " selected" : ""}`} onClick={onSelect}>
      <span className="job-title">{job.job_id}</span>
      <span className={`status ${job.status}`}>{job.status}</span>
      <span className="progress-value">{job.progress?.percent ?? 0}%</span>
    </button>
  );
}

export function GenericModuleWorkbench({ module, onBack }: { module: ModuleDefinition; onBack?: () => void }) {
  const [services, setServices] = useState<AlgorithmService[]>([]);
  const [compatibilities, setCompatibilities] = useState<Record<string, boolean>>({});
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null);
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [uploaded, setUploaded] = useState<Record<string, ArtifactRef>>({});
  const [uploading, setUploading] = useState(false);
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [logs, setLogs] = useState<JobLog[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [existingArtifactOptions, setExistingArtifactOptions] = useState<Record<string, { artifact: ArtifactRef; jobId: string }[]>>({});
  const [showExistingPicker, setShowExistingPicker] = useState<Record<string, boolean>>({});

  const selectedService = useMemo(() => services.find((service) => service.service_id === selectedServiceId) ?? null, [services, selectedServiceId]);
  const compatibleServices = services.filter((service) => compatibilities[service.service_id] && service.enabled);
  const { job, setJob, refresh } = useJobPolling(null);
  const requiredReady = module.input_slots.filter((slot) => slot.required).every((slot) => uploaded[slot.name]);

  const loadRecentJobs = async () => {
    const jobs = await api.listJobs(20, module.module_id);
    setRecentJobs(jobs);
    if (!selectedJobId && jobs.length > 0) setSelectedJobId(jobs[0].job_id);
    // Build existing artifact options from recent job outputs
    const options: Record<string, { artifact: ArtifactRef; jobId: string }[]> = {};
    for (const slot of module.input_slots) {
      const compatible: { artifact: ArtifactRef; jobId: string }[] = [];
      for (const recentJob of jobs) {
        if (recentJob.status !== "succeeded" && recentJob.status !== "failed") continue;
        for (const artifact of recentJob.output_artifacts) {
          if (artifact.type === slot.artifact_type || artifact.type === "unknown") {
            // Also match accepted extensions via the slot definition
            compatible.push({ artifact, jobId: recentJob.job_id });
          }
        }
      }
      if (compatible.length > 0) options[slot.name] = compatible;
    }
    setExistingArtifactOptions(options);
  };

  useEffect(() => {
    api.listServices().then(async (list) => {
      setServices(list);
      const compatibility = await api.moduleServices(module.module_id);
      const map: Record<string, boolean> = {};
      for (const item of compatibility) map[item.service_id] = item.compatible;
      setCompatibilities(map);
      const compatible = list.find((service) => map[service.service_id] && service.status === "online" && service.enabled);
      setSelectedServiceId(compatible?.service_id ?? null);
    }).catch((error) => setActionError(error instanceof Error ? error.message : String(error)));
    loadRecentJobs().catch((error) => setActionError(error instanceof Error ? error.message : String(error)));
  }, [module.module_id]);

  useEffect(() => {
    if (module.module_key === "frontend_demo") {
      api.getJob("job_frontend_demo").then((job) => {
        setJob(job);
        setSelectedJobId(job.job_id);
        setRecentJobs((current) => current.some((item) => item.job_id === job.job_id) ? current : [job, ...current]);
      }).catch((error) => setActionError(error instanceof Error ? error.message : String(error)));
    }
  }, [module.module_id]);

  useEffect(() => {
    const defaults: Record<string, unknown> = {};
    for (const definition of module.parameter_schema) defaults[definition.key] = definition.default ?? null;
    setParameters(defaults);
  }, [module.module_id]);

  useEffect(() => {
    if (!selectedJobId) return;
    let active = true;
    api.getJob(selectedJobId).then((loaded) => { if (active) setJob(loaded); }).catch(() => {});
    api.getLogs(selectedJobId).then((loadedLogs) => { if (active) setLogs(loadedLogs); }).catch(() => setLogs([]));
    return () => { active = false; };
  }, [selectedJobId]);

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return;
    let cancelled = false;
    const poll = window.setInterval(async () => {
      try {
        const refreshed = await refresh(job.job_id);
        const lastSeq = logs.at(-1)?.seq ?? -1;
        const newLogs = await api.getLogs(job.job_id, lastSeq);
        if (!cancelled && newLogs.length > 0) setLogs((current) => [...current, ...newLogs]);
        if (!cancelled) setRecentJobs((current) => current.map((item) => item.job_id === refreshed.job_id ? refreshed : item));
      } catch {}
    }, 1000);
    return () => { cancelled = true; window.clearInterval(poll); };
  }, [job?.job_id, job?.status, logs, refresh]);

  const handleUpload = async (slotName: string, artifactType: string) => {
    const file = files[slotName];
    if (!file) return;
    setUploading(true); setActionError(null);
    try {
      const artifact = await api.uploadArtifact(file, artifactType);
      setUploaded((current) => ({ ...current, [slotName]: { artifact_id: artifact.artifact_id, type: artifact.type, name: artifact.name, uri: artifact.uri } }));
    } catch (error) { setActionError(error instanceof Error ? error.message : String(error)); } finally { setUploading(false); }
  };

  const handleRun = async () => {
    if (!selectedServiceId) return;
    setSubmitting(true); setActionError(null);
    try {
      const created = await api.createJob(selectedServiceId, parameters, Object.values(uploaded).filter(Boolean), module.module_id);
      const submitted = await api.getJob(created.job_id);
      setJob(submitted); setSelectedJobId(created.job_id); setRecentJobs((current) => [submitted, ...current]);
    } catch (error) { setActionError(error instanceof Error ? error.message : String(error)); } finally { setSubmitting(false); }
  };

  const handleCancel = async () => { if (!job) return; try { setJob(await api.cancelJob(job.job_id)); } catch (error) { setActionError(error instanceof Error ? error.message : String(error)); } };
  const handleRerun = async () => { if (!job) return; try { const rerun = await api.rerunJob(job.job_id); setJob(await api.getJob(rerun.job_id)); } catch (error) { setActionError(error instanceof Error ? error.message : String(error)); } };

  const mappedOutputs = useMemo(() => {
    const mapped: Record<string, NonNullable<Job["output_artifacts"]>> = {};
    const unmapped: NonNullable<Job["output_artifacts"]> = [];
    for (const artifact of job?.output_artifacts ?? []) {
      const slotName = typeof artifact.metadata?.output_slot === "string" ? artifact.metadata.output_slot : null;
      const slot = slotName ? module.output_slots.find((definition) => definition.name === slotName) : undefined;
      if (slot) (mapped[slot.name] ??= []).push(artifact);
      else unmapped.push(artifact);
    }
    const missingRequired = module.output_slots.filter((slot) => slot.required && !mapped[slot.name]).map((slot) => slot.name);
    return { mapped, unmapped, missingRequired };
  }, [job?.output_artifacts, module.output_slots]);
  const glbArtifact = job?.output_artifacts.find((artifact) => artifact.type === "glb" || artifact.type === "mesh");

  return (
    <main className="app">
      <header className="app-header"><h1>{module.name}</h1><span className={`status ${module.status}`}>{module.status}</span></header>
      <div className="workbench-layout">
        <aside className="panel sidebar">
          <h2>Compatible Services</h2>
          <div className="service-list">
            {compatibleServices.map((service) => (
              <button key={service.service_id} type="button" className={`service-item${service.service_id === selectedServiceId ? " selected" : ""}`} onClick={() => setSelectedServiceId(service.service_id)}>
                <strong>{service.name}</strong><span>{service.status}</span>
              </button>
            ))}
            {compatibleServices.length === 0 ? <p className="muted">No compatible service.</p> : null}
          </div>
          <h2>Recent Jobs</h2>
          <div className="job-list">{recentJobs.map((item) => <JobListItem key={item.job_id} job={item} selected={item.job_id === selectedJobId} onSelect={() => setSelectedJobId(item.job_id)} />)}</div>
        </aside>
        <section className="panel detail-panel">
          <div className="run-grid">
            <section>
              <h3>Inputs</h3>
              {module.input_slots.map((slot) => (
                <div key={slot.name} className="slot-input">
                  <strong>{slot.name}{slot.required ? " *" : ""}</strong>
                  <div className="slot-input-controls">
                    <input type="file" accept={slot.accepted_extensions.join(",") || slot.accepted_mime_types.join(",")} onChange={(event) => setFiles((current) => ({ ...current, [slot.name]: event.target.files?.[0] ?? null }))} />
                    <button type="button" onClick={() => handleUpload(slot.name, slot.artifact_type)} disabled={!files[slot.name] || uploading}>Upload</button>
                    {(existingArtifactOptions[slot.name]?.length ?? 0) > 0 ? (
                      <button type="button" className="secondary" onClick={() => setShowExistingPicker((current) => ({ ...current, [slot.name]: !current[slot.name] }))}>
                        {showExistingPicker[slot.name] ? "Hide Existing" : "Use Existing"}
                      </button>
                    ) : null}
                  </div>
                  {showExistingPicker[slot.name] && existingArtifactOptions[slot.name] ? (
                    <div className="existing-artifact-list">
                      {existingArtifactOptions[slot.name].map((item) => (
                        <button key={item.artifact.artifact_id} type="button" className="existing-artifact-item" onClick={() => {
                          setUploaded((current) => ({ ...current, [slot.name]: item.artifact }));
                          setShowExistingPicker((current) => ({ ...current, [slot.name]: false }));
                        }}>
                          <small>{item.artifact.name ?? item.artifact.artifact_id} (from {item.jobId})</small>
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {uploaded[slot.name] ? <small className="uploaded-label">{uploaded[slot.name].name ?? uploaded[slot.name].artifact_id}</small> : null}
                </div>
              ))}
            </section>
            <section>
              <h3>Parameters</h3>
              <ParameterForm definitions={module.parameter_schema} values={parameters} disabled={submitting} onChange={(key, value) => setParameters((current) => ({ ...current, [key]: value }))} />
              <div className="actions">
                <button type="button" className="primary" onClick={handleRun} disabled={!requiredReady || !selectedServiceId || submitting}>Run</button>
                <button type="button" onClick={handleCancel} disabled={!job || !["queued", "running"].includes(job.status)}>Cancel</button>
                <button type="button" onClick={handleRerun} disabled={!job || job.status !== "succeeded"}>Rerun</button>
              </div>
            </section>
          </div>
          {job ? (
            <div className="job-details">
              <h3>Job Details</h3>
              <div className="metadata-grid">
                <div><span>Job ID</span><strong>{job.job_id}</strong></div>
                <div><span>Status</span><strong className={`status ${job.status}`}>{job.status}</strong></div>
                <div><span>Progress</span><strong>{job.progress?.percent ?? 0}% ? {job.progress?.phase ?? "unknown"}</strong></div>
              </div>
              <div className="progress-bar"><div style={{ width: `${job.progress?.percent ?? 0}%` }} /></div>
              <LogView logs={logs} error={job.error} />
              <h3>Output Artifacts</h3>
              <div className="output-grid">
                {module.output_slots.flatMap((slot) => (mappedOutputs.mapped[slot.name] ?? []).map((artifact) => (
                  <div key={artifact.artifact_id} className="artifact-card">
                    <strong>{slot.name} / {artifact.type}</strong><span>{artifact.name ?? artifact.artifact_id}</span>
                    <a href={api.artifactFileUrl(artifact.artifact_id)} target="_blank" rel="noreferrer">Download</a>
                  </div>
                )))}
                {mappedOutputs.unmapped.map((artifact) => (
                  <div key={artifact.artifact_id} className="artifact-card">
                    <strong>Unmapped Output / {artifact.type}</strong><span>{artifact.name ?? artifact.artifact_id}</span>
                    <a href={api.artifactFileUrl(artifact.artifact_id)} target="_blank" rel="noreferrer">Download</a>
                  </div>
                ))}
              </div>
              {mappedOutputs.missingRequired.length > 0 ? (
                <div className="toast error">Missing expected output slot: {mappedOutputs.missingRequired.join(", ")}</div>
              ) : null}
              {glbArtifact ? <MeshPreview artifact={glbArtifact} /> : null}
            </div>
          ) : null}
          {actionError ? <div className="toast error">{actionError}</div> : null}
        </section>
      </div>
    </main>
  );
}
