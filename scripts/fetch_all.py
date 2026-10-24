#!/usr/bin/env python3
"""五大类数据抓取。每类独立 try，一类挂掉不影响其余，最后汇总退出码。

产出（全部 merge 语义，绝不丢历史）：
  data/real_rates.csv      6月/1/2/3/5/10/30年期名义利率与实际利率   日频  FRED + 美联储GSW
  data/inflation_expectations.csv  通胀预期：市场 vs 消费者         月频  FRED + 纽约联储
  data/equity_indices.csv  标普500 / 纳指综合 / 纳指100             日频  FRED
  data/gold.csv            LBMA 伦敦金定盘价 USD/oz（主）/ gold-api.com XAU现货（备）  日频
  data/bitcoin.csv         BTC-USD 日收盘                           日频  Coinbase
  data/gpu_rental.csv      H100/H200/A100/B200/MI300X 租赁指数      日频  Silicon Data
  data/erp_monthly.csv     Damodaran 隐含股权风险溢价               月频  NYU Stern

用法：
  python3 scripts/fetch_all.py            # 增量（日常）
  python3 scripts/fetch_all.py --full     # 全量回补（首次运行）
"""
import datetime
import functools
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

from common import DATA, http_get, http_get_json, merge_csv, parse_fred_csv, read_csv

TODAY = datetime.date.today()
FULL = "--full" in sys.argv


# ------------------------------------------------------- 1. 实际利率期限结构
REAL_SERIES = {"dfii5": "DFII5", "dfii10": "DFII10", "dfii30": "DFII30",
               "dgs6mo": "DGS6MO", "dgs1": "DGS1", "dgs2": "DGS2", "dgs3": "DGS3",
               "dgs5": "DGS5", "dgs10": "DGS10", "dgs30": "DGS30",
               "t5yie": "T5YIE", "t10yie": "T10YIE", "t5yifr": "T5YIFR"}

# 美联储 GSW 的 TIPS 拟合曲线（Gurkaynak-Sack-Wright，staff 研究数据，非官方统计发布）。
# 要它只为一件事：**2 年和 3 年期的实际利率**。TIPS 固定期限序列最短就是 5 年，
# DFII2 / DFII3 在 FRED 根本不存在，短端实际利率只有这条拟合曲线给得出。
# 口径差已量过（2016 年以来）：TIPSY05 − DFII5 中位 −0.017pp、p95 0.11pp，
# 零息拟合与附息固定期限的差小到可以同图并列。
GSW_TIPS_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200805.csv"
GSW_COLS = {"tipsy2": "TIPSY02", "tipsy3": "TIPSY03",
            "bkeven2": "BKEVEN02", "bkeven3": "BKEVEN03"}
# TIPSY + BKEVEN 应当重建出同期限名义利率；实测与 DGS2/DGS3 中位差 0.000pp、p95 0.06pp。
# 超过 0.30pp 就不是口径差，是列对错了或文件改版。
GSW_CHECK_THR = 0.30
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


@functools.lru_cache(maxsize=None)
def _fred(sid):
    """FRED 序列 → [(date, float)]。同一轮里 T5YIE/T10YIE/T5YIFR 利率表和通胀表都要用，
    缓存住只下一次。"""
    return http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + sid,
                    browser_ua=False, parse=lambda raw: parse_fred_csv(raw, sid))


def _zip(raw):
    """xlsx 正文 → ZipFile；回来的是错误页时 BadZipFile 会让 http_get 重试。"""
    return zipfile.ZipFile(io.BytesIO(raw))


def _gsw_header(raw):
    """GSW CSV 开头若干行是免责声明，表头靠 TIPSY02 认，不写死行号。→ {字段: 列号}"""
    txt = raw.decode("utf-8", errors="ignore").splitlines()
    hdr = next((l for l in txt if "TIPSY02" in l and "Date" in l), None)
    if hdr is None:
        raise ValueError("GSW: 没找到表头（取回的多半是错误页）")
    cols = [c.strip() for c in hdr.split(",")]
    idx = {k: cols.index(v) for k, v in GSW_COLS.items() if v in cols}
    if len(idx) != len(GSW_COLS):
        raise ValueError("GSW 表头缺列：%s" % sorted(set(GSW_COLS) - set(idx)))
    return idx


