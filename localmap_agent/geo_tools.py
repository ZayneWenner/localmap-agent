"""
Agent 可调用的工具集（Function Calling 的实际执行体）

设计原则：
1. 工具是**真实执行**的，不是给模型看的假接口 —— search_place 真的会去查
   开放地理数据，haversine 真的会算球面距离。
2. 每个工具都对模型的输入做**边界校验**。小模型容易编造坐标，校验失败时会把
   错误信息回灌给模型，让它自己纠错 —— 这才是 Agent 循环，而不是一次性生成。
3. 所有坐标对外统一输出 WGS-84；渲染层再按国内合规要求转 GCJ-02。
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any

# --------------------------------------------------------------------------
# 地理常量：郑州西亚斯学院（Sias University），位于河南省新郑市
# --------------------------------------------------------------------------
# 注意：这个值是 v1 跑完之后修正过的。
# v1 里我凭印象写的是 34.4041 / 113.7270（经度差了约 3 公里），
# 后来用 search_place 查到 OSM 的真实坐标才是下面这个。
SIAS_CENTER = {"lat": 34.402844, "lng": 113.759351}

# 边界校验范围：郑州都市区（含新郑、郑州市区）。
# v1 只框了新郑市（lat 34.20~34.65），结果模型搜到的"郑州火车站""长途汽车站"
# 全部被判越界，反复失败 8 次后直接摆烂放弃 —— 这是 v1 只产出 1 个标记的直接原因。
# 教训：校验闸门是用来拦"坐标幻觉"的，不是用来拦"合理但稍远"的地点的。
# 西亚斯在新郑，离郑州市区本就有 ~40km，把阈值设成 30km 属于把自己的规则设错了。
VALID_BBOX = {"lat_min": 34.20, "lat_max": 34.95, "lng_min": 113.30, "lng_max": 114.20}
MAX_DISTANCE_KM = 60.0  # 距校园中心的最大合理距离

# Photon（基于 OpenStreetMap 的开源地理编码器）。
# 说明：这里查的是**公共地理事实数据**（地点是否在、经纬度是多少），
# 而地点的中文名、介绍文案、分类、取舍决策，全部由本地 Gemma 4 生成。
GEOCODE_URL = "https://photon.komoot.io/api/"


# --------------------------------------------------------------------------
# 几何工具
# --------------------------------------------------------------------------
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两经纬度之间的球面距离（公里）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_X_PI = math.pi * 3000.0 / 180.0
_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """
    WGS-84 → GCJ-02（火星坐标）。

    腾讯地图 / 高德 / 百度使用的都是 GCJ-02 系；OSM、Photon 返回的是 WGS-84。
    两个坐标系在中国境内约有 300~600 米的系统性偏移，不转换的话标记会明显错位，
    所以这一步在「地图质量」评审里是刚需，不是可选项。
    """
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


# --------------------------------------------------------------------------
# 画布状态：Agent 的记忆（短期工作记忆）
# --------------------------------------------------------------------------
@dataclass
class Marker:
    id: int
    name: str
    name_zh: str
    latitude: float
    longitude: float
    description: str
    category: str
    source: str = "model"          # model | geocoder-hint
    distance_km: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class MapBoard:
    """当前地图会话的可变状态 —— 相当于 Agent 的工作记忆。"""

    def __init__(self) -> None:
        self.markers: list[Marker] = []
        self.view: dict = {"lat": SIAS_CENTER["lat"], "lng": SIAS_CENTER["lng"], "zoom": 14}
        self.title: str = ""
        self._seq = 0

    def next_id(self) -> int:
        self._seq += 1
        return self._seq

    def add(self, **kw) -> Marker:
        m = Marker(id=self.next_id(), **kw)
        m.distance_km = round(
            haversine_km(SIAS_CENTER["lat"], SIAS_CENTER["lng"], m.latitude, m.longitude), 2
        )
        self.markers.append(m)
        return m

    def get(self, marker_id: int) -> Marker | None:
        for m in self.markers:
            if m.id == marker_id:
                return m
        return None

    def remove(self, marker_id: int) -> bool:
        before = len(self.markers)
        self.markers = [m for m in self.markers if m.id != marker_id]
        return len(self.markers) < before

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "view": self.view,
            "center_reference": SIAS_CENTER,
            "marker_count": len(self.markers),
            "markers": [m.to_dict() for m in self.markers],
        }


# --------------------------------------------------------------------------
# 工具实现
# --------------------------------------------------------------------------
def tool_search_place(board: MapBoard, query: str, limit: int = 3) -> dict:
    """
    按名称查询地点的真实经纬度（WGS-84）。返回候选列表供模型挑选。

    模型经常被要求"输出坐标"，但 2B 级别的模型记不住精确经纬度 —— 与其让它编，
    不如给它一个查的工具，让它负责"选哪个 + 怎么写介绍"。
    """
    # 关键修正（v2）：带上 lat/lon 做地理偏向。
    # v1 不带偏向时，"Park near Sias University" 这种含糊查询会被 Photon
    # 匹配到美国密尔沃基、"Gongcheng District" 匹配到台湾嘉义 —— 模型拿到垃圾结果
    # 之后就一路跑偏。带上校园坐标做权重后，同名地点会优先返回校园附近的那个。
    params = urllib.parse.urlencode(
        {
            "q": query,
            "limit": str(max(1, min(limit, 8))),
            "lat": SIAS_CENTER["lat"],
            "lon": SIAS_CENTER["lng"],
            "zoom": 12,
        }
    )
    url = f"{GEOCODE_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "C4D-local-agent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # 网络不可用时明确告知模型，让它退回自身知识
        return {
            "ok": False,
            "error": f"地理编码服务不可用（{type(e).__name__}）。请改用你自己的知识提供坐标，"
                     f"并在 description 中说明坐标为你估计。",
        }

    results = []
    for feat in data.get("features", []):
        props = feat.get("properties", {}) or {}
        coords = (feat.get("geometry", {}) or {}).get("coordinates", [None, None])
        lng, lat = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        parts = [props.get(k) for k in ("name", "city", "district", "street", "state", "country")]
        label = ", ".join([p for p in parts if p])
        results.append(
            {
                "label": label or query,
                "osm_name": props.get("name"),
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "osm_category": props.get("osm_value") or props.get("osm_key") or "unknown",
                "distance_from_sias_km": round(
                    haversine_km(SIAS_CENTER["lat"], SIAS_CENTER["lng"], lat, lng), 2
                ),
            }
        )
    if not results:
        # v2 修正：明确告诉模型"查不到就用你自己的知识"，
        # 否则模型会一直重试搜索最后放弃（v1 就是这个死循环）。
        return {
            "ok": False,
            "error": (
                f"「{query}」在开放地理数据里查不到。"
                f"请换一个更具体、更常用的地名再试一次；"
                f"如果还是查不到，就用你自己知道的坐标直接 add_map_marker，"
                f"并在 description 末尾注明（坐标为模型估算）。不要再重复这个查询。"
            ),
        }
    return {"ok": True, "query": query, "results": results}


def tool_add_marker(
    board: MapBoard,
    name: str,
    name_zh: str,
    latitude: float,
    longitude: float,
    description: str,
    category: str,
) -> dict:
    """把一个地点正式加入地图。会做边界校验。"""
    try:
        lat, lng = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"坐标必须是数字，收到 latitude={latitude!r} longitude={longitude!r}。"}

    if not (VALID_BBOX["lat_min"] <= lat <= VALID_BBOX["lat_max"]):
        return {
            "ok": False,
            "error": f"纬度 {lat} 超出新郑市范围 {VALID_BBOX['lat_min']}~{VALID_BBOX['lat_max']}，"
                     f"疑似幻觉。请先用 search_place 重新查询真实坐标。",
        }
    if not (VALID_BBOX["lng_min"] <= lng <= VALID_BBOX["lng_max"]):
        return {
            "ok": False,
            "error": f"经度 {lng} 超出新郑市范围 {VALID_BBOX['lng_min']}~{VALID_BBOX['lng_max']}，"
                     f"疑似幻觉。请先用 search_place 重新查询真实坐标。",
        }

    dist = haversine_km(SIAS_CENTER["lat"], SIAS_CENTER["lng"], lat, lng)
    if dist > MAX_DISTANCE_KM:
        return {
            "ok": False,
            "error": f"该点距离校园中心 {dist:.1f} km，超过 {MAX_DISTANCE_KM} km 上限。"
                     f"请换一个离学校更近的地点，或确认坐标正确。",
        }

    m = board.add(
        name=str(name),
        name_zh=str(name_zh),
        latitude=round(lat, 6),
        longitude=round(lng, 6),
        description=str(description),
        category=str(category) or "other",
    )
    return {
        "ok": True,
        "marker_id": m.id,
        "distance_from_sias_km": m.distance_km,
        "message": f"已添加 #{m.id} {m.name_zh}，距校园中心 {m.distance_km} km。当前共 {len(board.markers)} 个标记。",
    }


def tool_revise_marker(board: MapBoard, marker_id: int, **fields) -> dict:
    """修改已有点位的文案或坐标 —— 展示多轮交互式的 Agent 能力。"""
    m = board.get(int(marker_id))
    if not m:
        return {"ok": False, "error": f"找不到 id={marker_id} 的标记。"}
    allowed = {"name", "name_zh", "description", "category", "latitude", "longitude"}
    changed = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            setattr(m, k, v)
            changed.append(k)
    if "latitude" in changed or "longitude" in changed:
        m.distance_km = round(
            haversine_km(SIAS_CENTER["lat"], SIAS_CENTER["lng"], m.latitude, m.longitude), 2
        )
    return {"ok": True, "changed": changed, "marker": m.to_dict()}


def tool_remove_marker(board: MapBoard, marker_id: int) -> dict:
    ok = board.remove(int(marker_id))
    return {"ok": ok, "remain": len(board.markers)}


def tool_compute_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> dict:
    """计算两点距离。让模型能用工具做它不擅长的算术。"""
    try:
        d = haversine_km(float(lat1), float(lng1), float(lat2), float(lng2))
        return {"ok": True, "distance_km": round(d, 3)}
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"坐标解析失败: {e}"}


def tool_set_map_view(board: MapBoard, lat: float, lng: float, zoom: int, title: str) -> dict:
    """设置地图中心、缩放级别和标题。"""
    board.view = {"lat": float(lat), "lng": float(lng), "zoom": int(zoom)}
    board.title = str(title)
    return {"ok": True, "view": board.view, "title": board.title}


def tool_list_markers(board: MapBoard) -> dict:
    """列出当前所有标记，便于模型自查是否达到数量要求。"""
    return {
        "ok": True,
        "count": len(board.markers),
        "markers": [
            {"id": m.id, "name_zh": m.name_zh, "category": m.category, "distance_km": m.distance_km}
            for m in board.markers
        ],
    }


# --------------------------------------------------------------------------
# OpenAI Function Calling Schema（喂给本地 Gemma 4 看的工具说明书）
# --------------------------------------------------------------------------
def build_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_place",
                "description": (
                    "Query real-world latitude/longitude (WGS-84) for a place by its name. "
                    "Call this BEFORE adding a marker. Results are biased toward the campus area. "
                    "QUERY STYLE: use short concrete names, preferably in Chinese, e.g. "
                    "'新郑汽车站', '郑州园博园', '西亚斯学院'. "
                    "Never include words like 'near', 'Sias University', 'hub', 'food' in the query - "
                    "those match places in other countries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Place name, English or Chinese."},
                        "limit": {"type": "integer", "description": "Max candidates to return, 1-8.", "default": 3},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_map_marker",
                "description": (
                    "Add a location to the interactive map. Coordinates MUST be within "
                    "lat 34.20-34.95, lng 113.30-114.20 and within 60 km of campus, or rejected. "
                    "Write the `description` yourself: 1-2 sentences, Chinese, concrete and useful "
                    "for someone visiting the place for the first time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "English name of the place."},
                        "name_zh": {"type": "string", "description": "Chinese name of the place."},
                        "latitude": {"type": "number", "description": "Latitude in WGS-84."},
                        "longitude": {"type": "number", "description": "Longitude in WGS-84."},
                        "description": {
                            "type": "string",
                            "description": "Chinese description written by you, 1-2 sentences.",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["campus", "transport", "food", "nature", "culture", "shopping", "other"],
                            "description": "Category used to colour the marker.",
                        },
                    },
                    "required": ["name", "name_zh", "latitude", "longitude", "description", "category"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "revise_map_marker",
                "description": "Edit an existing marker's text or coordinates after the user gives feedback.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "marker_id": {"type": "integer", "description": "ID of the marker to edit."},
                        "name": {"type": "string"},
                        "name_zh": {"type": "string"},
                        "description": {"type": "string"},
                        "category": {"type": "string"},
                        "latitude": {"type": "number"},
                        "longitude": {"type": "number"},
                    },
                    "required": ["marker_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remove_map_marker",
                "description": "Delete a marker from the map.",
                "parameters": {
                    "type": "object",
                    "properties": {"marker_id": {"type": "integer"}},
                    "required": ["marker_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compute_distance",
                "description": "Great-circle distance in km between two coordinates. Use it instead of doing the math yourself.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lat1": {"type": "number"},
                        "lng1": {"type": "number"},
                        "lat2": {"type": "number"},
                        "lng2": {"type": "number"},
                    },
                    "required": ["lat1", "lng1", "lat2", "lng2"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_map_view",
                "description": "Set the map centre, zoom level and overall title.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "zoom": {"type": "integer", "description": "12-16 recommended for a campus."},
                        "title": {"type": "string"},
                    },
                    "required": ["lat", "lng", "zoom", "title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_markers",
                "description": "Review the markers added so far. Call this before finishing to verify the count.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


# 工具名 → 实际函数（只暴露给执行器，不进 prompt）
DISPATCH = {
    "search_place": tool_search_place,
    "add_map_marker": tool_add_marker,
    "revise_map_marker": tool_revise_marker,
    "remove_map_marker": tool_remove_marker,
    "compute_distance": tool_compute_distance,
    "set_map_view": tool_set_map_view,
    "list_markers": tool_list_markers,
}
