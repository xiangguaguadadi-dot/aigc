import type { ParameterDefinition } from "../api/types.js";

interface ParameterFormProps {
  definitions: ParameterDefinition[];
  values: Record<string, unknown>;
  disabled?: boolean;
  onChange: (key: string, value: unknown) => void;
}

export function ParameterForm({ definitions, values, disabled, onChange }: ParameterFormProps) {
  if (definitions.length === 0) {
    return <p className="muted">此服务没有声明参数。</p>;
  }

  return (
    <div className="parameter-grid">
      {definitions.map((definition) => {
        const value = values[definition.key] ?? definition.default ?? "";
        const id = `parameter-${definition.key}`;
        return (
          <label key={definition.key} htmlFor={id}>
            <span>{definition.label}</span>
            {definition.value_type === "boolean" ? (
              <select
                id={id}
                disabled={disabled}
                value={String(Boolean(value))}
                onChange={(event) => onChange(definition.key, event.target.value === "true")}
              >
                <option value="false">false</option>
                <option value="true">true</option>
              </select>
            ) : definition.options.length > 0 ? (
              <select
                id={id}
                disabled={disabled}
                value={String(value)}
                onChange={(event) => onChange(definition.key, event.target.value)}
              >
                <option value="">请选择</option>
                {definition.options.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                type={definition.value_type === "integer" || definition.value_type === "number" ? "number" : "text"}
                disabled={disabled}
                required={definition.required}
                min={definition.minimum ?? undefined}
                max={definition.maximum ?? undefined}
                value={String(value)}
                onChange={(event) => {
                  const raw = event.target.value;
                  if (definition.value_type === "integer") onChange(definition.key, raw === "" ? null : Number.parseInt(raw, 10));
                  else if (definition.value_type === "number") onChange(definition.key, raw === "" ? null : Number(raw));
                  else onChange(definition.key, raw);
                }}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}
