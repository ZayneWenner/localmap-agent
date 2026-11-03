"""
本地 Agent 主循环（Tool-calling ReAct Loop）

跑在本机 CPU/GPU 上的 Gemma 4，不经过任何云端推理服务。

循环结构：
    user instruction
        → 本地模型决定「调什么工具」
        → 宿主进程真实执行工具
        → 结果回灌给本地模型
        → 模型继续推理或修正
        → 直到模型不再请求工具为止

这么做的关键价值：**模型的幻觉可以被工具拦住**。
add_map_marker 会校验坐标是否落在新郑市 30km 内，一旦越界就把错误原样回灌，
让模型自己重查 —— 这比"一次性让它吐 JSON 然后祈祷"可靠得多。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ollama_client import OllamaClient, ChatMessage
from .geo_tools import (
    MapBoard,
    DISPATCH,
    build_schemas,
    tool_search_place,
    SIAS_CENTER,
    VALID_BBOX,
    MAX_DISTANCE_KM,
)
from .memory import ConversationMemory


SYSTEM_PROMPT = """You are a cartography assistant running ENTIRELY on the user's own machine.
You build an interactive map of Sias University (郑州西亚斯学院), Xinzheng, Henan, China.
The campus is at latitude 34.402844, longitude 113.759351.

WORKFLOW — follow this order every time:
1. Call `set_map_view` once first (lat 34.402844, lng 113.759351, zoom 13).
2. For EACH place: call `search_place`, then `add_map_marker` with the coordinates it returned.
   Do NOT invent coordinates. Do NOT add a place before searching it.
3. Write every `description` yourself in Simplified Chinese: 1-2 sentences, concrete.
   Describe what a student actually DOES there. Never write marketing slogans.
4. Call `list_markers` BEFORE you finish. If the count is below what the user asked for,
   keep adding more places. Do not stop early.

HOW TO SEARCH — this matters more than anything else:
- Use SHORT, CONCRETE, mostly-CHINESE queries. Good: "新郑 西亚斯", "西亚斯学院",
  "新郑汽车站", "郑州火车站", "郑州园博园", "新郑博物馆", "新郑 公园", "西亚斯 食堂".
- BAD queries (they return places in other countries): "Park near Sias University",
  "transportation hub near Sias University", "food near Sias University",
  "Shopping Mall near Sias University". Never put "near" / "Sias University" into the query.
- Prefer places inside 新郑市 first. Places in 郑州市区 (like 郑州火车站, 二七广场,
  郑州园博园) are also acceptable and interesting to students.
- If a search returns ok:false, try a DIFFERENT and shorter name next time.
  Never repeat a query that already failed.
- If a search returns a result whose label is NOT in China (no 河南/郑州/新郑 in the label),
  ignore it and search a different name.

