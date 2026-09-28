import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client.ts";
import type { InputSlot, ModuleDefinition, OutputSlot } from "../../api/types.ts";

type EditableSlot = { name: string; artifact_type: string; required: boolean; mime: string; extensions: string; description: string };
type EditableParameter = { key: string; label: string; value_type: string; required: boolean; default: string; description: string; options: string };

const ARTIFACT_TYPES = ["image", "mask", "video", "mesh", "glb", "texture", "point_cloud", "physics_asset", "trajectory", "report", "log_file", "unknown"];

function emptyInput(): EditableSlot { return { name: "image", artifact_type: "image", required: true, mime: "image/png", extensions: ".png", description: "" }; }
function emptyOutput(): EditableSlot { return { name: "mesh", artifact_type: "glb", required: true, mime: "model/gltf-binary", extensions: ".glb", description: "" }; }
function emptyParameter(): EditableParameter { return { key: "quality", label: "Quality", value_type: "integer", required: false, default: "", description: "", options: "" }; }

function toEditable(slot: InputSlot | OutputSlot): EditableSlot {
  const mime = "accepted_mime_types" in slot ? slot.accepted_mime_types : slot.expected_mime_types;
  const extensions = "accepted_extensions" in slot ? slot.accepted_extensions : slot.expected_extensions;
  return { name: slot.name, artifact_type: slot.artifact_type, required: slot.required, mime: mime.join(", "), extensions: extensions.join(", "), description: slot.description ?? "" };
}

function fromEditable(slot: EditableSlot, direction: "input"): InputSlot;
function fromEditable(slot: EditableSlot, direction: "output"): OutputSlot;
function fromEditable(slot: EditableSlot, direction: "input" | "output"): InputSlot | OutputSlot {
  const mimes = slot.mime.split(",").map((item) => item.trim()).filter(Boolean);
  const exts = slot.extensions.split(",").map((item) => item.trim()).filter(Boolean);
  const common = { name: slot.name, artifact_type: slot.artifact_type, required: slot.required, description: slot.description || null };
  return direction === "input"
    ? { ...common, accepted_mime_types: mimes, accepted_extensions: exts }
    : { ...common, expected_mime_types: mimes, expected_extensions: exts };
}

function parameterToEditable(parameter: ModuleDefinition["parameter_schema"][number]): EditableParameter {
  return {
    key: parameter.key, label: parameter.label, value_type: parameter.value_type, required: parameter.required,
    default: parameter.default === null || parameter.default === undefined ? "" : String(parameter.default),
    description: parameter.description ?? "", options: parameter.options.map((option) => option.value).join(","),
  };
}

