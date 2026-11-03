#!/usr/bin/env python
"""
命令行入口

用法：
    python run.py "给我在地图上标出郑州西亚斯学院及周边至少 6 个地点"
    python run.py --interactive          # 多轮对话模式，可增量增删标记
    python run.py --probe                # 只做环境与模型能力体检
    python run.py "..." --key <腾讯地图Key>   # 产出可脱离代理独立运行的 HTML

前置条件：
    本机已安装 Ollama 且已拉取 gemma4:e2b（详见 教学说明.md）
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from localmap_agent import (  # noqa: E402
    OllamaClient,
    ChatMessage,
    LocalMapAgent,
    RunConfig,
    explain_model_choice,
    render_html,
)

DEFAULT_INSTRUCTION = (
    "给我在地图上标出郑州西亚斯学院（Sias University）本身，"
    "以及它周边至少 6 个对在校学生真实有用的地点："
    "交通枢纽、吃饭的地方、可以跑步放松的自然/公园、有文化或历史价值的去处。"
    "每个地点的描述请你自己写，说清楚一个新生第一次去那里会发生什么。"
    "务必先用 search_place 查真实坐标，不要自己编经纬度。"
)


def probe(client: OllamaClient) -> dict:
    """环境自检：服务是否活着、模型在不在、函数调用支不支持。"""
    print("=" * 68)
    print("本地环境体检")
    print("=" * 68)
    info: dict = {}

    if not client.ping():
        print("✘ 连不上 Ollama，请先启动：ollama serve")
        return {"ok": False, "reason": "service-down"}

    ver = client.server_version()
    print(f"✔ Ollama 服务端版本 : {ver}")
    info["ollama_version"] = ver

    print(f"✔ 目标模型         : {client.model}")
    if not client.model_exists():
        print(f"✘ 本机没有 {client.model}，请先执行：ollama pull {client.model}")
        info["model_present"] = False
        return {"ok": False, **info}
    info["model_present"] = True

    details = client.model_details()
    if details:
        print(f"  量化/参数族       : {details.get('details', {}).get('quantization_level', 'n/a')}"
              f" / {details.get('details', {}).get('family', 'n/a')}")
        info["details"] = details.get("details", {})

    # --- 基础对话 ---
    print("\n[1/3] 基础对话测试")
    t0 = time.perf_counter()
    r1 = client.chat([ChatMessage(role="user", content="用一句话介绍郑州西亚斯学院。")])
    print(f"  耗时 {time.perf_counter() - t0:.1f}s / {r1.usage.tokens_per_second:.1f} tok/s")
    print(f"  输出：{(r1.message.content or '')[:220]}")
    info["chat"] = {"tps": round(r1.usage.tokens_per_second, 2), "ok": bool(r1.message.content)}

    # --- 结构化输出 ---
    print("\n[2/3] 结构化 JSON 输出测试")
    r2 = client.chat(
        [
            ChatMessage(role="system", content="Reply with valid JSON only. No markdown fences."),
            ChatMessage(role="user", content='Reply JSON with keys "a" and "b", values are integers.'),
        ],
        format_json=True,
    )
    txt2 = (r2.message.content or "").strip()
    try:
        json.loads(txt2)
        ok2 = True
        verdict2 = "JSON 可解析"
    except json.JSONDecodeError as e:
        ok2 = False
        verdict2 = f"JSON 解析失败：{e}"
    print(f"  {verdict2}  |  原文：{txt2[:160]}")
    info["json"] = {"ok": ok2, "tps": round(r2.usage.tokens_per_second, 2)}

    # --- 函数调用 ---
    print("\n[3/3] Function calling 测试")
    from localmap_agent import build_schemas

    tools = build_schemas()
    r3 = client.chat(
        [
            ChatMessage(role="system", content="Call tools when appropriate."),
            ChatMessage(role="user", content="What is the distance from the airport to campus? Use compute_distance with lat1=34.5200 lng1=113.8400 lat2=34.4041 lng2=113.7270."),
        ],
        tools=tools,
    )
    calls = r3.message.tool_calls or []
    ok3 = bool(calls)
    if ok3:
        c = calls[0]
        print(f"  ✔ 模型发起调用：{c['function']['name']}({c['function']['arguments'][:160]})")
    else:
        print(f"  ✘ 模型没有发起任何 tool_call，原文：{(r3.message.content or '')[:200]}")
        print("    → Agent 将回退到「代码块解析」模式兜底（见 agent.py::_extract_calls_from_text）")
    info["functions"] = {"ok": ok3, "tps": round(r3.usage.tokens_per_second, 2)}

    print("\n" + "=" * 68)
    print(f"Python {platform.python_version()} on {platform.system()} {platform.release()}")
    print("=" * 68)
    info["python"] = platform.python_version()
    info["ok"] = True
    return info


def write_outputs(agent: LocalMapAgent, out_dir: Path, api_key: str | None) -> dict:
    """产出 HTML 地图 + 数据 JSON + 原始日志。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    board = agent.board.to_dict()

    meta = {
        "model": agent.model,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    html = render_html(board, api_key=api_key, meta=meta)
    html_path = out_dir / "map.html"
    html_path.write_text(html, encoding="utf-8")

    data_path = out_dir / "map_data.json"
    data_path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

    log_path = agent.save_transcript("agent_run_log.json")

    print("\n" + "=" * 68)
    print(f"✔ 交互式地图  : {html_path}")
    print(f"✔ 结构化数据  : {data_path}")
    print(f"✔ 原始运行日志: {log_path}")
    print(f"✔ 标记数量    : {len(board['markers'])}")
    print("=" * 68)
    for m in board["markers"]:
        print(f"  #{m['id']} [{m['category']:<9}] {m['name_zh']:<16} "
              f"{m['latitude']:.5f},{m['longitude']:.5f}  {m['distance_km']} km")
        print(f"      {m['description'][:70]}")
    return {"html": str(html_path), "data": str(data_path), "log": str(log_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description="本地 Gemma 4 驱动的地图构建 Agent")
    ap.add_argument("instruction", nargs="?", default=None, help="用户指令")
    ap.add_argument("--model", default=None, help="模型 tag，默认 gemma4:e2b")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--probe", action="store_true", help="只做环境体检")
    ap.add_argument("--interactive", action="store_true", help="进入多轮交互模式")
    ap.add_argument("--key", default=None, help="腾讯地图 Key；不传则使用本地代理模式")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument(
        "--min-markers",
        type=int,
        default=6,
        help="最少标记数。模型中途放弃时宿主会把它推回去继续（默认 6）",
    )
    args = ap.parse_args()

    cfg = RunConfig()
    if args.model:
        cfg.model = args.model
    cfg.host = args.host

    client = OllamaClient(model=cfg.model, host=cfg.host, options=cfg.client_options())
    out_dir = Path(args.out).resolve()

    if args.probe:
        probe(client)
        return 0

    agent = LocalMapAgent(client, model=cfg.model, log_dir=out_dir / "logs")

    if args.interactive:
        print("本地地图 Agent 已就绪（输入 exit 退出）")
        print(f"model = {cfg.model} @ {cfg.host}\n")
        while True:
            try:
                q = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit", "退出"}:
                break
            if not q:
                continue
            agent.run(q, max_steps=cfg.max_steps, min_markers=0)
            print("\n助手 > 已更新到画布，当前标记数：", len(agent.board.markers), "\n")
        write_outputs(agent, out_dir, args.key)
        return 0

    instruction = args.instruction or DEFAULT_INSTRUCTION
    print("=" * 68)
    print("本地 Gemma 4 地图构建 Agent")
    print(f"model = {cfg.model}   endpoint = {cfg.host}")
    print(explain_model_choice())
    print("=" * 68)
    print(f"\n指令：{instruction}\n")

    if args.min_markers > 0:
        result = agent.run_planned(instruction, min_markers=args.min_markers)
    else:
        result = agent.run(instruction, max_steps=cfg.max_steps, min_markers=0)
    print(f"\n最终回复：{(result['final_text'] or '(空)')[:400]}")
    print(f"\n统计：{result['stats']}")
    write_outputs(agent, out_dir, args.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
