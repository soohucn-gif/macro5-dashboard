#!/usr/bin/env python3
"""把 data/*.csv 汇总成 dashboard.json + 自包含的 index.html + 当日文本快照。

输出：
  data/dashboard.json     看板用的十年窗口数据（HTML 内联同一份）
  index.html              自包含单文件看板（GitHub Pages 直接托管）
  data/latest.md          当日/当月文本快照（推送用）
"""
import csv
import datetime
import json
import os

from common import DATA, ROOT, read_csv

TODAY = datetime.date.today()
WINDOW_START = (TODAY - datetime.timedelta(days=3660)).isoformat()   # 约 10 年


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def panel(rows, cols, date_from=WINDOW_START, round_to=2):
    """把 CSV 行列表压成 {dates, series}，共享日期轴，缺测为 null。"""
    rows = [r for r in rows if r["date"] >= date_from]
    dates = [r["date"] for r in rows]
    series = {}
    for key, label in cols.items():
        vals = []
        for r in rows:
            v = f(r.get(key))
            vals.append(None if v is None else round(v, round_to))
        if any(v is not None for v in vals):
            series[label] = vals
    return {"dates": dates, "series": series}


def last_valid(p, label):
    """返回 (日期, 值)，取该序列最后一个非空点。"""
    vals = p["series"].get(label) or []
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] is not None:
            return p["dates"][i], vals[i]
    return None, None


def change(p, label, days):
    """相对 N 个自然日前最近一个有效点的变动 (绝对值差, 百分比)。"""
    d, cur = last_valid(p, label)
    if cur is None:
        return None, None
    target = (datetime.date.fromisoformat(d) - datetime.timedelta(days=days)).isoformat()
    vals, dates = p["series"][label], p["dates"]
    prev = None
    for i, dt in enumerate(dates):
        if dt <= target and vals[i] is not None:
            prev = vals[i]
    if prev in (None, 0):
        return None, None
    return round(cur - prev, 2), round((cur / prev - 1) * 100, 2)


