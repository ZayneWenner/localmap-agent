# AI_LOG.md — how AI was used to build this

> **Read this before judging the project.** It is the honest record, including
> the failed attempts. Nothing here is retro-fitted.

**One-line version:** AI (WorkBuddy, an agentic coding assistant) was used
across environment recon, code drafting, debugging, test writing and
documentation. It took **five code iterations (v1→v5) and four failures** to get
the agent loop working, plus a separate round to turn the result into this
repository. This was not one prompt producing one answer.

**Important distinction:** AI assisted in *building* this tool. The Chinese
descriptions you see on the generated map are written by the **local Gemma 4
E2B model running on localhost** — not by a cloud AI. Do not conflate the two.

---

## 1. Tooling

| Role | Tool |
|---|---|
| Development assistant | WorkBuddy (agentic IDE assistant with file + shell access) |
| Runtime model | Gemma 4 E2B via Ollama 0.40.0, on localhost |
| Geocoding | Photon (OpenStreetMap), called by the host code |
| Human | Jingwen Jia — set direction, reviewed, corrected, decided |

---

## 2. Phase 1 — figuring out what to build

**My instruction to the AI:** essentially "do the homework", plus the challenge
pack in the working directory.

**What the AI did:**

1. Read `CHALLENGE.md`, `challenge.json`, `rubric.json` and two PDFs.
2. Collected the machine's hardware profile via WMI.
3. Verified online that Gemma 4 actually exists and which Ollama tags are real.

**The decision that mattered.** The AI found a simplified track in the challenge
materials: run a model, post about it, write an AAR — done. It then cross-checked
`rubric.json` and showed the arithmetic: the simplified path forfeits the agent
capability and technical implementation dimensions **and** triggers two red flags
(`one_shot_ai`, `no_ai_log`). I chose the harder path. That choice is why this
repository exists instead of a screenshot.

**Two hardware constraints the AI surfaced before any code was written:**

- C drive had 6.8 GB free; the smallest model is 4.6 GB → runtime had to go on E drive.
- 16 GB RAM / 4 GB VRAM → the 26B and 31B tiers are physically impossible.

---

## 3. Phase 2 — environment setup: four real bugs

| # | Symptom | Wrong guess | Actual cause | Fix |
|---|---|---|---|---|
| 1 | `ollama pull` stuck at 0% for 10 min | slow network | service never started; port 11434 refused (`WinError 10061`) | `ollama serve` first |
| 2 | Python → `127.0.0.1:11434` returns `502 Bad Gateway` | "Ollama crashed" | `HTTP_PROXY` was set, and `requests` honours env vars even for localhost | `session.trust_env = False` |
| 3 | 4.59 GB model downloaded but `ollama list` empty | — | the v2 manifest file was written as **0 bytes** every time; the v1 manifest was a valid 1871-byte JSON | AI read the server log, found `bad manifest name`, and copied the v1 manifest to the v2 path |
| 4 | `Gemma4Assistant requires ctx_other to be set` | — | **only** `num_ctx` triggers it; `temperature` / `top_p` / `top_k` / `num_predict` are all safe | stop sending `num_ctx`; let Ollama size the context from VRAM |

**An AI mistake I caught:** the first attempt put `session.trust_env = False`
*before* `self.session = requests.Session()`, which raises `AttributeError`.
Reordering fixed it. Recorded here because the log is supposed to be honest.

Result after fixes: **20.5 tok/s**, model replies `OK`.

---

## 4. Phase 3 — building the agent (five iterations)

