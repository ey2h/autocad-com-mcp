# -*- coding: utf-8 -*-
"""
语义构件提取 —— 从 FrameExtract 的原始事实重建【人看得懂的构件清单】。

## 核心结论（用户教学驱动）

    构件清单【就是】引线分组，与块无关：
        构件名   = 引线标注的文字
        构件位置 = 引线箭头端
        实例数   = 该标注的箭头个数（一条标注挂 N 个箭头 = N 个同类实例）

    块（BlockReference）只在需要取几何形状时才用，**不是构件的身份来源**。
    早先"拿箭头端去匹配最近的块"从根上就是错的 —— 同一个点上可能叠着几十个块。

## 输入

FrameExtract 产出的 `data/<图号>.json`，字段：
    widthUnits/heightUnits   内框尺寸（图纸单位）
    texts[]                  文字：Text / relX / relY / Layer
    components[]             块实例：name / rel(bbox) / chain
    geometry[]               几何：Type / rel(bbox) / Layer / pts(引线顶点)
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict

## ── 注解文字里的参数 ────────────────────────────────────────────────────
## "铝合金插芯 L=50mm" 里 L=50mm 是【参数】而不是名字的一部分；
## "3-M8*40mm不锈钢销钉" 里数量规格是参数；"@300mm" 是间距。
RE_PARAM = re.compile(
    r"(?P<k>L\s*[=≤<>]\s*\d+(?:\.\d+)?\s*(?:mm)?)"
    r"|(?P<at>@\s*\d+(?:\.\d+)?\s*(?:mm)?)"
    r"|(?P<n>\d+\s*-\s*[MφΦ]\s*\d+(?:\.\d+)?(?:\s*[x×*]\s*\d+)?\s*(?:mm)?)"
    r"|(?P<phi>[φΦ]\s*\d+(?:\.\d+)?)", re.I)


def decode_acad(s: str) -> str:
    """解码 AutoCAD 文字转义码：%%c=Ø  %%d=°  %%p=±"""
    if not s:
        return s
    return (s.replace("%%c", "Ø").replace("%%C", "Ø")
             .replace("%%d", "°").replace("%%D", "°")
             .replace("%%p", "±").replace("%%P", "±")
             .replace("%%u", "").replace("%%U", ""))


def split_name_params(text: str):
    """
    把 "铝合金插芯 L=50mm" 拆成 ("铝合金插芯", {"L": "50mm"})。

    ★ 不要剥离"领头数字"：很多名字的首数字就是规格的一部分 ——
      8Low-e+12A+8钢化中空玻璃（8=玻璃厚）、4mm钢套芯连接件（4mm=板厚）、
      50*5热镀锌方钢（50=外径）。剥了反而把正确名字改错。
    """
    text = decode_acad(text)
    params = {}
    for m in RE_PARAM.finditer(text):
        raw = m.group(0).strip()
        if m.group("k"):
            params["L"] = re.sub(r"^L\s*[=≤<>]\s*", "", raw)
        elif m.group("at"):
            params["间距"] = re.sub(r"^@\s*", "", raw)
        elif m.group("n"):
            params["数量规格"] = raw
        elif m.group("phi"):
            params["直径"] = raw
    name = RE_PARAM.sub("", text).strip(" -—,，、")
    return (name or text), params


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def match_leaders(leaders, texts, width: float, height: float):
    """
    引线 → 标注文字的 **1:1 全局贪心匹配**。

    ★ 为什么必须 1:1 而不是"各自取最近"：
      实测 JD-201 有 30 条引线、30 条文字，正好一一对应。两条文字挨得近时，
      "各自取最近"会让近的那条把远的引线抢走（实测「4mm钢套芯连接件」
      被「防腐垫片」抢走）。1:1 配对才正确。

    容差按图幅自适应：JD-301 的引线端点正好落在文字上（距离 4.0），
    而 JD-304 的落在 96~242 —— 用固定阈值 60 会把整张图滤空（实测踩过）。
    """
    tol = max(80.0, 0.25 * min(width, height))
    cand = []
    for i, g in enumerate(leaders):
        pts = g.get("pts")
        if not pts or len(pts) < 2:
            continue
        tail = pts[-1]
        for j, t in enumerate(texts):
            cand.append((_dist((t["relX"], t["relY"]), tail), i, j, tail))
    cand.sort(key=lambda x: x[0])

    used_l, used_t = set(), set()
    pairs = []
    for dd, i, j, tail in cand:
        if i in used_l or j in used_t:
            continue
        if dd > tol:
            break
        used_l.add(i); used_t.add(j)
        g = leaders[i]
        pairs.append({
            "text": texts[j]["Text"], "layer": texts[j]["Layer"],
            "tip":  [round(g["pts"][0][0], 1), round(g["pts"][0][1], 1)],
            "tail": [round(tail[0], 1), round(tail[1], 1)],
            "dist": round(dd, 2),
        })
    return pairs


def wps_of_frame(frames_json: str, frame: str):
    """
    取某张图的定位点（WP / 工作点）。

    定位点是**现场放线的基准** —— 构件相对它的偏移才是可复用的几何信息
    （只记绝对坐标的话，图框一移动整条数据就废了）。
    实测本图 91 张里每张 1~4 个，另有 11 个落在所有图框之外（跨图纸的大装配块里）。

    别名见 FrameExtract 的 WpAliases：定位点 / WP / 工作点 / WP点 / WORKINGPOINT / 节点定位点。
    各设计院叫法不同，所以那边按名字匹配，这里只管读。
    """
    with open(frames_json, encoding="utf-8") as f:
        fj = json.load(f)
    return [w for w in (fj.get("wps") or []) if w.get("frame") == frame]


def components_of_frame(doc: dict, wps=None) -> dict:
    """
    一帧 → 语义构件清单（可选带定位点）。

    传了 wps 时，每个构件的每个实例都会带上：
        wpIndex  最近的定位点序号
        wp       定位点的相对坐标
        wpOffset 构件箭头端相对该定位点的偏移（这才是可复用的几何）
    """
    W = float(doc.get("widthUnits") or 0)
    H = float(doc.get("heightUnits") or 0)
    texts = doc.get("texts") or []
    leaders = [g for g in (doc.get("geometry") or []) if g.get("Type") == "Leader"]
    pairs = match_leaders(leaders, texts, W, H)

    groups = defaultdict(list)
    for p in pairs:
        nm, pa = split_name_params(p["text"])
        groups[nm].append(dict(p, params=pa))

    # 定位点（相对内框的坐标；没传就退化成绝对坐标）
    wp_list = []
    for w in (wps or []):
        rel = w.get("rel")
        wp_list.append({"x": w.get("x"), "y": w.get("y"),
                        "rel": [rel[0], rel[1]] if rel else None,
                        "block": w.get("block"), "inside": w.get("inside", True)})

    def nearest_wp(tip):
        """构件的箭头端离哪个定位点最近 —— 就是它归属的定位点。"""
        if not wp_list:
            return None, None
        best, bi = None, -1
        for i, w in enumerate(wp_list):
            p = w["rel"] if w["rel"] else [w["x"], w["y"]]
            if p is None or p[0] is None:
                continue
            d = _dist(tip, p)
            if best is None or d < best:
                best, bi = d, i
        if bi < 0:
            return None, None
        p = wp_list[bi]["rel"] if wp_list[bi]["rel"] else [wp_list[bi]["x"], wp_list[bi]["y"]]
        return bi, [round(tip[0] - p[0], 2), round(tip[1] - p[1], 2)]

    comps = []
    for nm, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        insts = []
        for x in ps:
            wi, off = nearest_wp(x["tip"])
            insts.append({"tip": x["tip"], "norm":
                          [round(x["tip"][0] / W, 4), round(x["tip"][1] / H, 4)] if W and H else [],
                          "wpIndex": wi, "wpOffset": off})
        comps.append({
            "name": nm,
            "count": len(ps),
            "rawTexts": sorted({x["text"] for x in ps}),
            "params": ps[0]["params"],
            "textLayer": ps[0]["layer"],
            "positions": [x["tip"] for x in ps],
            "norm": [i["norm"] for i in insts],
            "instances": insts,                     # 每个实例带 wpIndex / wpOffset
        })

    return {
        "frame": doc.get("drawingNumber"),
        "drawingName": doc.get("drawingName"),
        "widthUnits": W, "heightUnits": H,
        "leaderCount": len(leaders), "textCount": len(texts),
        "matchedPairs": len(pairs),
        "componentCount": len(comps),
        "instanceCount": sum(c["count"] for c in comps),
        "components": comps,
        "rawBlockCount": len(doc.get("components") or []),
        "wpCount": len(wp_list),
        "wps": wp_list,
    }


def find_spec_tables(doc: dict):
    """
    识别【成套同心的规格库】—— 它们是图例，不是真实构件。

    判据：成套（覆盖整个规格族）+ 同心（包围盒中心相同、逐层变大）。
    实测 JD-301 / JD-304 各 4 个中心 × 28 种规格 = 112 个块，
    占原始块记录的 26~30%。
    """
    fam = [c for c in (doc.get("components") or [])
           if c.get("named") and "方管钢" in (c.get("name") or "")]
    by_center = defaultdict(list)
    for c in fam:
        r = c.get("rel") or []
        if len(r) != 4:
            continue
        by_center[(round((r[0] + r[2]) / 2), round((r[1] + r[3]) / 2))].append(c)
    out = []
    for k, v in by_center.items():
        if len(v) >= 10:
            out.append({"center": [k[0], k[1]], "specs": len(v),
                        "sizes": sorted({round(c["rel"][2] - c["rel"][0]) for c in v})})
    return out


def find_break_candidates(doc: dict,
                          min_short: float = 3.0,
                          max_short_ratio: float = 0.03):
    """
    找【剖断线】候选 —— 锯齿折线。

    ## 判据（用户核对确认后定下的）

    剖断线在图上表现为：**有一定宽度 + 很长**的一条折线。
    本实例里是 4 条 8x125 的，在图层 @@FH@@ 上。

    ★ 关键是要**排除"只有 1 个单位宽的直线"**：
      最初只按长宽比排序，结果把 10 条 @@PJ@@ 层 1x131 的线排到了前面
      （长宽比 131 更大）—— 那些是引线/尺寸界线之类的**直线**，不是锯齿。
      锯齿是有真实宽度的（8 单位），所以加一个 min_short 下限就能把它们分开。

    ★ 仍然只给候选、不下结论：剖断线没有硬性指标，必须人核对。
      拿到 handle 后用 acad_select / acad_highlight 在 CAD 里选中给人看。
    """
    W = float(doc.get("widthUnits") or 1)
    H = float(doc.get("heightUnits") or 1)
    out = []
    for g in (doc.get("geometry") or []):
        if g.get("Type") not in ("LwPolyline", "Polyline"):
            continue
        r = g.get("rel") or []
        if len(r) != 4:
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        short, long_ = min(w, h), max(w, h)
        if long_ < 20 or short < min_short:
            continue
        if short > max_short_ratio * max(W, H):
            continue
        out.append({"handle": g.get("Handle"), "layer": g.get("Layer"),
                    "rel": [round(v, 2) for v in r],
                    "size": [round(w, 1), round(h, 1)],
                    "ratio": round(long_ / short, 1)})
    # 排序：先按面积（锯齿的"有宽度"特征更实在），再按长宽比
    out.sort(key=lambda x: (-(x["size"][0] * x["size"][1]), -x["ratio"]))
    return out


def load_frame(data_dir: str, frame: str) -> dict:
    with open(os.path.join(data_dir, frame + ".json"), encoding="utf-8") as f:
        return json.load(f)


def analyze_dir(data_dir: str, frames=None) -> dict:
    """批量分析一个目录下的所有帧。"""
    if frames is None:
        frames = sorted(os.path.basename(f)[:-5] for f in os.listdir(data_dir)
                        if f.endswith(".json") and not f.startswith("_"))
    recs = []
    for no in frames:
        p = os.path.join(data_dir, no + ".json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            recs.append(components_of_frame(json.load(f)))
    return {
        "frameCount": len(recs),
        "componentTotal": sum(r["componentCount"] for r in recs),
        "instanceTotal": sum(r["instanceCount"] for r in recs),
        "rawBlockTotal": sum(r["rawBlockCount"] for r in recs),
        "frames": recs,
    }
