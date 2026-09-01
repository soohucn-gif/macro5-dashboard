#!/usr/bin/env python3
"""五大类数据抓取。每类独立 try，一类挂掉不影响其余，最后汇总退出码。

产出（全部 merge 语义，绝不丢历史）：
  data/real_rates.csv      5/10/30年期实际利率(TIPS)与名义利率      日频  FRED
  data/inflation_expectations.csv  通胀预期：市场 vs 消费者         月频  FRED + 纽约联储
  data/equity_indices.csv  标普500 / 纳指综合 / 纳指100             日频  FRED
  data/gold.csv            LBMA 伦敦金定盘价 USD/oz                 日频  LBMA
  data/bitcoin.csv         BTC-USD 日收盘                           日频  Coinbase
  data/gpu_rental.csv      H100/H200/A100/B200/MI300X 租赁指数      日频  Silicon Data
  data/erp_monthly.csv     Damodaran 隐含股权风险溢价               月频  NYU Stern

用法：
  python3 scripts/fetch_all.py            # 增量（日常）
  python3 scripts/fetch_all.py --full     # 全量回补（首次运行）
"""
import datetime
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

from common import DATA, http_get, merge_csv, parse_fred_csv, read_csv

TODAY = datetime.date.today()
FULL = "--full" in sys.argv


# ------------------------------------------------------- 1. 实际利率期限结构
REAL_SERIES = {"dfii5": "DFII5", "dfii10": "DFII10", "dfii30": "DFII30",
               "dgs5": "DGS5", "dgs10": "DGS10", "dgs30": "DGS30",
               "t5yie": "T5YIE", "t10yie": "T10YIE", "t5yifr": "T5YIFR"}


def _fred(sid):
    return http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + sid,
                    browser_ua=False)


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
        for d, v in parse_fred_csv(_fred(sid), sid):
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


