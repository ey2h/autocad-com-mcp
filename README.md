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

## 许可

MIT
