# Architecture

Module-by-module notes. Read [`../README.md`](../README.md) first for the
five-iteration story; this file explains the structure that came out of it.

## Data flow

```
                         ┌──────────────────────────────┐
   user instruction ───► │ run.py                       │  CLI: parse args
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │ agent.LocalMapAgent          │
                         │  run()        single loop    │
                         │  run_planned() plan→execute  │
                         └───┬──────────────────────┬───┘
                             │                      │
              plan / prose   │                      │  tool calls
                             ▼                      ▼
              ┌────────────────────────┐  ┌──────────────────────────┐
              │ ollama_client          │  │ geo_tools                │
              │  127.0.0.1:11434       │  │  DISPATCH[name](board,**) │
              │  /v1/chat/completions  │  └────────────┬─────────────┘
              │  ──► /api/chat fallback│               │
              └────────────────────────┘               ▼
                                            ┌────────────────────────┐
                                            │ MapBoard  (state)      │
                                            │  markers, view, title  │
                                            └────────────┬───────────┘
                                                         │
                    ┌────────────────────────────────────┼──────────────┐
                    ▼                                    ▼              ▼
        ┌────────────────────┐            ┌──────────────────┐  ┌──────────────┐
        │ map_renderer       │            │ memory           │  │ logs/*.json  │
        │  WGS-84 → GCJ-02   │            │  window + facts  │  │  transcript  │
        │  → map.html        │            │  → session.json  │  └──────────────┘
        └────────────────────┘            └──────────────────┘
```

## Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `run.py` | CLI, probe, output writing | everything |
| `config.py` | Model tiers, hardware profile, sampling params, and the *reasoning* behind each | stdlib |
| `ollama_client.py` | HTTP to localhost; `/v1/chat/completions` first, `/api/chat` fallback; per-call timing | `requests` (optional) |
| `geo_tools.py` | Tool implementations, validation, coordinate transforms, board state, JSON schemas for the model | stdlib |
| `agent.py` | The loop: plan → execute → validate → feed errors back; fallback parsing when the model emits prose instead of a tool call | `ollama_client`, `geo_tools` |
| `memory.py` | Short-term window (last N messages) + long-term facts, persisted as plain JSON | stdlib |
| `map_renderer.py` | Board dict → one self-contained HTML file | stdlib |

## Three design decisions worth knowing

### 1. The v5 split: prose and tools are different jobs

This is the change that made the project work.

```python
# WRONG (v4): one call asks for both
chat(messages, tools=schemas)          # → keys wrong, descriptions empty

# RIGHT (v5): separate calls
text   = chat([...write a description...])         # no tools, pure generation
coords = geocode(query)                            # host, deterministic
call   = chat([...emit add_map_marker...], tools=schemas)   # structured only
args   = coerce(call.arguments)                    # host repairs the keys
```

A 2B model asked to write prose *and* emit structured arguments simultaneously
does neither. Given one job at a time, it does both acceptably.

### 2. Validation failures are messages, not exceptions

When `add_map_marker` rejects a coordinate, it does not raise. It returns
`{"ok": False, "error": "..."}` and that string goes back into the conversation
as a tool result, so the model can react. This is what makes it a loop rather
than a single generation.

The error strings are written to be *actionable for a language model*:

```
"经度 116.4074 超出新郑市范围 113.30~114.20，疑似幻觉。请先用 search_place 重新查询真实坐标。"
```

It says what is wrong, what the valid range is, and what to do next. Compare
with `"invalid"` — which is what v1 effectively sent, and why v1 retried 8 times
without recovering.

### 3. Coordinate systems are handled explicitly

OSM and Photon return **WGS-84**. Tencent Maps, Amap and Baidu expect **GCJ-02**.
The offset inside mainland China is 300–600 m — large enough that a marker lands
in the wrong field. The conversion happens in `map_renderer.to_gcj_markers()`,
never earlier, so all state and all logs stay in one system (WGS-84).

## State model

```python
@dataclass
class Marker:
    id: int                 # monotonic; never reused after deletion
    name: str               # English
    name_zh: str            # Chinese
    latitude, longitude     # WGS-84, 6 dp
    description: str        # written by the local model
    category: str           # colours the marker
    source: str             # "model" | "geocoder-hint"
    distance_km: float      # computed by the host, not the model
```

`MapBoard` holds the list plus view and title. It is deliberately a plain
dataclass tree: `board.to_dict()` is JSON-serialisable, which is what makes the
run reproducible from a log file.

## Extension points

- **New tool:** add `tool_*` in `geo_tools.py`, register in `DISPATCH`, add a
  schema in `build_schemas()`, add a test.
- **Different city:** `SIAS_CENTER`, `VALID_BBOX`, `MAX_DISTANCE_KM` in
  `geo_tools.py`. See the warning in the README — measure before you set thresholds.
- **Different model:** `--model <tag>`, or edit `RunConfig.model`. Bigger models
  need less scaffolding; `gemma4:26b` would probably survive the v4 design.
- **Different basemap:** `map_renderer.py`, but keep the GCJ-02 conversion unless
  you switch to a WGS-84 renderer.

## What is deliberately absent

- No async. One place at a time; a run takes minutes; parallelism would make the
  transcripts unreadable, and the transcripts are the evidence.
- No database. Memory is a JSON file you can copy to another machine.
- No plugin system. Seven tools is not enough to justify one.
- No retry budget abstraction. The loop has `max_steps`; v3 showed that adding
  clever nudges does not help a model that has already given up.
