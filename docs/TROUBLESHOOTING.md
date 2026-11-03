# Troubleshooting

Every bug in this file actually happened on the author's machine. Each entry
records the symptom, the wrong guess, the real cause, and the fix.

## Environment

### 1. `ollama pull` hangs at 0%

**Symptom:** download progress stays at zero for ten minutes.
**Wrong guess:** slow network.
**Real cause:** the Ollama service was never started. Port 11434 refuses
connections (`WinError 10061`).
**Fix:**

```bash
ollama serve        # in a separate terminal, keep it running
ollama pull gemma4:e2b
```

Confirm with `python run.py --probe`.

### 2. `502 Bad Gateway` when talking to `127.0.0.1:11434`

**Symptom:** Python cannot reach Ollama even though `ollama serve` is running.
**Wrong guess:** "Ollama crashed."
**Real cause:** an `HTTP_PROXY` environment variable is set, and `requests`
honours proxy environment variables **even for localhost**. The request is sent
to the proxy, which returns 502.
**Fix** (already in `ollama_client.py`):

```python
self.session = requests.Session()
self.session.trust_env = False          # must come AFTER the Session() call
self.session.proxies = {"http": None, "https": None}
```

> Ordering matters. Putting `trust_env` before `Session()` raises
> `AttributeError`. This mistake was made once and is recorded in `AI_LOG.md`.

### 3. Model downloaded (4.59 GB on disk) but `ollama list` is empty

**Symptom:** the file is there; Ollama does not see it.
**Real cause:** the v2 manifest was written as **0 bytes** every time. Deleting
and re-pulling did not help. The v1 manifest, however, was a valid 1871-byte JSON.
**Diagnosis:** the Ollama server log contained

```
WARN bad manifest name=registry.ollama.ai/library/gemma4:e2b
     error="unexpected end of JSON input"
```

**Fix:** copy the working v1 manifest to the v2 path
(`manifests-v2/ollama.com/library/gemma4/e2b`). If you hit this, check the
server log first — it tells you exactly which file is broken.

### 4. `Gemma4Assistant requires ctx_other to be set`

**Symptom:** the model loads, then inference fails.
**Real cause:** sending `num_ctx` in the request. Tested one parameter at a
time: `temperature`, `top_p`, `top_k` and `num_predict` are all safe; **only
`num_ctx` triggers this.**
**Fix:** do not send `num_ctx`. Let Ollama size the context from available VRAM
(4.1 GB VRAM → 4096 tokens here). To control it globally, use the server-side
environment variable `OLLAMA_CONTEXT_LENGTH`.

---

## Running the agent

### Model produces 1–2 markers and stops

This is the v3 failure mode: **a small model abandons a long composite task**.
Pushing it back into context does not work — once it has quit, it is no longer
in that context.

What does work:

1. Use `run_planned()` (the default with `--min-markers`), which plans place
   names first and then executes one place per call.
2. Keep each model call to a single job: prose *or* tool call, never both.
3. Raise `--min-markers` only if the model is actually capable; otherwise you
   just get more estimates.

### Markers stack on one coordinate

This was v4. Two causes:

- The geocoder returned nothing and the model fell back to the centre point.
- The model emitted the wrong argument keys (`{"query": ...}` instead of
  `{"latitude": ...}`), so the host filled in defaults.

Check `logs/agent_run_log.json`: if `source` is `model` and several markers share
identical coordinates, that is what happened. Improve POI coverage by using more
common place names, or add a second geocoder.

### Descriptions are empty or template-generated

The model returned empty text on the prose call. v4 hit this when prose and tool
calls were combined. If you see it with the default `run_planned()`, check that
`--model` points to a model that is actually loaded — a missing model makes the
client fall back and return empty content.

### `map.html` shows a blank grey area

- Internet access is required for the map tiles and the Tencent Maps GL JS
  script. The *inference* is offline; the *basemap* is not.
- If you are outside mainland China, the tile CDN may be unreachable. Point
  `map_renderer.py` at a renderer that serves your region.

### Markers appear offset by a few hundred metres

You skipped the WGS-84 → GCJ-02 conversion, or applied it twice. All internal
state is WGS-84; conversion happens only in `map_renderer.to_gcj_markers()`.

---

## Tests

### `Start directory is not importable`

`python -m unittest discover -s tests` fails on Python 3.11+ unless `tests/`
contains `__init__.py`. This repository has it, with a comment explaining why —
please do not delete it as "unused".

### `ModuleNotFoundError: No module named 'requests'`

Only needed to reach Ollama. Tests do not need it:

```bash
python -m unittest discover -s tests -v      # runs fine without requests
```

To run the agent: `pip install -r requirements.txt`.

---

## Still stuck?

Open an issue and attach `logs/agent_run_log.json` from the failing run. It
contains every tool call and every rejection, which is usually enough to
diagnose the problem without reproducing it.
