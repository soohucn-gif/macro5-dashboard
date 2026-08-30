#!/usr/bin/env python3
"""把一期从网上读到的美银 FMS 结果写进看板 CSV。带校验，写错比不写更糟。

给 Claude routine 用：routine 上网把数字读出来 → 组成 JSON → 喂给本脚本。
脚本负责**校验 + 幂等合并**，不负责抓取（抓取要读图和通稿，得由模型做）。

    python3 scripts/append_fms.py fms_2026-09.json
    cat payload.json | python3 scripts/append_fms.py -

JSON 结构（除 month / sources / crowded_trades 外都可省略，省略即留空）：
{
  "month": "2026-09",                 必填，YYYY-MM
  "release_date": "2026-09-16",
  "cash_pct": 3.6,
  "cash_rule_signal": "sell|neutral|buy",
  "sentiment_score": 8.2,
  "net_ow_equities": 50,
  "net_ow_us_equities": 20,
  "n_managers": 180,
  "aum_usd_bn": 520,
  "crowded_trades":   [{"name": "Long global semiconductors",
                        "name_cn": "做多全球半导体", "pct": 50}],   必填，至少一条
  "tail_risks":       [{"name": "AI bubble", "name_cn": "AI 泡沫", "pct": 30}],
  "contrarian_trades": ["long bonds / short commodities"],
  "most_underweight":  ["Bonds", "UK"],
  "sector_most_uw":    [{"name": "Staples", "pct": -19}],
  "sources": ["https://...", "https://..."],                       必填，至少一条
  "confidence": "high|medium|low",
  "notes": "读不清或有出入的地方写这里"
}
"""
import csv
import json
import os
import re
import sys

from common import DATA, read_csv

HEAD_FIELDS = ["month", "release_date", "cash_pct", "cash_rule_signal", "sentiment_score",
               "net_ow_equities", "net_ow_us_equities", "n_managers", "aum_usd_bn",
               "top_crowded_trade", "top_crowded_pct", "top_tail_risk", "top_tail_risk_pct",
               "confidence", "sources", "notes"]
CROWDED_FIELDS = ["month", "rank", "trade", "trade_cn", "pct"]
CONTRA_FIELDS = ["month", "kind", "rank", "item", "item_cn", "pct"]


def die(msg):
    sys.exit("拒绝写入：" + msg)


def num(v, lo, hi, label, required=False):
    if v in (None, ""):
        if required:
            die("%s 缺失" % label)
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        die("%s 不是数字：%r" % (label, v))
    if not (lo <= x <= hi):
        die("%s = %s 超出合理区间 [%s, %s]，八成是读错了" % (label, x, lo, hi))
    return round(x, 2)


def validate(p):
    m = p.get("month", "")
    if not re.fullmatch(r"\d{4}-\d{2}", str(m)):
        die("month 必须是 YYYY-MM，收到 %r" % m)
    srcs = [s for s in (p.get("sources") or []) if str(s).startswith("http")]
    if not srcs:
        die("sources 至少要有一条 http(s) 链接 —— 没有出处的数字不进库")
    ct = p.get("crowded_trades") or []
    if not ct:
        die("crowded_trades 为空 —— 这是本类数据的核心字段，读不到就别写这一期")
    for i, t in enumerate(ct, 1):
        if not t.get("name"):
            die("crowded_trades[%d] 缺 name" % i)
        num(t.get("pct"), 0, 100, "crowded_trades[%d].pct" % i)
    for i, t in enumerate(p.get("tail_risks") or [], 1):
        if not t.get("name"):
            die("tail_risks[%d] 缺 name" % i)
        num(t.get("pct"), 0, 100, "tail_risks[%d].pct" % i)
    for i, t in enumerate(p.get("sector_most_uw") or [], 1):
        num(t.get("pct"), -100, 100, "sector_most_uw[%d].pct" % i)
    num(p.get("cash_pct"), 1.0, 8.0, "cash_pct")
    num(p.get("sentiment_score"), 0, 10, "sentiment_score")
    num(p.get("net_ow_equities"), -100, 100, "net_ow_equities")
    num(p.get("net_ow_us_equities"), -100, 100, "net_ow_us_equities")
    sig = p.get("cash_rule_signal")
    if sig not in (None, "", "sell", "neutral", "buy"):
        die("cash_rule_signal 只能是 sell / neutral / buy，收到 %r" % sig)
    return srcs


