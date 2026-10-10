#!/usr/bin/env python3
"""五大类数据抓取。每类独立 try，一类挂掉不影响其余，最后汇总退出码。

产出（全部 merge 语义，绝不丢历史）：
  data/real_rates.csv      5/10/30年期实际利率(TIPS)与名义利率      日频  FRED
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
               "dgs5": "DGS5", "dgs10": "DGS10", "dgs30": "DGS30",
               "t5yie": "T5YIE", "t10yie": "T10YIE", "t5yifr": "T5YIFR"}


@functools.lru_cache(maxsize=None)
def _fred(sid):
    """FRED 序列 → [(date, float)]。同一轮里 T5YIE/T10YIE/T5YIFR 利率表和通胀表都要用，
    缓存住只下一次。"""
    return http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + sid,
                    browser_ua=False, parse=lambda raw: parse_fred_csv(raw, sid))


def _zip(raw):
    """xlsx 正文 → ZipFile；回来的是错误页时 BadZipFile 会让 http_get 重试。"""
    return zipfile.ZipFile(io.BytesIO(raw))


def fetch_real_rate():
    """FRED：DFII5 / DFII10 / DFII30 —— 5、10、30 年期通胀保值债券(TIPS)收益率，
    也就是市场对各期限**实际利率**的直接定价。

    同表存对应期限的名义利率(DGS*)与盈亏平衡通胀(T5YIE/T10YIE)，满足
    实际 ≈ 名义 − 盈亏平衡通胀，可逐日交叉验算。T5YIFR 是「5年后的5年」远期盈亏平衡，
    剔除了未来五年的短期通胀噪音，是市场长期通胀预期最干净的读数。

    注意 DFII30 只有 2010-02 起 —— 30 年期 TIPS 在 2001 停发、2010 才重启。
    """
    merged = {}
    for col, sid in REAL_SERIES.items():
        for d, v in _fred(sid):
            merged.setdefault(d, {"date": d})[col] = round(v, 2)
    rows = []
    for d in sorted(merged):
        r = merged[d]
        for tenor, be in (("5", "t5yie"), ("10", "t10yie")):
            nom, brk = r.get("dgs" + tenor), r.get(be)
            if nom is not None and brk is not None:
                r["implied_real" + tenor] = round(nom - brk, 2)
        rows.append(r)
    fields = ["date", "dfii5", "dfii10", "dfii30", "dgs5", "dgs10", "dgs30",
              "t5yie", "t10yie", "t5yifr", "implied_real5", "implied_real10"]
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
    """图表页 → (页面实际档位 or None, [(date, 价格)])。找不到指数块就抛错，交给 http_get 重试。"""
    html = raw.decode("utf-8", errors="ignore")
    m = _IDX_RE.search(html)
    pts = _PT_RE.findall(m.group(1)) if m else []
    if not pts:
        raise ValueError("no index points in page")
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
    if not rows:
        raise RuntimeError("silicon data: 0 points parsed")
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
    fields = ["date", "erp_t12m", "tbond_rate", "expected_return", "sp500",
              "erp_sustainable_payout", "erp_adj_rf"]
    n, added = merge_csv(os.path.join(DATA, "erp_monthly.csv"), fields, ("date",), rows)
    return "erp_monthly", n, added, rows[-1]["date"]


# ------------------------------------------------------------------- 主流程
JOBS = [("实际利率期限结构", fetch_real_rate),
        ("通胀预期", fetch_inflation_expectations), ("股指", fetch_equity),
        ("黄金", fetch_gold), ("比特币", fetch_bitcoin),
        ("GPU租赁指数", fetch_gpu), ("隐含股权风险溢价", fetch_erp)]


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
