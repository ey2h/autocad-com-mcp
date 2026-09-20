# -*- coding: utf-8 -*-
"""
MCP 服务端 —— 把 COM 层暴露成 MCP 工具。

用官方 @@mcp@@ SDK 的 FastMCP。工具刻意做得"薄"：每个工具就是 COM 层的一个方法，
不做多余的抽象 —— 这样出问题时能直接对应到 ActiveX 的哪一次调用。
"""
from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .com import Acad, AcadError

mcp = FastMCP("autocad-com")

_acad: Acad | None = None


def acad() -> Acad:
    """惰性连接，并在断线后自动重连（AutoCAD 重启过就要重连）。"""
    global _acad
    if _acad is None:
        _acad = Acad()
        return _acad
    try:
        _ = _acad.doc.Name            # 探活
    except Exception:                 # noqa: BLE001
        _acad = Acad()
    return _acad


def _dump(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, default=str, indent=1)


@mcp.tool()
def acad_info() -> str:
    """读取当前 AutoCAD 状态：文档名、模型/布局(TILEMODE)、视图中心与大小、
    PICKFIRST / GRIPS 开关、图形范围(EXTMIN/EXTMAX)。

    排查"操作了但看不见"时先看这个：
      PICKFIRST=0 -> pickfirst 选择集不生效
      GRIPS=0     -> 不画夹点
    """
    try:
        return _dump(acad().info())
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_zoom_window(min_x: float, min_y: float, max_x: float, max_y: float) -> str:
    """缩放到指定的 WCS 矩形（AutoCAD 世界坐标）。

    用原生的 Application.ZoomWindow —— 不产生命令，所以不会卡在"等待输入"。
    （用 SendCommand 发 ZOOM 会挂起，把后续调用全堵死。）
    """
    try:
        return _dump(acad().zoom_window(min_x, min_y, max_x, max_y))
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_zoom_extents() -> str:
    """缩放到全图范围（ZoomExtents）。"""
    try:
        return _dump(acad().zoom_extents())
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_select(handles: list[str]) -> str:
    """按 handle 选中实体（设置 pickfirst 选择集 = 用户看到的带夹点的选中状态）。

    handle 可以是十进制（DXF/ACadSharp 导出的常见形式）或十六进制字符串，
    本工具会自动判断并转换 —— AutoCAD 的 LISP @@handent@@ 要十六进制。

    多个 handle 用 @@handent@@ + @@ssadd@@ 逐个加入。
    注意：不能用 @@(ssget "_X" (list (cons 5 "A") (cons 5 "B")))@@ ——
    多个 @@(cons 5 ...)@@ 是 AND 关系，会一个都选不中。
    """
    try:
        return _dump(acad().select(handles))
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_highlight(handles: list[str]) -> str:
    """即时高亮实体（@@(redraw <实体名> 3)@@）。

    与 acad_select 的区别：这个不依赖 PICKFIRST / GRIPS，效果类似鼠标悬停，
    适合"只想让对方看一眼是哪些东西"的场合。
    """
    try:
        return _dump(acad().highlight(handles))
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_unhighlight(handles: list[str]) -> str:
    """取消 acad_highlight 的高亮。"""
    try:
        return _dump(acad().unhighlight(handles))
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_query(handles: list[str]) -> str:
    """按 handle 查询实体属性：类型(ObjectName)、图层、颜色、线型、线宽、包围盒。

    只有 handle 的时候，这是拿到实体信息最直接的方式 ——
    在图纸上选出目标、拿到 handle、再用本工具读属性。
    """
    try:
        return _dump(acad().query(handles))
    except AcadError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def acad_send_command(text: str) -> str:
    """向 AutoCAD 发送命令或 LISP 代码（等价于在命令行里输入）。

    ⚠️ 安全提示：这会以当前用户身份执行任意命令，能改能删。
       只在你信任调用方时使用；需要交互输入的命令（如 ZOOM 的部分选项）
       会停在"等待输入"并阻塞后续调用 —— 优先用专门的工具。

    常用：
      (getvar "DWGNAME")                 读变量
      (sssetfirst nil (ssget "_X"))      全选
      (command "_.REGEN")                重画
    """
    try:
        return _dump(acad().command(text))
    except AcadError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════