def _gsw_rows(raw, idx):
    """GSW CSV（整份或 Range 取回的尾段）→ {date: {tipsy2, tipsy3, bkeven2, bkeven3}}。

    只认列 0 是 ISO 日期的行，于是免责声明、表头、以及 Range 尾段开头那条
    半截记录都会被自然丢掉，不用特判取回来的是整份还是片段。
    """
    out = {}
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        a = line.split(",")
        d = a[0].strip()
        if not _ISO.fullmatch(d):
            continue
        rec = {}
        for k, j in idx.items():
            v = a[j].strip() if j < len(a) else ""
            if v and v.upper() != "NA":
                try:
                    rec[k] = round(float(v), 2)
                except ValueError:
                    pass
        if rec:
            out[d] = rec
    if not out:
        raise ValueError("GSW: 片段里没有可用数据行")
    return out


def _gsw_tips():
    """取 GSW 的 2/3 年期实际利率与盈亏平衡。

    整份 15MB，日更没必要每天拖一遍：先 Range 取前 80KB 定列号，再取尾部 2MB
    （约覆盖最近三年）。服务器不支持 Range 就会返回 200 整份，`_gsw_rows` 照样
    解析得了，不用特判。本地还没有 2 年期实际利率时必须整份取 —— 否则历史只会
    从最近三年开始长，`--full` 也就白加了。
    """
    have = any(r.get("tipsy2") for r in read_csv(os.path.join(DATA, "real_rates.csv")))
    if FULL or not have:
        return http_get(GSW_TIPS_URL, timeout=180,
                        parse=lambda raw: _gsw_rows(raw, _gsw_header(raw)))
    idx = http_get(GSW_TIPS_URL, headers={"Range": "bytes=0-80000"}, parse=_gsw_header)
    return http_get(GSW_TIPS_URL, headers={"Range": "bytes=-2000000"},
                    parse=lambda raw: _gsw_rows(raw, idx))


def _gsw_selfcheck(rows):
    """TIPSY + BKEVEN 必须重建出 FRED 的同期限名义利率，否则宁可报错也不入库。

    容忍零星不符（节假日日历差、FRED 事后修订），但列错位会让近乎每天都超阈值。
    """
    bad = []
    for r in rows[-250:]:
        for t in ("2", "3"):
            real, be, nom = r.get("tipsy" + t), r.get("bkeven" + t), r.get("dgs" + t)
            if None in (real, be, nom):
                continue
            if abs(real + be - nom) > GSW_CHECK_THR:
                bad.append((r["date"], t + "y", round(real + be - nom, 3)))
    if len(bad) > 5:
        raise RuntimeError("GSW 与 FRED 名义利率对不上：近 250 个交易日 %d 次超 %.2fpp，"
                           "前几例 %s —— 八成是文件改版或列错位" % (len(bad), GSW_CHECK_THR, bad[:3]))


def fetch_real_rate():
    """名义与实际利率的完整期限结构：6月 / 1 / 2 / 3 / 5 / 10 / 30 年。

    **名义**七档齐全，全部来自 FRED 的 DGS 系列，日频。

    **实际利率分三种口径，不能混为一谈**：
      · 5 / 10 / 30 年 —— DFII5/10/30，TIPS 固定期限收益率，市场直接定价，最硬。
        DFII30 只有 2010-02 起：30 年 TIPS 2001 年停发、2010 年才重启。
      · 2 / 3 年 —— 美联储 GSW 的 TIPS 拟合曲线（见 GSW_TIPS_URL）。TIPS 固定期限
        序列最短就是 5 年，短端只有拟合曲线给。日频，但该文件比 FRED 滞后约一周。
      · 1 年 —— 没有任何市场化来源，只能派生 = 名义 − 克利夫兰联储模型的 1 年通胀
        预期（月频，当月值套到当月每一天）。单独叫 real1_derived，面板里另行标注。
      · 6 月 —— 同样只能派生，而且**连配套期限的预期都没有**：克利夫兰联储那套
        最短就是 1 年。所以 real6mo_derived = DGS6MO − EXPINF1YR，用 1 年预期近似
        6 个月。误差量级实测约 0.1pp（EXPINF1YR 与 EXPINF2YR 2016 年以来 |差| 中位
        0.16pp，折半），通胀拐点处可到 0.3pp。要的是政策松紧的方向，不是小数点。

    派生那两档（6 月、1 年）在表里不参与盈亏平衡：名义减实际恰好等于当初减去的
    那个预期，是恒等式不是读数。

    同表存盈亏平衡通胀：5/10 年用 FRED 的 T5YIE/T10YIE，2/3 年用 GSW 的 BKEVEN，
    于是每一档都能逐日验算「实际 ≈ 名义 − 盈亏平衡」。T5YIFR 是「5年后的5年」远期
    盈亏平衡，剔除了未来五年的短期通胀噪音，是市场长期通胀预期最干净的读数。
    """
    merged = {}
    for col, sid in REAL_SERIES.items():
        for d, v in _fred(sid):
            merged.setdefault(d, {"date": d})[col] = round(v, 2)
    for d, rec in _gsw_tips().items():
        merged.setdefault(d, {"date": d}).update(rec)
    # 1 年期派生实际利率用的月频预期：键按年月取，当月每一天都用同一个预期值
    exp1 = {d[:7]: v for d, v in _fred("EXPINF1YR")}
    rows = []
    for d in sorted(merged):
        r = merged[d]
        for tenor, be in (("5", "t5yie"), ("10", "t10yie")):
            nom, brk = r.get("dgs" + tenor), r.get(be)
            if nom is not None and brk is not None:
                r["implied_real" + tenor] = round(nom - brk, 2)
        e1 = exp1.get(d[:7])
        if e1 is not None:
            if r.get("dgs1") is not None:
                r["real1_derived"] = round(r["dgs1"] - e1, 2)
            if r.get("dgs6mo") is not None:
                r["real6mo_derived"] = round(r["dgs6mo"] - e1, 2)
        rows.append(r)
    _gsw_selfcheck(rows)
    fields = ["date", "dgs6mo", "dgs1", "dgs2", "dgs3", "dgs5", "dgs10", "dgs30",
              "real6mo_derived", "real1_derived",
              "tipsy2", "tipsy3", "dfii5", "dfii10", "dfii30",
              "bkeven2", "bkeven3", "t5yie", "t10yie", "t5yifr",
              "implied_real5", "implied_real10"]
    n, added = merge_csv(os.path.join(DATA, "real_rates.csv"), fields, ("date",), rows)
    return "real_rates", n, added, rows[-1]["date"] if rows else ""


