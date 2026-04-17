# ADR-0001: Monorepo Structure

**Status:** Accepted
**Date:** 2026-04-17
**Author:** Staff Engineer

## Context

We are building a multi-tenant university knowledge-base chatbot. The system has several distinct components: a Python backend (API + ingestion + retrieval + generation), infrastructure-as-code (Terraform for GCP), and frontend applications (Textual TUI, Flutter web widget). We need a repository structure that supports independent development of these components while sharing core abstractions.

## Decision

Single monorepo with the following top-level layout:

```
v0.2/
├── packages/       # Python library code (core, api, ingestion, retrieval, generation)
├── apps/           # Runnable frontends (tui/, widget/)
├── infra/          # Terraform modules for GCP
├── migrations/     # Alembic database migrations
├── tests/          # All Python tests
└── docs/adr/       # Architecture decision records
```

**Key conventions:**
- `packages/` contains importable Python code, organized by domain. No runnable entry points live here except `packages/api/server.py` (the uvicorn target).
- `apps/` contains standalone applications with their own build systems (Python/Textual for TUI, Flutter/Dart for widget).
- `infra/` contains Terraform, separated from application code.
- One class or top-level function per file throughout.
- All Python deps managed by a single `pyproject.toml` at the root with `uv`.

## Alternatives Considered

1. **Separate repos per component** — rejected because shared abstractions (`Embedder`, `VectorStore`) would require publishing internal packages. Overhead not justified at this team size.
2. **Flat src/ layout** — rejected because mixing Terraform, Flutter, and Python in one namespace is confusing. The `packages/apps/infra` split makes ownership clear.

## Consequences

- CI must understand the monorepo and run relevant checks per changed path.
- Flutter widget in `apps/widget/` has its own `pubspec.yaml` and build step, independent of Python tooling.
- Terraform in `infra/` can be applied independently of application deploys.