def build():
    rr = read_csv(os.path.join(DATA, "real_rate_10y.csv"))
    eq = read_csv(os.path.join(DATA, "equity_indices.csv"))
    gold = read_csv(os.path.join(DATA, "gold.csv"))
    btc = read_csv(os.path.join(DATA, "bitcoin.csv"))
    erp = read_csv(os.path.join(DATA, "erp_monthly.csv"))
    gpu_rows = read_csv(os.path.join(DATA, "gpu_rental.csv"))
    fms = read_csv(os.path.join(DATA, "bofa_fms.csv"))
    fms_crowded = read_csv(os.path.join(DATA, "bofa_fms_crowded.csv"))
    fms_contra = read_csv(os.path.join(DATA, "bofa_fms_contrarian.csv"))

    p_rr = panel(rr, {"dfii10": "10年期实际利率 (TIPS)", "dgs10": "10年期名义利率",
                      "t10yie": "10年期盈亏平衡通胀"})
    p_eq = panel(eq, {"sp500": "标普500", "nasdaq_comp": "纳斯达克综合",
                      "nasdaq_100": "纳斯达克100"})
    p_gold = panel(gold, {"usd_per_oz": "伦敦金 (美元/盎司)"})
    p_btc = panel(btc, {"close": "比特币 (美元)"})
    p_erp = panel(erp, {"erp_t12m": "隐含股权风险溢价", "expected_return": "隐含预期收益率",
                        "tbond_rate": "10年期美债收益率"}, date_from="2008-09-01")

    # GPU：长表转宽表，每条 (卡型, 档位) 一列
    gdates = sorted({r["date"] for r in gpu_rows})
    keys = sorted({(r["gpu"], r["segment"]) for r in gpu_rows})
    lookup = {(r["date"], r["gpu"], r["segment"]): f(r["usd_per_hr"]) for r in gpu_rows}
    seg_cn = {"neo-cloud": "Neo-Cloud", "hyperscaler": "超大规模云"}
    p_gpu = {"dates": gdates, "series": {}}
    for gpu, seg in keys:
        label = "%s · %s" % (gpu, seg_cn.get(seg, seg))
        p_gpu["series"][label] = [lookup.get((d, gpu, seg)) for d in gdates]

    # 美银 FMS：月频，month 列补成月初日期以复用同一套图表逻辑
    fms_rows = [dict(r, date=r["month"] + "-01") for r in fms]
    p_fms = panel(fms_rows, {"cash_pct": "现金水位 %",
                             "top_crowded_pct": "头号拥挤交易 拥挤度 %",
                             "top_tail_risk_pct": "头号尾部风险 占比 %",
                             "sentiment_score": "情绪分 (0-10)"}, date_from="1900-01-01")

    def fms_list(rows, pred, limit=8):
        items = sorted([r for r in rows if pred(r)], key=lambda r: int(r["rank"]))[:limit]
        out = []
        for r in items:
            label = r.get("trade_cn") or r.get("item_cn") or r.get("trade") or r.get("item")
            en = r.get("trade") or r.get("item") or ""
            pv = f(r.get("pct"))
            out.append({"label": label, "en": en if en != label else "",
                        "pct": None if pv is None else round(pv, 1)})
        return out

    fms_month = fms[-1]["month"] if fms else None
    # 本类由本机按月同步（云端读不到私有存档），超期就在面板上讲明白，别让人误读成最新
    fms_stale = ""
    if fms_month:
        age = (TODAY - datetime.date.fromisoformat(fms_month + "-01")).days
        if age > 45:
            fms_stale = ("　⚠️ 最新一期为 %s，距今 %d 天，本机月度同步可能没跑成。"
                         % (fms_month, age))
    else:
        fms_stale = "　⚠️ 尚未同步到任何一期数据。"
    fms_tables = []
    if fms_month:
        fms_tables = [
            {"title": "最拥挤交易", "note": "「你认为当前最拥挤的交易是什么」的答案占比",
             "items": fms_list(fms_crowded, lambda r: r["month"] == fms_month)},
            {"title": "最大尾部风险", "note": "受访者票选的头号风险",
             "items": fms_list(fms_contra,
                               lambda r: r["month"] == fms_month and r["kind"] == "tail_risk")},
            {"title": "官方反向交易", "note": "BofA 每期 Bottom Line 给出的 Contrarian Trades",
             "items": fms_list(fms_contra,
                               lambda r: r["month"] == fms_month and r["kind"] == "contrarian")},
            {"title": "最被低配 · 资产与地区", "note": "基金经理躲得最远的大类与市场",
             "items": fms_list(fms_contra, lambda r: r["month"] == fms_month
                               and r["kind"] == "most_underweight")},
            {"title": "最被低配 · 行业", "note": "行业净超配百分比，负值即净低配",
             "items": fms_list(fms_contra, lambda r: r["month"] == fms_month
                               and r["kind"] == "sector_underweight")},
        ]
        fms_tables = [t for t in fms_tables if t["items"]]

    # 跨资产归一：十年窗口内各自首个有效值 = 100
    def rebase(p, label, out_label):
        vals = p["series"].get(label)
        if not vals:
            return None
        base = next((v for v in vals if v), None)
        if not base:
            return None
        return {"dates": p["dates"], "label": out_label,
                "values": [None if v is None else round(v / base * 100, 1) for v in vals]}

    norm_parts = [rebase(p_eq, "标普500", "标普500"),
                  rebase(p_eq, "纳斯达克综合", "纳斯达克综合"),
                  rebase(p_gold, "伦敦金 (美元/盎司)", "黄金"),
                  rebase(p_btc, "比特币 (美元)", "比特币")]
    all_dates = sorted({d for part in norm_parts if part for d in part["dates"]})
    p_norm = {"dates": all_dates, "series": {}}
    for part in norm_parts:
        if not part:
            continue
        m = dict(zip(part["dates"], part["values"]))
        p_norm["series"][part["label"]] = [m.get(d) for d in all_dates]

    kpis = []

    def add_kpi(name, unit, p, label, note, is_rate=False):
        d, v = last_valid(p, label)
        if v is None:
            return
        d1, pct1 = change(p, label, 1 if not is_rate else 7)
        d30, pct30 = change(p, label, 30)
        d365, pct365 = change(p, label, 365)
        kpis.append({"name": name, "unit": unit, "date": d, "value": v, "note": note,
                     "is_rate": is_rate,
                     "chg_30": d30 if is_rate else pct30,
                     "chg_365": d365 if is_rate else pct365})

    add_kpi("10年期实际利率", "%", p_rr, "10年期实际利率 (TIPS)", "FRED DFII10 · 日频", True)
    add_kpi("隐含股权风险溢价", "%", p_erp, "隐含股权风险溢价", "Damodaran · 月频", True)
    add_kpi("标普500", "", p_eq, "标普500", "FRED SP500 · 日频")
    add_kpi("纳斯达克综合", "", p_eq, "纳斯达克综合", "FRED NASDAQCOM · 日频")
    add_kpi("伦敦金", "美元/盎司", p_gold, "伦敦金 (美元/盎司)", "LBMA 定盘价 · 日频")
    add_kpi("比特币", "美元", p_btc, "比特币 (美元)", "Coinbase 收盘 · 日频")
    for lab in sorted(p_gpu["series"]):
        if lab.startswith("H100") or lab.startswith("B200"):
            add_kpi("GPU " + lab, "美元/小时", p_gpu, lab, "Silicon Data · 日频", True)
    add_kpi("FMS 现金水位", "%", p_fms, "现金水位 %", "美银基金经理调查 · 月频", True)
    add_kpi("FMS 头号拥挤交易", "%", p_fms, "头号拥挤交易 拥挤度 %",
            (fms[-1]["top_crowded_trade"] if fms else "") + " · 月频", True)

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "window_start": WINDOW_START,
        "kpis": kpis,
        "panels": {
            "real_rate": {"title": "① 10年期实际利率",
                          "sub": "名义利率 − 预期通胀率。TIPS 收益率是市场对该差值的直接定价，"
                                 "也是一切风险资产的贴现率锚。",
                          "unit": "%", "freq": "日频",
                          "source": "FRED · DFII10 / DGS10 / T10YIE", "data": p_rr},
            "erp": {"title": "② 隐含股权风险溢价 (ERP)",
                    "sub": "Damodaran 以当前指数点位反解出的市场隐含风险补偿。"
                           "隐含预期收益率 = 无风险利率 + ERP。",
                    "unit": "%", "freq": "月频",
                    "source": "NYU Stern · Damodaran ERPbymonth", "data": p_erp},
            "equity": {"title": "③ 标普500 与纳斯达克",
                       "sub": "美股两大宽基指数收盘点位。", "unit": "点", "freq": "日频",
                       "source": "FRED · SP500 / NASDAQCOM / NASDAQ100", "data": p_eq},
            "gold": {"title": "④ 黄金", "sub": "伦敦金银市场协会(LBMA)下午定盘价。",
                     "unit": "美元/盎司", "freq": "日频",
                     "source": "LBMA 官方定盘价", "data": p_gold},
            "bitcoin": {"title": "⑤ 比特币", "sub": "Coinbase BTC-USD 日收盘价，对数坐标。",
                        "unit": "美元", "freq": "日频", "log": True,
                        "source": "Coinbase Exchange", "data": p_btc},
            "gpu": {"title": "⑥ GPU 租赁价格指数",
                    "sub": "Silicon Data 各卡型小时租赁基准价。公开层只放出滚动 7 天窗口，"
                           "本仓库每日抓取累积，历史自 2026-08-23 起在此逐日生长。",
                    "unit": "美元/小时", "freq": "日频",
                    "source": "Silicon Data · SiliconIndex", "data": p_gpu},
            "fms": {"title": "⑦ 美银基金经理调查：拥挤交易与反向交易",
                    "sub": "BofA Global FMS 月度问卷。现金水位是老牌反向指标"
                           "（<4.0% 触发 sell signal）；拥挤度看的是共识有多挤，"
                           "反向交易看的是没人站的那一边。" + fms_stale,
                    "unit": "%", "freq": "月频", "month": fms_month,
                    "tables": fms_tables,
                    "source": "BofA Global Fund Manager Survey（派生数字口径，不含原图）",
                    "data": p_fms},
            "normalized": {"title": "⑧ 跨资产归一对比",
                           "sub": "所选区间的起点 = 100，对数坐标；切换区间基期会跟着走。"
                                  "看的是相对赔率，不是绝对价格。",
                           "unit": "指数 (区间起点=100)", "freq": "日频", "log": True,
                           "rebase": True, "source": "由上述各源计算", "data": p_norm},
        },
    }
    with open(os.path.join(DATA, "dashboard.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    return out


# ------------------------------------------------------------------ 文本快照
def write_summary(d):
    lines = ["# 五大类数据看板 · 快照 %s" % TODAY.isoformat(), "",
             "生成时间 (UTC)：%s" % d["generated_at"], "",
             "| 指标 | 最新值 | 数据日期 | 30日变动 | 一年变动 |",
             "|---|---:|---|---:|---:|"]
    for k in d["kpis"]:
        unit = (" " + k["unit"]) if k["unit"] and k["unit"] != "%" else k["unit"]
        val = "%s%s" % (("{:,.2f}".format(k["value"]) if k["value"] >= 100
                         else "%.2f" % k["value"]), unit)

        def fmt(x):
            if x is None:
                return "—"
            return ("%+.2f pp" % x) if k["is_rate"] else ("%+.1f%%" % x)
        lines.append("| %s | %s | %s | %s | %s |"
                     % (k["name"], val, k["date"], fmt(k["chg_30"]), fmt(k["chg_365"])))
    lines += ["", "## 数据覆盖", "",
              "| 模块 | 频率 | 起点 | 最新 | 点数 |", "|---|---|---|---|---:|"]
    for key, p in d["panels"].items():
        dd = p["data"]["dates"]
        if not dd:
            continue
        lines.append("| %s | %s | %s | %s | %d |"
                     % (p["title"], p["freq"], dd[0], dd[-1], len(dd)))
    lines += ["", "> 完整历史见 `data/*.csv`；看板见 `index.html`。"]
    txt = "\n".join(lines) + "\n"
    with open(os.path.join(DATA, "latest.md"), "w", encoding="utf-8") as fh:
        fh.write(txt)
    # 同时归档一份当日快照，留审计痕迹
    daily_dir = os.path.join(DATA, "daily")
    os.makedirs(daily_dir, exist_ok=True)
    with open(os.path.join(daily_dir, TODAY.isoformat() + ".md"), "w",
              encoding="utf-8") as fh:
        fh.write(txt)
    return txt


if __name__ == "__main__":
    d = build()
    write_summary(d)
    from render_html import render
    render(d)
    import real_rate_readout
    real_rate_readout.main()
    print("built: index.html, data/dashboard.json, data/latest.md")
