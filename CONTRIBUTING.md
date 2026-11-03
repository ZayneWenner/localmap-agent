# Contributing

Thanks for looking at this. It is a small project, so contributing is easy.

## The one rule

**Do not add heavy dependencies.** The entire point of this repository is that a
local model on a laptop can drive a real tool loop. If a change needs
`langchain` or a cloud SDK, it probably does not belong here. Current total
dependency count: **1** (`requests`).

## Getting set up

```bash
git clone https://github.com/ZayneWenner/localmap-agent.git
cd localmap-agent
pip install -r requirements.txt
```

You do **not** need Ollama or a model to contribute to the tests, the geometry
layer, the renderer, or the docs:

```bash
python -m unittest discover -s tests -v      # 33 tests, zero extra packages
```

You **do** need Ollama to run the agent end to end:

```bash
ollama pull gemma4:e2b && ollama serve
python run.py --probe
python run.py "Mark 6 places around Sias University"
```

## Where to start

| If you want to… | Look at |
|---|---|
| Fix a bug in validation or coordinates | `localmap_agent/geo_tools.py` |
| Improve how the model is prompted | `localmap_agent/agent.py` (`SYSTEM_PROMPT`, `_plan_places`, `_write_description`) |
| Change the map's appearance | `localmap_agent/map_renderer.py` |
| Support another model / Ollama version | `localmap_agent/ollama_client.py`, `localmap_agent/config.py` |
| Add tests | `tests/` |
| Improve docs | `README.md`, `docs/` |

## Code style

- Python 3.10+, 4-space indent, type hints on public functions.
- Comments in Chinese are fine — the author works in Chinese. **Documentation
  (`*.md`) is in English.** Keep that split consistent.
- Explain *why* in comments, not *what*. The existing comments record why
  `num_ctx` is not sent and why `trust_env=False`; that is the standard.
- Every new tool needs: a `tool_*` function, an entry in `DISPATCH`, an entry in
  `build_schemas()`, and at least one test.

## Tests

Required for any change to `geo_tools.py`, `memory.py` or `map_renderer.py`.
They must stay **offline and deterministic** — no network, no model.

```bash
python -m unittest discover -s tests -v
# or, if you prefer:
pip install pytest && pytest tests/
```

## Commit messages

Short, imperative, and say what changed:

```
fix(geo): reject NaN coordinates before the bbox check
docs(readme): document the --key flag
test(memory): cover corrupted session file
```

Prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.

## Pull requests

1. Fork and branch (`feat/...`, `fix/...`).
2. Make sure `python -m unittest discover -s tests -v` passes.
3. Update `CHANGELOG.md` under **Unreleased**.
4. Fill in the PR template — especially "what did you observe the model doing
   before and after", if you touched the agent loop.

## Reporting a bug

Use the issue template. The most useful thing you can include is the run log:
`logs/agent_run_log.json` from the failing run. It records every tool call and
every rejection, which is usually enough to diagnose the problem without a
model.

## A note on AI-assisted contributions

This project was built with AI assistance and says so in `AI_LOG.md`. If you use
AI for your contribution, say so in the PR. Do not submit work you have not read.