def _sheet_rows(z, sheet_name):
    """从 xlsx 里按表名取出二维字符串数组（共享字符串已解引用）。"""
    wb = z.read("xl/workbook.xml").decode("utf-8", errors="ignore")
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                           z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "ignore")))
    tgt = next((rels[r] for n, r in
                re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb)
                if n == sheet_name), None)
    if tgt is None:
        raise RuntimeError("xlsx 里找不到工作表 %r" % sheet_name)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(NS + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si")]
    path = "xl/" + tgt.lstrip("/").replace("xl/", "", 1)
    out = []
    for row in ET.fromstring(z.read(path)).find(NS + "sheetData").findall(NS + "row"):
        cells = []
        for c in row.findall(NS + "c"):
            v = c.find(NS + "v")
            if v is None or v.text is None:
                cells.append("")
            else:
                cells.append(shared[int(v.text)] if c.get("t") == "s" else v.text)
        out.append(cells)
    return out


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
        for d, v in parse_fred_csv(_fred(sid), sid):
            merged.setdefault(d, {"date": d})[col] = round(v, 2)

    # 日频的盈亏平衡取每月最后一个有效值，好跟月频序列并排
    daily = {}
    for col, sid in (("be5y", "T5YIE"), ("be10y", "T10YIE"), ("fwd5y5y", "T5YIFR")):
        for d, v in parse_fred_csv(_fred(sid), sid):
            daily.setdefault(d[:7] + "-01", {})[col] = round(v, 2)
    for m, vals in daily.items():
        merged.setdefault(m, {"date": m}).update(vals)

    # 纽约联储消费者预期调查（SCE）—— 公开下载，无需授权
    z = zipfile.ZipFile(__import__("io").BytesIO(http_get(SCE_URL)))
    for sheet, cols in (("Inflation expectations", {1: "sce_1y", 2: "sce_3y"}),
                        ("Five-year ahead Infl Exp", {1: "sce_5y"})):
        for row in _sheet_rows(z, sheet):
            d = _ym(row[0] if row else "")
            if d is None:
                continue
            for idx, col in cols.items():
                if idx < len(row) and row[idx] not in ("", None):
                    try:
                        merged.setdefault(d, {"date": d})[col] = round(float(row[idx]), 2)
                    except ValueError:
                        pass

    rows = [merged[d] for d in sorted(merged)]
    fields = ["date", "be5y", "be10y", "be30y", "fwd5y5y",
              "cleveland_1y", "cleveland_5y", "cleveland_10y", "cleveland_30y",
              "michigan_1y", "sce_1y", "sce_3y", "sce_5y"]
    n, added = merge_csv(os.path.join(DATA, "inflation_expectations.csv"),
                         fields, ("date",), rows)
    return "inflation_expectations", n, added, rows[-1]["date"] if rows else ""


# ------------------------------------------------------------------ 2. 股指
def fetch_equity():
    """FRED：SP500(标普500, 仅存最近10年) / NASDAQCOM(纳指综合) / NASDAQ100。"""
    series = {"sp500": "SP500", "nasdaq_comp": "NASDAQCOM", "nasdaq_100": "NASDAQ100"}
    merged = {}
    for col, sid in series.items():
        for d, v in parse_fred_csv(_fred(sid), sid):
            merged.setdefault(d, {"date": d})[col] = round(v, 2)
    rows = [merged[d] for d in sorted(merged)]
    n, added = merge_csv(os.path.join(DATA, "equity_indices.csv"),
                         ["date", "sp500", "nasdaq_comp", "nasdaq_100"],
                         ("date",), rows)
    return "equity_indices", n, added, rows[-1]["date"] if rows else ""


# ------------------------------------------------------------------ 3. 黄金
def fetch_gold():
    """LBMA 官方定盘价 JSON，v = [USD, GBP, EUR]，1968 年至今。"""
    raw = http_get("https://prices.lbma.org.uk/json/gold_pm.json")
    data = json.loads(raw.decode("utf-8"))
    rows = []
    for p in data:
        v = p.get("v") or []
        if not v or v[0] in (None, ""):
            continue
        rows.append({"date": p["d"], "usd_per_oz": round(float(v[0]), 2)})
    n, added = merge_csv(os.path.join(DATA, "gold.csv"),
                         ["date", "usd_per_oz"], ("date",), rows)
    return "gold", n, added, rows[-1]["date"] if rows else ""


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
        for c in json.loads(http_get(url).decode("utf-8")):
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


def fetch_gpu():
    """Silicon Data 公开图表端点。免费层只吐**滚动 7 天**窗口，

    所以本地 CSV 用 append 语义：每天跑一次，历史就在仓库里自己长出来。
    没有任何 10 年历史可回补 —— 该指数 2025 年才发布。
    """
    rows = []
    for gpu in GPUS:
        for seg in SEGMENTS[gpu]:
            url = ("https://portal.silicondata.com/gpu-index-chart"
                   "?standalone=true&gpu=%s&mainTab=%s" % (gpu, seg))
            html = http_get(url).decode("utf-8", errors="ignore")
            m = _IDX_RE.search(html)
            if not m:
                continue
            # 页面对不支持双档的卡会静默回落到 neo-cloud，此处以回传的 initialMainTab 为准
            got = re.search(r'initialMainTab\\?":\\?"([a-z\-]+)', html)
            seg_actual = got.group(1) if got else seg
            for d, v in _PT_RE.findall(m.group(1)):
                rows.append({"date": d, "gpu": gpu.upper(), "segment": seg_actual,
                             "usd_per_hr": v})
    if not rows:
        raise RuntimeError("silicon data: 0 points parsed")
    n, added = merge_csv(os.path.join(DATA, "gpu_rental.csv"),
                         ["date", "gpu", "segment", "usd_per_hr"],
                         ("date", "gpu", "segment"), rows)
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
    raw = http_get("https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx")
    z = zipfile.ZipFile(__import__("io").BytesIO(raw))
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
            name, total, added, last = fn()
            report.append({"job": name, "label": label, "ok": True, "rows": total,
                           "added": added, "last_date": last})
            print("[ok]   %-14s %-22s rows=%-6d new=%-4d last=%s"
                  % (name, label, total, added, last), flush=True)
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