def merge(path, fields, rows_for_month, month):
    """同月旧行整体替换，其余月份原样保留，按月份排序落盘。"""
    kept = [r for r in read_csv(path) if r.get("month") != month]
    out = kept + [{k: ("" if r.get(k) is None else str(r.get(k))) for k in fields}
                  for r in rows_for_month]
    out.sort(key=lambda r: (r.get("month", ""), int(r.get("rank") or 0),
                            r.get("kind", "")))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    return len(out)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    try:
        p = json.loads(raw)
    except json.JSONDecodeError as e:
        die("JSON 解析失败：%s" % e)

    srcs = validate(p)
    month = p["month"]
    ct = p["crowded_trades"]
    tr = p.get("tail_risks") or []

    head = [{
        "month": month, "release_date": p.get("release_date", ""),
        "cash_pct": num(p.get("cash_pct"), 1.0, 8.0, "cash_pct"),
        "cash_rule_signal": p.get("cash_rule_signal", ""),
        "sentiment_score": num(p.get("sentiment_score"), 0, 10, "sentiment_score"),
        "net_ow_equities": num(p.get("net_ow_equities"), -100, 100, "net_ow_equities"),
        "net_ow_us_equities": num(p.get("net_ow_us_equities"), -100, 100, "ow_us"),
        "n_managers": p.get("n_managers", ""), "aum_usd_bn": p.get("aum_usd_bn", ""),
        "top_crowded_trade": ct[0]["name"],
        "top_crowded_pct": num(ct[0].get("pct"), 0, 100, "top_crowded_pct"),
        "top_tail_risk": tr[0]["name"] if tr else "",
        "top_tail_risk_pct": num(tr[0].get("pct"), 0, 100, "top_tail") if tr else "",
        "confidence": p.get("confidence", "medium"),
        "sources": " | ".join(srcs), "notes": p.get("notes", ""),
    }]
    crowded = [{"month": month, "rank": i, "trade": t["name"],
                "trade_cn": t.get("name_cn", ""), "pct": t.get("pct", "")}
               for i, t in enumerate(ct, 1)]
    contra = []
    for i, t in enumerate(tr, 1):
        contra.append({"month": month, "kind": "tail_risk", "rank": i, "item": t["name"],
                       "item_cn": t.get("name_cn", ""), "pct": t.get("pct", "")})
    for i, t in enumerate(p.get("contrarian_trades") or [], 1):
        contra.append({"month": month, "kind": "contrarian", "rank": i, "item": t,
                       "item_cn": "", "pct": ""})
    for i, t in enumerate(p.get("most_underweight") or [], 1):
        contra.append({"month": month, "kind": "most_underweight", "rank": i, "item": t,
                       "item_cn": "", "pct": ""})
    for i, t in enumerate(p.get("sector_most_uw") or [], 1):
        contra.append({"month": month, "kind": "sector_underweight", "rank": i,
                       "item": t.get("name", ""), "item_cn": "", "pct": t.get("pct", "")})

    n1 = merge(os.path.join(DATA, "bofa_fms.csv"), HEAD_FIELDS, head, month)
    n2 = merge(os.path.join(DATA, "bofa_fms_crowded.csv"), CROWDED_FIELDS, crowded, month)
    n3 = merge(os.path.join(DATA, "bofa_fms_contrarian.csv"), CONTRA_FIELDS, contra, month)
    print("已写入 %s：拥挤交易 %d 条、反向/尾部风险 %d 条、置信度 %s"
          % (month, len(crowded), len(contra), head[0]["confidence"]))
    print("出处：%s" % head[0]["sources"])
    print("三张表现共 %d / %d / %d 行" % (n1, n2, n3))


if __name__ == "__main__":
    main()
