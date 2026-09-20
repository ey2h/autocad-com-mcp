# -*- coding: utf-8 -*-
"""入口：MCP stdio 服务端，或命令行自测。"""
from __future__ import annotations

import json
import sys


def _cli(argv: list[str]) -> int:
    from .com import Acad, AcadError

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("""用法：
  python -m autocad_com_mcp                启动 MCP stdio 服务（给 AI 客户端用）
  python -m autocad_com_mcp info           打印当前 AutoCAD 状态
  python -m autocad_com_mcp zoom x0 y0 x1 y1
  python -m autocad_com_mcp extents
  python -m autocad_com_mcp select  <handle> [...]
  python -m autocad_com_mcp highlight <handle> [...]
  python -m autocad_com_mcp query   <handle> [...]
  python -m autocad_com_mcp cmd "<lisp 或命令>"
""")
        return 0
    try:
        a = Acad()
    except AcadError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    c = argv[0]
    out: object
    if c == "info":
        out = a.info()
    elif c == "zoom":
        out = a.zoom_window(*(float(v) for v in argv[1:5]))
    elif c == "extents":
        out = a.zoom_extents()
    elif c == "select":
        out = a.select(argv[1:])
    elif c == "highlight":
        out = a.highlight(argv[1:])
    elif c == "query":
        out = a.query(argv[1:])
    elif c == "cmd":
        out = a.command(" ".join(argv[1:]))
    else:
        print(json.dumps({"error": "未知命令 " + c}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


def main() -> int:
    # 有任何参数就走命令行自测；无参数才启动 MCP 服务
    if len(sys.argv) > 1:
        return _cli(sys.argv[1:])
    from .server import mcp
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
