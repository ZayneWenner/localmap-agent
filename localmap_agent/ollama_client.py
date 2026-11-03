"""
Ollama 本地模型客户端（零云端依赖）

设计要点：
1. 只走 http://127.0.0.1:11434 —— 数据不出本机，符合 C4D「数据主权」要求。
2. 同时支持两种调用方式：
   - /v1/chat/completions (OpenAI 兼容) —— 首选，支持 tools/function calling
   - /api/chat (Ollama 原生) —— 兜底，用于探测模型能力与获取 eval 统计
3. 每一次调用都会记录 wall-clock 耗时与 tok/s，供「验证报告」引用。

为什么不用 openai 官方 SDK？
    本机只有 Python 标准库 + requests 即可运行，降低复现门槛（教学说明要求别人能跑通）。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised only in a bare env
    # requests is the single runtime dependency, and it is only needed to talk
    # to the local Ollama server. Keeping the import optional means the geometry,
    # guardrail, renderer and memory layers can be imported and unit-tested on a
    # machine that has nothing installed. You get a clear error instead of a
    # ModuleNotFoundError only at the moment you actually try to run the agent.
    requests = None


# Sentinel used in `except` clauses so the code paths above stay importable
# when requests is absent.
_REQ_EXC: type[BaseException] = requests.RequestException if requests is not None else OSError


class OllamaError(RuntimeError):
    """本地推理服务调用失败。"""


@dataclass
class UsageStats:
    """单次推理的性能数据与可观测指标。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_duration_s: float = 0.0
    eval_duration_s: float = 0.0
    wall_clock_s: float = 0.0

    @property
    def tokens_per_second(self) -> float:
        """生成速度（tok/s）—— 评审要求必须在截图里体现的指标。"""
        if self.eval_duration_s > 0 and self.completion_tokens > 0:
            return self.completion_tokens / self.eval_duration_s
        return 0.0


@dataclass
class ChatMessage:
    """统一的消息结构，兼容 OpenAI / Ollama 两种 wire format。"""
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class LLMResponse:
    message: ChatMessage
    usage: UsageStats = field(default_factory=UsageStats)
    raw: dict = field(default_factory=dict)


class OllamaClient:
    """轻量 Ollama 客户端。"""

    def __init__(
        self,
        model: str = "gemma4:e2b",
        host: str = "http://127.0.0.1:11434",
        timeout: float = 600.0,
        options: dict | None = None,
    ) -> None:
        self.model = model
        self.base_url = host.rstrip("/")
        self.timeout = timeout
        # Gemma 4 官方推荐采样参数：temperature=1.0 / top_p=0.95 / top_k=64
        # 工具调用场景对稳定性更敏感，默认略微收紧 temperature。
        # 注意：默认**不带** num_ctx。见 config.py 里的踩坑说明 ——
        # 手动传 num_ctx 会导致 gemma4 起不来（Gemma4Assistant requires ctx_other）。
        self.options: dict = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 64,
        }
        if options:
            self.options.update(options)
        if requests is None:
            raise OllamaError(
                "缺少依赖 requests。请先执行：pip install -r requirements.txt\n"
                "（几何、校验、渲染、记忆模块不需要它，只有连接本地 Ollama 时需要。）"
            )
        self.session = requests.Session()
        # trust_env=False —— 关键坑：本机若配置了系统/应用级 HTTP 代理，
        # requests 会把 127.0.0.1:11434 的请求也发给代理，结果是 502 Bad Gateway，
        # 而现象看起来很像"Ollama 挂了"。调本机一律直连。
        self.session.trust_env = False
        # 同时清掉可能被继承的 proxies 设置
        self.session.proxies = {"http": None, "https": None}

    # ------------------------------------------------------------------
    # 服务健康检查
    # ------------------------------------------------------------------
    def ping(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except _REQ_EXC:
            return False

    def model_exists(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/api/tags", timeout=10)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            return any(n == self.model or n.startswith(self.model.split(":")[0]) for n in names)
        except _REQ_EXC:
            return False

    # ------------------------------------------------------------------
    # 主调用：带 function calling 能力
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        format_json: bool = False,
    ) -> LLMResponse:
        """
        发起一轮对话。

        优先走 OpenAI 兼容端点（工具生态完整），
        失败时自动降级到 Ollama 原生 /api/chat 以便拿到完整的性能统计。
        """
        try:
            return self._chat_openai(messages, tools, tool_choice, format_json)
        except (OllamaError, _REQ_EXC):
            return self._chat_native(messages, tools, format_json)

    def _chat_openai(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None,
        tool_choice: str | dict | None,
        format_json: bool,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "options": self.options,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if format_json:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.perf_counter()
        resp = self.session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        wall = time.perf_counter() - t0
        if resp.status_code != 200:
            raise OllamaError(f"OpenAI 兼容端点返回 {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        usage_raw = data.get("usage") or {}

        # Ollama 的 OpenAI 兼容层不总是返回 prompt_eval_count/eval_count，
        # 这里做一次保守还原：拿不到就用 wall clock 兜底，保证 tok/s 始终有值可读。
        prompt_tokens = usage_raw.get("prompt_tokens", 0) or 0
        completion_tokens = usage_raw.get("completion_tokens", 0) or 0
        stats = UsageStats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            wall_clock_s=wall,
            eval_duration_s=wall if completion_tokens else 0.0,
        )
        return LLMResponse(
            message=ChatMessage(
                role=msg.get("role", "assistant"),
                content=msg.get("content"),
                tool_calls=msg.get("tool_calls"),
            ),
            usage=stats,
            raw=data,
        )

    def _chat_native(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None,
        format_json: bool,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "options": self.options,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if format_json:
            payload["format"] = "json"

        t0 = time.perf_counter()
        resp = self.session.post(
            f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
        )
        wall = time.perf_counter() - t0
        if resp.status_code != 200:
            raise OllamaError(f"Ollama 原生端点返回 {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        msg = data.get("message", {})
        stats = UsageStats(
            prompt_tokens=data.get("prompt_eval_count", 0) or 0,
            completion_tokens=data.get("eval_count", 0) or 0,
            total_duration_s=(data.get("total_duration", 0) or 0) / 1e9,
            eval_duration_s=(data.get("eval_duration", 0) or 0) / 1e9,
            wall_clock_s=wall,
        )
        return LLMResponse(
            message=ChatMessage(
                role=msg.get("role", "assistant"),
                content=msg.get("content"),
                tool_calls=msg.get("tool_calls"),
            ),
            usage=stats,
            raw=data,
        )

    # ------------------------------------------------------------------
    # 服务自省：返回模型、版本、显存/卸载层等运行环境信息
    # ------------------------------------------------------------------
    def server_version(self) -> str:
        try:
            r = self.session.get(f"{self.base_url}/api/version", timeout=5)
            return str(r.json().get("version", "unknown"))
        except _REQ_EXC:
            return "unknown"

    def model_details(self) -> dict:
        try:
            r = self.session.post(
                f"{self.base_url}/api/show", json={"model": self.model}, timeout=20
            )
            r.raise_for_status()
            return r.json()
        except _REQ_EXC:
            return {}


def new_id(prefix: str = "call") -> str:
    """本地生成 tool_call id（不依赖任何外部服务）。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
