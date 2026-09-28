#!/usr/bin/env python3
import argparse
import json
import sys
import time
import uuid
from typing import Any

import httpx


class HttpE2EError(RuntimeError):
    pass


def json_request(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    response = client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise HttpE2EError(f"{method} {url}: HTTP {response.status_code}: {response.text}")
    try:
        return response.json()
    except Exception as exc:
        raise HttpE2EError(f"{method} {url}: invalid JSON") from exc


def wait_status(client: httpx.Client, base_url: str, job_id: str, target: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    job = {}
    while time.monotonic() < deadline:
        job = json_request(client, "GET", f"{base_url}/api/v1/jobs/{job_id}")
        print(f"  {job_id}: {job.get('status')}")
        if job.get("status") == target:
            return job
        if job.get("status") in {"failed", "timeout"}:
            raise HttpE2EError(f"job {job_id} ended in {job.get('status')}")
        time.sleep(0.5)
    raise HttpE2EError(f"timeout waiting for {target}: {job}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--fast", default="http://127.0.0.1:8101")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    token = uuid.uuid4().hex[:8]
    result: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=10) as client:
            health = json_request(client, "GET", f"{args.backend}/api/v1/health")
            assert health["status"] == "ok"
            json_request(client, "GET", f"{args.fast}/v1/health")
            print("1. backend and mock-fast reachable")

            service = json_request(
                client,
                "POST",
                f"{args.backend}/api/v1/services",
                data={"name": "Frontend E2E Mock Fast", "base_url": args.fast, "instance_label": token},
            )
            service_id = service["service_id"]
            result["service_id"] = service_id
            print(f"2. registered {service_id}")

            content = f"frontend e2e image {token}".encode()
            upload = client.post(
                f"{args.backend}/api/v1/artifacts",
                files={"file": ("e2e-input.png", content, "image/png")},
                data={"artifact_type": "image"},
            )
            if upload.status_code >= 400:
                raise HttpE2EError(f"upload failed: {upload.text}")
            uploaded = upload.json()
            input_artifacts = [{
                "artifact_id": uploaded["artifact_id"],
                "type": "image",
                "name": uploaded["name"],
                "uri": f"{args.backend}/api/v1/artifacts/{uploaded['artifact_id']}/file",
            }]
            result["input_artifact_id"] = uploaded["artifact_id"]
            print(f"3. uploaded {uploaded['artifact_id']}")

            job = json_request(
                client,
                "POST",
                f"{args.backend}/api/v1/jobs",
                data={
                    "service_id": service_id,
                    "parameters": json.dumps({"message": f"e2e-{token}"}),
                    "input_artifacts": json.dumps(input_artifacts),
                },
            )
            job_id = job["job_id"]
            result["job_id"] = job_id
            final = wait_status(client, args.backend, job_id, "succeeded", args.timeout)
            result["final_status"] = final["status"]
            result["progress"] = final["progress"]["percent"]
            print(f"4. job succeeded at {final['progress']['percent']}%")

            logs = json_request(client, "GET", f"{args.backend}/api/v1/jobs/{job_id}/logs")
            result["log_seq"] = [log["seq"] for log in logs]
            if result["log_seq"] != [0, 1, 2]:
                raise HttpE2EError(f"unexpected log seq: {result['log_seq']}")
            print("5. logs synced with seq 0..2")

            outputs = final["output_artifacts"]
            glb = next((artifact for artifact in outputs if artifact["type"] == "glb"), None)
            if not glb:
                raise HttpE2EError("no GLB output artifact")
            file_response = client.get(f"{args.backend}{glb['uri']}")
            if file_response.status_code >= 400 or not file_response.content.startswith(b"glTF"):
                raise HttpE2EError("GLB download failed")
            result["glb_artifact_id"] = glb["artifact_id"]
            result["glb_bytes"] = len(file_response.content)
            print(f"6. downloaded {glb['artifact_id']} ({len(file_response.content)} bytes)")

        print("\nPHASE 6 HTTP E2E PASS")
        print(json.dumps(result, indent=2))
        return 0
    except (HttpE2EError, AssertionError) as exc:
        print(f"\nPHASE 6 HTTP E2E FAIL: {exc}", file=sys.stderr)
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
