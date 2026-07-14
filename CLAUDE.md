# Physical Modeling Agent

## Project Overview

A **physical model compilation system** that transforms images/text into structured physical models, runs simulations, validates results, and iteratively refines them. This is **not** a simple image-to-3D tool — it is a full pipeline from perception → abstract domain model → geometry compilation → simulation compilation → physical execution → result validation → automated repair or active questioning.

### Core Pipeline

```
User Input (image/text)
  → Perception (VLM / Mock)
  → Model Selection & Hypotheses
  → Geometry Engine (procedural meshes)
  → Simulation Compiler
  → Simulation Backend (PyBullet / Analytical)
  → Result Validator
  → Auto-repair or Active Query → output
```

## Architecture

Six-layer system with strict dependency direction. **Upper layers call down; domain never depends on concrete engines, VLM, or UI.**

```
Presentation Layer (Gradio/Streamlit, API, CLI)
        ↓
Application Layer (pipeline orchestration, context, error recovery)
        ↓
Domain Layer (core abstractions — GeometryModel, ObjectModel, SimulationTask…)
```

External capabilities are injected via interfaces:

```
Intelligence Layer  →  interface
Geometry Engine     →  interface
Simulation Layer    →  interface
Infrastructure      →  interface
```

### Layer Details

| Layer | Path | Responsibility |
|---|---|---|
| **Presentation** | `presentation/` | File upload, text input, parameter input, candidate display, animation/video, validation reports |
| **Application** | `application/` | Pipeline orchestration, `PipelineContext`, stage management, retry, active query routing |
| **Domain** | `domain/` | `ObjectModel`, `GeometryModel`, `SimulationTask`, `ModelHypothesis`, `SimulationResult`, `ValidationReport` — NO dependency on PyBullet/VLM/Gradio |
| **Intelligence** | `intelligence/` | Perception (VLM adapter), model selection, hypothesis generation, material priors, active questioning |
| **Geometry Engine** | `geometry_engine/` | Procedural primitives, CSG, revolve/sweep, mesh generation/cleanup/validation, collision proxies, mass properties |
| **Simulation** | `simulation/` | `SimulationBackend` interface, compiler, PyBullet backend, analytical backend (ground truth), trajectory recording |
| **Validation** | `validation/` | Schema checking, geometry checking, physics checking (NaN, penetration, energy, inertia), auto-repair |
| **Infrastructure** | `infrastructure/` | Config (YAML), logging, cache, serialization (JSON), file storage, output path management |

## Design Principles

1. **Monorepo** — no microservices in Phase 1 (tight coupling, low debug cost, no distributed needed).
2. **Layered architecture** — strict top-down dependency, domain is the stable core.
3. **Domain-simulator decoupling** — abstract `ObjectModel`/`SimulationTask` first, compile to PyBullet/MuJoCo later.
4. **VLM outputs structured candidates only** — no code generation, no direct PyBullet body creation, no bypassing validation.
5. **Visual / collision / physical geometry separated** — what you see ≠ what collides ≠ what computes mass & inertia.
6. **Procedural Geometry Tree** — parameterized primitives + transforms + Boolean ops + revolve/sweep, not ad-hoc mesh拼接.
7. **Every stage saves intermediate results** — perception → hypothesis → model → mesh → compiled sim → trajectory → validation → repair record. Enables debugging, caching, resume, and system reasoning display.
8. **Mock-first** — hand-crafted `MockPerceptionService` before any real VLM. Verify the full pipeline end-to-end before adding real perception.

## Core Domain Objects

### ObjectModel
Describes one physical object (geometry + material + semantic). Does **not** contain gravity, ground, forces, or solver settings.

### SimulationTask
Describes one experiment: objects + environment + initial conditions + external actions + target quantity + solver settings.

### ModelHypothesis
One candidate physical interpretation of the input — object model + confidence + assumptions + unknowns + provenance.

### SimulationResult
Full simulation output: timestamps, positions, orientations, velocities, contact events, energy history, validation report, output files.

## Key Interfaces

```python
class PerceptionService(ABC):
    def analyze(self, request: InputRequest) -> PerceptionResult: ...

class GeometryEngine(ABC):
    def build_visual_mesh(self, geometry: GeometryModel) -> MeshData: ...
    def build_collision_geometry(self, geometry: GeometryModel) -> CollisionGeometry: ...
    def compute_mass_properties(self, geometry: GeometryModel, density: float) -> MassProperties: ...

class SimulationBackend(ABC):
    def compile(self, model: ObjectModel, task: SimulationTask) -> CompiledSimulation: ...
    def run(self, simulation: CompiledSimulation) -> SimulationResult: ...

class ResultValidator(ABC):
    def validate(self, task: SimulationTask, result: SimulationResult) -> ValidationReport: ...
```

## Project Structure

```
aigc/
├── pyproject.toml
├── configs/                    # YAML configs (app, materials, geometry bounds, prompts)
│   └── prompts/
├── src/physical_agent/
│   ├── presentation/           # API, Web (Gradio), CLI
│   ├── application/            # Pipeline orchestration, context
│   ├── domain/                 # Core abstractions
│   │   ├── geometry/           # GeometryModel, GeometryNode, transforms
│   │   ├── physics/            # Body, material, contact, state
│   │   ├── task/               # SimulationTask, target quantity
│   │   ├── uncertainty/        # Estimate, hypothesis, provenance
│   │   └── results/            # Trajectory, simulation result
│   ├── intelligence/           # Perception, model selection, hypothesis, active query
│   ├── geometry_engine/        # Procedural primitives, CSG, mesh, collision, mass properties
│   ├── simulation/             # Backend interface, compiler, PyBullet, analytical, mock
│   ├── validation/             # Schema, geometry, physics checkers + repair
│   └── infrastructure/         # Config, logging, cache, serialization, file storage
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── regression/
│   └── fixtures/
├── examples/                   # falling_ball, ball_on_slope, bouncing_ball, torus_drop, hinged_door
└── outputs/                    # meshes, trajectories, videos, reports
```

