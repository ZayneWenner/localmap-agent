# Changelog

All notable changes to this project. Format: `Keep a Changelog`, SemVer.

## [Unreleased]

Nothing yet. Ideas, in rough priority order:

- Make the campus area configurable via CLI (`--center`, `--max-distance-km`)
  instead of editing `geo_tools.py`.
- Add a second geocoder (Nominatim) as a fallback for thin POI coverage.
- Retry-with-reflection when the model abandons the task mid-run (the v3 problem).
- Export GeoJSON in addition to HTML.

## [1.1.0] — 2026-10-11 — open-sourced

The project was extracted from an assignment submission and published as a
standalone repository.

### Added

- 33 unit tests covering haversine, GCJ-02 conversion, every guardrail
  rejection path, board operations, tool schemas, HTML rendering and memory
  persistence. Zero third-party dependencies, no network, no model required.
- `README.md`, `ATTRIBUTION.md`, `AI_LOG.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.
- `docs/ARCHITECTURE.md` and `docs/TROUBLESHOOTING.md`.
- `examples/`: a real v5 output (`map_data.json`), the successful v5 transcript,
  and the failed v1 transcript.
- `.github/`: bug report and feature request issue templates, and a PR template.
- `ci/github-actions-ci.yml`: the GitHub Actions workflow (test suite on
  Python 3.10–3.13). It lives outside `.github/workflows/` because the token used
  to publish this repository carried the `repo` scope only, which GitHub refuses
  for workflow paths; copying it into `.github/workflows/ci.yml` enables it.
- MIT `LICENSE`, `.gitignore`.

### Changed

- `requests` is now an **optional import**. The geometry, guardrail, renderer
  and memory layers can be imported and tested on a machine with nothing
  installed; a clear error appears only when you actually try to reach Ollama.
- Output filename changed from the submission-specific
  `贾静文_C4D_map.html` to a neutral `map.html`.
- Added `tests/__init__.py` so `unittest discover` works on Python 3.11+.

### Fixed

- `unittest discover` raised `Start directory is not importable` because
  `tests/` was not a package (Python 3.11 removed namespace-package support).

## [1.0.0] — 2026-10-08 — the agent loop works

First version where the local model drives the tool loop end to end.

### Added

- Five modules: `config.py`, `ollama_client.py`, `geo_tools.py`, `agent.py`,
  `memory.py`, `map_renderer.py`.
- CLI with three modes: `--probe`, one-shot, `--interactive`.
- Seven tools: `search_place`, `add_map_marker`, `revise_map_marker`,
  `remove_map_marker`, `compute_distance`, `set_map_view`, `list_markers`.
- Two-layer memory: short-term chat window + persistent JSON facts.
- Tencent Maps GL JS rendering with WGS-84 → GCJ-02 conversion.

### The v5 design

Splitting "write prose" (model) from "look up and validate coordinates" (host)
was the change that made it work. v1–v4 are documented in `AI_LOG.md` — four
failed iterations, kept deliberately.

### Verified on

Intel i7-7700HQ · 16 GB RAM · GTX 1050 Ti 4 GB · Ollama 0.40.0 · `gemma4:e2b`
Q4_K_M · peak 30.74 tok/s.
