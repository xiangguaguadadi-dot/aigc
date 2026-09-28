#!/usr/bin/env python3
import argparse
import json
import sys
import time
import uuid
from typing import Any, Optional

import httpx

BACKEND = "http://127.0.0.1:8000"
FAST = "http://127.0.0.1:8101"
SLOW = "http://127.0.0.1:8102"


class SmokeError(RuntimeError):
    pass


def request(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise SmokeError(f"{method} {url} transport error: {exc}") from exc
    if response.status_code >= 400:
        raise SmokeError(f"{method} {url} returned HTTP {response.status_code}: {response.text}")
    try:
        return response.json()
    except Exception as exc:
        raise SmokeError(f"{method} {url} returned non-JSON response: {response.text}") from exc


def wait_for_terminal(client: httpx.Client, job_id: str, timeout: float, want_running_before_cancel: bool = False) -> dict:
    started = time.monotonic()
    saw_running = False
    last_status = "unknown"
    while time.monotonic() - started < timeout:
        job = request(client, "GET", f"{BACKEND}/api/v1/jobs/{job_id}")
        last_status = job.get("status", last_status)
        print(f"  {job_id}: {last_status} progress={safe_progress(job)}")
        if last_status == "running":
            saw_running = True
        if last_status in {"succeeded", "failed", "cancelled", "timeout"}:
            return job
        if want_running_before_cancel and saw_running:
            return job
        time.sleep(0.5)
    raise SmokeError(f"timeout waiting for job {job_id}; last status={last_status}")


def safe_progress(job: dict) -> Any:
    progress = job.get("progress")
    return progress.get("percent") if isinstance(progress, dict) else progress


def wait_for_background(client: httpx.Client, job_id: str, target_status: str, timeout: float) -> dict:
    started = time.monotonic()
    last_status = "unknown"
    while time.monotonic() - started < timeout:
        job = request(client, "GET", f"{BACKEND}/api/v1/jobs/{job_id}")
        last_status = job.get("status", last_status)
        print(f"  {job_id}: {last_status} progress={safe_progress(job)}")
        if last_status == target_status:
            return job
        if last_status in {"succeeded", "failed", "cancelled", "timeout"}:
            break
        time.sleep(0.5)
    raise SmokeError(f"job {job_id} did not reach {target_status}; last status={last_status}")


def cancel_job(client: httpx.Client, job_id: str) -> dict:
    try:
        return request(client, "POST", f"{BACKEND}/api/v1/jobs/{job_id}/cancel")
    except SmokeError as exc:
        if "JOB_ALREADY_FINISHED" in str(exc):
            return {"job_id": job_id, "status": "already_finished"}
        raise


def register_service(client: httpx.Client, name: str, base_url: str, label: str) -> str:
    service = request(
        client,
        "POST",
        f"{BACKEND}/api/v1/services",
        data={"name": name, "base_url": base_url, "instance_label": label},
    )
    if service.get("status") != "online":
        raise SmokeError(f"{name} is not online: {json.dumps(service)}")
    service_id = service.get("service_id")
    if not service_id:
        raise SmokeError(f"service registration returned no service_id: {json.dumps(service)}")
    return service_id


def validate_logs(client: httpx.Client, job_id: str) -> list[dict]:
    logs = request(client, "GET", f"{BACKEND}/api/v1/jobs/{job_id}/logs")
    if not logs:
        raise SmokeError(f"job {job_id} has no logs")
    seqs = [entry.get("seq") for entry in logs]
    if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
        raise SmokeError(f"invalid log seq order: {seqs}")
    return logs


def validate_artifact(client: httpx.Client, job: dict) -> str:
    artifacts = job.get("output_artifacts") or []
    if not artifacts:
        raise SmokeError(f"job {job['job_id']} has no output artifacts")
    artifact = artifacts[0]
    artifact_id = artifact.get("artifact_id")
    if not artifact_id:
        raise SmokeError(f"invalid output artifact descriptor: {json.dumps(artifact)}")
    metadata = request(client, "GET", f"{BACKEND}/api/v1/artifacts/{artifact_id}")
    file_response = client.get(f"{BACKEND}/api/v1/artifacts/{artifact_id}/file")
    if file_response.status_code >= 400 or not file_response.content:
        raise SmokeError(f"artifact download failed: HTTP {file_response.status_code}, bytes={len(file_response.content)}")
    metadata_text = json.dumps(metadata)
    if "storage_key" in metadata_text or "/data/artifacts" in metadata_text:
        raise SmokeError("artifact metadata leaked internal storage information")
    return artifact_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--fast", default="http://127.0.0.1:8101")
    parser.add_argument("--slow", default="http://127.0.0.1:8102")
    parser.add_argument("--slow-duration", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    global BACKEND, FAST, SLOW
    BACKEND, FAST, SLOW = args.backend, args.fast, args.slow
    token = uuid.uuid4().hex[:8]
    results: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=10) as client:
            health = request(client, "GET", f"{BACKEND}/api/v1/health")
            if health.get("contract_version") != "v1":
                raise SmokeError(f"unexpected backend health: {json.dumps(health)}")
            request(client, "GET", f"{FAST}/v1/health")
            request(client, "GET", f"{SLOW}/v1/health")
            print("1. services reachable")

            fast_service_id = register_service(client, "Smoke Mock Fast", args.fast, f"fast_{token}")
            slow_service_id = register_service(client, "Smoke Mock Slow", args.slow, f"slow_{token}")
            results["service_ids"] = {"mock_fast": fast_service_id, "mock_slow": slow_service_id}
            print(f"2. registered services: {results['service_ids']}")

            upload = client.post(
                f"{BACKEND}/api/v1/artifacts",
                files={"file": ("smoke-input.txt", f"smoke input {token}".encode(), "text/plain")},
                data={"artifact_type": "image"},
            )
            if upload.status_code >= 400:
                raise SmokeError(f"artifact upload failed: HTTP {upload.status_code}: {upload.text}")
            uploaded = upload.json()
            input_artifacts = [{
                "artifact_id": uploaded["artifact_id"],
                "type": "image",
                "name": uploaded["name"],
                "uri": f"{BACKEND}/api/v1/artifacts/{uploaded['artifact_id']}/file",
            }]
            print(f"3. uploaded input artifact: {uploaded['artifact_id']}")

            fast_job = request(
                client,
                "POST",
                f"{BACKEND}/api/v1/jobs",
                data={
                    "service_id": fast_service_id,
                    "parameters": json.dumps({"message": f"smoke-{token}"}),
                    "input_artifacts": json.dumps(input_artifacts),
                },
            )
            fast_job_id = fast_job["job_id"]
            results["fast_job_id"] = fast_job_id
            fast_final = wait_for_terminal(client, fast_job_id, args.timeout)
            if fast_final.get("status") != "succeeded" or safe_progress(fast_final) != 100:
                raise SmokeError(f"fast job did not succeed: {json.dumps(fast_final)}")
            logs = validate_logs(client, fast_job_id)
            artifact_id = validate_artifact(client, fast_final)
            results["fast_log_count"] = len(logs)
            results["output_artifact_id"] = artifact_id
            print(f"4. fast job succeeded, logs={len(logs)}, artifact={artifact_id}")

            slow_job = request(
                client,
                "POST",
                f"{BACKEND}/api/v1/jobs",
                data={
                    "service_id": slow_service_id,
                    "parameters": json.dumps({"duration_seconds": args.slow_duration}),
                },
            )
            slow_job_id = slow_job["job_id"]
            results["slow_job_id"] = slow_job_id
            wait_for_background(client, slow_job_id, "running", args.timeout)
            cancel_response = cancel_job(client, slow_job_id)
            print(f"5. cancel requested: {cancel_response}")
            slow_final = wait_for_terminal(client, slow_job_id, args.timeout)
            if slow_final.get("status") != "cancelled":
                raise SmokeError(f"slow job did not cancel: {json.dumps(slow_final)}")
            results["cancel_final_status"] = slow_final.get("status")
            print("6. slow job cancelled")
        print("\nSMOKE TEST PASS")
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0
    except SmokeError as exc:
        print(f"\nSMOKE TEST FAIL: {exc}", file=sys.stderr)
        print(json.dumps(results, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
