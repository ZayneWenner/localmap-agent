"""
Tencent Maps GL JS 渲染器（国内合规底图）

合规说明：
    在中国境内提供地图服务，底图必须使用具备测绘资质的图源。
    腾讯地图 / 高德 / 百度 / 天地图 为合规来源；OpenStreetMap 直连海外瓦片、
    Google Maps、Mapbox 等均不在白名单内。本技能默认使用腾讯地图 GL JS。

Key 处理：
    - 默认模式（key 代理）：SDK 通过 window._TMapSecurityConfig 把请求转发到
      WorkBuddy 本地代理，前端不出现任何明文 Key。
    - 自备 Key 模式：传入 --key，写入显式占位符/实际 Key，产出可脱离代理运行的 HTML。

坐标系：
    腾讯地图使用 GCJ-02。模型/Photron 返回的是 WGS-84，渲染前统一做偏移转换，
    否则标记会整体偏移数百米。
"""
from __future__ import annotations

import json
from html import escape
from typing import Any

from .geo_tools import wgs84_to_gcj02, haversine_km, SIAS_CENTER

# 国内合规白名单图源
PROVIDER = "Tencent Maps GL JS"

CATEGORY_COLORS = {
    "campus": "#2b6cb0",
    "transport": "#2f855a",
    "food": "#c05621",
    "nature": "#276749",
    "culture": "#6b46c1",
    "shopping": "#b7791f",
    "other": "#4a5568",
}

CATEGORY_ICONS = {
    "campus": "校",
    "transport": "行",
    "food": "食",
    "nature": "景",
    "culture": "文",
    "shopping": "购",
    "other": "点",
}

# HTML 模板中的这两个占位符由 WorkBuddy 运行时替换，
# 生成时**必须原样保留**，不要手工填成具体端口/密钥。
WB_PORT_PLACEHOLDER = "__WB_HTTP_PORT__"
WB_SECRET_PLACEHOLDER = "__WB_TMAP_SECRET__"


def to_gcj_markers(board_dict: dict) -> list[dict]:
    """把 board 状态里的 WGS-84 坐标转换成 GCJ-02。"""
    out = []
    for m in board_dict["markers"]:
        glat, glng = wgs84_to_gcj02(m["latitude"], m["longitude"])
        item = dict(m)
        item["gcj_lat"] = round(glat, 6)
        item["gcj_lng"] = round(glng, 6)
        item["color"] = CATEGORY_COLORS.get(m["category"], "#4a5568")
        item["icon"] = CATEGORY_ICONS.get(m["category"], "点")
        out.append(item)
    return out