# ------------------------------------------------ 1b. 通胀预期：市场 vs 消费者
FRED_MONTHLY_IE = {"be30y": "T30YIEM", "cleveland_1y": "EXPINF1YR",
                   "cleveland_5y": "EXPINF5YR", "cleveland_10y": "EXPINF10YR",
                   "cleveland_30y": "EXPINF30YR", "michigan_1y": "MICH"}
SCE_URL = ("https://www.newyorkfed.org/medialibrary/interactives/sce/sce/"
           "downloads/data/FRBNY-SCE-Data.xlsx")
# 2026-10 纽约联储删掉了独立工作表「Five-year ahead Infl Exp」，把五年中位数
# 并进 Inflation expectations。表头原文如下；它左边紧挨着一列空列，不能写死列号。
SCE_FIVE_YEAR_HEADER = "Median five-year ahead expected inflation rate"
SCE_FIVE_YEAR_SHEET = "Five-year ahead Infl Exp"


def _norm_header(v):
    return " ".join(str(v).replace("\n", " ").split()).lower()


def _is_five_year_median_header(v):
    """认五年期中位数预期列，排除分位数、点预测和人口分组表头。"""
    s = _norm_header(v)
    if not s:
        return False
    if s == _norm_header(SCE_FIVE_YEAR_HEADER):
        return True
    if not s.startswith("median five-year ahead expected"):
        return False
    return not any(w in s for w in ("percentile", "point", "uncertainty", "demographic"))