## Phase 1 Implementation Order

### Step 1 — Project skeleton
- `pyproject.toml` with Python project metadata and dependencies (pybullet, pydantic, pytest, PyYAML, trimesh/numpy-stl)
- `src/physical_agent/` package structure
- `tests/` with pytest configuration
- `configs/` with base YAML files
- Basic logging setup

### Step 2 — Domain layer (core interfaces & data models)
Define all four core interfaces (`PerceptionService`, `GeometryEngine`, `SimulationBackend`, `ResultValidator`) and domain objects (`ObjectModel`, `GeometryModel`, `SimulationTask`, `ModelHypothesis`, `SimulationResult`, `ValidationReport`, `PipelineContext`). Simple dataclasses/Pydantic models — no implementation logic yet.

### Step 3 — MockPerceptionService
Hand-crafted service returning structured `PerceptionResult` for: sphere, box, cylinder, torus. Used to test the rest of the pipeline.

### Step 4 — Geometry Engine (primitives)
Procedural generation of sphere, box, cylinder, torus — output vertices, triangles, normals, bounding box. Mesh file export (OBJ/STL).

### Step 5 — PyBulletBackend
Create rigid bodies from compiled geometry, set mass/inertia, gravity, friction, restitution, initial pose. Run fixed-duration simulation, record trajectory.

### Step 6 — AnalyticalBackend
Closed-form solutions for: free fall, projectile motion, ideal slope, simple pendulum (small angle), 1D spring. Used as ground-truth comparison vs PyBullet.

### Step 7 — PhysicsChecker
Validate: NaN, severe penetration, non-positive mass, invalid inertia, abnormal energy growth, numerical explosion.

### Step 8 — End-to-end pipeline (torus drop demo)
```
MockInput → ObjectModel → Torus Geometry → PyBullet → Trajectory → ValidationReport
```
Run the full chain for "a torus dropped from height" — record position, orientation, first contact.

## Phase 1 Scope — What NOT to implement

- Real VLM / arbitrary image reconstruction
- Arbitrary complex meshes
- Deformable bodies, fluids, fracture
- Multi-physics
- Microservices / database / multi-user / distributed
- General code generation
- Model training

## Code Conventions

- **Python** throughout
- **Pydantic** (preferred) or `dataclass` for data models
- **Abstract base classes** for all service interfaces
- **Custom exception hierarchy**: `PhysicalAgentError` → `PerceptionError`, `GeometryBuildError`, `SimulationCompileError`, `SimulationRuntimeError`, `ValidationFailure`, etc.
- **PipelineError** dataclass records stage + module + message + retryable + suggested_action for every failure
- **YAML** for configuration (never hardcode material bounds, geometry resolution, simulation defaults)
- **pytest** with fixtures for all tests
- Type hints everywhere
- Docstrings on public interfaces
- Every pipeline stage persists its intermediate result

## Error Handling

Unified error system with `PipelineError` recording:
- `stage` — which pipeline stage failed
- `module` — which module
- `message` — summary
- `retryable` — can this be retried automatically?
- `suggested_action` — what fix to attempt

Rule-based auto-repair for common issues:

| Issue | Auto-fix |
|---|---|
| Parameter out of bounds | Clamp to valid range |
| Mass ≤ 0 | Use minimum legal mass |
| Unnormalized quaternion | Normalize |
| Mesh not closed | Patch or fall back to collision proxy |
| Invalid inertia | Recompute from geometry |
| Severe penetration | Reduce time step or increase solver iterations |
| Numerical explosion | Reduce time step, add damping |
| Non-convex collision fails | Fall back to convex hull / decomposition |

## Testing Strategy

### Unit tests
- Primitive parameter validation (torus inner/outer radius, etc.)
- Quaternion normalization
- Sphere/box/cylinder/torus geometry generation
- Coefficient of restitution range
- Mass/inertia validity
- CSG tree validity
- Config parsing

### Integration tests
- `GeometryModel → MeshData`
- `ObjectModel → CompiledSimulation`
- `CompiledSimulation → PyBullet`
- `InputRequest → PerceptionResult`
- `SimulationResult → ValidationReport`

### Regression tests (fixed scenarios)
- Free fall, ball bounce, slope slide, cylinder roll, torus drop
- Simple pendulum, hinged door
- Record: final position, max height, first contact time, max velocity, total energy error, penetration flag, numerical stability flag

## Phase 1 Acceptance Criteria

1. Project installs and imports cleanly (`pip install -e .`)
2. All four core interfaces defined
3. `MockPerceptionService` produces structured results
4. Sphere, box, cylinder, torus meshes generated
5. Geometry compilable to PyBullet rigid bodies
6. Free-fall simulation runs and saves trajectory
7. At least one validation report outputs
8. `AnalyticalBackend` compares with PyBullet results
9. Torus free-fall demo runs stably end-to-end

## Development Workflow

- Work from `main` branch during Phase 1
- Implement each step in order (Step 1 → Step 8)
- After each step, run associated tests before moving on
- Use `/verify` to exercise the pipeline when making behavioral changes
- Use `/code-review` before committing significant changes
- Use `physical-agent` prefix for commit messages (e.g., `physical-agent: add GeometryEngine interface`)
