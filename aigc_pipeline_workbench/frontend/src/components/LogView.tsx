import { useEffect, useRef } from "react";
import type { JobLog } from "../api/types.js";

interface LogViewProps {
  logs: JobLog[];
  error?: { code: string; message: string; details: Record<string, unknown> } | null;
}

export function LogView({ logs, error }: LogViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs.length]);

  return (
    <div className="log-panel">
      {error ? (
        <div className="error-box">
          <strong>{error.code}</strong>
          <p>{error.message}</p>
        </div>
      ) : null}
      <div ref={scrollRef} className="log-scroll">
        {logs.length === 0 ? <p className="muted">暂无日志。</p> : logs.map((log) => (
          <div key={log.log_id} className={`log-line level-${log.level}`}>
            <span>#{log.seq}</span>
            <span>{new Date(log.created_at).toLocaleTimeString()}</span>
            <span>{log.source}</span>
            <span>{log.level}</span>
            <span>{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