def _sheet_rows(z, sheet_name, required=True):
    """从 xlsx 里按表名取出按列对齐的二维字符串数组（共享字符串已解引用）。

    单元格按 r 属性落列，缺的列补空串，避免前导空单元格把后面的字段挤偏。
    工作表不存在时：required=False 返回 None，否则抛 RuntimeError。
    """
    wb = z.read("xl/workbook.xml").decode("utf-8", errors="ignore")
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                           z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "ignore")))
    tgt = next((rels[r] for n, r in
                re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb)
                if n == sheet_name), None)
    if tgt is None:
        if not required:
            return None
        raise RuntimeError("xlsx 里找不到工作表 %r" % sheet_name)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(NS + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si")]
    path = "xl/" + tgt.lstrip("/").replace("xl/", "", 1)
    out = []
    for row in ET.fromstring(z.read(path)).find(NS + "sheetData").findall(NS + "row"):
        by_col = {}
        for c in row.findall(NS + "c"):
            col = _col_num(c.get("r") or "") - 1
            if col < 0:
                continue
            v = c.find(NS + "v")
            if v is None or v.text is None:
                val = ""
            else:
                val = shared[int(v.text)] if c.get("t") == "s" else v.text
            by_col[col] = val
        if not by_col:
            out.append([])
            continue
        dense = [""] * (max(by_col) + 1)
        for i, val in by_col.items():
            dense[i] = val
        out.append(dense)
    return out


def _header_col(rows, pred, scan=20):
    """在表头区域找第一列满足 pred 的 0-based 列号，找不到返回 None。"""
    for row in rows[:scan]:
        for idx, val in enumerate(row):
            if pred(val):
                return idx
    return None


def _ym(v):
    """SCE 用 '202607' 这种 YYYYMM，统一成月初日期。"""
    s = str(v).strip()
    if not re.fullmatch(r"\d{6}", s):
        return None
    return "%s-%s-01" % (s[:4], s[4:])


def fetch_inflation_expectations():
    """通胀预期的两个世界，放同一张表里好直接对照。

    **市场口径**（投资者用真金白银押的）：TIPS 盈亏平衡通胀 5/10/30 年、5年后5年远期。
    **模型口径**：克利夫兰联储把市场价格与调查数据一起塞进模型算出的 1/5/10/30 年期望。
    **消费者口径**（问卷问出来的）：密歇根大学 1 年期、纽约联储 SCE 1/3/5 年中位数。

    两个口径长期系统性地不一样 —— 消费者常年高出市场 1 个百分点以上，因为普通人对
    食品、油价、房租这些高频可见价格更敏感，而市场定价的是一篮子 CPI 的加权平均。
    看的时候要分开看，不能混成一个「通胀预期」。
    """
    merged = {}
    for col, sid in FRED_MONTHLY_IE.items():
        for d, v in _fred(sid):
            merged.setdefault(d, {"date": d})[col] = round(v, 2)

    # 日频的盈亏平衡取每月最后一个有效值，好跟月频序列并排
    daily = {}
    for col, sid in (("be5y", "T5YIE"), ("be10y", "T10YIE"), ("fwd5y5y", "T5YIFR")):
        for d, v in _fred(sid):
            daily.setdefault(d[:7] + "-01", {})[col] = round(v, 2)
    for m, vals in daily.items():
        merged.setdefault(m, {"date": m}).update(vals)

    # 纽约联储消费者预期调查（SCE）—— 公开下载，无需授权。
    # 1y/3y 仍在 Inflation expectations 的第 2、3 列（0-based 1、2）。
    # 5y 优先读同一张表上的五年中位数列；该列为空的月份留空，不拿别的列补。
    # 旧表名如果重新出现，只在新列找不到时才用，缺表不再让整类失败。
    z = http_get(SCE_URL, parse=_zip)
    ie = _sheet_rows(z, "Inflation expectations")
    _fill_sce(merged, ie, {1: "sce_1y", 2: "sce_3y"})
    note = _fill_sce_5y(z, ie, merged)

    rows = [merged[d] for d in sorted(merged)]
    fields = ["date", "be5y", "be10y", "be30y", "fwd5y5y",
              "cleveland_1y", "cleveland_5y", "cleveland_10y", "cleveland_30y",
              "michigan_1y", "sce_1y", "sce_3y", "sce_5y"]
    n, added = merge_csv(os.path.join(DATA, "inflation_expectations.csv"),
                         fields, ("date",), rows)
    last = rows[-1]["date"] if rows else ""
    if note:
        return "inflation_expectations", n, added, last, note
    return "inflation_expectations", n, added, last


def _fill_sce(merged, rows, cols):
    """把 SCE 表里指定列写进 merged。空单元格跳过，留给 merge 写成空。"""
    for row in rows:
        d = _ym(row[0] if row else "")
        if d is None:
            continue
        for idx, col in cols.items():
            if idx >= len(row) or row[idx] in ("", None):
                continue
            try:
                merged.setdefault(d, {"date": d})[col] = round(float(row[idx]), 2)
            except ValueError:
                pass


def _fill_sce_5y(z, ie_rows, merged):
    """写入 sce_5y。成功读到新列时返回空串；只能走旧表或两处都没有时返回说明。

    新列、旧表都不在时保留 CSV 里已有的 sce_5y，避免 merge 把历史整列抹掉。
    """
    col = _header_col(ie_rows, _is_five_year_median_header)
    if col is not None:
        _fill_sce(merged, ie_rows, {col: "sce_5y"})
        return ""
    old = _sheet_rows(z, SCE_FIVE_YEAR_SHEET, required=False)
    if old is not None:
        legacy_col = _header_col(old, _is_five_year_median_header)
        if legacy_col is None:
            legacy_col = 1
        _fill_sce(merged, old, {legacy_col: "sce_5y"})
        return "sce_5y 来自旧表 %s" % SCE_FIVE_YEAR_SHEET
    _keep_existing_sce_5y(merged)
    return "sce_5y 未更新（Inflation expectations 无五年中位数列，旧表也不在）"


def _keep_existing_sce_5y(merged):
    """新源没有五年列时，把 CSV 里已有的 sce_5y 抄回 merged，防止被空值覆盖。"""
    for r in read_csv(os.path.join(DATA, "inflation_expectations.csv")):
        d = (r.get("date") or "").strip()
        v = (r.get("sce_5y") or "").strip()
        if not d or not v:
            continue
        slot = merged.setdefault(d, {"date": d})
        if slot.get("sce_5y") in (None, ""):
            try:
                slot["sce_5y"] = round(float(v), 2)
            except ValueError:
                slot["sce_5y"] = v


# ------------------------------------------------------------------ 2. 股指
def fetch_equity():
    """FRED：SP500(标普500, 仅存最近10年) / NASDAQCOM(纳指综合) / NASDAQ100。"""
    series = {"sp500": "SP500", "nasdaq_comp": "NASDAQCOM", "nasdaq_100": "NASDAQ100"}
    merged = {}
    for col, sid in series.items():
        for d, v in _fred(sid):
            merged.setdefault(d, {"date": d})[col] = round(v, 2)
    rows = [merged[d] for d in sorted(merged)]
    n, added = merge_csv(os.path.join(DATA, "equity_indices.csv"),
                         ["date", "sp500", "nasdaq_comp", "nasdaq_100"],
                         ("date",), rows)
    return "equity_indices", n, added, rows[-1]["date"] if rows else ""


# ------------------------------------------------------------------ 3. 黄金
def _gold_fallback():
    """备用：gold-api.com 免费 XAU/USD 现货价（无需 key）。

    LBMA 主源被 Cloudflare 拦截时用。返回 [(date, usd_per_oz)]。
    注意这是抓取时刻的现货价，不是 LBMA 下午定盘价 —— 语义上记为备用源，
    上游调用方会在飞书推送里标出来。
    """
    d = http_get_json("https://api.gold-api.com/price/XAU", browser_ua=False)
    px = d.get("price")
    if not px:
        raise ValueError("gold-api.com: 响应里没有 price 字段")
    # updatedAt 如 "2026-10-01T04:49:19Z"，取日期部分；拿不到就用今天
    ts = str(d.get("updatedAt") or "")
    date = ts[:10] if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-" else TODAY.isoformat()
    return [(date, round(float(px), 2))]


def fetch_gold():
    """LBMA 官方定盘价 JSON（主源），v = [USD, GBP, EUR]，1968 年至今。

    2026-10-01 起 LBMA 对 GitHub Runner IP 回 403（Cloudflare 拦截），
    主源失败时自动降级到 gold-api.com 免费 XAU 现货价。实际用的源放在
    返回的第 5 个元素里，进 fetch_report.json 的 source 字段，飞书推送里
    会把备用源标出来。
    """
    try:
        data = http_get_json("https://prices.lbma.org.uk/json/gold_pm.json", expect=list)
        rows = []
        for p in data:
            v = p.get("v") or []
            if not v or v[0] in (None, ""):
                continue
            rows.append({"date": p["d"], "usd_per_oz": round(float(v[0]), 2)})
        if not rows:
            raise ValueError("LBMA: 0 rows parsed")
        source = "LBMA"
    except Exception as e:                        # noqa: BLE001 — 主源挂了就降级
        print("[warn] gold: LBMA 失败（%s: %s），降级到 gold-api.com 备用源"
              % (type(e).__name__, e), file=sys.stderr, flush=True)
        rows = [{"date": d, "usd_per_oz": v} for d, v in _gold_fallback()]
        source = "gold-api.com（备用）"
    n, added = merge_csv(os.path.join(DATA, "gold.csv"),
                         ["date", "usd_per_oz"], ("date",), rows)
    return "gold", n, added, rows[-1]["date"] if rows else "", source


# ---------------------------------------------------------------- 4. 比特币
def fetch_bitcoin():
    """Coinbase Exchange 日线蜡烛。单次上限 300 根，按 290 天一段翻页。

    增量模式只回看 60 天；--full 时从 Coinbase BTC-USD 上线日 2015-07-20 起全量。
    返回字段 [time, low, high, open, close, volume]。
    """
    path = os.path.join(DATA, "bitcoin.csv")
    start = datetime.date(2015, 7, 20) if (FULL or not read_csv(path)) \
        else TODAY - datetime.timedelta(days=60)
    rows, cur = [], start
    while cur <= TODAY:
        end = min(cur + datetime.timedelta(days=290), TODAY)
        url = ("https://api.exchange.coinbase.com/products/BTC-USD/candles"
               "?granularity=86400&start=%sT00:00:00Z&end=%sT00:00:00Z" % (cur, end))
        for c in http_get_json(url, expect=list):
            d = datetime.datetime.fromtimestamp(
                c[0], datetime.timezone.utc).date().isoformat()
            rows.append({"date": d, "close": round(float(c[4]), 2),
                         "high": round(float(c[2]), 2), "low": round(float(c[1]), 2)})
        cur = end + datetime.timedelta(days=1)
    n, added = merge_csv(path, ["date", "close", "high", "low"], ("date",), rows)
    return "bitcoin", n, added, max((r["date"] for r in rows), default="")


# ------------------------------------------------------- 5. GPU 租赁价格指数
GPUS = ["h100", "h200", "a100", "b200", "mi300x"]
# h100 / a100 同时公开 neo-cloud 与 hyperscaler 两档；其余三卡只公开 neo-cloud
SEGMENTS = {"h100": ["neo-cloud", "hyperscaler"], "a100": ["neo-cloud", "hyperscaler"],
            "h200": ["neo-cloud"], "b200": ["neo-cloud"], "mi300x": ["neo-cloud"]}
_IDX_RE = re.compile(r'"indexes\\?":\s*\\?\{(.*?)\\?\}', re.S)
_PT_RE = re.compile(r'\\?"(\d{4}-\d{2}-\d{2})\\?":\s*\\?"([\d.]+)\\?"')


def _gpu_page(raw):
    """图表页 → (页面实际档位 or None, [(date, 价格)])。

    **找不到 indexes 结构**才抛错（页面改版 / 被挡 / 半截响应），交给 http_get 重试。
    **结构在但里面是空的**返回空列表，不抛 —— 2026-10-21 起上游连续几天如此，
    页面自己显示 "No chart data available"。这是「当期没放数」，不是抓取失败，
    重试多少次都一样，上层据此降级为告警而不是整轮标红。
    """
    html = raw.decode("utf-8", errors="ignore")
    m = _IDX_RE.search(html)
    if not m:
        raise ValueError("no indexes block in page")
    pts = _PT_RE.findall(m.group(1))
    # 页面对不支持双档的卡会静默回落到 neo-cloud，此处以回传的 initialMainTab 为准
    got = re.search(r'initialMainTab\\?":\\?"([a-z\-]+)', html)
    return (got.group(1) if got else None), pts


def fetch_gpu():
    """Silicon Data 公开图表端点。免费层只吐**滚动 7 天**窗口，

    所以本地 CSV 用 append 语义：每天跑一次，历史就在仓库里自己长出来。
    没有任何 10 年历史可回补 —— 该指数 2025 年才发布。

    某张卡的页面解析不出来时，其余卡照常入库，但整类仍记失败 ——
    否则那张卡会悄无声息地停更，而错过的 7 天窗口事后补不回来。
    """
    rows, missing = [], []
    for gpu in GPUS:
        for seg in SEGMENTS[gpu]:
            url = ("https://portal.silicondata.com/gpu-index-chart"
                   "?standalone=true&gpu=%s&mainTab=%s" % (gpu, seg))
            try:
                seg_actual, pts = http_get(url, parse=_gpu_page)
            except RuntimeError:
                missing.append("%s/%s" % (gpu, seg))
                continue
            for d, v in pts:
                rows.append({"date": d, "gpu": gpu.upper(), "segment": seg_actual or seg,
                             "usd_per_hr": v})
    total_pages = sum(len(v) for v in SEGMENTS.values())
    if not rows:
        # 区分两种空：页面能打开、结构也还在，只是上游当期没放数（2026-10-21 起连续空，
        # 页面自己显示 "No chart data available"）—— 这种不该天天把整轮标红。
        # 全部页面都解析不出结构才算真改版。
        if len(missing) < total_pages:
            existing = read_csv(os.path.join(DATA, "gpu_rental.csv"))
            last = max((r["date"] for r in existing), default="—")
            print("[warn] gpu: %d/%d 个页面正常返回但 indexes 为空"
                  "（Silicon Data 当期未放数），保留已有历史，最后有值 %s"
                  % (total_pages - len(missing), total_pages, last), file=sys.stderr)
            return ("gpu_rental", len(existing), 0, last,
                    "上游无数据（最后有值 %s）" % last)
        raise RuntimeError("silicon data: %d 个页面均未解析出 indexes 结构，像是改版了"
                           % total_pages)
    n, added = merge_csv(os.path.join(DATA, "gpu_rental.csv"),
                         ["date", "gpu", "segment", "usd_per_hr"],
                         ("date", "gpu", "segment"), rows)
    if missing:
        raise RuntimeError("silicon data: %s 解析不到数据（其余 %d 个点已入库）"
                           % ("、".join(missing), len(rows)))
    return "gpu_rental", n, added, max(r["date"] for r in rows)


# --------------------------------------------- 6. 隐含股权风险溢价 (Damodaran)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
ERP_COLS = {1: "date", 2: "sp500", 3: "tbond_rate", 9: "erp_sustainable_payout",
            10: "erp_t12m", 11: "erp_adj_rf", 16: "expected_return"}


def _col_num(ref):
    """'AB12' → 28（1-indexed 列号）。"""
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n


def _text_date(v):
    """兼容原表里被存成文本的日期，如 '1-Sep-24' / '9/1/2024'。"""
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_erp():
    """Damodaran《Historical ERP》月度表。用 zipfile+ElementTree 直读，免装 openpyxl。

    注意：该工作簿用的是 **1904 日期系统**，序列号要以 1904-01-01 为原点，
    否则整条序列会整体偏移 4 年多。
    """
    z = http_get("https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx",
                 parse=_zip)
    wb = z.read("xl/workbook.xml").decode("utf-8", errors="ignore")
    epoch = (datetime.date(1904, 1, 1) if 'date1904="1"' in wb or "date1904=\"true\"" in wb
             else datetime.date(1899, 12, 30))
    sheets = re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb)
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", errors="ignore")
    rid2tgt = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))
    target = next((rid2tgt[r] for nm, r in sheets if nm.strip() == "Historical ERP"), None)
    if target is None:
        raise RuntimeError("ERPbymonth.xlsx: sheet 'Historical ERP' not found")
    path = "xl/" + target.lstrip("/").replace("xl/", "", 1)

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))

    def cell_val(c):
        v = c.find(NS + "v")
        if v is None or v.text is None:
            return None
        return shared[int(v.text)] if c.get("t") == "s" else v.text

    def num(x):
        if x in (None, ""):
            return None
        s = str(x).strip().replace(",", ".")
        pct = s.endswith("%")
        try:
            f = float(s.rstrip("%"))
        except ValueError:
            return None
        return f / 100.0 if pct else f

    rows = []
    for row in ET.fromstring(z.read(path)).find(NS + "sheetData").findall(NS + "row"):
        cells = {_col_num(c.get("r") or ""): cell_val(c) for c in row.findall(NS + "c")}
        serial = num(cells.get(1))
        if serial is not None and serial >= 1000:
            d = epoch + datetime.timedelta(days=int(serial))
        else:
            # 原表里个别月份（如 2024-09）日期被存成文本 '1-Sep-24'，序列号解析不到
            d = _text_date(cells.get(1))
            if d is None:                            # 表头行/空行
                continue
        rec = {"date": d.isoformat()}
        for col, key in ERP_COLS.items():
            if key == "date":
                continue
            v = num(cells.get(col))
            if v is None:
                rec[key] = ""
            elif key == "sp500":
                rec[key] = round(v, 2)
            else:
                rec[key] = round(v * 100, 2)          # 小数 → 百分比
        rows.append(rec)
    if not rows:
        raise RuntimeError("ERPbymonth.xlsx: 0 rows parsed")
    # ERP ÷ 无风险利率：绝对值在不同利率环境下不可比，这个比值才可比。
    # 2026-10 就是例子 —— ERP 3.70% 是 2008 以来最低（月度分位 0%），
    # 但比值 0.70 在 65 年里只是中位附近（分位 49%），差别全在 10Y 从 0.5% 到 5.3%。
    for r in rows:
        tb = r.get("tbond_rate")
        r["erp_over_rf"] = (round(r["erp_t12m"] / tb, 4)
                            if (tb and r.get("erp_t12m") not in (None, "")) else "")
    fields = ["date", "erp_t12m", "tbond_rate", "expected_return", "erp_over_rf", "sp500",
              "erp_sustainable_payout", "erp_adj_rf"]
    n, added = merge_csv(os.path.join(DATA, "erp_monthly.csv"), fields, ("date",), rows)
    return "erp_monthly", n, added, rows[-1]["date"]


