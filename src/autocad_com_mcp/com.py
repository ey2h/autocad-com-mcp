# -*- coding: utf-8 -*-
"""
AutoCAD COM 层 —— 通过 Windows COM (ActiveX / IDispatch) 控制正在运行的 AutoCAD。

## 为什么走 COM 而不是 .NET 插件

.NET 程序集一旦加载进 AutoCAD 的 AppDomain 就**无法卸载**（NETUNLOAD 在现代
AutoCAD 已移除）。所以插件代码每改一次就得重启 CAD。COM 走 ActiveX 接口，
是进程外调用 —— **改脚本不用重启**，而且 ActiveX 早就提供了需要的全部方法。

## 本文件里几处"踩过才知道"的地方（都是实测）

1. **连正在运行的实例用 GetActiveObject，不要 Dispatch。**
   Dispatch 在已有实例时可能新建一个（取决于注册表），GetActiveObject 才明确是"附着"。

2. **系统变量在 Document 上，方法名是 GetVariable / SetVariable。**
   不是 Application.GetSystemVariable —— 那是 .NET 的名字，ActiveX 没有。

3. **点坐标要包成 VARIANT 双精度数组。**
   @@app.ZoomWindow(pt1, pt2)@@ 的 pt 不是元组，必须
   @@VARIANT(VT_ARRAY | VT_R8, [x, y, 0])@@。

4. **缩放用原生 @@app.ZoomWindow@@，不要用 @@SendCommand("ZOOM")@@。**
   发命令字符串时 ZOOM 会停在"等待输入"，把后续所有调用堵死
   （实测 /ready 报 commandActive=1 commandNames=ZOOM）。原生方法不产生命令。

5. **按 handle 选中不能用 @@(ssget "_X" (list (cons 5 "A") (cons 5 "B")))@@。**
   同一个过滤器列表里多个 @@(cons 5 ...)@@ 是 **AND** 关系 ——
   一个实体不可能有多个 handle，结果一个都选不中（实测 Count=0）。
   正确做法：@@handent@@ 逐个取实体名 → @@ssadd@@ → @@sssetfirst@@。

6. **handle 的进制。** DXF/ACadSharp 导出常是**十进制**，AutoCAD 的 @@(handent)@@
   要**十六进制**字符串，必须转换。

7. **COM 是 STA。** 同一个 apartment 里的调用要**串行**，多线程并发会出
   RPC_E_* 错误。本模块用一个全局锁把调用串起来。
"""
from __future__ import annotations

import re
import sys
import threading
import time
from typing import Any, Iterable, Sequence

_LOCK = threading.RLock()

try:
    import pythoncom
    import win32com.client as wc
    _HAVE_COM = True
except ImportError:                                     # pragma: no cover
    _HAVE_COM = False

## 依次尝试的 ProgID：具体版本优先，最后退回通用名
PROG_IDS = (
    "AutoCAD.Application.25.1",     # AutoCAD 2026
    "AutoCAD.Application.25.0",     # AutoCAD 2025
    "AutoCAD.Application.24.3",     # AutoCAD 2024
    "AutoCAD.Application",          # 通用（跟随默认版本）
)


class AcadError(RuntimeError):
    """COM 调用失败。"""


def _require_com() -> None:
    if not _HAVE_COM:
        raise AcadError("未安装 pywin32，请先运行：python -m pip install pywin32")


