import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { api } from "../api/client.js";
import type { ArtifactRef } from "../api/types.js";

interface MeshPreviewProps {
  artifact: ArtifactRef;
}

export function MeshPreview({ artifact }: MeshPreviewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const resetRef = useRef<(() => void) | null>(null);
  const [viewerStatus, setViewerStatus] = useState<"loading" | "loaded" | "error">("loading");
  const [meshCount, setMeshCount] = useState(0);
  const fitRef = useRef<{ center: THREE.Vector3; distance: number } | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111827);

    const camera = new THREE.PerspectiveCamera(55, container.clientWidth / Math.max(1, container.clientHeight), 0.1, 1000);
    camera.position.set(3, 2.5, 4);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = true;
    controls.zoomSpeed = 0.8;
    controls.target.set(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const directionalLight = new THREE.DirectionalLight(0xffffff, 2.2);
    directionalLight.position.set(4, 6, 5);
    scene.add(directionalLight);
    const grid = new THREE.GridHelper(8, 8, 0x4b5563, 0x374151);
    scene.add(grid);

    const url = api.artifactFileUrl(artifact.artifact_id);
    const loader = new GLTFLoader();
    let disposed = false;
    loader.load(
      url,
      (gltf) => {
        if (disposed) return;
        const model = gltf.scene;
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const maxDimension = Math.max(size.x, size.y, size.z, 0.001);
        model.position.sub(center);
        model.scale.setScalar(2 / maxDimension);
        scene.add(model);
        const fittedBox = new THREE.Box3().setFromObject(model);
        const fittedSize = fittedBox.getSize(new THREE.Vector3());
        const fittedCenter = fittedBox.getCenter(new THREE.Vector3());
        const fittedRadius = Math.max(fittedSize.length() / 2, 0.001);
        const direction = new THREE.Vector3(1, 0.75, 1.2).normalize();
        const distance = fittedRadius / Math.sin((camera.fov * Math.PI / 180) / 2) * 1.15;
        fitRef.current = { center: fittedCenter.clone(), distance };
        controls.target.copy(fittedCenter);
        camera.position.copy(fittedCenter).addScaledVector(direction, distance);
        camera.updateProjectionMatrix();
        controls.update();
        let loadedMeshCount = 0;
        model.traverse((object) => {
          if (object instanceof THREE.Mesh) loadedMeshCount += 1;
        });
        setMeshCount(loadedMeshCount);
        setViewerStatus("loaded");
      },
      undefined,
      (error) => {
        console.error("GLB load failed", error);
        setViewerStatus("error");
      },
    );

    const animation = () => {
      requestAnimationFrame(animation);
      controls.update();
      renderer.render(scene, camera);
    };
    animation();

    const resizeObserver = new ResizeObserver(() => {
      if (!container.clientWidth || !container.clientHeight) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    });
    resizeObserver.observe(container);

    resetRef.current = () => {
      const fittedBox = new THREE.Box3().setFromObject(scene);
      if (!fitRef.current) {
        controls.target.set(0, 0, 0);
        camera.position.set(3, 2.5, 4);
      } else {
        const direction = new THREE.Vector3(1, 0.75, 1.2).normalize();
        controls.target.copy(fitRef.current.center);
        camera.position.copy(fitRef.current.center).addScaledVector(direction, fitRef.current.distance);
      }
      controls.update();
    };

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      controls.dispose();
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };
  }, [artifact.artifact_id]);

  return (
    <div className="mesh-preview" data-viewer-status={viewerStatus} data-mesh-count={meshCount}>
      <div ref={containerRef} aria-label="Interactive GLB 3D preview" />
      <div className="mesh-toolbar">
        <span>Drag = rotate · Scroll = zoom · Right drag = pan</span>
        <button type="button" onClick={() => resetRef.current?.()}>Reset View</button>
      </div>
    </div>
  );
}
