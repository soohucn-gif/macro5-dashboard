#!/usr/bin/env python3
"""10年期实际利率的 5 年月末读数表 → data/real_rate_5y_monthly.md。

日频全量在 data/real_rate_10y.csv；这份是给人看的月度凝缩版，
额外把「名义 − 盈亏平衡通胀」逐月算出来跟 TIPS 收益率对账。
"""
import csv
import datetime
import os
import statistics

from common import DATA

YEARS = 5


def main():
    rows = []
    with open(os.path.join(DATA, "real_rate_10y.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["dfii10"]:
                continue
            def g(k):
                return float(r[k]) if r[k] else None
            rows.append((r["date"], float(r["dfii10"]), g("dgs10"), g("t10yie")))
    cut = (datetime.date.today() - datetime.timedelta(days=365 * YEARS)).isoformat()
    win = [r for r in rows if r[0] >= cut]
    vals = [r[1] for r in win]
    cur = win[-1]
    pct = sum(1 for v in vals if v < cur[1]) / len(vals) * 100

    out = [
        "# 10年期实际利率 · 近 5 年读数",
        "",
        "FRED `DFII10` —— 10 年期通胀保值债券(TIPS)收益率，即市场对「名义利率 − 预期通胀率」"
        "这个差值的直接定价。右侧两列用 `DGS10 − T10YIE` 独立复算，两者应当逐月吻合。",
        "",
        "| 项 | 值 |", "|---|---|",
        "| 最新 | **%.2f%%**（%s） |" % (cur[1], cur[0]),
        "| 5 年区间 | %.2f%% ~ %.2f%% |" % (min(vals), max(vals)),
        "| 最低点 | %.2f%%（%s） |" % (min(vals), win[vals.index(min(vals))][0]),
        "| 最高点 | %.2f%%（%s） |" % (max(vals), win[vals.index(max(vals))][0]),
        "| 均值 / 中位 | %.2f%% / %.2f%% |" % (sum(vals) / len(vals),
                                               statistics.median(vals)),
        "| 当前 5 年分位 | %.0f%% |" % pct,
        "| 日频样本 | %d 个交易日（%s → %s） |" % (len(win), win[0][0], win[-1][0]),
        "",
        "## 月末读数",
        "",
        "| 月份 | 实际利率 DFII10 | 名义 DGS10 | 盈亏平衡通胀 T10YIE | 复算 DGS10−T10YIE |",
        "|---|---:|---:|---:|---:|",
    ]
    bym = {}
    for d, a, b, c in win:
        bym[d[:7]] = (d, a, b, c)
    for m in sorted(bym):
        d, a, b, c = bym[m]
        chk = "%.2f%%" % (b - c) if (b is not None and c is not None) else "—"
        out.append("| %s | %.2f%% | %s | %s | %s |"
                   % (m, a, "%.2f%%" % b if b else "—", "%.2f%%" % c if c else "—", chk))
    out += ["", "> 日频全量见 `data/real_rate_10y.csv`（2003-01 至今）。"]
    path = os.path.join(DATA, "real_rate_5y_monthly.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
