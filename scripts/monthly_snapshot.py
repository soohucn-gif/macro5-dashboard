#!/usr/bin/env python3
"""月度快照：写 data/monthly/YYYY-MM.md。

月频的那一类（Damodaran 隐含 ERP）每月只动一次，日频的几类则给出月度收盘/月内区间，
方便按月回看，而不是只有一个当日截面。
"""
import datetime
import json
import os
import sys

from common import DATA, read_csv

TODAY = datetime.date.today()


def month_of(d):
    return d[:7]


def monthly_last(rows, col):
    """每月最后一个有效值 → {'YYYY-MM': (date, value)}。"""
    out = {}
    for r in rows:
        try:
            v = float(r[col])
        except (TypeError, ValueError, KeyError):
            continue
        out[month_of(r["date"])] = (r["date"], v)
    return out


def monthly_range(rows, col):
    """每月的最低/最高 → {'YYYY-MM': (lo, hi)}。"""
    out = {}
    for r in rows:
        try:
            v = float(r[col])
        except (TypeError, ValueError, KeyError):
            continue
        m = month_of(r["date"])
        lo, hi = out.get(m, (v, v))
        out[m] = (min(lo, v), max(hi, v))
    return out


SERIES = [
    ("10年期实际利率 (TIPS)", "real_rate_10y.csv", "dfii10", "%", True),
    ("10年期名义利率", "real_rate_10y.csv", "dgs10", "%", True),
    ("10年期盈亏平衡通胀", "real_rate_10y.csv", "t10yie", "%", True),
    ("隐含股权风险溢价", "erp_monthly.csv", "erp_t12m", "%", True),
    ("隐含预期收益率", "erp_monthly.csv", "expected_return", "%", True),
    ("标普500", "equity_indices.csv", "sp500", "点", False),
    ("纳斯达克综合", "equity_indices.csv", "nasdaq_comp", "点", False),
    ("纳斯达克100", "equity_indices.csv", "nasdaq_100", "点", False),
    ("伦敦金", "gold.csv", "usd_per_oz", "美元/盎司", False),
    ("比特币", "bitcoin.csv", "close", "美元", False),
]


