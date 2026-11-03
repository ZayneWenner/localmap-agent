# Examples

Real output from real runs on the author's machine, unedited. The failed run is
here on purpose — it is the best documentation of why the design looks the way
it does.

## Files

| File | What it is |
|---|---|
| [`map_data.json`](./map_data.json) | The v5 output: 6 markers around Sias University. This is the input that `map_renderer` turns into `map.html`. |
| [`sample_run_v5.txt`](./sample_run_v5.txt) | Console transcript of the successful run. |
| [`sample_run_v1_FAILED.txt`](./sample_run_v1_FAILED.txt) | Console transcript of the **failed** v1 run: 19 steps, 1 marker. |

## Reproduce

```bash
ollama serve
python run.py "给我在地图上标出郑州西亚斯学院及周边至少 6 个地点"
```

Your output will differ — a 2B model is not deterministic, and Photon's data
changes. What should stay stable: 6 markers, non-empty model-written
descriptions, and coordinates that pass validation.

## What to look for in the failed run

`sample_run_v1_FAILED.txt` shows both classic small-model failure modes in
eleven lines:

```
[step 6]  search_place({"query": "Park near Sias University"})
          ✔ {'label': 'Marquette University High School, Milwaukee, ...'}   ← wrong hemisphere

[step 8]  add_map_marker({... "latitude": 34.747508 ...})
          ✘ {'error': '纬度 34.747508 超出新郑市范围 34.2~34.65，疑似幻觉。'}
```

1. **Bad queries produce garbage matches.** "Park near Sias University" matched
   Milwaukee. Fixed in v2 by biasing the geocoder with `lat`/`lon` and by
   requiring short Chinese place names.
2. **A guardrail that is too tight is worse than none.** The model found the
   *correct* coordinates for Zhengzhou Railway Station and my own 30 km rule
   rejected them. The model retried eight times, then abandoned the task.

Both are discussed in [`../AI_LOG.md`](../AI_LOG.md) and summarised in the
[README](../README.md#five-iterations-four-failures).

## Note on estimated coordinates

In `map_data.json`, three of six coordinates came from the model's own knowledge
because Photon has thin POI coverage for Xinzheng. Those descriptions end with
`（坐标为模型估算）`. The project refuses to fabricate silently — if a coordinate
is estimated, the text says so.
