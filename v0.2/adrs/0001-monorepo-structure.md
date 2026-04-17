# ADR-0001: Monorepo Structure

**Status:** Accepted
**Date:** 2026-04-17
**Author:** Staff Engineer

## Context

We are building a multi-tenant university knowledge-base chatbot. The system has several distinct components: a Python backend (API + ingestion + retrieval + generation + eval), infrastructure-as-code (Terraform for GCP), and a frontend application (Flutter web widget). We need a repository structure that supports independent development of these components while sharing core abstractions.

## Decision

Single monorepo with the following top-level layout:

```
/
├── packages/           # Python packages (core, api, ingestion, retrieval, tui, eval)
├── apps/
│   └── flutter_widget/ # Flutter web-embed widget
├── migrations/         # Alembic
├── adrs/               # Architecture Decision Records
├── scripts/            # Dev/ops scripts
└── tests/              # All Python tests
```

**Key conventions:**
- `packages/` contains importable Python code, organized by domain. TUI lives here as `packages/tui/` since it's a Python package sharing `packages/core` types.
- `apps/flutter_widget/` has its own `pubspec.yaml` and Dart build system, independent of Python tooling.
- All services run via `docker-compose.yml` — no separate IaC tooling needed for v1.
- One class or top-level function per file throughout.
- All Python deps managed by a single `pyproject.toml` at the root with `uv`.

## Alternatives Considered

1. **Separate repos per component** — rejected because shared abstractions (`Embedder`, `VectorStore`) would require publishing internal packages. Overhead not justified at this team size.
2. **Flat src/ layout** — rejected because mixing Flutter and Python in one namespace is confusing. The `packages/apps` split makes ownership clear.

## Consequences

- CI must understand the monorepo and run relevant checks per changed path.
- Flutter widget in `apps/flutter_widget/` has its own `pubspec.yaml` and build step, independent of Python tooling.
- All infrastructure is Docker-based — `docker-compose.yml` is the single source of truth for service topology.