Full table in [README.md](./README.md#five-iterations-four-failures). Summary:

- **v1** ❌ 1 marker — my own boundary was wrong (30 km when the campus is ~40 km
  from the city centre), so every legitimate answer was rejected; the model
  retried 8 times, then gave up.
- **v2** ⚠️ 2 markers — added geographic biasing to the geocoder; foreign matches
  (Milwaukee, Chiayi) disappeared.
- **v3** ❌ 2 markers — added a "goal check" that pushes the model back when the
  count is low. Nudged 3 times, never resumed. **Key insight: a 2B model's
  failure mode is giving up, not being wrong — and once it has quit, you cannot
  push it back into context.**
- **v4** ⚠️ 6 markers, quality collapsed — 4 stacked on one coordinate, empty
  descriptions, wrong argument keys. Cause: I asked the model to write prose *and*
  call tools *simultaneously*; it did neither well.
- **v5** ✅ 6 markers — split "write text" (model, plain chat) from "call tools"
  (model) from "fetch and validate coordinates" (host). Descriptions 100%
  model-written.

### Prompt optimisation log

| Version | Prompt change | Effect |
|---|---|---|
| v1 | "Call `search_place` first" | model used long English queries → matched foreign places |
| v2 | "Use short Chinese names; never include *near* / *Sias University*; ignore results outside China" | foreign matches gone |
| v3 | "Call `list_markers` before finishing to check the count" | **no effect** — the model ignored it |
| v4 | "Prefer large, real places; do not invent vague names" | better place selection |
| v5 | "Under 40 characters; say what a visitor actually does; no filler like '值得一去'" | visibly better descriptions |

**Most transferable lesson:** state the *specific* thing to avoid. "Do not invent
places" does nothing. "Do not invent names like 'XX 美食街' or '本地连锁超市'" works.

---

## 5. Phase 4 — turning the skill into this repository (the C5 round)

A second, separate round of AI use:

| Step | AI's role | My role |
|---|---|---|
| Repo scaffolding (structure, `.gitignore`, CI, issue/PR templates) | drafted | reviewed, trimmed |
| Porting the code out of the assignment folder | executed by AI | I set the rule: no hardcoded submission filenames |
| `requests` made optional in `ollama_client.py` | proposed by me after tests failed to import | AI implemented |
| 33 unit tests | AI drafted; **I required them to be zero-dependency** | I rejected the pytest version when it could not be installed |
| README / ATTRIBUTION / CONTRIBUTING / CHANGELOG / docs | AI drafted from the existing Chinese logs | I checked every factual claim against the original run logs |
| This file | AI drafted from the C4D log | I verified against the failure records |

**A real constraint worth recording:** `pytest` could not be installed in this
environment (sandbox blocked it). Rather than ship tests I could not run, I
rewrote them with the standard library's `unittest`. Result: `python -m unittest
discover -s tests -v` works on a machine with **nothing** installed, which is
better for a "clone and it runs in 5 minutes" goal anyway. Verified: 33 passed.

**Second real bug found in this round:** `unittest discover` on Python 3.11+
raises `Start directory is not importable` unless `tests/` has an `__init__.py`
when the start dir differs from the top-level dir. Fixed by adding the marker
file. The reason is documented in that file so it does not get "cleaned up".

---

## 6. What was done by hand, and why

Reverse evidence, as required:

| Item | Why not AI |
|---|---|
| The decision to take the harder path | A judgement call about grading risk; AI supplied the arithmetic, I decided |
| `MAX_DISTANCE_KM = 60` | AI suggested widening the boundary; I measured the real distances and chose the number |
| Renaming `贾静文_C4D_map.html` → `map.html` | AI copied the file with the submission-specific name; I caught it |
| Rejecting the pytest-based tests | I decided after the install failed |
| Every factual claim in this file and the README | Verified line by line against `logs/agent_run_log.json` |

---

## 7. Boundaries of AI involvement

| Stage | AI involvement |
|---|---|
| Environment recon and model selection | AI-led, I confirmed |
| Code skeletons for the five modules | AI-drafted, revised across five rounds |
| Locating the four environment bugs | AI-led diagnosis, I provided the machine |
| Unit tests | AI-drafted, I changed the framework and fixed the discovery bug |
| All documentation | AI-drafted from real logs, I verified |
| **Map descriptions (Chinese text)** | **Written by the local Gemma 4 E2B model — not by a cloud AI** |
| **Coordinates** | **Photon / OpenStreetMap public data, plus model estimates that are labelled as such** |

---

## 8. What I would do differently

1. **Probe the model's capability ceiling on day one**, before designing a
   multi-step loop around it. v3 and v4 were spent discovering what a
   capability check would have told me in ten minutes.
2. **Validate the data source before depending on it.** Photon's coverage of
   Xinzheng POIs is poor, and three of six coordinates paid for that.
3. **Measure before setting thresholds.** The 30 km boundary was invented; the
   60 km one was measured.
4. **Write tests earlier.** They existed only in the C5 round; if they had
   existed in the C4D round, the argument-key mismatch in v4 would have been
   caught by a test instead of by reading logs.

---

## 9. Evidence index

```
examples/
├── map_data.json                 real v5 output, 6 markers
├── sample_run_v5.txt             successful run transcript
└── sample_run_v1_FAILED.txt      v1: 19 steps, 1 marker

tests/                            33 unit tests, all passing
docs/TROUBLESHOOTING.md           the four environment bugs in detail
docs/ARCHITECTURE.md              module-by-module design
```

Run logs are regenerated on every run into `logs/` (git-ignored).
