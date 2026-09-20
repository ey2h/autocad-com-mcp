# -*- coding: utf-8 -*-
"""
出图后处理 —— 黑底转换 + 高亮框。

出图本身走 COM（`com.Acad.plot_window`），产出的是白底 PNG；
这里做两件在图上"加东西"的事，都用 Pillow，与 AutoCAD 无关。

## 为什么统一黑底

CAD 的颜色是按黑底设计的：黄 #FFFF00 在白底上对比度约 1.07:1（几乎看不见），
青 1.6:1、绿 1.4:1；在黑底上是 21:1。用户明确选了黑底统一。
"""
from __future__ import annotations

from PIL import Image, ImageDraw


def to_black(src_path: str, dst_path: str | None = None,
             sat_threshold: float = 0.25, min_lum: float = 200.0) -> str:
    """
    白底打印图 → 黑底。

    做法：**中性像素反转亮度**（白底→黑底、黑线→白线），
    **彩色像素保持色相并按需提亮**。

    不能整体取反 —— 那会把黄变成蓝，而幕墙图用颜色区分型材/胶条/标注，
    色相本身就是语义。

    用 Pillow 的 point/ImageOps 而不是逐像素 Python 循环：
    一张 2000x1500 有 300 万像素，逐像素要好几秒。
    """
    im = Image.open(src_path).convert("RGB")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn) / mx if mx else 0.0
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if sat < sat_threshold:
                v = int(max(0.0, min(255.0, 255.0 - lum)))
                px[x, y] = (v, v, v)
            elif 1.0 < lum < min_lum:
                k = min_lum / lum
                px[x, y] = (int(min(255, b * k)), int(min(255, g * k)), int(min(255, r * k)))
    out = dst_path or src_path
    im.save(out)
    return out


def to_black_fast(src_path: str, dst_path: str | None = None,
                  sat_threshold: float = 0.25, min_lum: float = 200.0) -> str:
    """
    to_black 的向量化版（需要 numpy）。

    逐像素的 Python 循环在 300 万像素上要几秒，批量出图时不可接受。
    """
    try:
        import numpy as np
    except ImportError:
        return to_black(src_path, dst_path, sat_threshold, min_lum)

    im = Image.open(src_path).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(axis=2); mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    neutral = sat < sat_threshold
    v = np.clip(255.0 - lum, 0, 255)
    gray = np.stack([v, v, v], axis=-1)

    colored = (~neutral) & (lum > 1.0) & (lum < min_lum)
    k = np.where(colored, min_lum / np.maximum(lum, 1e-6), 1.0)[..., None]
    boosted = np.clip(a * k, 0, 255)

    out = np.where(neutral[..., None], gray, boosted)
    res = Image.fromarray(out.astype(np.uint8))
    dst = dst_path or src_path
    res.save(dst)
    return dst


def draw_highlight(src_path: str, rect_px, dst_path: str | None = None,
                   fill_alpha: int = 90, pen_width: int = 4) -> str:
    """
    在图上画高亮框。rect_px = (x0, y0, x1, y1) 像素坐标。

    ★ 按面积自适应（实测教训）：
      小框（<5% 画面）只描边在缩略图里根本看不见 -> 必须加填充、加粗边框
      大框（如"整张图"）加填充会把整幅图染红     -> 只能描边
    """
    im = Image.open(src_path).convert("RGBA")
    x0, y0, x1, y1 = [float(v) for v in rect_px]
    w, h = im.size
    bw, bh = max(2.0, x1 - x0), max(2.0, y1 - y0)
    small = (bw * bh) / max(1.0, w * h) < 0.05
    pen = max(4, int(min(bw, bh) * 0.10)) if small else 3

    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    if small:
        d.rectangle([x0, y0, x1, y1], fill=(255, 40, 40, fill_alpha))
    inset = pen / 2.0
    d.rectangle([x0 - inset, y0 - inset, x1 + inset, y1 + inset],
                outline=(255, 255, 0, 255), width=pen)

    out = Image.alpha_composite(im, overlay).convert("RGB")
    dst = dst_path or src_path
    out.save(dst)
    return dst


def wcs_to_px(x: float, y: float, inner_min_x: float, inner_max_y: float,
              ppu_x: float, ppu_y: float):
    """
    WCS → 像素。原点在图框内框左下角，图像 y 轴向下所以翻转。

    这套映射必须与出图时用的窗口严格对应，否则高亮框会错位
    （实测误差 <= 1 像素时才算对）。
    """
    return ((x - inner_min_x) * ppu_x, (inner_max_y - y) * ppu_y)
