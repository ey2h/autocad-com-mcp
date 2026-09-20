# autocad-com-mcp

通过 **Windows COM (ActiveX)** 控制正在运行的 AutoCAD 的 MCP 服务端。

**不需要 .NET 插件，因此改工具逻辑不用重启 AutoCAD。**

---

## 为什么不是 .NET 插件

.NET 程序集一旦加载进 AutoCAD 的 AppDomain 就**无法卸载**（`NETUNLOAD` 在现代
AutoCAD 已移除）。所以插件代码每改一次就得重启 CAD —— 开发时这是实打实的负担。

COM 走 ActiveX 接口，**跨进程调用**：脚本改完直接生效。而 ActiveX 早就提供了
需要的全部方法：

| 需要的能力 | ActiveX 现成接口 |
|---|---|
| 缩放到矩形 / 全图 | `Application.ZoomWindow` / `ZoomExtents` |
| 系统变量 | `Document.GetVariable` / `SetVariable` |
| 按 handle 取实体 | `Document.HandleToObject` |
| 选中（带夹点） | LISP `(sssetfirst nil ss)` |
| 即时高亮 | LISP `(redraw <ename> 3)` |
| 执行任意命令 | `Document.SendCommand` |

---

## 安装

`bash
git clone https://github.com/<you>/autocad-com-mcp
cd autocad-com-mcp
pip install -e .
`

需要 **Windows + 已安装并启动 AutoCAD**。依赖 `pywin32`。

## 用法

### 作为 MCP 服务（给 AI 客户端）

`bash
python -m autocad_com_mcp
`

接 Claude Desktop / Cursor 等客户端时，在它们的 MCP 配置里指向这个命令即可。
服务走 stdio。

### 作为命令行工具（自测 / 脚本调用）

`bash
python -m autocad_com_mcp info
python -m autocad_com_mcp zoom -1084.4 -3724.9 -384.4 -3150.9
python -m autocad_com_mcp extents
python -m autocad_com_mcp select 1845635 1845636      # handle 可十进制
python -m autocad_com_mcp highlight 1C2983            # 也可十六进制
python -m autocad_com_mcp query 1C2983
python -m autocad_com_mcp cmd '(getvar "DWGNAME")'
`

---

## 工具一览

| 工具 | 作用 |
|---|---|
| `acad_info` | 文档名、TILEMODE、VIEWCTR/VIEWSIZE、PICKFIRST/GRIPS、EXTMIN/EXTMAX |
| `acad_zoom_window` | 缩放到 WCS 矩形 |
| `acad_zoom_extents` | 缩放到全图 |
| `acad_select` | 按 handle 选中（pickfirst 选择集，带夹点） |
| `acad_highlight` / `acad_unhighlight` | 即时高亮 / 取消 |
| `acad_query` | 按 handle 查实体属性（类型/图层/颜色/线型/包围盒） |
| `acad_send_command` | 发送任意命令或 LISP |

---

## 踩过的坑（都在代码注释里，这里汇总）

这些都是**实测撞出来的**，不是照文档写的：

### 1. 系统变量在 `Document` 上，不叫 `GetSystemVariable`

`python
doc.GetVariable("TILEMODE")     # ✅ ActiveX 的名字
app.GetSystemVariable(...)      # ❌ 那是 .NET 的名字，ActiveX 没有
`

### 2. 点要包成 VARIANT 双精度数组

`ZoomWindow` 的参数不是元组：

`python
vt = winc32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x, y, 0.0])
app.ZoomWindow(vt1, vt2)
`

### 3. 缩放别用 `SendCommand("ZOOM")`

发命令字符串时 ZOOM 会停在"等待输入"，**把后续所有调用堵死**
（现象：@/ready` 报 `commandActive=1, commandNames=ZOOM`）。
原生 `ZoomWindow` 不产生命令，没有这个问题。

### 4. 按 handle 选中：`(cons 5)` 多个是 **AND**

`lisp
;; ❌ 一个实体不可能有多个 handle，结果 0 个
(sssetfirst nil (ssget "_X" (list (cons 5 "A") (cons 5 "B"))))

