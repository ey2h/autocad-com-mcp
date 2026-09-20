# -*- coding: utf-8 -*-
"""
型材读取 —— 从块定义内部几何读出规格（外径 D / 壁厚 T）与视图类型。

## 依据的制图规范（全部由用户教学得到）

    剖面（垂直构件轴线切开）
        外轮廓（闭合多段线）-> 外径 D
        内轮廓（闭合多段线）-> 内径 d，壁厚 T = (D - d) / 2
        方管有圆角，图上常用切角近似 -> 轮廓是 8 个顶点而不是 4 个
    投影（从侧面看）
        两条平行实线 -> 外径 D
        内侧虚线到实线的距离 -> 壁厚 T
        ★ 这个距离【也应该等于剖面的壁厚】—— 这是可用的查错规则

## 命名规律（块名直接编码了规格与视图）

    方管钢DxT     方管【剖面】
    AxBxC         角钢/矩形管剖面（A×B 外形，C 壁厚）
    ...-侧面 / ...投影   【投影画法】
    ...通长        通长版本（整根，非节点局部）

## 实测

    方管钢50x5   外 ±25 / 内 ±20 -> D=50 T=5   ✓ 与名字一致
    方管钢80x5   外 ±40 / 内 ±35 -> D=80 T=5   ✓
    4mm厚钢通-侧面  外 ±35 / 虚线 ±31 -> T=4   ✓ 正好等于名字里的 4mm
    88 个型材块，名实 0 个不符
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

RE_FANGGUAN = re.compile(r"^方管钢(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$")
RE_AXBXC = re.compile(r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)")


def parse_name(name: str):
    """
    解析块名 -> (类别, 视图, A, B, T)；不是型材则返回 None。

    视图判定只看名字里有没有"侧面/投影" —— 本项目的图里
    投影件会在块名或图层名里写明（例如 4mm厚钢通-侧面、
    图层 R-TJ-T铁件+不锈钢投影线）。
    """
    view = "投影" if ("侧面" in name or "投影" in name) else "剖面"
    m = RE_FANGGUAN.match(name)
    if m:
        D, T = float(m.group(1)), float(m.group(2))
        return ("方管", view, D, D, T)
    m = RE_AXBXC.match(name)
    if m:
        return ("角钢/矩管", view, float(m.group(1)), float(m.group(2)), float(m.group(3)))
    return None


def _pts_of_lw(g):
    p = g["p"]
    return [(p[i], p[i + 1]) for i in range(0, len(p), 2)]


def _span(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _inside(inner, outer, eps=0.5):
    return (inner[0] >= outer[0] - eps and inner[1] >= outer[1] - eps and
            inner[2] <= outer[2] + eps and inner[3] <= outer[3] + eps)


def read_geometry(block: dict):
    """
    从块定义几何判断视图类型并读 D / d / T。

    判别器：内轮廓是【闭合多段线】-> 剖面；是【线】-> 投影。
    """
    geo = [e for e in block.get("ents") or [] if e.get("t") == "G"]
    closed, lines = [], []
    for e in geo:
        g = e.get("g") or {}
        if g.get("t") == "LW" and g.get("closed"):
            closed.append((_span(_pts_of_lw(g)), e))
        elif g.get("t") == "L":
            p = g["p"]
            lines.append(((min(p[0], p[2]), min(p[1], p[3]),
                           max(p[0], p[2]), max(p[1], p[3])), e))
    if not closed:
        return None
    closed.sort(key=lambda c: (c[0][2] - c[0][0]) * (c[0][3] - c[0][1]), reverse=True)
    ob, _ = closed[0]
    D = (round(ob[2] - ob[0], 2), round(ob[3] - ob[1], 2))
    inner_poly = [c for c in closed[1:] if _inside(c[0], ob)]
    inner_line = [l for l in lines if _inside(l[0], ob)]
    if inner_poly:
        ib = inner_poly[0][0]
        dx, dy = ib[2] - ib[0], ib[3] - ib[1]
        return {"kind": "剖面", "D": D, "d": (round(dx, 2), round(dy, 2)),
                "T": (round((D[0] - dx) / 2, 2), round((D[1] - dy) / 2, 2)),
                "innerLinetype": inner_poly[0][1].get("lt")}
    if inner_line:
        xs0 = min(l[0][0] for l in inner_line); xs1 = max(l[0][2] for l in inner_line)
        ys0 = min(l[0][1] for l in inner_line); ys1 = max(l[0][3] for l in inner_line)
        return {"kind": "投影", "D": D,
                "d": (round(xs1 - xs0, 2), round(ys1 - ys0, 2)),
                "T": (round((D[0] - (xs1 - xs0)) / 2, 2), round((D[1] - (ys1 - ys0)) / 2, 2)),
                "innerLinetype": dict(Counter(l[1].get("lt") for l in inner_line)),
                "innerLines": len(inner_line)}
    return {"kind": "空心", "D": D, "d": None, "T": None}


def analyze_blocks(blocks_file: str, verify: bool = True) -> dict:
    """
    读 `_blocks.json`，对每个型材类块解析规格并与名字互校。

    返回逐块结果 + 统计。名实不符即为**可疑图纸错误**（库块通常是 0）。
    """
    with open(blocks_file, encoding="utf-8") as f:
        data = json.load(f)
    blocks = data.get("blocks") or {}

    rows, mismatch = [], []
    for name, b in blocks.items():
        pn = parse_name(name)
        if not pn:
            continue
        cat, view, A, B, T = pn
        rg = read_geometry(b) or {}
        gT = rg.get("T")
        verdict = "无内线（只能靠名字取 T）"
        if gT:
            cand = [t for t in gT if abs(t) > 0.01]
            if cand:
                t0 = cand[0]
                if abs(t0 - T) < 0.05:
                    verdict = "名实相符"
                else:
                    verdict = "壁厚不符（几何 %s vs 名字 %s）" % (t0, T)
                    mismatch.append({"block": name, "nameT": T, "geomT": gT,
                                     "geomD": rg.get("D"), "kind": rg.get("kind")})
            else:
                verdict = "几何无壁厚（只有外形）"
        rows.append({"block": name, "category": cat, "view": view,
                     "nameSpec": {"A": A, "B": B, "T": T},
                     "geometry": rg, "verdict": verdict})

    return {
        "source": blocks_file,
        "blockCount": len(blocks),
        "profileCount": len(rows),
        "mismatchCount": len(mismatch),
        "mismatch": mismatch,
        "viewCounts": dict(Counter(r["view"] for r in rows)),
        "categoryCounts": dict(Counter(r["category"] for r in rows)),
        "rows": rows,
    }
