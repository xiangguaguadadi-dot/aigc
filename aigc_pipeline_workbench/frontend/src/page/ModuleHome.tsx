import { useEffect, useState } from "react";
import { api } from "../api/client.ts";
import type { ModuleDefinition } from "../api/types.ts";
import { GenericModuleWorkbench } from "./workbench/GenericModuleWorkbench.tsx";
import { ModuleStudio } from "./modules/ModuleStudio.tsx";

type View = { page: "home" } | { page: "workbench"; module: ModuleDefinition } | { page: "studio"; module?: ModuleDefinition };

export function ModuleHome() {
  const [modules, setModules] = useState<ModuleDefinition[]>([]);
  const [compatibilities, setCompatibilities] = useState<Record<string, { compatible: number; online: number }>>({});
  const [view, setView] = useState<View>({ page: "home" });
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const list = await api.listModules();
      setModules(list);
      const counts: Record<string, { compatible: number; online: number }> = {};
      for (const module of list) {
        const services = await api.moduleServices(module.module_id);
        const serviceMap = new Map(services.map((service) => [service.service_id, service]));
        const allServices = await api.listServices();
        const compatible = allServices.filter((service) => serviceMap.get(service.service_id)?.compatible);
        counts[module.module_id] = {
          compatible: compatible.length,
          online: compatible.filter((service) => service.enabled && service.status === "online").length,
        };
      }
      setCompatibilities(counts);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };

  useEffect(() => { load(); }, []);

  if (view.page === "workbench") return <GenericModuleWorkbench module={view.module} onBack={() => setView({ page: "home" })} />;
  if (view.page === "studio") return <ModuleStudio initialModule={view.module} onBack={() => setView({ page: "home" })} />;

  return (
    <main className="app">
      <header className="app-header"><h1>Modules</h1><button type="button" className="primary" onClick={() => setView({ page: "studio" })}>+ Create Module</button></header>
      <div className="module-grid">
        {modules.map((module) => (
          <div key={module.module_id} className="module-card">
            <strong>{module.name}</strong>
            <span>{module.input_slots.map((slot) => slot.artifact_type).join(" + ")} ? {module.output_slots.map((slot) => slot.artifact_type).join(" + ")}</span>
            <span className={`status ${module.status}`}>{module.status} · {(compatibilities[module.module_id]?.online ?? 0) > 0 ? "Runtime Available" : "Runtime Unavailable"}</span>
            <div className="actions">
              <button type="button" onClick={() => setView({ page: "workbench", module })} disabled={module.status !== "ready" || (compatibilities[module.module_id]?.online ?? 0) === 0}>Open</button>
              <button type="button" onClick={() => setView({ page: "studio", module })}>Edit</button>
            </div>
          </div>
        ))}
      </div>
      {error ? <div className="toast error">{error}</div> : null}
    </main>
  );
}
