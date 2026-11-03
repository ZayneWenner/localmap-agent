# ATTRIBUTION.md — what is borrowed, what is original

> The point of this file: a reviewer should be able to tell, without asking me,
> which lines are mine and which came from somewhere else.

---

## 1. Third-party components

### Runtime

| Component | Version | Role | License |
|---|---|---|---|
| [Ollama](https://ollama.com) | 0.40.0 | Local model runtime + OpenAI-compatible API | MIT |
| Gemma 4 E2B | Q4_K_M, 4.6B | The only "brain" in this project | Apache 2.0 |
| NVIDIA Vulkan runtime | — | Lets a GTX 1050 Ti participate in inference | bundled with driver |

### Python dependencies

| Package | Role | Required? |
|---|---|---|
| `requests` | HTTP calls to the local Ollama server | Yes — and it is the *only* one |
| stdlib `json / math / urllib / pathlib / dataclasses / unittest` | tools, coordinate maths, logging, tests | Yes |

**Deliberately not used:** `openai`, `langchain`, `llama-index`, `transformers`,
`gradio`. Fewer dependencies means fewer things that can break on someone else's
machine, and it keeps every HTTP request visible and auditable — which is the
point of a *local* agent.

### Front end / rendering

| Component | Role | Source |
|---|---|---|
| Tencent Maps GL JS | Basemap and marker rendering | `https://map.qq.com/api/gljs?v=1.exp` (official CDN; no key is embedded) |

---

## 2. Documentation and knowledge I consulted

| Source | What I took from it |
|---|---|
| [Ollama Gemma 4 model page](https://ollama.com/library/gemma4) | Sizes, context lengths, and the recommended sampling parameters (`temperature=1.0`, `top_p=0.95`, `top_k=64`) |
| [Google's Ollama integration docs](https://ai.google.dev/gemma/docs/integrations/ollama) | Correct tag naming and `ollama pull` usage |
| [Tencent Maps GL JS docs](https://lbs.qq.com/webApi/javascriptGL/glGuide/glOverview) | `MultiMarker` / `MultiLabel` / `MultiPolyline` / `InfoWindow` API usage |
| [Photon geocoder](https://photon.komoot.io/) | Query parameters, including the `lat`/`lon` biasing that fixed v2 |
| Wikipedia / public references on GCJ-02 | The coordinate-offset algorithm (see §3) |
| Python `unittest` docs | Discovery rules — specifically the `__init__.py` requirement on 3.11+ |

---

## 3. Algorithms that are public knowledge, not my invention

- **WGS-84 → GCJ-02 conversion.** The "Mars coordinate" offset is a published
  Chinese national standard transform. I implemented it from the public formula;
  the mathematics is not mine, the implementation and its integration are.
- **Haversine distance.** Standard great-circle formula.
- **ReAct loop** (reason → act → observe). A published agent pattern
  (Yao et al., 2022). My contribution is the specific split in §4, not the loop.

---

## 4. What I wrote myself

| Module | Originality |
|---|---|
| `ollama_client.py` | Mine. The proxy bypass (`trust_env = False`) and the endpoint fallback are specific to this machine's failure modes |
| `geo_tools.py` | Mine. The tool set, the validation rules, and the "reject and feed the error back" mechanic were designed in response to watching a 2B model hallucinate coordinates |
| `agent.py` | Mine. The plan-then-execute structure, the fallback parser for malformed tool calls, and the argument coercion |
| `memory.py` | Mine. The two-layer structure (window + persistent JSON facts) |
| `map_renderer.py` | Mine. The card list + connecting lines + category colouring combination |
| `tests/` | Mine, written for this repository |
| All documentation | Mine (drafted with AI assistance, verified by me — see `AI_LOG.md`) |

---

## 5. AI assistance

AI (WorkBuddy) was used throughout: scaffolding, drafting, debugging,
documentation. It was **not** one prompt producing one answer — see
[`AI_LOG.md`](./AI_LOG.md) for the five-iteration record, the four failed
attempts, the AI mistake I corrected, and the tasks I did by hand.

Content on the generated map (place names, Chinese descriptions, categories) is
produced by the **local Gemma 4 E2B model**, not by a cloud AI.

---

## 6. Compliance

- Basemap: Tencent Maps, which holds the required mainland-China map service
  qualification. OSM / Google / Mapbox tiles are not used for rendering.
- OSM-derived WGS-84 coordinates are converted to GCJ-02 before rendering;
  skipping that shifts markers by 300–600 m inside China.
- No API key appears in the generated HTML unless the user passes `--key`.
- All location data is public geographic information; no personal coordinates.
- Gemma 4 is Apache 2.0 and is downloaded by the user, not redistributed here.

---

## 7. Licence compatibility

Project code: MIT (see `LICENSE`). Dependencies: `requests` (Apache 2.0),
Ollama (MIT), Gemma 4 (Apache 2.0). No copyleft component is linked or vendored.
