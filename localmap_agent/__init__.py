"""
localmap_agent —— 跑在本地 Gemma 4 上的地图构建 Agent 技能

零 API 费用、零数据外发：推理在 127.0.0.1:11434 完成，
只有插件式工具 search_place 会去查公开地理数据（可选，断网自动降级）。
"""

from .ollama_client import OllamaClient, ChatMessage, UsageStats, OllamaError
from .geo_tools import MapBoard, build_schemas, wgs84_to_gcj02, haversine_km, SIAS_CENTER
from .agent import LocalMapAgent, SYSTEM_PROMPT
from .memory import ConversationMemory
from .map_renderer import render_html
from .config import RunConfig, GEMMA4_FAMILY, DEVICE_FINGERPRINT, explain_model_choice

__version__ = "1.1.0"
__all__ = [
    "OllamaClient",
    "ChatMessage",
    "UsageStats",
    "OllamaError",
    "MapBoard",
    "build_schemas",
    "wgs84_to_gcj02",
    "haversine_km",
    "SIAS_CENTER",
    "LocalMapAgent",
    "SYSTEM_PROMPT",
    "ConversationMemory",
    "render_html",
    "RunConfig",
    "GEMMA4_FAMILY",
    "DEVICE_FINGERPRINT",
    "explain_model_choice",
]