;; ✅ 逐个取实体名再加
(progn (setq ss (ssadd))
       (foreach h (list "A" "B") (if (handent h) (ssadd (handent h) ss)))
       (sssetfirst nil ss))
`

### 5. handle 有进制

DXF / ACadSharp 导出的常是**十进制**，`(handent)` 要**十六进制**。
本模块的 `to_hex()` 会处理（纯数字按十进制转，否则原样大写）。

### 6. 选中看不见时，先查 `PICKFIRST` / `GRIPS`

`acad_info` 会一起返回这两个。`PICKFIRST=0` 时 pickfirst 选择集根本不生效；
`GRIPS=0` 时不画夹点 —— 都会表现为"选中了但看不到"。

### 7. COM 是 STA，调用要串行

同一 apartment 里并发调用会出 `RPC_E_*` 错误。`com.py` 用一把全局锁
把所有调用串起来。

---

## 与同类项目的关系

| 项目 | 后端 | 说明 |
|---|---|---|
| [varavista/autocad-mcp](https://github.com/varavista/autocad-mcp) | File IPC / COM / ezdxf | 工具面最全（22 工具 / 130+ 操作），本项目的 COM 调用写法参考了它（Apache-2.0） |
| [LokmenoWer/best-cad-mcp](https://github.com/LokmenoWer/best-cad-mcp) | COM | handle-first、CAD-IR、dry-run 校验，思路最接近 |
| [codesknight/AutoCAD-MCP](https://github.com/codesknight/AutoCAD-MCP) | COM | 中文、带网页 UI |

本项目刻意做得**小而专**：只做"附着到运行中的 AutoCAD、看和指"，
不做绘图/建模/校验 —— 那些交给上面更全的项目。


---

## 不做的事：出图

试过用 ActiveX 的 `Plot` 接口出图，**结论是不做了** —— 不是不能，是不如已有的插件管线准。

实测记录（都在这台 AutoCAD 2026 上撞出来的）：

| PlotType | 结果 |
|---|---|
| `acWindow(4)` + `SetWindowToPlot(WCS)` | `GetWindowToPlot` 精确读回、`PlotToFile` 返回 True，**出图全白**（2560x1440 里非白像素 0 个） |
| `acView(3)` / `acLayout(5)` | 直接设不上（OLE "输入无效"） |
| `acLimits(2)` | 能设，出图同样全白 |
| `acExtents(1)` | 能出，但那是**全图** —— 91 张图跨 9 万单位，单张图纸在全图里只是一个像素点 |
| `acDisplay(0)` | 唯一能出内容的，但它打的是**屏幕视口**；屏幕 16:9 而图框内框 700x574，四周留白后**像素与坐标的对应关系就不准了** |

根因在官方 `SetWindowToPlot` 文档那句：

> The units for these values are specified by the **PaperUnits** property.

—— **窗口坐标不是 WCS**。而 .NET 的 `SetPlotWindowArea` 要 DCS 坐标，也得自己算变换矩阵。
两条路的"指定矩形出图"都不直观。

**出图留给 CurtainWallAI 插件**：2.3 秒/张 + 按内容裁剪，像素↔坐标误差 ≤1 像素，
91 帧 74 秒 0 失败。

**能跑通且更准的东西，不要为了架构好看去重写。**

---

## 与 `@CurtainWallAI`@ 的分工

`text
autocad-com-mcp      看和指（zoom / select / highlight / query）  + 离线分析（构件/型材/剖断线）
CurtainWallAI 插件   教学面板（WPF 调色板）  +  出图管线（需要 AutoCAD 绘图引擎）
`

分析逻辑放在 Python 侧的好处：**改判定规则不用编译、不用重启 CAD**。
C# 侧的 FrameExtract 负责"把 DWG 变成结构化事实"，这是它擅长的（离线、不需要字体、2.7 秒/全图）。

## 许可

MIT