# Phase 5 Local E2E Guide

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

Install dependencies:

~~~bash
~/.local/bin/uv sync --project backend
~/.local/bin/uv sync --project mock_services
~~~

## Start Main Backend

~~~bash
cd backend
~/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

## Start mock-fast

~~~bash
cd mock_services
~/.local/bin/uv run uvicorn mock_services.fast_service:app --host 127.0.0.1 --port 8101
~~~

## Start mock-slow

~~~bash
cd mock_services
CONTROL_PLANE_BASE_URL=http://127.0.0.1:8000 ~/.local/bin/uv run uvicorn mock_services.slow_service:app --host 127.0.0.1 --port 8102
~~~

## Environment Variables

Main Backend uses Pydantic Settings:

- , default 
- , default 
- , default 
- , default 
- , default 
- , default 
- , default 
- , default 

Mock services use:

- , default 

## Run Smoke Test

With all three services running:

~~~bash
~/.local/bin/uv run --project backend python scripts/e2e_smoke.py
~~~

Useful options:

~~~bash
~/.local/bin/uv run --project backend python scripts/e2e_smoke.py   --backend http://127.0.0.1:8000   --fast http://127.0.0.1:8101   --slow http://127.0.0.1:8102   --slow-duration 3
~~~

The script only uses Main Backend public APIs for the business flow. It directly calls mock  only to verify that both workers are reachable.

## Expected Flow

mock-fast:

~~~text
queued -> running -> succeeded
~~~

mock-slow:

~~~text
queued -> running -> cancelling -> cancelled
~~~

The script verifies logs, progress, output artifact metadata, artifact download, and cancel behavior.

## Restart Recovery Test

1. Start all three services.
2. Submit a mock-slow job with, for example, .
3. Wait until the job reaches .
4. Stop Main Backend.
5. Start Main Backend again.
6. Call  with the same job ID.
7. Observe that the job continues polling and reaches a terminal state without a new job ID.
8. Check  to confirm old logs were not lost.

## Common Errors

- : the mock service is not running or has the wrong port.
- :  is wrong on the mock service.
- : another process is using 8000, 8101, or 8102.
- Jobs remain  or : confirm .
- Registration returns offline: check the service URL and health endpoint first.
