#!/usr/bin/env python3
"""把当日看板数据交给 Claude，产出一段中文点评 → data/commentary.md。

单次调用，不需要 agent：输入是已经算好的 KPI 与变动，模型只做解读，不做取数。

**必须是可降级的。** 日更推送的铁律是「无论如何都要发出那一条」，所以这个脚本
任何一步出错都只打警告、返回 0，由 notify_feishu 决定有没有点评都照发。

用法：
    python3 scripts/commentary.py            # 写 data/commentary.md
    python3 scripts/commentary.py --dry-run  # 只打印
环境变量：ANTHROPIC_API_KEY（没有就静默跳过）
"""
import argparse
import datetime
import json
import os
import sys

from common import DATA

MODEL = "claude-opus-5-5"
OUT = os.path.join(DATA, "commentary.md")
BJT = datetime.timezone(datetime.timedelta(hours=8))

SYSTEM = """\
你在给一个私人用的宏观数据看板写每日点评。读者是专业投资者，不需要名词解释。

写**约 250 字**中文，不分点，不用小标题。

篇幅是硬约束，但不是靠删字达成的：**优先把当天最重要的那一处变化讲透**
（它是什么、为什么、对什么不利），次要的线索宁可不提，也不要每条都蜻蜓点水。
三四句话写满 250 字，好过八句话各说一半。

其余要求：

- **只说数据里有的东西。** 不引入看板之外的新闻、传闻或预测。
- **先说今天最值得注意的那一处变化**，再说它和别的序列连起来意味着什么。
  没有值得注意的变化就直说盘整，不要为了凑字数找话讲。
- 利率要分清是实际利率还是通胀预期在动 —— 两条线之间的差就是盈亏平衡通胀。
  名义在涨而盈亏平衡不动，涨的是实际利率（钱本身的价格）。
- ERP 的月度分位只覆盖 2008-09 以来 18 年、起点是雷曼，**低分位不等于极端乐观**；
  同期 10 年期美债从 0.5% 涨到 5.3%，利率抬升本身就会压薄 ERP。提到分位时带上这个限制。
- 不给买卖建议，不用「建议」「应该配置」这类措辞。可以说某个变化对什么资产不利。
- 不用「值得关注」「需密切跟踪」「市场情绪谨慎」这类套话。
- 数字直接引用，不要重算。

输出纯文本，不要 markdown 标记。"""


def fmt_kpis(dash):
    lines = []
    for k in dash.get("kpis", []):
        unit = k.get("unit") or ""
        v = ("%.2f%%" % k["value"]) if unit == "%" else (
            "{:,.2f}".format(k["value"]) if k["value"] < 1000
            else "{:,.0f}".format(k["value"]))
        seg = "%s %s%s（%s）" % (k["name"], v, unit if unit != "%" else "", k["date"])
        for lbl, key in (("30日", "chg_30"), ("一年", "chg_365")):
            c = k.get(key)
            if c is None:
                continue
            seg += "，%s %s" % (lbl, ("%+.2fpp" % c) if k.get("is_rate") else "%+.1f%%" % c)
        lines.append("- " + seg)
    return "\n".join(lines)


def fmt_fms(dash):
    p = dash.get("panels", {}).get("fms") or {}
    tables = p.get("tables") or []
    if not tables:
        return ""
    out = ["美银基金经理调查（%s 期）：" % (p.get("month") or "—")]
    for t in tables[:3]:
        items = "；".join("%s%s" % (i["label"], (" %g%%" % i["pct"]) if i.get("pct") is not None else "")
                          for i in t["items"][:5])
        out.append("- %s：%s" % (t["title"], items))
    return "\n".join(out)


def build_prompt(dash):
    ep = dash.get("erp_pctiles") or {}
    erp_line = ""
    if ep.get("p_monthly") is not None:
        erp_line = ("\nERP %.2f%%（%s），月度分位 %d%%，样本 %s 起共 %d 个月。"
                    % (ep["erp"], (ep.get("month") or "")[:7], ep["p_monthly"],
                       ep.get("span_from", "2008-09"), ep.get("n_months", 0)))
    return ("今天是 %s。以下是看板当日读数。\n\n%s\n%s\n\n%s\n\n请写今天的点评。"
            % (datetime.datetime.now(BJT).strftime("%Y-%m-%d"),
               fmt_kpis(dash), erp_line, fmt_fms(dash)))


def _client():
    """组织级 API key 必须带 anthropic-workspace-id 头；workspace 级 key 不用。"""
    import anthropic
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    return anthropic.Anthropic(
        default_headers={"anthropic-workspace-id": ws} if ws else None)


def generate(dash, model=MODEL):
    client = _client()
    resp = client.messages.create(
        model=model, max_tokens=2000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": build_prompt(dash)}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("模型拒答：%s" % getattr(resp.stop_details, "explanation", ""))
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise RuntimeError("响应没有文本，stop_reason=%s" % resp.stop_reason)
    return text, resp.usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("commentary: ANTHROPIC_API_KEY 未配置，跳过（推送照常，只是没有点评）")
        return 0
    try:
        with open(os.path.join(DATA, "dashboard.json"), encoding="utf-8") as fh:
            dash = json.load(fh)
        text, usage = generate(dash, a.model)
    except Exception as e:                       # noqa: BLE001 — 点评失败绝不能挡住推送
        # 一律返回 0（推送是铁律），但把**配置类**错误和「接口抖了一下」区分开：
        # 前者天天都会复现，必须在 Actions 日志里醒目，否则点评会静默失效很久没人发现。
        msg = "%s: %s" % (type(e).__name__, e)
        cfg = any(k in msg for k in ("authentication", "permission", "not scoped",
                                     "invalid_request_error", "401", "403", "400"))
        tag = ("::error::点评配置有误（推送照常，但这个错天天都会复现，要处理）"
               if cfg else "::warning::点评生成失败（推送照常，可能只是临时抖动）")
        print("%s：%s" % (tag, msg), file=sys.stderr)
        return 0

    print(text)
    print("\n[tokens in=%s out=%s]" % (usage.input_tokens, usage.output_tokens),
          file=sys.stderr)
    if a.dry_run:
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("<!-- %s 生成，模型 %s -->\n%s\n"
                 % (datetime.datetime.now(BJT).strftime("%Y-%m-%d %H:%M"), a.model, text))
    print("\n写出 %s" % OUT, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