# --------------------------------- 6b. 年度隐含 ERP (FCFE)，1961 至今 65 年
# 月度表只回到 2008-09，不够判断"现在算不算极端"。年度表给的是跨越
# 1970s 滞胀、1999 泡沫、2008 危机、2020 零利率的完整分布。
# 两条序列口径不同（月度 T12m vs 年度 FCFE），重叠 18 年里 15 年吻合，
# 2011/2012/2020 分别差 131/22/52bp —— 所以分别落盘，年度只作量级校准。
def _num_pct(x):
    """'4.06%' / '0.0406' / 4.06e-2 都收，返回小数。解析不了返回 None。"""
    if x in (None, ""):
        return None
    t = str(x).strip().replace(",", ".")
    pct = t.endswith("%")
    try:
        f = float(t.rstrip("%"))
    except ValueError:
        return None
    return f / 100.0 if pct else f


ANNUAL_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xlsx"
ANNUAL_SHEET = "Historical Impl Premiums"
# 『Historical Impl Premiums』列号（0-indexed）
ACOL = {0: "year", 1: "earnings_yield", 2: "dividend_yield", 3: "sp500",
        10: "tbond_rate", 12: "smoothed_growth", 15: "erp_fcfe",
        17: "erp_sustainable_payout", 18: "erp_over_rf_src"}


