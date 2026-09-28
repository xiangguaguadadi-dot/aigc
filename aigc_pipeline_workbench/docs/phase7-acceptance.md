# Phase 7 Acceptance

Overall: PASS

## Closure Summary

Phase 7 is complete. The system now has persistent Module Definitions, Module CRUD APIs, Module/Service compatibility, a Module-centric Home, Module Studio, a data-driven Generic Module Workbench, module-aware job integration, output-slot mapping, and SQLite persistence. The production frontend builds successfully with Linux-native Node.js, and the runtime HTTP regression passes.

No Workflow, DAG, module chaining, scheduler, retry engine, or real GPU integration was introduced.

## Environment

- OS: WSL2 Ubuntu.
- Node.js: v22.22.2, Linux native.
- npm: 10.9.7.
- Vite: 7.3.6.
- Backend runtime: Python 3.11 virtual environments managed by uv.
- Frontend commands are run from the repository root with `npm run check` and `npm run build`.

The earlier build blocker was caused by a stale `vite.config.ts` that contained Windows UNC-derived `W:\...` paths. The file was restored to normal package imports, `node_modules` was reinstalled with Linux Node, and the Windows/WSL boundary issue no longer occurs.

## Module Semantics

- `ready` means the Module Definition is structurally valid.
- Runtime Availability is displayed separately and requires at least one compatible, enabled, online service.
- Opening a Workbench requires the module to be Ready and runtime-available.
- Offline service availability never invalidates a Ready definition.

## Output Slot Mapping

Mock successful jobs now attach `metadata.output_slot` to uploaded artifacts:

- Report artifact -> `output_slot: report`.
- GLB artifact -> `output_slot: mesh`.

The Generic Workbench maps artifacts to Module output slots using `metadata.output_slot`, while retaining GLB type-based lookup for MeshPreview.

Behavior:

- Known slots render under their Module output slot names.
- Missing `output_slot` remains visible as `Unmapped Output`.
- Unknown `output_slot` does not crash the UI and is also shown as unmapped.
- A missing required output slot displays `Missing expected output slot: ...`.
- The built-in frontend demo job now includes output-slot metadata and appears as the default Recent Job for the demo module.

## Browser Runtime Scenarios

### A. Module Creation

Module Studio creates and edits basic information, input slots, output slots, and parameters. Draft and Ready behavior is driven by the backend validation API.

### B. Image to Mesh

The compatible mock service is selectable, required image upload gates Run, the job runs to `succeeded`, and Report/GLB outputs render with download links and MeshPreview.

### C. Multi-Input Module

The seeded `multi_input_test` module renders dynamic required and optional input controls and uses the same data-driven Workbench.

### D. Draft Module

A draft remains visible/editable in Module Studio and does not expose Workbench execution as Ready.

### E. Compatibility Mismatch

Incompatible services are excluded from the selectable compatible-service list; module cards distinguish definition readiness from runtime availability.

### F. Default Demo Job

Opening the built-in `frontend_demo` module loads `job_frontend_demo`, its logs, and its report/mesh artifacts without requiring a GPU service. This exercises service/job selection, recent-job selection, job details, output mapping, download links, and GLB preview.

## Job Integration

- New jobs persist nullable `module_id`.
- Legacy jobs with no module association remain valid.
- Required-input and parameter validation remains backend-enforced.
- Existing JobManager state machine, polling, cancellation, rerun, logs, artifacts, and GPU client behavior are unchanged.

## Persistence

SQLite stores modules in a dedicated table with unique `module_key`; slot and parameter structures are JSON columns. The jobs table has a nullable `module_id` migration. Restart verification confirmed that modules, demo/recent jobs, artifact records, and output-slot metadata remain available after backend restart.

## Regression

- Backend pytest: 46 passed.
- Backend mypy: pass, 31 source files.
- Backend compileall: pass.
- Mock services pytest: 6 passed, including new output-slot metadata coverage.
- Mock services mypy: pass, 11 source files.
- Frontend TypeScript check: pass.
- Frontend production build: pass.
- Real HTTP E2E: PASS through backend + mock-fast, ending with a 956-byte GLB download.
- Runtime persistence: PASS after backend restart.
- Vite dev proxy: PASS at `/` and `/api/v1/health`.

## Architecture

The accepted boundaries remain:

- Frontend accesses only Main Backend.
- Main Backend owns orchestration, state, registry, artifact metadata, and storage.
- GPU Services own execution and use Contract v1.
- Artifact files stay behind Main Backend.
- No local paths cross service boundaries.
- Workflow/DAG concepts remain explicitly out of scope.

## Known Limitations

- Matching uses artifact types and module key; MIME, extension, parameter compatibility, and runtime capacity are not compatibility keys.
- Optional-output capability matching is intentionally deferred.
- Module archive/delete is omitted.
- Browser interaction was verified against HTTP/DOM-level behavior and proxy/runtime responses; screenshot-based visual review was not used.
- GLB rendering visual quality still requires a human visual check.

## Manual Check

Start with:

```bash
scripts/start_phase6.sh
npm run dev
```

Then open `http://localhost:5173/`. From Module Home, open the built-in demo module to inspect the default job, then test image upload and job execution with the compatible mock service. GLB preview should show an interactive mesh.

## Final Decision

Phase 7 - DONE.