class Acad:
    """附着到正在运行的 AutoCAD，提供一层方法化的操作。"""

    def __init__(self, prog_id: str | None = None) -> None:
        _require_com()
        ids = (prog_id,) if prog_id else PROG_IDS
        last: Exception | None = None
        for pid in ids:
            with _LOCK:
                try:
                    self.app = wc.GetActiveObject(pid)
                    self.prog_id = pid
                    break
                except Exception as exc:                # noqa: BLE001
                    last = exc
        else:
            raise AcadError(
                "连不上正在运行的 AutoCAD（试过 %s）。"
                "请确认 AutoCAD 已启动并打开了图纸。最后错误：%s" % (ids, last))
        self.doc = self.app.ActiveDocument

    # ── 底层 ────────────────────────────────────────────────────────────
    @staticmethod
    def _vt(point: Sequence[float]) -> Any:
        """
        点 → COM VARIANT 双精度数组（**3 个元素**）。

        @@ZoomWindow(pt1, pt2)@@ 要 3 元素（AutoCAD 把它当 3D 点）。
        """
        return wc.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                          [float(point[0]), float(point[1]), 0.0])

    @staticmethod
    def _vt2(point: Sequence[float]) -> Any:
        """
        点 → COM VARIANT 双精度数组（**2 个元素**）。

        ★ @@Layout.SetWindowToPlot(pt1, pt2)@@ 要 2 元素 —— 给 3 个会报
          "安全数组中的元素数目不正确"（实测）。与 ZoomWindow 不一样，别混用。
        """
        return wc.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                          [float(point[0]), float(point[1])])

    @staticmethod
    def to_hex(handle: str | int) -> str:
        """十进制 handle → 十六进制字符串（@@handent@@ 要的格式）。"""
        s = str(handle).strip()
        return format(int(s), "X") if s.isdigit() else s.upper()

    def lisp(self, code: str, settle: float = 0.0) -> None:
        """执行一段 LISP / 命令。SendCommand 是同步的（命令结束才返回）。"""
        with _LOCK:
            self.doc.SendCommand(code if code.endswith("\n") else code + "\n")
        if settle:
            time.sleep(settle)

    # ── 查询 ────────────────────────────────────────────────────────────
    def getvar(self, name: str) -> Any:
        with _LOCK:
            return self.doc.GetVariable(name)

    def info(self) -> dict:
        def gv(n: str) -> Any:
            try:
                v = self.getvar(n)
                return list(v) if isinstance(v, tuple) else v
            except Exception as exc:                    # noqa: BLE001
                return "读取失败: %s" % exc
        return {
            "progId": self.prog_id,
            "document": self.doc.Name,
            "fullName": getattr(self.doc, "FullName", None),
            "tilemode": gv("TILEMODE"),          # 1=模型空间 0=布局
            "cvport": gv("CVPORT"),
            "viewctr": gv("VIEWCTR"),
            "viewsize": gv("VIEWSIZE"),
            "pickfirst": gv("PICKFIRST"),        # 0 时 pickfirst 选择集不生效
            "grips": gv("GRIPS"),                # 0 时不画夹点
            "extmin": gv("EXTMIN"),
            "extmax": gv("EXTMAX"),
        }

    def query(self, handles: Iterable[str | int]) -> list[dict]:
        """
        按 handle 取实体属性。

        用 ActiveX 的 @@Document.HandleToObject@@ —— ActiveX 有直接接口，
        不需要绕 LISP 写临时文件（我先写了那版，又长又脆）。
        """
        res: list[dict] = []
        for h in handles:
            hx = self.to_hex(h)
            try:
                o = self.handle_to_objectid(h)
                item: dict[str, Any] = {
                    "handle": hx, "type": getattr(o, "ObjectName", "?"),
                    "layer": getattr(o, "Layer", "?"),
                }
                for k, attr in (("color", "Color"), ("linetype", "Linetype"),
                                ("lineweight", "Lineweight"), ("space", "Space")):
                    try: item[k] = getattr(o, attr)
                    except Exception: pass
                # 包围盒（有些实体没有 BoundingBox，忽略即可）
                try:
                    mn, mx = o.GetBoundingBox()
                    item["bbox"] = {"min": list(mn), "max": list(mx)}
                except Exception: pass
                res.append(item)
            except Exception as exc:                    # noqa: BLE001
                res.append({"handle": hx, "error": str(exc)})
        return res


    def handle_to_objectid(self, handle: str | int) -> Any:
        """
        按 handle 取 COM 对象。ActiveX 的 @@HandleToObject@@ 要十六进制字符串。
        """
        with _LOCK:
            try:
                return self.doc.HandleToObject(self.to_hex(handle))
            except Exception as exc:                    # noqa: BLE001
                raise AcadError("HandleToObject(%s) 失败: %s" % (handle, exc)) from exc

    # ── 视图 ────────────────────────────────────────────────────────────
    def zoom_window(self, x0: float, y0: float, x1: float, y1: float) -> dict:
        """缩放到 WCS 矩形。用原生 ZoomWindow —— 不产生命令，不会挂起。"""
        with _LOCK:
            self.app.ZoomWindow(self._vt((x0, y0)), self._vt((x1, y1)))
        return {"viewctr": list(self.getvar("VIEWCTR")),
                "viewsize": self.getvar("VIEWSIZE")}

    def zoom_extents(self) -> dict:
        with _LOCK:
            self.app.ZoomExtents()
        return {"viewctr": list(self.getvar("VIEWCTR")),
                "viewsize": self.getvar("VIEWSIZE")}

    # ── 选中 / 高亮 ─────────────────────────────────────────────────────
    def select(self, handles: Iterable[str | int]) -> dict:
        """
        设置 pickfirst 选择集（= 用户看到的"选中状态"，带夹点）。

        ★ 不能用 (ssget "_X" (list (cons 5 "A") (cons 5 "B")))：
          多个 (cons 5 ...) 是 AND，一个实体不可能有多个 handle → 选不中任何东西。
          正确：handent 逐个取实体名 → ssadd → sssetfirst。
        """
        hexes = [self.to_hex(h) for h in handles]
        if not hexes:
            return {"selected": 0, "hex": []}
        lst = " ".join('"%s"' % h for h in hexes)
        code = ('(progn (setq ss (ssadd)) '
                '(foreach h (list %s) (if (handent h) (ssadd (handent h) ss))) '
                '(sssetfirst nil ss) (sslength ss))' % lst)
        self.lisp(code, settle=0.4)
        # 回读：PickfirstSelectionSet 是权威来源
        try:
            with _LOCK:
                cnt = self.doc.PickfirstSelectionSet.Count
        except Exception as exc:                        # noqa: BLE001
            cnt = "读取失败: %s" % exc
        # PICKFIRST=0 时选择集不生效，顺手纠正并告知
        pf = None
        try:
            pf = self.getvar("PICKFIRST")
            if int(pf) == 0:
                with _LOCK:
                    self.doc.SetVariable("PICKFIRST", 1)
        except Exception:                               # noqa: BLE001
            pass
        return {"selected": len(hexes), "hex": hexes,
                "pickfirstCount": cnt, "pickfirstVar": pf}

    def highlight(self, handles: Iterable[str | int]) -> dict:
        """即时高亮（@@(redraw <实体名> 3)@@）—— 不依赖 pickfirst / grips。"""
        hexes = [self.to_hex(h) for h in handles]
        if not hexes:
            return {"highlighted": 0}
        lst = " ".join('"%s"' % h for h in hexes)
        self.lisp('(foreach h (list %s) (if (handent h) (redraw (handent h) 3)))' % lst)
        return {"highlighted": len(hexes), "hex": hexes}

    def unhighlight(self, handles: Iterable[str | int]) -> dict:
        hexes = [self.to_hex(h) for h in handles]
        lst = " ".join('"%s"' % h for h in hexes)
        self.lisp('(foreach h (list %s) (if (handent h) (redraw (handent h) 4)))' % lst)
        return {"unhighlighted": len(hexes)}

    # ── 出图：不在本模块做 ──────────────────────────────────────────────
    #
    # 试过 ActiveX 的 Plot 接口，结论是**不如** CurtainWallAI 插件里那条出图管线。
    # 实测记录（都在这台 AutoCAD 2026 上撞出来的）：
    #
    #   官方 SetWindowToPlot 文档：「The units for these values are specified by the
    #   PaperUnits property.」—— 窗口坐标不是 WCS。
    #   PlotType=acWindow(4) + SetWindowToPlot(给 WCS)：
    #       GetWindowToPlot 精确读回、PlotToFile 返回 True，但出图**全白**
    #       （2560x1440 里非白像素 0 个），换任何媒体都一样。
    #   PlotType=acView(3) / acLayout(5)：直接设不上（OLE "输入无效"）。
    #   PlotType=acLimits(2)：也能设，但出图同样全白。
    #   PlotType=acExtents(1)：能出，但那是**全图** —— 91 张图跨 9 万单位，
    #       单张图纸在全图里只是一个像素点。
    #   PlotType=acDisplay(0)：唯一能出内容的，但它打的是**屏幕视口**；
    #       屏幕 16:9 而图框内框 700x574，内框塞进 16:9 后四周留白，
    #       像素与坐标的对应关系就不准了 —— 而出图必须能 1:1 反推坐标。
    #
    # 还有两个坑（即使改用 acDisplay 也得处理）：
    #   · PlotToFile 的第二个参数要 PC3 的**完整路径**；给裸名会 E_FAIL。
    #     本机 APPDATA 下同时装着 AutoCAD 2022/R24.1 和 2026/R25.1，
    #     递归搜到的第一个可能是**别的版本**的 PC3 —— 必须按版本号取最新。
    #   · 默认是后台绘图（BACKGROUNDPLOT=2），PlotToFile 立刻返回而文件还没落盘。
    #     要前台必须设 BACKGROUNDPLOT=0。
    #
    # 插件那条管线：2.3 秒/张 + 按内容裁剪，像素<->坐标误差 <=1 像素，
    # 验证过 91 帧 74 秒 0 失败。**能跑通且更准的东西，不要为了架构好看去重写。**
    # ───────────────────────────────────────────────────────────────────

    # ── 命令 ────────────────────────────────────────────────────────────
    def command(self, text: str) -> dict:
        """发送任意命令或 LISP。调用方自己保证不会挂在等输入上。"""
        self.lisp(text)
        return {"sent": text.strip()}
