# Pull request

## What changed

<!-- One or two sentences. -->

## Why

<!-- What problem does this solve? Link the issue if there is one. -->

## Type

- [ ] Bug fix
- [ ] New feature / new tool
- [ ] Documentation
- [ ] Tests / CI
- [ ] Refactor

## How was it tested

- [ ] `python -m unittest discover -s tests -v` passes
- [ ] Ran the agent end to end (`python run.py "..."`) — attach the marker count
      and, if you touched the loop, a before/after comparison
- [ ] Docs updated if behaviour changed

## If you touched the agent loop

This matters more here than in most projects: the model is 2B and its failure
mode is *giving up*, not *being wrong*. Please record:

| | Before | After |
|---|---|---|
| Markers produced | | |
| Steps used | | |
| Descriptions model-written | | |
| Model tag | | |

Paste the relevant part of `logs/agent_run_log.json`.

## AI assistance

This project was built with AI assistance and documents it in `AI_LOG.md`. If
you used AI for this PR, say what it did and confirm you have read the diff.

<!-- e.g. "Claude drafted the test cases; I rewrote the assertions." -->

## Checklist

- [ ] No new heavy dependencies
- [ ] Comments explain *why*, not *what*
- [ ] Docs in English, comments may be Chinese
- [ ] `CHANGELOG.md` updated under Unreleased
