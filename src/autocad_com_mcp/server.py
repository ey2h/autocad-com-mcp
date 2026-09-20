# -*- coding: utf-8 -*-
"""
MCP 服务端 —— 把 COM 层暴露成 MCP 工具。

用官方 @@mcp@@ SDK 的 FastMCP。工具刻意做得"薄"：每个工具就是 COM 层的一个方法，
不做多余的抽象 —— 这样出问题时能直接对应到 ActiveX 的哪一次调用。
"""
from __future__ import annotations

import json
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