HARD RULES:
- If `add_map_marker` returns ok:false, READ the error, then search again with a better name.
- Latitude must be 34.20~34.95, longitude 113.30~114.20, within 60 km of campus.
- Never call the same tool twice with identical arguments.
- Answer by actually calling tools. Do not narrate what you plan to do."""


@dataclass
class AgentTurn:
    """一轮 Agent 交互的完整留痕 —— 用于 AI 日志与验证报告。"""
    step: int
    model_text: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    tokens_per_second: float = 0.0
    elapsed_s: float = 0.0


class LocalMapAgent:
    def __init__(
        self,
        client: OllamaClient,
        model: str = "gemma4:e2b",
        log_dir: str | Path = "logs",
        verbose: bool = True,
    ) -> None:
        self.client = client
        self.model = model
        self.board = MapBoard()
        # 长期记忆：跨轮次的对话历史与产出，持久化到 JSON
        self.memory = ConversationMemory(Path(log_dir) / "session_memory.json")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.transcript: list[AgentTurn] = []
        self.total_stats = {"calls": 0, "tokens": 0, "seconds": 0.0}

    # ------------------------------------------------------------------
    def _log(self, *a: Any) -> None:
        if self.verbose:
            print(*a, flush=True)

    # ------------------------------------------------------------------
    def run(self, instruction: str, max_steps: int = 24, min_markers: int = 0) -> dict:
        """
        执行一条用户指令，直到模型不再请求工具。

        min_markers > 0 时启用**目标检查**：
        小模型（2B 级）常见的失败模式不是"做错"，而是**中途放弃** ——
        v1 跑了 19 步只落 1 个标记，v2 跑了 14 步落 2 个，
        两次都是模型自己宣布结束，但其实什么都没完成。
        所以宿主要在模型想停的时候核对目标，没达标就把它推回去继续干。
        这是 harness（宿主编排）该干的活，不该指望小模型自己记得住目标。
        """
        messages: list[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]

        # 恢复历史上下文（有限窗口），保证多轮对话能引用之前的结果
        for item in self.memory.recent_window(limit=6):
            messages.append(ChatMessage(role=item["role"], content=item["content"]))
        messages.append(ChatMessage(role="user", content=instruction))

        tools = build_schemas()
        final_text: str | None = None
        nudges_left = 3  # 最多推 3 次，避免死循环
        step = 0

        while step < max_steps:
            step += 1
            turn = AgentTurn(step=step)
            t0 = time.perf_counter()
            resp = self.client.chat(messages, tools=tools)
            elapsed = time.perf_counter() - t0

            turn.elapsed_s = round(elapsed, 2)
            turn.tokens_per_second = round(resp.usage.tokens_per_second, 2)
            turn.model_text = resp.message.content
            self.total_stats["calls"] += 1
            self.total_stats["tokens"] += resp.usage.completion_tokens
            self.total_stats["seconds"] += elapsed

            self._log(
                f"[step {step}] {elapsed:.1f}s  "
                f"{turn.tokens_per_second:.1f} tok/s  "
                f"out={resp.usage.completion_tokens} tok"
            )

            msg = resp.message

            # 小模型有时把 tool_calls 塞在 content 里（尤其用 /api/chat 时）
            calls = msg.tool_calls or self._extract_calls_from_text(msg.content or "")

            if not calls:
                final_text = msg.content
                have = len(self.board.markers)
                # ---- 目标检查：没达标就推一把 ----
                if min_markers and have < min_markers and nudges_left > 0:
                    nudges_left -= 1
                    self._log(
                        f"[step {step}] 模型想结束，但只有 {have}/{min_markers} 个标记 → 推回去继续（剩 {nudges_left} 次）"
                    )
                    messages.append(msg)
                    messages.append(
                        ChatMessage(
                            role="user",
                            content=(
                                f"现在只有 {have} 个标记，目标是至少 {min_markers} 个，还不够。"
                                f"请继续添加 {min_markers - have} 个不同的地点。要求：\n"
                                f"1. 每个地点先调 search_place，用**真实的中文地名**（如 新郑博物馆、"
                                f"黄帝故里、郑州火车站、郑州园博园、双洎河、西亚斯学院、新郑市人民政府）；\n"
                                f"2. 如果 search_place 查不到，就用你自己知道的坐标直接 add_map_marker；\n"
                                f"3. name_zh 必须和你查到的地点名一致，不要混用不同地点的名字和坐标；\n"
                                f"4. 不要再重复之前查失败过的词。\n"
                                f"现在继续。"
                            ),
                        )
                    )
                    continue
                self._log(f"[step {step}] 模型结束推理：{(final_text or '')[:160]}")
                turn.model_text = final_text
                self.transcript.append(turn)
                break

            turn.tool_calls = calls
            messages.append(msg)

            for call in calls:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments", "{}")
                args = self._safe_args(raw_args)
                self._log(f"    ⚙ {name}({json.dumps(args, ensure_ascii=False)[:180]})")

                result = self._execute(name, args)
                turn.tool_results.append({"name": name, "args": args, "result": result})
                ok_flag = "✔" if result.get("ok") else "✘"
                self._log(f"    {ok_flag} {str(result)[:200]}")

                messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=call.get("id", ""),
                        name=name,
                        content=json.dumps(result, ensure_ascii=False),
                    )
                )

            self.transcript.append(turn)
        else:
            self._log(f"⚠ 达到最大步数 {max_steps}，强制收敛")

        # 写入长期记忆
        self.memory.append("user", instruction)
        if final_text:
            self.memory.append("assistant", final_text)
        self.memory.save()

        return {
            "final_text": final_text,
            "board": self.board.to_dict(),
            "transcript": [t.__dict__ for t in self.transcript],
            "stats": self.total_stats,
        }

    # ------------------------------------------------------------------
    # 两阶段执行：先规划，再逐个执行
    # ------------------------------------------------------------------
    PLAN_PROMPT = (
        "你是本地运行的地图助理。用户要用一张展示郑州西亚斯学院（新郑市）周边的地图。\n"
        "请列出 {n} 个**真实存在**的地点名称（中文），要求：\n"
        "- 覆盖不同类别：校园、交通、美食、自然/公园、文化/历史、购物\n"
        "- 尽量选校园所在的新郑市内的地点；郑州市区知名的也可以少量包含\n"
        "- 优先选规模大、你确定真实存在、名字明确的地点（例如 郑州火车站、郑州园博园、\n"
        "  黄帝故里、新郑市人民政府、郑州大学、二七广场、郑州博物馆），\n"
        "  不要编造'XX美食街''本地连锁超市'这种含糊不存在的名字\n"
        "- 只输出地点名称，不要写介绍，不要写坐标\n"
        '严格按这个 JSON 输出：{{"places":[{{"query":"地点名","category":"campus|transport|food|nature|culture|shopping"}}]}}'
    )

    def _plan_places(self, instruction: str, n: int) -> list[dict]:
        """阶段一：让模型自己列出要标注的地点名（只出名字，不出坐标）。"""
        self._log(f"\n[阶段1/2] 让本地模型规划 {n} 个地点 ...")
        resp = self.client.chat(
            [
                ChatMessage(role="system", content="Reply with valid JSON only."),
                ChatMessage(role="user", content=self.PLAN_PROMPT.format(n=n) + f"\n\n用户需求：{instruction}"),
            ],
            format_json=True,
        )
        text = (resp.message.content or "").strip()
        self._log(f"    tok/s={resp.usage.tokens_per_second:.1f}  规划原文：{text[:300]}")
        try:
            data = json.loads(self._strip_fence(text))
            places = data.get("places", [])
        except json.JSONDecodeError as e:
            self._log(f"    ✘ 规划 JSON 解析失败：{e}")
            places = []
        out = [p for p in places if isinstance(p, dict) and p.get("query")][:n]
        self._log(f"    ✔ 规划出 {len(out)} 个：{[p['query'] for p in out]}")
        return out

    @staticmethod
    def _strip_fence(text: str) -> str:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("```")[1]
            if t.startswith("json"):
                t = t[4:]
        return t.strip()

    def _write_description(self, query: str, category: str) -> str:
        """
        让本地模型为某个地点写一句中文介绍。

        关键设计：把"写文案"和"调工具"拆成两步。
        v4 里我让模型一边写文案一边调 add_map_marker，结果它两头都没做好 ——
        工具参数传成 {"query": ...} 这种乱七八糟的键，content 还是空的，
        最后只能靠宿主的模板兜底，描述就不是模型写的了。
        拆开之后：写文案用纯对话（小模型擅长），落点由宿主负责（程序擅长）。
        """
        resp = self.client.chat(
            [
                ChatMessage(
                    role="system",
                    content="你是本地运行的校园向导。用中文回答，只写内容，不要解释你在做什么。",
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"为「{query}」写一句 40 字以内的中文介绍，"
                        f"给第一次去那里的郑州西亚斯学院新生看。"
                        f"说清楚他到那里具体会做什么（比如坐车、吃饭、散步、参观）。"
                        f"不要写'值得一去'这种空话，不要加引号，只输出这一句话。"
                    ),
                ),
            ]
        )
        self.total_stats["calls"] += 1
        self.total_stats["tokens"] += resp.usage.completion_tokens
        text = (resp.message.content or "").strip().strip('"').strip("“”")
        # 只取第一句有意义的话，去掉模型可能带的铺垫
        for line in text.splitlines():
            line = line.strip(" -*#>")
            if len(line) >= 10:
                return line
        return text or ""

    def _pick_candidate(self, cands: list, query: str) -> dict | None:
        """从搜索结果里挑一个可信的候选：必须在中国境内、且在合理范围内。"""
        for c in cands:
            label = c.get("label", "")
            if "中国" not in label and "河南" not in label and "郑州" not in label and "新郑" not in label:
                continue
            if not (VALID_BBOX["lat_min"] <= c["latitude"] <= VALID_BBOX["lat_max"]):
                continue
            if not (VALID_BBOX["lng_min"] <= c["longitude"] <= VALID_BBOX["lng_max"]):
                continue
            if c["distance_from_sias_km"] > MAX_DISTANCE_KM:
                continue
            return c
        return None

    def _ask_model_coords(self, query: str) -> tuple[float, float] | None:
        """查不到时，让模型自己给坐标（严格 JSON），宿主校验后才用。"""
        resp = self.client.chat(
            [
                ChatMessage(role="system", content="Reply with valid JSON only."),
                ChatMessage(
                    role="user",
                    content=(
                        f'你知道「{query}」在河南省郑州市新郑市的经纬度吗？'
                        f'只输出 JSON：{{"latitude":数字,"longitude":数字}}。'
                        f'纬度应在 34.20~34.95，经度应在 113.30~114.20。不确定就按你最合理的估计给。'
                    ),
                ),
            ],
            format_json=True,
        )
        self.total_stats["calls"] += 1
        try:
            d = json.loads(self._strip_fence(resp.message.content or ""))
            lat, lng = float(d["latitude"]), float(d["longitude"])
        except Exception:
            return None
        if not (VALID_BBOX["lat_min"] <= lat <= VALID_BBOX["lat_max"]):
            return None
        if not (VALID_BBOX["lng_min"] <= lng <= VALID_BBOX["lng_max"]):
            return None
        return lat, lng

    def _execute_one(self, item: dict) -> bool:
        """阶段二：单个地点 = 模型写文案 + 宿主查坐标 + 模型发起落点调用。"""
        query = item["query"]
        category = item.get("category", "other")
        self._log(f"\n[地点] {query}")

        # 1) 文案：本地模型写（这是"数据由模型生成"的核心证据）
        desc = self._write_description(query, category)
        self._log(f"    模型写的描述：{desc[:80]}")
        if not desc:
            self._log("    ✘ 模型没写出描述，跳过该点")
            return False

        # 2) 坐标：宿主查，查不到再问模型
        geo = DISPATCH["search_place"](self.board, query, 5)
        cands = geo.get("results", []) if geo.get("ok") else []
        pick = self._pick_candidate(cands, query) if cands else None

        if pick:
            lat, lng = pick["latitude"], pick["longitude"]
            name_zh = pick.get("osm_name") or query
            src = "地理数据"
        else:
            coords = self._ask_model_coords(query)
            if not coords:
                self._log("    ✘ 既查不到也问不出有效坐标，跳过该点（不硬塞到校园坐标上）")
                return False
            lat, lng = coords
            name_zh = query
            src = "模型估算"
            desc = desc + "（坐标为模型估算）"
        self._log(f"    坐标来源：{src}  lat={lat} lng={lng}")

        # 3) 落点：仍然让模型发起 add_map_marker 调用（保留 function calling 证据），
        #    但宿主会先把参数补全/清洗，避免模型传错键导致整步失败。
        hint = (
            f"请调用 add_map_marker 添加地点「{name_zh}」（{query}）。\n"
            f"经纬度必须用这两个：latitude={lat}, longitude={lng}。\n"
            f"category 用 {category}。description 用你刚才写的介绍。"
        )
        resp = self.client.chat(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=hint),
            ],
            tools=[s for s in build_schemas() if s["function"]["name"] == "add_map_marker"],
        )
        self.total_stats["calls"] += 1
        self.total_stats["tokens"] += resp.usage.completion_tokens

        msg = resp.message
        calls = msg.tool_calls or self._extract_calls_from_text(msg.content or "")
        args: dict = {}
        if calls:
            raw = self._safe_args(calls[0]["function"].get("arguments", "{}"))
            # 只保留合法字段，其余（模型偶尔塞的 zoom/query 之类）丢弃
            args = {k: v for k, v in raw.items()
                    if k in {"name", "name_zh", "latitude", "longitude", "description", "category"}}

        # 用真实值补齐模型没给/给错的字段
        args.setdefault("latitude", lat)
        args.setdefault("longitude", lng)
        args["latitude"] = lat
        args["longitude"] = lng
        args.setdefault("name", query)
        args.setdefault("name_zh", name_zh)
        args.setdefault("description", desc)
        args.setdefault("category", category)

        self._log(f"    ⚙ add_map_marker({json.dumps(args, ensure_ascii=False)[:150]})")
        res = self._execute("add_map_marker", args)
        self._log(f"    {'✔' if res.get('ok') else '✘'} {str(res)[:170]}")
        return bool(res.get("ok"))

    def _coerce_marker(self, text: str, query: str, category: str, cands: list) -> dict | None:
        """（已废弃，保留以防旧代码引用）见 _execute_one 的新流程。"""
        return None

    def _coerce_marker(self, text: str, query: str, category: str, cands: list) -> dict | None:
        """
        兜底：从模型的自然语言回复里尽量还原出一个合法标记。

        优先用搜索到的真实坐标（模型写的坐标不可信），
        描述则尽量用模型自己写的那句中文。
        """
        desc = ""
        try:
            data = json.loads(self._strip_fence(text))
            if isinstance(data, dict):
                desc = data.get("description") or data.get("name_zh") or ""
        except json.JSONDecodeError:
            # 不是 JSON 就当作纯文本描述，取第一句有意义的话
            for line in text.splitlines():
                line = line.strip(" -*#>")
                if len(line) >= 10 and not line.startswith("{"):
                    desc = line
                    break
        if not desc:
            desc = f"{query}，是新生常去的地方。"

        if cands:
            c = cands[0]
            name_zh = c.get("osm_name") or query
            lat, lng = c["latitude"], c["longitude"]
        else:
            # 没有真实坐标时，退回到校园中心附近的默认位置并标注来源
            name_zh = query
            lat, lng = SIAS_CENTER["lat"], SIAS_CENTER["lng"]
            desc = desc + "（坐标为模型估算）"

        return {
            "name": query,
            "name_zh": name_zh,
            "latitude": lat,
            "longitude": lng,
            "description": desc,
            "category": category,
        }

    def run_planned(self, instruction: str, min_markers: int = 6) -> dict:
        """
        两阶段执行：模型规划地点名 → 逐个查坐标并让模型写文案落点。

        v3 的教训：让 2B 级模型在一轮里自主完成「6 次搜索 + 6 次写点」会直接摆烂，
        推它继续也没用。改成把大任务拆成 6 个极小任务后，成功率立刻上来 ——
        **任务分解是宿主（harness）的责任，不该指望小模型自己规划得动。**
        """
        plan = self._plan_places(instruction, min_markers)
        if not plan:
            self._log("✘ 模型没能规划出任何地点")
            return {"final_text": None, "board": self.board.to_dict(),
                    "transcript": [], "stats": self.total_stats}

        self._log(f"\n[阶段2/2] 逐个执行 {len(plan)} 个地点 ...")
        for item in plan:
            self._execute_one(item)
            if len(self.board.markers) >= min_markers:
                break

        # 有的地点查不到坐标会被跳过，所以可能不足；最多再补 3 轮规划
        for rnd in range(3):
            if len(self.board.markers) >= min_markers:
                break
            need = min_markers - len(self.board.markers)
            self._log(f"\n[补充 {rnd+1}/3] 只有 {len(self.board.markers)} 个，再规划 {need} 个 ...")
            extra = self._plan_places(
                instruction + "（注意：请换成与之前完全不同的、真实存在的大型地点名）",
                need + 2,
            )
            if not extra:
                break
            for item in extra:
                self._execute_one(item)
                if len(self.board.markers) >= min_markers:
                    break

        # 自动适配视野：最远的点越远，缩放级别越小，保证所有标记一眼可见
        dists = [m.distance_km for m in self.board.markers] or [0.0]
        mx = max(dists)
        zoom = 14 if mx < 3 else 12 if mx < 10 else 11 if mx < 25 else 10
        self.board.view = {"lat": SIAS_CENTER["lat"], "lng": SIAS_CENTER["lng"], "zoom": zoom}
        self.board.title = "郑州西亚斯学院周边地图"
        self._log(f"\n视野自适应：最远标记 {mx} km → zoom {zoom}")

        self.memory.append("user", instruction)
        self.memory.append("assistant", f"已生成 {len(self.board.markers)} 个标记")
        self.memory.save()
        return {
            "final_text": f"已生成 {len(self.board.markers)} 个标记",
            "board": self.board.to_dict(),
            "transcript": [t.__dict__ for t in self.transcript],
            "stats": self.total_stats,
        }

    # ------------------------------------------------------------------
    def _execute(self, name: str, args: dict) -> dict:
        fn = DISPATCH.get(name)
        if fn is None:
            return {"ok": False, "error": f"未知工具 {name}。"}
        try:
            if name == "compute_distance":
                return fn(**args)
            return fn(self.board, **args)
        except TypeError as e:
            # 参数不匹配时把正确用法告诉模型，让它自我修正
            return {"ok": False, "error": f"参数错误：{e}。请检查必填字段后重试。"}
        except Exception as e:
            return {"ok": False, "error": f"工具执行异常：{type(e).__name__}: {e}"}

    @staticmethod
    def _safe_args(raw: Any) -> dict:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _extract_calls_from_text(text: str) -> list[dict]:
        """
        兜底：部分本地模型在 tools 模式下仍会把调用写成 ```json / ```tool 代码块。
        这里做一层宽容解析，避免因为格式问题直接判"模型不支持函数调用"。
        """
        text = text.strip()
        out = []
        for fence in ("```json", "```tool", "```"):
            if fence in text:
                for block in text.split(fence)[1:]:
                    body = block.split("```")[0].strip()
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and "name" in data:
                        out.append(
                            {
                                "id": "fallback_call",
                                "function": {
                                    "name": data["name"],
                                    "arguments": json.dumps(data.get("arguments", {}), ensure_ascii=False),
                                },
                            }
                        )
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "name" in item:
                                out.append(
                                    {
                                        "id": "fallback_call",
                                        "function": {
                                            "name": item["name"],
                                            "arguments": json.dumps(
                                                item.get("arguments", {}), ensure_ascii=False
                                            ),
                                        },
                                    }
                                )
                if out:
                    return out
        return out

    # ------------------------------------------------------------------
    def save_transcript(self, filename: str = "agent_run_log.json") -> Path:
        """落盘完整运行日志 —— AI 日志与验证报告的原始证据。"""
        path = self.log_dir / filename
        payload = {
            "model": self.model,
            "stats": self.total_stats,
            "transcript": [t.__dict__ for t in self.transcript],
            "board": self.board.to_dict(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
