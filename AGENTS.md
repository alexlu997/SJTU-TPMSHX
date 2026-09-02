# SJTU-TPMSHX agent instructions

Read [README.md](README.md) for setup and [docs/architecture.md](docs/architecture.md)
before changing solver, pipeline, closure, or data-loading code.

## Scope discipline

- Do only the requested work and its necessary consequences.
- Do not add speculative fallbacks, compatibility layers, migrations,
  abstractions, dependencies, or defensive wrappers.
- Do not add hash-, digest-, or checksum-based tests.
- Preserve validation that protects physical correctness, data integrity, or a
  demonstrated failure mode.
- Keep raw experiment and CFD data under `data/raw_data/`; `data/` is local and
  must not be committed.
- Do not commit or push unless the user asks.

## Change discipline

- Keep GUI concerns in `ui/` and `controllers/`; lower layers stay Qt-free.
- Treat `pipelines/` as orchestration and `solvers/` as numerical
  implementation. Do not duplicate correlations or physical constants across
  those layers.
- Run the existing tests relevant to the files changed. Run broader numerical
  validation only when solver, closure, or pipeline behavior changes.