def fetch_erp_annual():
    """Damodaran 年度 Implied ERP (FCFE)。

    官网同时挂 .xls 与 .xlsx，内容一致（65 年逐年比对零偏差），这里取 .xlsx
    以便继续用标准库 zipfile 解析，不引 xlrd。
    """
    raw = http_get(ANNUAL_URL)
    z = zipfile.ZipFile(__import__("io").BytesIO(raw))
    sheet = _sheet_rows(z, ANNUAL_SHEET)
    rows = []
    for row in sheet:
        if not row:
            continue

        def cell(idx):
            return row[idx] if idx < len(row) else ""
        y = _num_pct(cell(0))
        if y is None or not (1950 < y < 2100):
            continue
        erp = _num_pct(cell(15))
        if erp is None:                       # 最后一年有时只有表头没有数
            continue
        rec = {"year": int(y)}
        for c, k in ACOL.items():
            if k == "year":
                continue
            v = _num_pct(cell(c))
            rec[k] = round(v, 6) if v is not None else ""
        tb = rec.get("tbond_rate")
        rec["erp_over_rf"] = round(erp / tb, 4) if tb else ""
        rows.append(rec)
    if len(rows) < 50:
        raise RuntimeError("histimpl.xlsx 只解析出 %d 年，像是表结构变了" % len(rows))
    rows.sort(key=lambda r: r["year"])
    # 自校验：用他自己的 ERP/Riskfree 列对账，偏差 >0.02 说明列号读错了
    chk = [(r["year"], r["erp_over_rf"], r["erp_over_rf_src"]) for r in rows
           if r["erp_over_rf"] != "" and r["erp_over_rf_src"] != ""]
    bad = [y for y, a, b in chk if abs(a - b) > 0.02]
    if bad:
        raise RuntimeError("年度 ERP/无风险利率自校验失败，%d 年对不上：%s"
                           % (len(bad), bad[:5]))
    fields = ["year", "erp_fcfe", "tbond_rate", "erp_over_rf", "erp_over_rf_src",
              "erp_sustainable_payout", "earnings_yield", "dividend_yield",
              "smoothed_growth", "sp500"]
    n, added = merge_csv(os.path.join(DATA, "erp_annual.csv"), fields, ("year",), rows)
    return "erp_annual", n, added, str(rows[-1]["year"])


