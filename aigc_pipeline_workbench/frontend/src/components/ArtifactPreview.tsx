import type { ArtifactRef } from "../api/types.js";
import { api } from "../api/client.js";

interface ArtifactPreviewProps {
  artifact: ArtifactRef;
}

export function ArtifactPreview({ artifact }: ArtifactPreviewProps) {
  if (artifact.type === "image") {
    return <img className="artifact-preview" src={api.artifactFileUrl(artifact.artifact_id)} alt={artifact.name ?? artifact.artifact_id} />;
  }
  if (artifact.type === "glb" || artifact.type === "mesh") {
    return null;
  }
  return (
    <pre className="artifact-text">
      {artifact.name ?? artifact.artifact_id}
    </pre>
  );
}
