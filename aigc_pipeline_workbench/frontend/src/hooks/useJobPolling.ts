import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import type { Job } from "../api/types.js";

const ACTIVE_STATUSES = new Set(["created", "submitting", "submitted", "queued", "running", "cancelling"]);

export function useJobPolling(initialJob: Job | null) {
  const [job, setJob] = useState<Job | null>(initialJob);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    setJob(initialJob);
  }, [initialJob]);

  const refresh = useCallback(async (jobId: string) => {
    const updated = await api.getJob(jobId);
    setJob(updated);
    return updated;
  }, []);

  useEffect(() => {
    if (!job || !ACTIVE_STATUSES.has(job.status)) {
      return;
    }
    const jobId = job.job_id;
    const schedule = () => {
      timerRef.current = window.setTimeout(async () => {
        try {
          const updated = await refresh(jobId);
          if (ACTIVE_STATUSES.has(updated.status)) schedule();
        } catch {
          schedule();
        }
      }, 1000);
    };
    schedule();
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [job?.job_id, job?.status, refresh]);

  return { job, setJob, refresh };
}