# ------------------------------------------------------------------- 主流程
JOBS = [("实际利率期限结构", fetch_real_rate),
        ("通胀预期", fetch_inflation_expectations), ("股指", fetch_equity),
        ("黄金", fetch_gold), ("比特币", fetch_bitcoin),
        ("GPU租赁指数", fetch_gpu), ("隐含股权风险溢价", fetch_erp), ("年度ERP(65年)", fetch_erp_annual)]


def main():
    os.makedirs(DATA, exist_ok=True)
    report, failed = [], []
    for label, fn in JOBS:
        try:
            res = fn()
            name, total, added, last = res[:4]
            entry = {"job": name, "label": label, "ok": True, "rows": total,
                     "added": added, "last_date": last}
            src = res[4] if len(res) > 4 and res[4] else ""
            if src:
                entry["source"] = src
            report.append(entry)
            print("[ok]   %-14s %-22s rows=%-6d new=%-4d last=%s%s"
                  % (name, label, total, added, last,
                     "  [源:%s]" % src if src else ""), flush=True)
        except Exception as e:                        # noqa: BLE001
            failed.append(label)
            report.append({"job": fn.__name__, "label": label, "ok": False,
                           "error": "%s: %s" % (type(e).__name__, e)})
            print("[FAIL] %-14s %-22s %s: %s" % (fn.__name__, label, type(e).__name__, e),
                  file=sys.stderr, flush=True)
    with open(os.path.join(DATA, "fetch_report.json"), "w", encoding="utf-8") as f:
        json.dump({"run_at_utc": datetime.datetime.now(datetime.timezone.utc)
                   .isoformat(timespec="seconds"),
                   "full": FULL, "jobs": report}, f, ensure_ascii=False, indent=2)
    if failed:
        print("\n%d/%d 类失败：%s" % (len(failed), len(JOBS), "、".join(failed)),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
