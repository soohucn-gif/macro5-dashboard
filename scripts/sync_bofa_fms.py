#!/usr/bin/env python3
"""从本地私有存档 bofa-fms 同步**派生数字口径**到本公开仓库。

刻意只搬三样东西：月度头条数字（现金水位、情绪分、净超配）、最拥挤交易/尾部风险的
排名与占比、BofA 官方 Contrarian Trades 标签。**不搬图表、不搬报告原文** ——
原图版权归 BofA Global Research，私有存档 `soohucn-gif/bofa-fms` 不对外分发。

用法（在本机、bofa-fms 已更新之后跑）：
    python3 scripts/sync_bofa_fms.py [/path/to/bofa-fms]
默认路径为本仓库同级目录下的 ../bofa-fms。
"""
import csv
import json
import os
import sys

from common import DATA, ROOT

DEFAULT_SRC = os.path.join(os.path.dirname(ROOT), "bofa-fms")

HEAD_FIELDS = ["month", "release_date", "cash_pct", "cash_rule_signal", "sentiment_score",
               "net_ow_equities", "net_ow_us_equities", "n_managers", "aum_usd_bn",
               "top_crowded_trade", "top_crowded_pct", "top_tail_risk", "top_tail_risk_pct"]


def _n(v):
    return "" if v is None else v


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    hist_path = os.path.join(src, "history.json")
    if not os.path.exists(hist_path):
        sys.exit("找不到 %s —— 本脚本只能在本机跑，云端 Actions 读不到私有存档。" % hist_path)
    months = sorted(json.load(open(hist_path, encoding="utf-8"))["months"],
                    key=lambda m: m["month"])

    head, crowded, contra = [], [], []
    for m in months:
        ct = m.get("crowded_trades") or []
        tr = m.get("tail_risks") or []
        head.append({
            "month": m["month"], "release_date": _n(m.get("release_date")),
            "cash_pct": _n(m.get("cash_pct")),
            "cash_rule_signal": _n(m.get("cash_rule_signal")),
            "sentiment_score": _n(m.get("sentiment_score")),
            "net_ow_equities": _n(m.get("net_ow_equities")),
            "net_ow_us_equities": _n(m.get("net_ow_us_equities")),
            "n_managers": _n(m.get("n_managers")), "aum_usd_bn": _n(m.get("aum_usd_bn")),
            "top_crowded_trade": ct[0]["name"] if ct else "",
            "top_crowded_pct": _n(ct[0].get("pct")) if ct else "",
            "top_tail_risk": tr[0]["name"] if tr else "",
            "top_tail_risk_pct": _n(tr[0].get("pct")) if tr else "",
        })
        for i, t in enumerate(ct, 1):
            crowded.append({"month": m["month"], "rank": i, "trade": t.get("name", ""),
                            "trade_cn": t.get("name_cn", ""), "pct": _n(t.get("pct"))})
        for i, t in enumerate(tr, 1):
            contra.append({"month": m["month"], "kind": "tail_risk", "rank": i,
                           "item": t.get("name", ""), "item_cn": t.get("name_cn", ""),
                           "pct": _n(t.get("pct"))})
        # BofA 官方 Contrarian Trades：只有文字标签，没有百分比
        for i, t in enumerate(m.get("contrarian_trades") or [], 1):
            contra.append({"month": m["month"], "kind": "contrarian", "rank": i,
                           "item": t, "item_cn": "", "pct": ""})
        for i, t in enumerate(m.get("most_underweight") or [], 1):
            contra.append({"month": m["month"], "kind": "most_underweight", "rank": i,
                           "item": t, "item_cn": "", "pct": ""})
        for i, t in enumerate(m.get("sector_most_uw") or [], 1):
            contra.append({"month": m["month"], "kind": "sector_underweight", "rank": i,
                           "item": t.get("name", ""), "item_cn": "", "pct": _n(t.get("pct"))})

    n1 = write(os.path.join(DATA, "bofa_fms.csv"), HEAD_FIELDS, head)
    n2 = write(os.path.join(DATA, "bofa_fms_crowded.csv"),
               ["month", "rank", "trade", "trade_cn", "pct"], crowded)
    n3 = write(os.path.join(DATA, "bofa_fms_contrarian.csv"),
               ["month", "kind", "rank", "item", "item_cn", "pct"], contra)
    print("bofa_fms: %d 期 / 拥挤交易 %d 行 / 反向与尾部风险 %d 行，最新 %s"
          % (n1, n2, n3, head[-1]["month"] if head else "—"))


if __name__ == "__main__":
    main()