export function ModuleStudio({ initialModule, onBack }: { initialModule?: ModuleDefinition; onBack?: () => void }) {
  const [modules, setModules] = useState<ModuleDefinition[]>([]);
  const [editing, setEditing] = useState<ModuleDefinition | null>(initialModule ?? null);
  const [name, setName] = useState(initialModule?.name ?? "");
  const [moduleKey, setModuleKey] = useState(initialModule?.module_key ?? "");
  const [description, setDescription] = useState(initialModule?.description ?? "");
  const [version, setVersion] = useState(initialModule?.version ?? "1.0");
  const [inputs, setInputs] = useState<EditableSlot[]>(initialModule?.input_slots.map(toEditable) ?? [emptyInput()]);
  const [outputs, setOutputs] = useState<EditableSlot[]>(initialModule?.output_slots.map(toEditable) ?? [emptyOutput()]);
  const [parameters, setParameters] = useState<EditableParameter[]>(initialModule?.parameter_schema.map(parameterToEditable) ?? []);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const payload = useMemo(() => ({
    module_key: moduleKey, name, description: description || null, version,
    input_slots: inputs.map((slot) => fromEditable(slot, "input")),
    output_slots: outputs.map((slot) => fromEditable(slot, "output")),
    parameter_schema: parameters.map((parameter) => ({
      key: parameter.key, label: parameter.label, value_type: parameter.value_type, required: parameter.required,
      default: parameter.value_type === "integer" && parameter.default !== "" ? Number.parseInt(parameter.default, 10) : parameter.value_type === "number" && parameter.default !== "" ? Number(parameter.default) : parameter.value_type === "boolean" ? parameter.default === "true" : parameter.default || null,
      minimum: null, maximum: null,
      options: parameter.value_type === "enum" ? parameter.options.split(",").filter(Boolean).map((value) => ({ value, label: value })) : [],
      description: parameter.description || null,
    })),
  }), [moduleKey, name, description, version, inputs, outputs, parameters]);

  const load = () => api.listModules().then(setModules).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  useEffect(() => { load(); }, []);

  const reset = () => {
    setEditing(null); setName(""); setModuleKey(""); setDescription(""); setVersion("1.0");
    setInputs([emptyInput()]); setOutputs([emptyOutput()]); setParameters([]);
  };

  const loadModule = (module: ModuleDefinition) => {
    setEditing(module); setName(module.name); setModuleKey(module.module_key); setDescription(module.description ?? ""); setVersion(module.version);
    setInputs(module.input_slots.map(toEditable)); setOutputs(module.output_slots.map(toEditable)); setParameters(module.parameter_schema.map(parameterToEditable));
  };

  const save = async (status?: string) => {
    setError(null); setMessage(null);
    try {
      const saved = editing ? await api.updateModule(editing.module_id, { ...payload, ...(status ? { status } : {}) }) : await api.createModule(payload);
      setMessage(`Saved ${saved.status}`); loadModule(saved); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };

  return (
    <main className="app">
      <header className="app-header"><h1>Module Studio</h1><button type="button" className="primary" onClick={reset}>+ Create Module</button></header>
      <div className="studio-grid">
      {onBack ? <button type="button" onClick={onBack}>Back to Modules</button> : null}
        <aside className="panel">
          <h2>Modules</h2>
          {modules.map((module) => (
            <div key={module.module_id} className="module-card">
              <strong>{module.name}</strong>
              <span>{module.input_slots.map((slot) => slot.artifact_type).join(" + ")} ? {module.output_slots.map((slot) => slot.artifact_type).join(" + ")}</span>
              <span className={`status ${module.status}`}>{module.status}</span>
              <div className="actions"><button type="button" onClick={() => loadModule(module)}>Edit</button></div>
            </div>
          ))}
        </aside>
        <section className="panel detail-panel">
          <h2>{editing ? "Edit Module" : "Create Module"}</h2>
          <div className="module-form">
            <label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>Module Key<input value={moduleKey} onChange={(event) => setModuleKey(event.target.value)} /></label>
            <label>Version<input value={version} onChange={(event) => setVersion(event.target.value)} /></label>
            <label>Description<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          </div>
          <h3>Inputs</h3>
          {inputs.map((slot, index) => (
            <div key={index} className="slot-editor">
              <input value={slot.name} onChange={(event) => setInputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} placeholder="Name" />
              <select value={slot.artifact_type} onChange={(event) => setInputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, artifact_type: event.target.value } : item))}>{ARTIFACT_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
              <label><input type="checkbox" checked={slot.required} onChange={(event) => setInputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, required: event.target.checked } : item))} /> required</label>
              <input value={slot.mime} onChange={(event) => setInputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, mime: event.target.value } : item))} placeholder="MIME types" />
              <input value={slot.extensions} onChange={(event) => setInputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, extensions: event.target.value } : item))} placeholder="Extensions" />
              <button type="button" onClick={() => setInputs((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
            </div>
          ))}
          <button type="button" onClick={() => setInputs((current) => [...current, emptyInput()])}>+ Add Input</button>
          <h3>Outputs</h3>
          {outputs.map((slot, index) => (
            <div key={index} className="slot-editor">
              <input value={slot.name} onChange={(event) => setOutputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} placeholder="Name" />
              <select value={slot.artifact_type} onChange={(event) => setOutputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, artifact_type: event.target.value } : item))}>{ARTIFACT_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
              <label><input type="checkbox" checked={slot.required} onChange={(event) => setOutputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, required: event.target.checked } : item))} /> required</label>
              <input value={slot.mime} onChange={(event) => setOutputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, mime: event.target.value } : item))} placeholder="Expected MIME types" />
              <input value={slot.extensions} onChange={(event) => setOutputs((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, extensions: event.target.value } : item))} placeholder="Expected extensions" />
              <button type="button" onClick={() => setOutputs((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
            </div>
          ))}
          <button type="button" onClick={() => setOutputs((current) => [...current, emptyOutput()])}>+ Add Output</button>
          <h3>Parameters</h3>
          {parameters.map((parameter, index) => (
            <div key={index} className="slot-editor">
              <input value={parameter.key} onChange={(event) => setParameters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item))} placeholder="Key" />
              <input value={parameter.label} onChange={(event) => setParameters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, label: event.target.value } : item))} placeholder="Label" />
              <select value={parameter.value_type} onChange={(event) => setParameters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, value_type: event.target.value } : item))}>{["string", "integer", "number", "boolean", "enum"].map((type) => <option key={type}>{type}</option>)}</select>
              <input value={parameter.default} onChange={(event) => setParameters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, default: event.target.value } : item))} placeholder="Default" />
              {parameter.value_type === "enum" ? <input value={parameter.options} onChange={(event) => setParameters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, options: event.target.value } : item))} placeholder="choices" /> : null}
              <button type="button" onClick={() => setParameters((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
            </div>
          ))}
          <button type="button" onClick={() => setParameters((current) => [...current, emptyParameter()])}>+ Add Parameter</button>
          <div className="actions">
            <button type="button" onClick={() => save("draft")}>Save Draft</button>
            <button type="button" className="primary" onClick={() => save("ready")}>Mark Ready</button>
          </div>
          {message ? <p className="muted">{message}</p> : null}
          {error ? <div className="toast error">{error}</div> : null}
        </section>
      </div>
    </main>
  );
}
