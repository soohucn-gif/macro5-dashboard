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


def at_date(p, label, date):
    """取某序列在**指定日期**的值，该日无值就返回 None。

    期限结构必须是同一天的横截面，所以这里刻意不向前回退找值 —— 回退会把
    不同交易日的点拼成一条假曲线。
    """
    try:
        i = p["dates"].index(date)
    except ValueError:
        return None
    vals = p["series"].get(label)
    return vals[i] if vals else None


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
    rr = read_csv(os.path.join(DATA, "real_rates.csv"))
    ie = read_csv(os.path.join(DATA, "inflation_expectations.csv"))
    eq = read_csv(os.path.join(DATA, "equity_indices.csv"))
    gold = read_csv(os.path.join(DATA, "gold.csv"))
    btc = read_csv(os.path.join(DATA, "bitcoin.csv"))
    erp = read_csv(os.path.join(DATA, "erp_monthly.csv"))
    erpa = read_csv(os.path.join(DATA, "erp_annual.csv"))
    gpu_rows = read_csv(os.path.join(DATA, "gpu_rental.csv"))
    fms = read_csv(os.path.join(DATA, "bofa_fms.csv"))
    fms_crowded = read_csv(os.path.join(DATA, "bofa_fms_crowded.csv"))
    fms_contra = read_csv(os.path.join(DATA, "bofa_fms_contrarian.csv"))

    # 七档期限，短→长。实际利率三种口径：TIPS 固定期限(5/10/30)、GSW 拟合(2/3)、
    # 派生(1 年，名义 − 克利夫兰联储模型预期)。6 月期没有实际利率，只有名义。
    p_rr = panel(rr, {"dgs6mo": "6月期名义利率",
                      "real1_derived": "1年期实际利率(派生)", "dgs1": "1年期名义利率",
                      "tipsy2": "2年期实际利率", "dgs2": "2年期名义利率",
                      "tipsy3": "3年期实际利率", "dgs3": "3年期名义利率",
                      "dfii5": "5年期实际利率", "dgs5": "5年期名义利率",
                      "dfii10": "10年期实际利率", "dgs10": "10年期名义利率",
                      "dfii30": "30年期实际利率", "dgs30": "30年期名义利率"})
    p_ie = panel(ie, {"be10y": "市场 · 10年盈亏平衡", "fwd5y5y": "市场 · 5年后5年远期",
                      "cleveland_10y": "模型 · 克利夫兰联储10年",
                      "michigan_1y": "消费者 · 密歇根1年",
                      "sce_3y": "消费者 · 纽约联储3年",
                      "sce_5y": "消费者 · 纽约联储5年"}, date_from="2013-06-01")
    p_eq = panel(eq, {"sp500": "标普500", "nasdaq_comp": "纳斯达克综合",
                      "nasdaq_100": "纳斯达克100"})
    p_gold = panel(gold, {"usd_per_oz": "伦敦金 (美元/盎司)"})
    p_btc = panel(btc, {"close": "比特币 (美元)"})
    p_erp = panel(erp, {"erp_t12m": "隐含股权风险溢价", "expected_return": "隐含预期收益率",
                        "tbond_rate": "10年期美债收益率"}, date_from="2008-09-01")

    # ===== ERP 三件套（2026-10-15 与用户确认的汇报口径）=====
    # 只看月度分位会把「利率抬升」误读成「风险偏好极端」：2026-10 的 ERP 3.70%
    # 是 2008 年以来最低（月度分位 0%），但放进 65 年年度分布只是 40% 分位，
    # 除以无风险利率后的比值 0.70 更只有 49% 分位。三个口径必须一起看。
    def pctile(series, cur):
        s_ = sorted(series)
        return round(sum(1 for v in s_ if v < cur) / len(s_) * 100) if s_ else None

    erp_cur = erp[-1] if erp else {}
    m_erp = [f(r["erp_t12m"]) for r in erp if f(r["erp_t12m"]) is not None]
    m_er = [f(r["expected_return"]) for r in erp if f(r["expected_return"]) is not None]
    m_tb = [f(r["tbond_rate"]) for r in erp if f(r["tbond_rate"]) is not None]
    a_erp = [f(r["erp_fcfe"]) * 100 for r in erpa if f(r["erp_fcfe"]) is not None]
    a_ratio = [f(r["erp_over_rf"]) for r in erpa if f(r["erp_over_rf"]) is not None]
    cur_erp, cur_ratio = f(erp_cur.get("erp_t12m")), f(erp_cur.get("erp_over_rf"))

    erp_tables = []
    if cur_erp is not None and m_erp:
        erp_tables = [
            {"title": "月度分位", "note": "当前值在 %s 至今这 %d 个月里的位置。"
                                          "分位越高＝相对这段历史越便宜（补偿越厚）。"
                                          "条长按 0–100%% 绝对刻度画。"
                                          % (erp[0]["date"][:7], len(m_erp)),
             "scale": 100,
             "items": [{"label": "隐含 ERP (T12m) %.2f%%" % cur_erp,
                        "en": "%s 至 %s · %d 个月"
                              % (erp[0]["date"][:7], erp[-1]["date"][:7], len(m_erp)),
                        "pct": pctile(m_erp, cur_erp)}]},
        ]

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
    # 超期就在面板上讲明白，别让人误读成最新。FMS 每月中旬的周二发布，相邻两期最多隔约
    # 5 周，定时任务 16~24 号上网抓。所以按**上一期发布日**算、超过 40 天才报 —— 按月初算
    # 45 天的话，每逢第三个周二才发布的月份，16 号起就会误报好几天。
    fms_stale = ""
    if fms_month:
        try:
            last = datetime.date.fromisoformat(fms[-1].get("release_date") or "")
        except ValueError:                           # 缺发布日（或格式不对）按月中估
            last = datetime.date.fromisoformat(fms_month + "-15")
        age = (TODAY - last).days
        if age > 40:
            fms_stale = ("　⚠️ 最新一期为 %s，距上期发布已 %d 天，"
                         "月度抓取（macro5-fms-monthly）可能没跑成。" % (fms_month, age))
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

    # GPU 上游会整天不放数（2026-10-21 起连续空）。看板必须自己说出来，
    # 否则读者会把几天前的价当成今天的。
    gpu_stale = ""
    if p_gpu["dates"]:
        age = (TODAY - datetime.date.fromisoformat(p_gpu["dates"][-1])).days
        if age >= 3:
            gpu_stale = ("　⚠️ 上游最后放数 %s，已 %d 天未更新（Silicon Data 当期未放数）。"
                         % (p_gpu["dates"][-1], age))

    # 利率期限结构的当期横截面：七档并排看曲线形状。倒挂、陡平、哪一段在动，
    # 看横截面比看 13 条时间序列直观得多。
    # 两个参考日刻意分开：名义取最新交易日，实际取「2 年期有值」的最新交易日
    # —— 美联储 GSW 那个文件比 FRED 滞后约一周，混成一天就是假曲线。
    RATE_TENORS = [("6月", "6月期名义利率", None),
                   ("1年", "1年期名义利率", "1年期实际利率(派生)"),
                   ("2年", "2年期名义利率", "2年期实际利率"),
                   ("3年", "3年期名义利率", "3年期实际利率"),
                   ("5年", "5年期名义利率", "5年期实际利率"),
                   ("10年", "10年期名义利率", "10年期实际利率"),
                   ("30年", "30年期名义利率", "30年期实际利率")]
    nom_date, _ = last_valid(p_rr, "10年期名义利率")
    real_date, _ = last_valid(p_rr, "2年期实际利率")
    rate_tables = []
    if nom_date:
        rate_tables.append({
            "title": "名义利率曲线",
            "note": "%s · FRED DGS 系列" % nom_date,
            "scale": 6,
            "items": [{"label": lab, "pct": at_date(p_rr, nk, nom_date)}
                      for lab, nk, _ in RATE_TENORS]})
    if real_date:
        rate_tables.append({
            "title": "实际利率曲线",
            "note": ("%s · 5/10/30年=TIPS 固定期限，2/3年=美联储 GSW 拟合，"
                     "1年=派生（名义 − 克利夫兰联储模型预期），6月期无此数据"
                     % real_date),
            "scale": 6,
            "items": [{"label": lab + ("*" if lab == "1年" else ""),
                       "pct": (None if rk is None else at_date(p_rr, rk, real_date))}
                      for lab, _, rk in RATE_TENORS]})
        # 盈亏平衡 = 同一天的名义 − 实际。必须同日相减，跨日相减得到的是噪音。
        be_items = []
        for lab, nk, rk in RATE_TENORS:
            nv = at_date(p_rr, nk, real_date)
            rv = None if rk is None else at_date(p_rr, rk, real_date)
            be_items.append({"label": lab + ("*" if lab == "1年" else ""),
                             "pct": (None if None in (nv, rv) else round(nv - rv, 2))})
        rate_tables.append({
            "title": "盈亏平衡通胀（名义 − 实际）",
            "note": "%s · 同日相减。1年期带*的那档是模型口径，与其余档不同源" % real_date,
            "scale": 6, "items": be_items})

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
    # 日频序列超过一周没有新点就标「停更」。抓取「成功」但源头冻住（或被悄悄改版）时
    # fetch_report 全绿，只有看日期才发现得了。正常滞后最多 5 天左右
    # （FRED H.15 次日才发 + 周末 + 假日）。
    STALE_DAYS = 7

    def add_kpi(name, unit, p, label, note, is_rate=False, daily=False):
        d, v = last_valid(p, label)
        if v is None:
            return
        d30, pct30 = change(p, label, 30)
        d365, pct365 = change(p, label, 365)
        k = {"name": name, "unit": unit, "date": d, "value": v, "note": note,
             "is_rate": is_rate,
             "chg_30": d30 if is_rate else pct30,
             "chg_365": d365 if is_rate else pct365}
        age = (TODAY - datetime.date.fromisoformat(d)).days
        if daily and age > STALE_DAYS:
            k["stale_days"] = age
        kpis.append(k)

    add_kpi("30年期实际利率", "%", p_rr, "30年期实际利率", "FRED DFII30 · 日频", True, True)
    add_kpi("30年期名义利率", "%", p_rr, "30年期名义利率", "FRED DGS30 · 日频", True, True)
    add_kpi("10年期实际利率", "%", p_rr, "10年期实际利率", "FRED DFII10 · 日频", True, True)
    add_kpi("10年期名义利率", "%", p_rr, "10年期名义利率", "FRED DGS10 · 日频", True, True)
    add_kpi("5年期实际利率", "%", p_rr, "5年期实际利率", "FRED DFII5 · 日频", True, True)
    add_kpi("5年期名义利率", "%", p_rr, "5年期名义利率", "FRED DGS5 · 日频", True, True)
    # 2 年期是政策预期最敏感的一档。实际利率走美联储 GSW 拟合曲线，比 FRED 滞后约
    # 一周，所以 daily 的陈旧判定对它会常态触发 —— 这里不传 daily，改在 note 里写明。
    add_kpi("2年期实际利率", "%", p_rr, "2年期实际利率",
            "美联储 GSW 拟合 · 日频（较 FRED 滞后约一周）", True)
    add_kpi("2年期名义利率", "%", p_rr, "2年期名义利率", "FRED DGS2 · 日频", True, True)
    add_kpi("市场通胀预期(10年)", "%", p_ie, "市场 · 10年盈亏平衡", "FRED T10YIE · 月末", True)
    add_kpi("消费者通胀预期(5年)", "%", p_ie, "消费者 · 纽约联储5年",
            "纽约联储 SCE 中位数 · 月频", True)
    add_kpi("隐含股权风险溢价", "%", p_erp, "隐含股权风险溢价", "Damodaran · 月频", True)
    add_kpi("标普500", "", p_eq, "标普500", "FRED SP500 · 日频", daily=True)
    add_kpi("纳斯达克综合", "", p_eq, "纳斯达克综合", "FRED NASDAQCOM · 日频", daily=True)
    add_kpi("伦敦金", "美元/盎司", p_gold, "伦敦金 (美元/盎司)", "LBMA 定盘价 · 日频",
            daily=True)
    add_kpi("比特币", "美元", p_btc, "比特币 (美元)", "Coinbase 收盘 · 日频", daily=True)
    # GPU 是价格（美元/小时）不是利率，变动按百分比算 —— 按 pp 算会把 +0.22 美元写成「+0.22pp」
    for lab in sorted(p_gpu["series"]):
        if lab.startswith("H100") or lab.startswith("B200"):
            add_kpi("GPU " + lab, "美元/小时", p_gpu, lab, "Silicon Data · 日频", daily=True)
    add_kpi("FMS 现金水位", "%", p_fms, "现金水位 %", "美银基金经理调查 · 月频", True)
    add_kpi("FMS 头号拥挤交易", "%", p_fms, "头号拥挤交易 拥挤度 %",
            (fms[-1]["top_crowded_trade"] if fms else "") + " · 月频", True)

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "window_start": WINDOW_START,
        "kpis": kpis,
        # ERP 三件套：推送与外部脚本直接读这里，别去反解面板表格的文案
        # ERP 月度分位：推送与外部脚本直读这里
        "erp_pctiles": ({"month": erp_cur.get("date"), "erp": cur_erp,
                         "span_from": erp[0]["date"][:7], "n_months": len(m_erp),
                         "p_monthly": pctile(m_erp, cur_erp)}
                        if (cur_erp is not None and m_erp) else None),
        "panels": {
            "real_rate": {"title": "① 利率期限结构：实际 vs 名义"
                                   "（6月 / 1 / 2 / 3 / 5 / 10 / 30 年）",
                          "sub": "实线是实际利率，虚线是同期限名义利率，同期限同色。"
                                 "两条线之间的竖直间距就是该期限的盈亏平衡通胀 —— "
                                 "名义在涨而间距不变，涨的就是实际利率（钱本身的价格）；"
                                 "间距跟着张开，才是通胀预期在推。"
                                 "默认只画 2 / 5 / 10 / 30 年，点图例可开关任意一档。"
                                 "下方横截面是当期的曲线形状，看倒挂与陡平用它。"
                                 "　实际利率有三种口径，级别不同："
                                 "5 / 10 / 30 年是 TIPS 固定期限收益率，市场直接定价，最硬"
                                 "（30 年期只有 2010-02 起，30 年 TIPS 2001 年停发、2010 年重启）；"
                                 "2 / 3 年是美联储 GSW 的 TIPS 拟合曲线 —— TIPS 固定期限序列"
                                 "最短就是 5 年，短端只有拟合曲线给，代价是该文件比 FRED 滞后约一周；"
                                 "1 年期没有任何市场化来源，只能用名义减克利夫兰联储模型的 1 年"
                                 "通胀预期派生，标了星号；6 月期连派生都做不了，只报名义。"
                                 "　派生口径和市场口径在同一期限上历史是吻合的"
                                 "（2 年期 2016 年以来中位差 −0.05pp），所以 1 年期那个点偏低"
                                 "不是口径毛病：当下克利夫兰模型的近端通胀预期比市场的 2 年"
                                 "盈亏平衡高出约 0.6pp，短端这段落差是这个分歧，不是曲线形状。",
                          "unit": "%", "freq": "日频",
                          "month": nom_date,
                          "tables": rate_tables,
                          "flat": True,          # 曲线没有排名，首行不着强调色
                          "colors": {"6月期名义利率": 0,
                                     "1年期实际利率(派生)": 1, "1年期名义利率": 1,
                                     "2年期实际利率": 2, "2年期名义利率": 2,
                                     "3年期实际利率": 3, "3年期名义利率": 3,
                                     "5年期实际利率": 4, "5年期名义利率": 4,
                                     "10年期实际利率": 5, "10年期名义利率": 5,
                                     "30年期实际利率": 6, "30年期名义利率": 6},
                          "dash": ["6月期名义利率", "1年期名义利率", "2年期名义利率",
                                   "3年期名义利率", "5年期名义利率", "10年期名义利率",
                                   "30年期名义利率"],
                          "hidden": ["6月期名义利率", "1年期实际利率(派生)",
                                     "1年期名义利率", "3年期实际利率", "3年期名义利率"],
                          "source": "FRED · DGS6MO/1/2/3/5/10/30（名义）· DFII5/10/30（实际）"
                                    "；美联储 GSW feds200805（2/3 年实际）"
                                    "；FRED EXPINF1YR（1 年派生）",
                          "data": p_rr},
            "infexp": {"title": "② 通胀预期：市场 vs 消费者",
                       "sub": "两个口径长期系统性打架，必须分开看。市场（TIPS 盈亏平衡）是"
                              "投资者真金白银押出来的，常年 2%出头；消费者（问卷）对食品、"
                              "油价、房租这些高频可见价格更敏感，常年高出 1 个百分点以上。"
                              "「5年后5年远期」剔除了未来五年的短期通胀噪音，是长期预期最干净的读数。",
                       "unit": "%", "freq": "月频",
                       "source": "FRED T10YIE / T5YIFR / EXPINF10YR / MICH ＋ 纽约联储 SCE",
                       "data": p_ie},
            "erp": {"title": "③ 隐含股权风险溢价 (ERP)",
                    "sub": "Damodaran 以当前指数点位反解出的市场隐含风险补偿。"
                           "隐含预期收益率 = 无风险利率 + ERP。"
                           "下方给出当前值在 2008-09 以来的月度分位。"
                           "注意这段历史只有 18 年、且起点正是雷曼危机，"
                           "低分位未必等于「极端乐观」—— 同期 10 年期美债"
                           "从 0.5% 涨到 5.3%，利率抬升本身就会压薄 ERP。",
                    "unit": "%", "freq": "月频",
                    "month": (erp[-1]["date"][:7] if erp else None),
                    "tables": erp_tables,
                    "source": "NYU Stern · Damodaran ERPbymonth（月度）", "data": p_erp},
            "equity": {"title": "④ 标普500 与纳斯达克",
                       "sub": "美股两大宽基指数收盘点位。", "unit": "点", "freq": "日频",
                       "source": "FRED · SP500 / NASDAQCOM / NASDAQ100", "data": p_eq},
            "gold": {"title": "⑤ 黄金", "sub": "伦敦金银市场协会(LBMA)下午定盘价。",
                     "unit": "美元/盎司", "freq": "日频",
                     "source": "LBMA 官方定盘价", "data": p_gold},
            "bitcoin": {"title": "⑥ 比特币", "sub": "Coinbase BTC-USD 日收盘价，对数坐标。",
                        "unit": "美元", "freq": "日频", "log": True,
                        "source": "Coinbase Exchange", "data": p_btc},
            "gpu": {"title": "⑦ GPU 租赁价格指数",
                    "sub": gpu_stale + "Silicon Data 各卡型小时租赁基准价。公开层只放出滚动 7 天窗口，"
                           "本仓库每日抓取累积，历史自 2026-08-23 起在此逐日生长。",
                    "unit": "美元/小时", "freq": "日频",
                    "source": "Silicon Data · SiliconIndex", "data": p_gpu},
            "fms": {"title": "⑧ 美银基金经理调查：拥挤交易与反向交易",
                    "sub": "BofA Global FMS 月度问卷。现金水位是老牌反向指标"
                           "（<4.0% 触发 sell signal）；拥挤度看的是共识有多挤，"
                           "反向交易看的是没人站的那一边。" + fms_stale,
                    "unit": "%", "freq": "月频", "month": fms_month,
                    "tables": fms_tables,
                    "source": "BofA Global Fund Manager Survey（派生数字口径，不含原图）",
                    "data": p_fms},
            "normalized": {"title": "⑨ 跨资产归一对比",
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
        date = k["date"] + (" ⚠ %d 天没更新" % k["stale_days"] if k.get("stale_days") else "")
        lines.append("| %s | %s | %s | %s | %s |"
                     % (k["name"], val, date, fmt(k["chg_30"]), fmt(k["chg_365"])))
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
