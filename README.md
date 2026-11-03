# localmap-agent

**A local LLM agent that builds an interactive map: input a sentence of plain language, output a self-contained HTML map.**

No API key. No cloud inference. No monthly fee. Everything runs on `127.0.0.1`.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-1%20(requests)-orange)
![Tests](https://img.shields.io/badge/tests-33%20passing-brightgreen)

---

## 提交物（EduSeed C5 交付物）

| 平台要求 | 仓库内文件 |
|---|---|
| README.md | `README.md`（本文件） |
| repo 链接 | [`贾静文_C5_repo链接.md`](./贾静文_C5_repo链接.md) |
| AI 日志 | [`贾静文_C5_AI日志.md`](./贾静文_C5_AI日志.md)（英文版 `AI_LOG.md`） |
| 拿来说明 | [`贾静文_C5_拿来说明.md`](./贾静文_C5_拿来说明.md)（英文版 `ATTRIBUTION.md`） |

> 四类交付物均位于仓库根目录，可直接点击查看。

---

## What problem does this solve?

Most "LLM agent" demos have a dirty secret: the model runs on someone else's
computer. You paste an API key, your prompt leaves your machine, and the bill
arrives monthly.

This project asks a narrower question:

> Can a **2B-parameter model on a 4 GB laptop GPU** actually drive a real tool
> loop — decide what to call, get the result back, notice it was wrong, and fix it?

The answer is yes, but only if you stop asking the model to do what code does
better. That discovery is the whole project. See
[Five iterations, four failures](#five-iterations-four-failures).

| | Before this project | With this project |
|---|---|---|
| Inference | Cloud API, key required, data leaves the machine | `gemma4:e2b` on localhost via Ollama |
| Coordinates | Model dreams them up (hallucinated) | Geocoder supplies them, guardrails verify them |
| Arithmetic | Model guesses the distance | `compute_distance` tool does the maths |
| Failure | Silent wrong output | Invalid input is rejected and fed back to the model as an error |
| Cost | Per-token, forever | Electricity |

---

## Quick start

### 0. Prerequisites

1. Install [Ollama](https://ollama.com).
2. Pull the model and start the server:

```bash
ollama pull gemma4:e2b      # 4.6 GB, Q4_K_M
ollama serve                # keep this terminal open
```

> `gemma4:e2b` is the edge tier. On a machine with more VRAM, `gemma4:e4b` or
> `gemma4:26b` also work — pass `--model gemma4:e4b`. The model list and the
> reasoning behind the choice live in `localmap_agent/config.py`.

### 1. Install

```bash
git clone https://github.com/ZayneWenner/localmap-agent.git
cd localmap-agent
pip install -r requirements.txt     # exactly one package: requests
```

### 2. Verify your environment

```bash
python run.py --probe
```

This checks that Ollama is reachable, the model is present, and the model can
chat, emit JSON, and emit tool calls. It prints tok/s so you know what to expect.

### 3. Build a map

```bash
python run.py "Mark at least 6 places around Sias University: transport hubs, places to eat, parks, and somewhere with history."
```

Output:

```
✔ Interactive map : ./map.html
✔ Structured data : ./map_data.json
✔ Raw run log     : ./logs/agent_run_log.json
✔ Markers         : 6
```

Open `map.html` in a browser. That is it — one self-contained file.

---

## Example

**Input**

```
python run.py "Mark at least 6 places around Sias University that are genuinely useful to a student."
```

**Output** (abridged from `examples/map_data.json`, a real run)

```json
{
  "title": "郑州西亚斯学院周边地图",
  "view": {"lat": 34.402844, "lng": 113.759351, "zoom": 10},
  "marker_count": 6,
  "markers": [
    {
      "id": 1, "name_zh": "郑州西亚斯学院", "category": "campus",
      "latitude": 34.402844, "longitude": 113.759351, "distance_km": 0.0,
      "description": "新生到达后，带你熟悉校园路线，参加各项迎新活动，并在食堂和图书馆开启精彩的学习生活。"
    },
    {
      "id": 2, "name_zh": "郑州火车站", "category": "transport",
      "latitude": 34.747607, "longitude": 113.649278, "distance_km": 39.64
    },
    {
      "id": 5, "name_zh": "丰巢美食街", "category": "food",
      "latitude": 34.5, "longitude": 113.6, "distance_km": 18.17,
      "description": "来到丰巢美食街，你可以边走边品尝各种特色小吃。（坐标为模型估算）"
    }
  ]
}
```

Note marker #5: when the geocoder has no match, the model supplies its own
estimate **and says so in the text**. Silent fabrication is the failure mode
this design refuses.

A rendered sample is in [`examples/`](./examples/).

---

## How it works

```
Your instruction
      │
      ▼
Local Gemma 4 reads the task and plans a list of place names   ← model: natural language
      │
      ▼
Host geocodes each name (Photon / OSM) and returns real WGS-84 coords ← code: reliable
      │
      ▼
Host validates: inside the bbox? within 60 km? numeric?        ← code: paranoid
      │   rejected ──► error string is fed back to the model, which retries
      ▼
Local model writes the Chinese description for each place      ← model: its strength
      │
      ▼
Host renders: WGS-84 ──► GCJ-02 ──► Tencent Maps GL JS ──► map.html
```

The division of labour is the design:

| Step | Who does it | Why |
|---|---|---|
| Pick places, write descriptions | **model** (plain chat, no tools) | small models are good at natural language |
| Look up coordinates | **host** (Photon) | deterministic and verifiable |
| Validate coordinates | **host** (bbox + distance) | the model is not trustworthy here |
| Emit the marker tool call | **model** (function calling) | keeps the agent loop honest and auditable |
| Clean up / fill in arguments | **host** | a 2B model sends `{"query": ...}` when you wanted `{"latitude": ...}` |

This split is the difference between v4 (6 markers, all stacked on one
coordinate, empty descriptions) and v5 (6 markers, real coordinates, original
descriptions).

---

## Five iterations, four failures

The agent loop took five attempts. All failures are real and the logs are kept.

| Version | Idea | Result |
|---|---|---|
| v1 | Single ReAct loop, model calls whatever it wants | ❌ 19 steps, **1** marker. The 30 km boundary rejected every place in Zhengzhou proper, the model retried 8 times, then gave up and returned empty |
| v2 | Add geographic biasing to the geocoder, widen the boundary | ⚠️ 2 markers. Foreign matches disappeared (Milwaukee, Chiayi) but the model still quit early |
| v3 | "Goal check": nudge the model when the marker count is low | ❌ 2 markers. Nudged 3 times, never picked up. **Key finding: a 2B model's failure mode is not *being wrong*, it is *giving up* — and once it has, you cannot push it back** |
| v4 | Plan first, then execute one place at a time | ⚠️ 6 markers but quality collapsed: 4 stacked on one coordinate, descriptions empty, argument keys wrong |
| v5 | **Separate "write text" from "call tools"** | ✅ 6 markers, real coordinates, descriptions 100% model-written |

Prompt changes that mattered, in order of impact:

1. `Use short Chinese names; never put "near" or "Sias University" in the query`
   — killed the foreign matches.
2. `Do not invent vague names like "XX food street"` — specifying *what* not to
   invent works; saying "don't make things up" does not.
3. `If the geocoder has no result, use your own knowledge and say so` — stopped
   the retry-until-abandon loop.

The v1 and v5 transcripts are both preserved in [`examples/`](./examples/) and
`AI_LOG.md`.

---

## Project structure

```
localmap-agent/
├── run.py                     CLI entry point (probe / one-shot / interactive)
├── requirements.txt           one dependency: requests
├── localmap_agent/
│   ├── config.py              model tiers, hardware profile, sampling params + why
│   ├── ollama_client.py       localhost HTTP client (incl. the proxy-bypass fix)
│   ├── geo_tools.py           tool definitions, real execution, WGS-84 → GCJ-02
│   ├── agent.py               ReAct loop, self-correction, fallback parsing
│   ├── memory.py              short-term window + long-term JSON memory
│   └── map_renderer.py        Tencent Maps GL JS rendering → one HTML file
├── tests/                     33 unit tests, zero dependencies, no network needed
├── docs/
│   ├── ARCHITECTURE.md        module-by-module design notes
│   └── TROUBLESHOOTING.md     the four real bugs and how they were found
├── examples/                  real input/output from a v5 run
├── AI_LOG.md                  how AI was used to build this (required reading)
├── ATTRIBUTION.md             what is borrowed, what is original
├── CONTRIBUTING.md
├── CHANGELOG.md
├── .github/                   issue templates, PR template
└── ci/                        GitHub Actions config (copy into .github/workflows/ to enable)
```

---

## CLI reference

```bash
python run.py "instruction"                  # one-shot build
python run.py --interactive                  # multi-turn: add, revise, remove
python run.py --probe                        # environment + model capability check
python run.py "..." --model gemma4:e4b       # use a bigger local model
python run.py "..." --min-markers 10         # raise the target count
python run.py "..." --out ./build            # choose the output directory
python run.py "..." --key <TENCENT_MAP_KEY>  # produce a standalone HTML (no proxy)
```

Interactive mode:

```
you > Mark 6 places around campus
agent > 已更新到画布，当前标记数： 7
you > Make the third description more conversational
agent > 已更新到画布，当前标记数： 7
you > Add two more places to eat
agent > 已更新到画布，当前标记数： 9
```

Conversation state is written to `logs/session_memory.json` and restored on the
next start.

---

## Available tools

| Tool | What it does |
|---|---|
| `search_place` | Look up real coordinates (WGS-84), biased toward the campus area |
| `add_map_marker` | Add a marker, with bbox + distance validation |
| `revise_map_marker` | Edit text or coordinates of an existing marker |
| `remove_map_marker` | Delete a marker |
| `compute_distance` | Great-circle distance in km |
| `set_map_view` | Set centre, zoom, and title |
| `list_markers` | Self-check how many markers exist so far |

---

## Porting to your own city

Three constants in `localmap_agent/geo_tools.py`:

```python
SIAS_CENTER    = {"lat": 34.402844, "lng": 113.759351}  # your centre point
VALID_BBOX     = {"lat_min": ..., "lat_max": ..., "lng_min": ..., "lng_max": ...}
MAX_DISTANCE_KM = 60.0
```

Everything else — tools, validation, rendering, memory — is reused unchanged.

> Worth knowing before you tune the numbers: v1's failure was caused by setting
> `MAX_DISTANCE_KM = 30` when the campus is genuinely ~40 km from the city
> centre. A guardrail that rejects legitimate answers is worse than no
> guardrail. Measure the real distances first.

---

## Testing

```bash
python -m unittest discover -s tests -v     # 33 tests, no third-party packages
```

The tests need no model, no Ollama and no network. They cover the haversine
implementation, the GCJ-02 offset, every guardrail rejection path, board
operations, tool-schema shape, HTML rendering, and memory persistence
(including recovery from a corrupted JSON file). Only the LLM loop is untested,
because a 2B model's output is not deterministic.

`pytest tests/` works too, if you prefer it.

---

## Known limitations

Stated plainly, because they are real:

1. **`gemma4:e2b` is a 2B model.** It quits on long composite tasks. v5 works
   around this by splitting the work; it does not fix the model.
2. **Photon's POI coverage for small Chinese cities is thin.** In the sample
   run, 3 of 6 coordinates came from the model's own knowledge and are labelled
   as estimates. They are approximate.
3. **The campus area is hardcoded** (Sias University, Xinzheng). See above.
4. **Chinese descriptions.** The model writes Chinese; the code comments are
   Chinese; the documentation is English. Mixed on purpose — the author works in
   Chinese and publishes in English.
5. **No async, no batching.** One place at a time. A full run takes minutes.

---

## Tech stack

- **Language:** Python 3.10+
- **Runtime:** [Ollama](https://ollama.com) 0.40.0 (MIT)
- **Model:** Gemma 4 E2B, Q4_K_M, 4.6B (Apache 2.0) — runs locally
- **Dependencies:** `requests` (only one, and only for talking to localhost)
- **Geocoding:** [Photon](https://photon.komoot.io/) (OpenStreetMap data)
- **Rendering:** Tencent Maps GL JS (licensed map provider for mainland China)
- **AI in development:** WorkBuddy (see [`AI_LOG.md`](./AI_LOG.md))
- **Deliberately not used:** openai SDK, langchain, llama-index, transformers, gradio

---

## Compliance

- Basemap is Tencent Maps, which holds the required mainland-China map service
  qualification. OSM / Google / Mapbox tiles are not used for rendering.
- WGS-84 coordinates from OSM are converted to GCJ-02 before rendering;
  skipping this shifts markers by 300–600 m inside China.
- No map API key is embedded in the generated HTML unless you pass `--key`.
- All location data is public geographic information.

---

## AI usage

This project was built with AI assistance — project scaffolding, code drafting,
debugging, and documentation. It was **not** one prompt producing one answer:
the agent loop took five iterations and four failures, all recorded.

See [`AI_LOG.md`](./AI_LOG.md) for the full log, including what was done by hand
and why.

## Attribution

What is borrowed, from where, and what is original:
[`ATTRIBUTION.md`](./ATTRIBUTION.md).

## License

[MIT](./LICENSE).

The model (Gemma 4) is Apache 2.0 and is downloaded separately by you; it is
not redistributed here.
