# ADR 0001: Bootstrap Python Project and Authoritative Domain Contracts

- Status: accepted
- Date: 2026-03-10

## Context

NullVector starts from an almost empty repository but must establish strict typed contracts,
reproducible local development, CI-ready validation commands, and scaffolding for future parser,
workflow, storage, and observability phases.

## Decision

Bootstrap the repository as a Python package under `src/nullvector` with:

- Pydantic v2 as the authoritative runtime contract layer
- `ruff`, `mypy`, and `pytest` as the baseline validation stack
- `uv`-driven local setup and command execution through `make`
- explicit fixture, integration-test, corpus-test, and ADR directories

## Consequences

- Phase 00 delivers a typed foundation without prematurely implementing parser or workflow logic.
- Later phases can extend the package structure without changing the repository skeleton.
- CI systems can invoke the same validation commands as local development through `make ci`.

