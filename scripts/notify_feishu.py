#!/usr/bin/env python3
"""日更结束后，把当日快照压成一条飞书私聊消息发给 Henry。

只用标准库。凭据从环境变量读（GitHub Actions Secrets）：
  FEISHU_APP_ID / FEISHU_APP_SECRET   自建应用
  FEISHU_OPEN_ID                      接收人 open_id（Henry）

规则：
  - 无论前面抓取/构建成功与否都要发出一条（宁可推"今天出数失败"，不要静默）。
  - 每天只发一条：发成功后把北京日期写进 data/last_notify.txt（随日更一起提交），
    同一天的补枪 / 月度快照运行看到标记就跳过；--force 忽略标记。
  - 利率**实际与名义都播**，再带一行 10 年盈亏平衡（= 名义 − 实际），
    这样一眼能看出涨的是钱的价格还是通胀预期。
  - 数据源有 ok:false 的放最前面；日频序列超过一周没新点（抓取「成功」但源头冻住）
    紧随其后；30 日变动越过阈值的单独提示：
    实际/名义利率 ±10bp、股指 ±2%、黄金 ±2%、BTC ±5%。
  - 发送失败以非零退出，让 Actions 把它标红。
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

from common import DATA

DASHBOARD_URL = "https://soohucn-gif.github.io/macro5-dashboard/"
BJT = datetime.timezone(datetime.timedelta(hours=8))

# (KPI 名, 展示名, 30 日变动阈值；rate 用 pp、其余用 %)
# 利率按期限归并告警：报实际利率的变动，只有当同期限名义与实际的变动差
# （＝盈亏平衡通胀的变动）≥5bp 时才额外点出通胀预期那一半。
# 否则"实际+22bp、名义+22bp"两条说的是同一件事，占版面还不给信息。
TENORS = [("30y", "30年期实际利率", "30年期名义利率"),
          ("10y", "10年期实际利率", "10年期名义利率"),
          ("5y", "5年期实际利率", "5年期名义利率")]
RATE_THR = 0.10          # pp
BE_THR = 0.05            # pp，盈亏平衡自身的变动阈值

WATCH = [
    ("标普500", "标普", 2.0),
    ("纳斯达克综合", "纳指", 2.0),
    ("伦敦金", "黄金", 2.0),
    ("比特币", "BTC", 5.0),
]


def load(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:                       # noqa: BLE001 — 缺文件也要能发
        print("read %s failed: %s" % (name, e), file=sys.stderr)
        return None


def num(v, digits=0):
    return ("{:,.%df}" % digits).format(v)


def yoy(k):
    c = k.get("chg_365")
    if c is None:
        return ""
    return " (%+.1f%%)" % c


def compose(dash, report, build_failed):
    today = datetime.datetime.now(BJT).strftime("%m-%d")
    lines = ["五大类看板 %s" % today]

    bad = []
    if report:
        bad = [j["label"] for j in report.get("jobs", []) if not j.get("ok")]
    if build_failed:
        lines.append("❌ 今日构建失败，以下为上次快照")
    if bad:
        lines.append("❌ 抓取失败：" + "、".join(bad))

    if not dash:
        lines.append("看板数据文件缺失，云端状态未知")
        lines.append(DASHBOARD_URL)
        return "\n".join(lines)

    stale = {}
    for x in dash["kpis"]:
        if x.get("stale_days"):
            stale.setdefault(x["date"], []).append(x["name"])
    if stale:
        lines.append("⚠ 超过一周没有新数据：" + "；".join(
            "%s 停在 %s" % ("、".join(v), d[5:]) for d, v in sorted(stale.items())))

    k = {x["name"]: x for x in dash["kpis"]}

    def g(name):
        return k.get(name)

    r30, r10, r5 = g("30年期实际利率"), g("10年期实际利率"), g("5年期实际利率")
    n30, n10, n5 = g("30年期名义利率"), g("10年期名义利率"), g("5年期名义利率")
    if r30 and r10 and r5:
        lines.append("实际 30y %.2f%% / 10y %.2f%% / 5y %.2f%%  (%s)"
                     % (r30["value"], r10["value"], r5["value"], r10["date"][5:]))
    if n30 and n10 and n5:
        lines.append("名义 30y %.2f%% / 10y %.2f%% / 5y %.2f%%"
                     % (n30["value"], n10["value"], n5["value"]))
    # 盈亏平衡通胀 = 名义 − 实际，用同一天的 KPI 现算，避免月频那条序列的滞后
    if n10 and r10 and n10["date"] == r10["date"]:
        be10 = n10["value"] - r10["value"]
        be30 = (n30["value"] - r30["value"]) if (n30 and r30) else None
        lines.append("盈亏平衡 10y %.2f%%%s" %
                     (be10, "" if be30 is None else " / 30y %.2f%%" % be30))
    erp = g("隐含股权风险溢价")
    if erp:
        lines.append("ERP %.2f%%  (%s)" % (erp["value"], erp["date"][:7]))
    spx, ndx = g("标普500"), g("纳斯达克综合")
    if spx and ndx:
        lines.append("标普 %s%s · 纳指 %s%s  (%s)"
                     % (num(spx["value"]), yoy(spx), num(ndx["value"]), yoy(ndx),
                        spx["date"][5:]))
    gold, btc = g("伦敦金"), g("比特币")
    if gold and btc:
        lines.append("黄金 %s%s · BTC %s%s"
                     % (num(gold["value"]), yoy(gold), num(btc["value"]), yoy(btc)))
    h100, b200 = g("GPU H100 · Neo-Cloud"), g("GPU B200 · Neo-Cloud")
    if h100 and b200:
        lines.append("GPU H100 $%.2f/h · B200 $%.2f/h" % (h100["value"], b200["value"]))

    alerts = []
    for short, real_name, nom_name in TENORS:
        rx, nx = g(real_name), g(nom_name)
        dr = rx.get("chg_30") if rx else None
        dn = nx.get("chg_30") if nx else None
        if dr is None and dn is None:
            continue
        # 盈亏平衡的变动 = 名义变动 − 实际变动
        dbe = (dn - dr) if (dr is not None and dn is not None) else None
        if dr is not None and abs(dr) >= RATE_THR:
            tail = ""
            if dbe is not None and abs(dbe) >= BE_THR:
                tail = "（通胀预期%+.0fbp）" % (dbe * 100)
            alerts.append("%s 实际%+.0fbp%s" % (short, dr * 100, tail))
        elif dbe is not None and abs(dbe) >= BE_THR:
            # 实际没怎么动，但盈亏平衡动了 —— 这本身就值得说
            alerts.append("%s 通胀预期%+.0fbp" % (short, dbe * 100))
    for name, short, thr in WATCH:
        x = g(name)
        if not x or x.get("chg_30") is None:
            continue
        c = x["chg_30"]
        if abs(c) >= thr:
            alerts.append("%s %s" % (short, ("%+.0fbp" % (c * 100)) if x["is_rate"]
                                      else "%+.1f%%" % c))
    if alerts:
        lines.append("⚠ 30日变动：" + "，".join(alerts))

    lines.append(DASHBOARD_URL)
    return "\n".join(lines)


def send(text):
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    open_id = os.environ.get("FEISHU_OPEN_ID", "")
    if not (app_id and app_secret and open_id):
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_OPEN_ID 未配置")

    def post(url, body, headers):
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **headers})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    tok = post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
               {"app_id": app_id, "app_secret": app_secret}, {})
    if tok.get("code") != 0:
        raise RuntimeError("tenant_access_token: %s" % tok.get("msg"))
    r = post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
             {"receive_id": open_id, "msg_type": "text",
              "content": json.dumps({"text": text})},
             {"Authorization": "Bearer " + tok["tenant_access_token"]})
    if r.get("code") != 0:
        raise RuntimeError("send message: %s %s" % (r.get("code"), r.get("msg")))


MARKER = os.path.join(DATA, "last_notify.txt")


def main():
    build_failed = os.environ.get("BUILD_FAILED", "") == "true"
    today = datetime.datetime.now(BJT).date().isoformat()
    if "--force" not in sys.argv and "--dry-run" not in sys.argv:
        try:
            with open(MARKER, encoding="utf-8") as fh:
                if fh.read().strip() == today:
                    print("feishu: 今天已推送过，跳过")
                    return
        except FileNotFoundError:
            pass
    text = compose(load("dashboard.json"), load("fetch_report.json"), build_failed)
    print(text)
    if "--dry-run" in sys.argv:
        return
    try:
        send(text)
        print("feishu: sent")
    except (urllib.error.URLError, RuntimeError) as e:
        print("::error::飞书推送失败：%s" % e)
        sys.exit(1)
    with open(MARKER, "w", encoding="utf-8") as fh:
        fh.write(today + "\n")


if __name__ == "__main__":
    main()