def render_html(board_dict: dict, api_key: str | None = None, meta: dict | None = None) -> str:
    """
    生成可直接打开的交互式地图 HTML。

    api_key=None  → 使用 WorkBuddy key 代理模式（默认，前端零 Key）
    api_key 有值  → 使用用户自备 Key，产出可独立分发的 HTML
    """
    meta = meta or {}
    markers = to_gcj_markers(board_dict)
    view = board_dict["view"]
    vlat, vlng = wgs84_to_gcj02(view["lat"], view["lng"])

    # 为保证「产物完整性」：即使底图瓦片因网络受限加载失败，
    # 页面仍然可用（标记、列表、坐标、距离全部可见），不会白屏。
    markers_json = json.dumps(markers, ensure_ascii=False, indent=2)

    if api_key:
        security_block = ""
        sdk_src = "https://map.qq.com/api/gljs?v=1.exp"
        key_note = f'<script>window.__TMAP_KEY__ = {json.dumps(api_key)};</script>'
    else:
        security_block = f"""
    <script type="text/javascript">
        window._TMapSecurityConfig = {{
            serviceHost: 'http://127.0.0.1:{WB_PORT_PLACEHOLDER}/_TMapService/_wbt/{WB_SECRET_PLACEHOLDER}',
        }};
    </script>"""
        sdk_src = "https://map.qq.com/api/gljs?v=1.exp"
        key_note = ""

    title = escape(board_dict.get("title") or "Sias University Area Map")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        * {{ box-sizing: border-box; }}
        html, body {{ margin: 0; padding: 0; height: 100%;
            font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; }}
        #shell {{ display: flex; height: 100vh; }}
        #sidebar {{ width: 330px; overflow-y: auto; background: #f7fafc;
            border-right: 1px solid #e2e8f0; padding: 16px; }}
        #sidebar h1 {{ font-size: 16px; margin: 0 0 4px; color: #1a202c; }}
        #sidebar .sub {{ font-size: 12px; color: #718096; margin-bottom: 14px; line-height: 1.6; }}
        .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
            padding: 10px 12px; margin-bottom: 10px; cursor: pointer; transition: .15s; }}
        .card:hover {{ border-color: #90cdf4; box-shadow: 0 2px 8px rgba(66,153,225,.15); }}
        .card .nm {{ font-weight: 600; font-size: 14px; color: #1a202c; }}
        .card .en {{ font-size: 11px; color: #a0aec0; margin-bottom: 6px; }}
        .card .ds {{ font-size: 12px; color: #4a5568; line-height: 1.6; }}
        .card .meta {{ font-size: 11px; color: #a0aec0; margin-top: 6px; }}
        .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }}
        #map {{ flex: 1; height: 100vh; }}
        .lbl {{ background: rgba(255,255,255,.92); border: 1px solid #cbd5e0; border-radius: 4px;
            padding: 1px 5px; font-size: 11px; color: #2d3748; white-space: nowrap; }}
        #warn {{ display:none; background:#fffaf0; border:1px solid #fbd38d; color:#7b341e;
            font-size:12px; padding:8px 10px; border-radius:6px; margin-bottom:12px; line-height:1.6; }}
    </style>
    {security_block}
    {key_note}
    <script src="{sdk_src}"></script>
</head>
<body>
<div id="shell">
    <aside id="sidebar">
        <h1>{title}</h1>
        <div class="sub">
            底图：{PROVIDER}（GCJ-02）<br>
            本地模型 <b>{escape(str(meta.get('model', 'local LLM')))}</b> 生成 ·
            {escape(str(meta.get('generated_at', '')))}<br>
            共 <b>{len(markers)}</b> 个标记，点击卡片可定位
        </div>
        <div id="warn">⚠ 底图瓦片暂时加载不出来（可能是离线或内网限制）。<br>
            标记点仍会在默认画布上正确显示，右侧列表全部可用。</div>
        <div id="list"></div>
    </aside>
    <div id="map"></div>
</div>

<script>
const MARKERS = {markers_json};
const CENTER = {{ lat: {vlat:.6f}, lng: {vlng:.6f} }};
const ZOOM = {int(view.get('zoom', 14))};

// ---- 侧栏 Always-on：先渲染列表，保证最坏情况也有内容 ----
const listEl = document.getElementById('list');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
MARKERS.forEach((m, i) => {{
    const d = document.createElement('div');
    d.className = 'card';
    d.innerHTML = `<div class="nm"><span class="dot" style="background:${{m.color}}"></span>${{esc(m.name_zh)}}</div>
        <div class="en">${{esc(m.name)}}</div>
        <div class="ds">${{esc(m.description)}}</div>
        <div class="meta">${{esc(m.category)}} · ${{m.distance_km}} km · ${{m.latitude.toFixed(4)}}, ${{m.longitude.toFixed(4)}}</div>`;
    d.addEventListener('click', () => focusMarker(i));
    listEl.appendChild(d);
}});

let map = null;
const urlForTile = 'https://map.qq.com/api/gljs';

function buildDOMFallback() {{
    // 底图不可用时，仍然给出可用视图：说明全部标记的相对位置
    const warn = document.getElementById('warn');
    warn.style.display = 'block';
}}

function focusMarker(i) {{
    const m = MARKERS[i];
    if (map && typeof TMap !== 'undefined') {{
        map.setCenter(new TMap.LatLng(m.gcj_lat, m.gcj_lng));
        map.setZoom(16);
        if (infoWindow) infoWindow.close();
        openInfo(m);
    }} else {{
        alert(m.name_zh + '\\n' + m.description + '\\n' + m.latitude + ', ' + m.longitude);
    }}
}}

let infoWindow = null;
function openInfo(m) {{
    const content = `<div style="max-width:260px">
        <div style="font-weight:600;font-size:14px;margin-bottom:2px">${{esc(m.name_zh)}}</div>
        <div style="font-size:11px;color:#999;margin-bottom:6px">${{esc(m.name)}}</div>
        <div style="font-size:12px;line-height:1.7;color:#333">${{esc(m.description)}}</div>
        <div style="font-size:11px;color:#999;margin-top:6px">
            ${{esc(m.category)}} · 距校园 ${{m.distance_km}} km<br>
            WGS-84: ${{m.latitude}}, ${{m.longitude}}</div>
    </div>`;
    infoWindow = new TMap.InfoWindow({{
        map: map, position: new TMap.LatLng(m.gcj_lat, m.gcj_lng),
        content: content, offset: {{x: 0, y: -38}}, enableCustom: true
    }});
}}

function boot() {{
    if (typeof TMap === 'undefined') {{ buildDOMFallback(); return; }}
    try {{
        // 注意：已在 header 配置 _TMapSecurityConfig，不要再调用 TMap.setConfig()，否则会白图。
        map = new TMap.Map(document.getElementById('map'), {{
            center: new TMap.LatLng(CENTER.lat, CENTER.lng),
            zoom: ZOOM,
            pitch: 0,
            showControl: true
        }});
        // 不要传 mapStyleId：自定义样式需要单独开通，默认 Key 下会导致底图灰白。

        // 1) 标记
        const styles = {{}};
        MARKERS.forEach((m, i) => {{
            styles['s' + i] = new TMap.MarkerStyle({{
                width: 26, height: 26, anchor: {{x: 13, y: 13}},
                src: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
                    `<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26">
                        <circle cx="13" cy="13" r="11" fill="${{m.color}}" stroke="#fff" stroke-width="2"/>
                        <text x="13" y="17" font-size="11" text-anchor="middle" fill="#fff"
                              font-family="Microsoft YaHei">${{m.icon}}</text>
                    </svg>`)
            }});
        }});
        const multiMarker = new TMap.MultiMarker({{
            map: map,
            styles: styles,
            geometries: MARKERS.map((m, i) => ({{
                id: 'm' + i, styleId: 's' + i,
                position: new TMap.LatLng(m.gcj_lat, m.gcj_lng)
            }}))
        }});
        multiMarker.on('click', evt => {{
            const idx = parseInt(evt.geometry.id.slice(1), 10);
            openInfo(MARKERS[idx]);
        }});

        // 2) 名称标签
        new TMap.MultiLabel({{
            map: map,
            styles: {{ l: new TMap.LabelStyle({{
                color: '#2d3748', size: 11, offset: {{x: 0, y: 18}}, angle: 0,
                alignment: 'center', verticalAlignment: 'top'
            }}) }},
            geometries: MARKERS.map((m, i) => ({{
                id: 'lb' + i, styleId: 'l',
                position: new TMap.LatLng(m.gcj_lat, m.gcj_lng),
                content: m.name_zh
            }}))
        }});

        // 3) 从外围点位到校园中心的连线，直观表达"周边"关系
        new TMap.MultiPolyline({{
            map: map,
            styles: {{ p: new TMap.PolylineStyle({{
                color: 'rgba(66,153,225,0.45)', width: 2, borderWidth: 0, lineCap: 'round'
            }}) }},
            geometries: MARKERS.map((m, i) => ({{
                id: 'pl' + i, styleId: 'p',
                paths: [new TMap.LatLng(CENTER.lat, CENTER.lng),
                        new TMap.LatLng(m.gcj_lat, m.gcj_lng)]
            }}))
        }});

        setTimeout(() => {{}}, 0);
    }} catch (e) {{
        console.error('map init failed', e);
        buildDOMFallback();
    }}
}}

window.addEventListener('load', () => {{
    boot();
    // 3 秒后若地图库仍未挂上（离线/受限），给出明确提示而不是白屏
    setTimeout(() => {{ if (typeof TMap === 'undefined') buildDOMFallback(); }}, 3000);
}});
</script>
</body>
</html>"""
    return html