#  离线图纸分析（不需要 AutoCAD 运行）
#
#  C# 侧（FrameExtract）负责"把 DWG 变成结构化事实"，Python 侧负责
#  "从事实里读出语义"。分开的好处：改判定规则只改 Python，**不用编译、不用重启**。
# ══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def dwg_extract_frames(dwg_path: str, out_dir: str,
                       frame_extract_exe: str = "") -> str:
    """对 DWG 跑一遍离线提取（FrameExtract，C#/ACadSharp，**不需要 AutoCAD**）。

    产出三样东西到 out_dir：
      _frames.json     图框定义与实例（含内框 WCS 坐标）
      data/<图号>.json  每帧的内容：组件、文字、几何、引线顶点
      _blocks.json     块定义内部几何（含颜色与线型）

    实测：91 个图框的图纸约 60 秒。
    """
    from .analysis import frames as F
    return _dump(F.run(dwg_path,
                       os.path.join(out_dir, "_frames.json"),
                       os.path.join(out_dir, "data"),
                       os.path.join(out_dir, "_blocks.json"),
                       exe=frame_extract_exe or None))


@mcp.tool()
def dwg_components(data_dir: str, frame: str) -> str:
    """提取一张图的【语义构件清单】。

    ★ 构件清单 = 引线分组，与块无关：
        构件名   = 引线标注的文字
        构件位置 = 引线箭头端
        实例数   = 该标注的箭头个数（一条标注挂 N 个箭头 = N 个同类实例）

    实测 JD-201：425 条块记录 -> 11 类构件 / 12 个实例。
    注解文字里的参数会被拆出来（"铝合金插芯 L=50mm" -> {L: 50mm}）。
    """
    from .analysis import semantic as S
    doc = S.load_frame(data_dir, frame)
    out = S.components_of_frame(doc)
    out["specTables"] = S.find_spec_tables(doc)
    return _dump(out)


@mcp.tool()
def dwg_spec_tables(data_dir: str, frame: str) -> str:
    """找一帧里的【成套同心规格库】—— 这些是图例，不是真实构件。

    判据：同一个中心上叠着 >=10 个"方管钢"块（成套且同心）。
    实测 JD-301/JD-304 各 4 个中心 x 28 种规格。
    """
    from .analysis import semantic as S
    return _dump(S.find_spec_tables(S.load_frame(data_dir, frame)))


@mcp.tool()
def dwg_break_candidates(data_dir: str, frame: str,
                         max_short_ratio: float = 0.02) -> str:
    """找一帧里的【剖断线】候选（锯齿折线，图上表现为"很窄很长"的多段线）。

    只给候选、不下结论 —— 剖断线没有硬指标，需要人核对。
    拿到 handle 后可以用 acad_select / acad_highlight 在 CAD 里选中给人看。
    """
    from .analysis import semantic as S
    return _dump(S.find_break_candidates(S.load_frame(data_dir, frame),
                                         max_short_ratio))


@mcp.tool()
def dwg_profiles(blocks_file: str) -> str:
    """读取所有型材块的规格（外径 D / 壁厚 T）并与块名互校。

    从块定义内部几何判断视图类型：
      内轮廓是【闭合多段线】-> 剖面，T = (D - d) / 2
      内轮廓是【线】      -> 投影，T = 实线到虚线的距离
    两者都应等于名字里的壁厚；不等即为**可疑图纸错误**。

    实测 88 个型材块，名实 0 个不符。
    """
    from .analysis import profiles as P2
    out = P2.analyze_blocks(blocks_file)
    out.pop("rows", None)      # 逐块明细太长，用 dwg_profiles_detail 取
    return _dump(out)


@mcp.tool()
def dwg_profiles_detail(blocks_file: str) -> str:
    """dwg_profiles 的逐块明细版。"""
    from .analysis import profiles as P2
    return _dump(P2.analyze_blocks(blocks_file))


@mcp.tool()
def dwg_analyze_dir(data_dir: str) -> str:
    """批量分析一整个 data 目录（所有帧的语义构件清单 + 总量统计）。"""
    from .analysis import semantic as S
    out = S.analyze_dir(data_dir)
    out["frames"] = [{"frame": r["frame"], "components": r["componentCount"],
                      "instances": r["instanceCount"], "rawBlocks": r["rawBlockCount"]}
                     for r in out["frames"]]
    return _dump(out)

