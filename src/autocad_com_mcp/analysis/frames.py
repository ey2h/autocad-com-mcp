# -*- coding: utf-8 -*-
"""
FrameExtract 子进程封装。

## 为什么是"两边都写"

FrameExtract 是 **C# / .NET + ACadSharp**，因为它要**离线读 DWG**：
  · 不需要 AutoCAD 运行
  · 不需要字体（只读文字字符串，不渲染）
  · 实测 2.7 秒跑完全图 91 个图框（AutoCAD 里那条路会卡死）

而本 MCP server 是 Python。两者**不冲突**：
  · C# 侧负责"把 DWG 变成结构化事实"（这是它擅长的）
  · Python 侧负责"从事实里读出语义"（改规则不用编译，迭代极快）

所以这里只做进程调用，不重复实现 DWG 解析。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def find_exe(hint: str | None = None) -> str | None:
    """找 FrameExtract.exe：显式路径 -> 环境变量 -> PATH -> 常见位置。"""
    if hint and os.path.exists(hint):
        return hint
    env = os.environ.get("FRAME_EXTRACT_EXE")
    if env and os.path.exists(env):
        return env
    onpath = shutil.which("FrameExtract") or shutil.which("frame-extract")
    if onpath:
        return onpath
    for cand in (
        r"D:\Code\CurtainWallAI\corpus\FrameExtract\bin\Release\net8.0\FrameExtract.exe",
        r"D:\Code\CurtainWallAI\corpus\FrameExtract\bin\Debug\net8.0\FrameExtract.exe",
    ):
        if os.path.exists(cand):
            return cand
    return None


def run(dwg: str, out_frames: str, content_dir: str | None = None,
        blocks_out: str | None = None, exe: str | None = None,
        timeout: int = 600) -> dict:
    """
    调用 FrameExtract。

    产出：
      out_frames     图框定义与实例（含内框 WCS）
      content_dir/   每帧的内容 JSON（组件/文字/几何/引线顶点）
      blocks_out     块定义内部几何（含颜色/线型）
    """
    exe = find_exe(exe)
    if not exe:
        return {"ok": False, "error":
                "找不到 FrameExtract.exe。设置环境变量 FRAME_EXTRACT_EXE，"
                "或先构建 corpus/FrameExtract。"}
    if not os.path.exists(dwg):
        return {"ok": False, "error": "DWG 不存在: %s" % dwg}

    cmd = [exe, dwg, out_frames]
    if content_dir:
        cmd += ["--content", content_dir]
    if blocks_out:
        cmd += ["--blocks", blocks_out]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "FrameExtract 超时（%ss）" % timeout}

    tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()][-8:]
    return {
        "ok": p.returncode == 0,
        "returncode": p.returncode,
        "exe": exe,
        "frames": out_frames,
        "contentDir": content_dir,
        "blocks": blocks_out,
        "stdoutTail": tail,
        "stderr": (p.stderr or "")[-1500:] or None,
    }