def main():
    month = sys.argv[1] if len(sys.argv) > 1 else TODAY.strftime("%Y-%m")
    prev_dt = datetime.date.fromisoformat(month + "-01") - datetime.timedelta(days=1)
    prev = prev_dt.strftime("%Y-%m")
    yr_dt = datetime.date.fromisoformat(month + "-01") - datetime.timedelta(days=365)
    yr = yr_dt.strftime("%Y-%m")

    lines = ["# 五大类数据看板 · %s 月度快照" % month, "",
             "生成于 %s（UTC）。日频序列取当月最后一个有效收盘；月频序列取当月官方值。" %
             datetime.datetime.now(datetime.timezone.utc)
             .isoformat(timespec="seconds"), "",
             "| 指标 | 本月 | 上月 | 环比 | 去年同月 | 同比 | 月内区间 |",
             "|---|---:|---:|---:|---:|---:|---|"]
    cache = {}
    for name, fname, col, unit, is_rate in SERIES:
        if fname not in cache:
            cache[fname] = read_csv(os.path.join(DATA, fname))
        rows = cache[fname]
        last = monthly_last(rows, col)
        rng = monthly_range(rows, col)
        if month not in last:
            continue

        def q(v):
            if v is None:
                return "—"
            return ("%.2f" % v) if is_rate else ("{:,.2f}".format(v) if v < 1000
                                                 else "{:,.0f}".format(v))
        cur = last[month][1]
        pv = last.get(prev, (None, None))[1]
        yv = last.get(yr, (None, None))[1]

        def delta(base):
            if base in (None, 0):
                return "—"
            return ("%+.2f pp" % (cur - base)) if is_rate \
                else ("%+.1f%%" % ((cur / base - 1) * 100))
        lo, hi = rng.get(month, (None, None))
        lines.append("| %s (%s) | %s | %s | %s | %s | %s | %s ~ %s |"
                     % (name, unit, q(cur), q(pv), delta(pv), q(yv), delta(yv),
                        q(lo), q(hi)))

    # GPU：本月覆盖到多少天，各卡月末值
    gpu = read_csv(os.path.join(DATA, "gpu_rental.csv"))
    gm = [r for r in gpu if month_of(r["date"]) == month]
    if gm:
        lines += ["", "## GPU 租赁价格指数（%s，覆盖 %d 天）" % (month, len({r["date"] for r in gm})),
                  "", "| 卡型 · 档位 | 月末 | 月内最低 | 月内最高 |", "|---|---:|---:|---:|"]
        keys = sorted({(r["gpu"], r["segment"]) for r in gm})
        for gpu_name, seg in keys:
            pts = sorted([(r["date"], float(r["usd_per_hr"])) for r in gm
                          if r["gpu"] == gpu_name and r["segment"] == seg])
            if not pts:
                continue
            vals = [v for _, v in pts]
            lines.append("| %s · %s | %.2f | %.2f | %.2f |"
                         % (gpu_name, seg, pts[-1][1], min(vals), max(vals)))

    # 美银 FMS（月频，本机同步）
    fms = read_csv(os.path.join(DATA, "bofa_fms.csv"))
    fms_cur = next((r for r in fms if r["month"] == month), None)
    if fms_cur:
        prev_row = next((r for r in fms if r["month"] == prev), None)

        def d(k, unit="pp"):
            try:
                a, b = float(fms_cur[k]), float(prev_row[k])
            except (TypeError, ValueError, KeyError):
                return "—"
            return "%+.1f %s" % (a - b, unit)
        lines += ["", "## 美银基金经理调查（%s 期）" % month, "",
                  "| 指标 | 本期 | 环比 |", "|---|---:|---:|",
                  "| 现金水位 | %s%% | %s |" % (fms_cur["cash_pct"], d("cash_pct")),
                  "| Cash Rule 信号 | %s | — |" % fms_cur["cash_rule_signal"],
                  "| 头号拥挤交易 | %s（%s%%） | %s |"
                  % (fms_cur["top_crowded_trade"], fms_cur["top_crowded_pct"], d("top_crowded_pct")),
                  "| 头号尾部风险 | %s（%s%%） | %s |"
                  % (fms_cur["top_tail_risk"], fms_cur["top_tail_risk_pct"], d("top_tail_risk_pct")),
                  "| 股票净超配 | %s%% | %s |"
                  % (fms_cur["net_ow_equities"] or "—", d("net_ow_equities"))]
        crowded = [r for r in read_csv(os.path.join(DATA, "bofa_fms_crowded.csv"))
                   if r["month"] == month]
        contra = [r for r in read_csv(os.path.join(DATA, "bofa_fms_contrarian.csv"))
                  if r["month"] == month]
        if crowded:
            lines += ["", "**最拥挤交易**：" + "；".join(
                "%s %s%%" % (r["trade_cn"] or r["trade"], r["pct"]) for r in crowded)]
        tails = [r for r in contra if r["kind"] == "tail_risk"]
        if tails:
            lines += ["", "**尾部风险**：" + "；".join(
                "%s %s%%" % (r["item_cn"] or r["item"], r["pct"]) for r in tails)]
        cts = [r for r in contra if r["kind"] == "contrarian"]
        if cts:
            lines += ["", "**BofA 官方反向交易**：" + "；".join(r["item"] for r in cts)]
        uw = [r for r in contra if r["kind"] == "most_underweight"]
        if uw:
            lines += ["", "**最被低配**：" + "、".join(r["item"] for r in uw)]
        lines += ["", "> FMS 仅收录派生数字口径，原始图表与报告正文版权归 "
                      "BofA Global Research，不在本仓库分发。"]

    rep_path = os.path.join(DATA, "fetch_report.json")
    if os.path.exists(rep_path):
        rep = json.load(open(rep_path, encoding="utf-8"))
        bad = [j for j in rep["jobs"] if not j.get("ok")]
        if bad:
            lines += ["", "## 抓取异常", ""]
            lines += ["- **%s**：%s" % (j["label"], j.get("error")) for j in bad]

    lines += ["", "> 完整历史见 `data/*.csv`；看板见 [index.html](../../index.html)。"]
    out_dir = os.path.join(DATA, "monthly")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, month + ".md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
