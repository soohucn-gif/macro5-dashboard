#!/usr/bin/env python3
"""实际利率期限结构的 5 年月末读数表 → data/real_rate_5y_monthly.md。

日频全量在 data/real_rates.csv；这份是给人看的月度凝缩版：
5/10/30 年三个期限并排，外加用「名义 − 盈亏平衡通胀」对 10 年期做独立复算。
"""
import csv
import datetime
import os
import statistics

from common import DATA

YEARS = 5


def main():
    rows = []
    with open(os.path.join(DATA, "real_rates.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["dfii10"]:
                continue
            def g(k):
                return float(r[k]) if r.get(k) else None
            rows.append((r["date"], float(r["dfii10"]), g("dgs10"), g("t10yie"),
                         g("dfii5"), g("dfii30")))
    cut = (datetime.date.today() - datetime.timedelta(days=365 * YEARS)).isoformat()
    win = [r for r in rows if r[0] >= cut]
    vals = [r[1] for r in win]
    cur = win[-1]
    pct = sum(1 for v in vals if v < cur[1]) / len(vals) * 100

    out = [
        "# 实际利率期限结构 · 近 5 年读数",
        "",
        "TIPS 收益率 = 市场对「名义利率 − 预期通胀率」这个差值的直接定价。"
        "下表以 10 年期为主轴，并列 5 年与 30 年看曲线形态；最右列用 `DGS10 − T10YIE` "
        "独立复算 10 年期，两者应当逐月吻合。30 年期 2010-02 才有数据。",
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
        "| 月份 | 5年实际 | **10年实际** | 30年实际 | 10年名义 | 10年盈亏平衡 | 复算 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    bym = {}
    for row in win:
        bym[row[0][:7]] = row
    def q(x):
        return "%.2f%%" % x if x is not None else "—"
    for m in sorted(bym):
        d, a, b, c, f5, f30 = bym[m]
        chk = q(b - c) if (b is not None and c is not None) else "—"
        out.append("| %s | %s | **%.2f%%** | %s | %s | %s | %s |"
                   % (m, q(f5), a, q(f30), q(b), q(c), chk))
    out += ["", "> 日频全量见 `data/real_rates.csv`（10年/5年 2003-01 起，30年 2010-02 起）。"]
    path = os.path.join(DATA, "real_rate_5y_monthly.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
