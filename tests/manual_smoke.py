# -*- coding: utf-8 -*-
import sys, json, io, os
sys.path.insert(0, r"D:\Code\autocad-com-mcp\src")
sys.stdout.reconfigure(encoding="utf-8")

from autocad_com_mcp.analysis import semantic as S
from autocad_com_mcp.analysis import profiles as P

DATA = r"D:\Code\CurtainWallAI\corpus\frames\data"
BLK  = r"D:\Code\CurtainWallAI\corpus\frames\_blocks.json"

print("=" * 74)
print("① 语义构件清单  JD-201")
print("=" * 74)
doc = S.load_frame(DATA, "JD-201")
r = S.components_of_frame(doc)
print("  引线 %d 条 -> 配对 %d 条   语义构件 %d 类 / %d 个实例   （原始块记录 %d）"
      % (r["leaderCount"], r["matchedPairs"], r["componentCount"],
         r["instanceCount"], r["rawBlockCount"]))
for c in r["components"]:
    pa = ("  " + json.dumps(c["params"], ensure_ascii=False)) if c["params"] else ""
    print("     %-32s x%d%s" % (c["name"][:32], c["count"], pa))

print()
print("=" * 74)
print("② 规格库识别  JD-201 / JD-301")
print("=" * 74)
for no in ("JD-201", "JD-301"):
    st = S.find_spec_tables(S.load_frame(DATA, no))
    print("  %s: %d 个中心，%d 个块被判为规格库" % (no, len(st), sum(x["specs"] for x in st)))
    for x in st[:3]:
        print("     中心 (%.0f,%.0f)  %d 种规格，尺寸 %s" % (x["center"][0], x["center"][1], x["specs"], x["sizes"][:6]))

print()
print("=" * 74)
print("③ 剖断线候选  JD-201")
print("=" * 74)
bc = S.find_break_candidates(S.load_frame(DATA, "JD-201"))
print("  候选 %d 条（按长宽比排序）" % len(bc))
for x in bc[:6]:
    print("     handle=%-9s 层=%-6s rel=%s  尺寸 %sx%s  比值 %.1f"
          % (x["handle"], x["layer"], x["rel"], x["size"][0], x["size"][1], x["ratio"]))

print()
print("=" * 74)
print("④ 型材读取  名实互校")
print("=" * 74)
pr = P.analyze_blocks(BLK)
print("  块定义 %d 个，其中型材类 %d 个" % (pr["blockCount"], pr["profileCount"]))
print("  类别: %s   视图: %s" % (pr["categoryCounts"], pr["viewCounts"]))
print("  名实【不符】: %d 个" % pr["mismatchCount"])
for m in pr["mismatch"][:5]:
    print("     %s  名字T=%s  几何T=%s" % (m["block"], m["nameT"], m["geomT"]))
print()
print("  抽样（前 5 个方管）:")
for row in pr["rows"]:
    if row["category"] == "方管":
        g = row["geometry"]
        print("     %-14s %-4s  D=%s d=%s T=%s   %s"
              % (row["block"], g.get("kind"), g.get("D"), g.get("d"), g.get("T"), row["verdict"]))
        if pr["rows"].index(row) > 0 and sum(1 for x in pr["rows"][:pr["rows"].index(row)+1] if x["category"]=="方管") >= 5:
            break

print()
print("=" * 74)
print("⑤ 全目录批量")
print("=" * 74)
d = S.analyze_dir(DATA)
print("  %d 帧   语义构件 %d 个 / 实例 %d 个   （原始块记录 %d）"
      % (d["frameCount"], d["componentTotal"], d["instanceTotal"], d["rawBlockTotal"]))
