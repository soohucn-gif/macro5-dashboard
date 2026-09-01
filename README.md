# 五大类数据看板

六条序列，每天由 GitHub Actions 自动抓取、落 CSV、重建单文件看板，全部推回本仓库。

**看板：** https://soohucn-gif.github.io/macro5-dashboard/

| # | 模块 | 频率 | 数据源 | 历史起点 |
|---|---|---|---|---|
| ① | 实际利率期限结构 5/10/30 年 | 日频 | FRED `DFII5/10/30` · `DGS5/10/30` | 5/10年 2003-01；30年 2010-02 |
| ② | 通胀预期：市场 vs 消费者 | 月频 | FRED `T10YIE`/`T5YIFR`/`EXPINF*`/`MICH` ＋ 纽约联储 SCE | 市场 2003；SCE 2013-06 |
| ② | 隐含股权风险溢价 ERP | 月频 | NYU Stern · Damodaran `ERPbymonth.xlsx` | 2008-09 |
| ③ | 标普500 / 纳斯达克综合 / 纳斯达克100 | 日频 | FRED `SP500` / `NASDAQCOM` / `NASDAQ100` | 标普 10 年上限；纳指 1971 |
| ④ | 黄金（伦敦金定盘价） | 日频 | LBMA 官方 JSON | 1968-04 |
| ⑤ | 比特币 | 日频 | Coinbase Exchange BTC-USD | 2015-07 |
| ⑥ | GPU 租赁价格指数 | 日频 | Silicon Data SiliconIndex | 2026-08-23（见下） |
| ⑦ | 美银基金经理调查：拥挤交易与反向交易 | 月频 | BofA Global FMS（派生口径，见下） | 2025-10 |

## 目录

```
data/
  real_rates.csv       date, dfii5, dfii10, dfii30, dgs5, dgs10, dgs30, t5yie, t10yie, t5yifr, ...
  inflation_expectations.csv  date, be5y, be10y, be30y, fwd5y5y, cleveland_*, michigan_1y, sce_1y/3y/5y
  erp_monthly.csv      date, erp_t12m, tbond_rate, expected_return, sp500, ...
  equity_indices.csv   date, sp500, nasdaq_comp, nasdaq_100
  gold.csv             date, usd_per_oz
  bitcoin.csv          date, close, high, low
  gpu_rental.csv       date, gpu, segment, usd_per_hr
  bofa_fms.csv             month, cash_pct, top_crowded_trade, ..., confidence, sources, notes
  bofa_fms_crowded.csv     month, rank, trade, trade_cn, pct
  bofa_fms_contrarian.csv  month, kind, rank, item, item_cn, pct
  dashboard.json       看板内联的十年窗口数据
  latest.md            当日文本快照（覆盖写）
  daily/YYYY-MM-DD.md  当日文本快照存档
  monthly/YYYY-MM.md   月度文本快照（环比 / 同比 / 月内区间）
  fetch_report.json    上一轮各源成败与增量行数
index.html             自包含单文件看板（无外部依赖）
scripts/               抓取与构建脚本，纯标准库，无需 pip install
```

## 几处必须说明的口径

**① 实际利率要看期限结构，不能只看 10 年。** `DFII5/10/30` 是 5、10、30 年期 TIPS 收益率。
三个期限一起看才知道曲线是整体抬升还是只有长端在动 —— **长端实际利率才是压估值的那一根**。
同表另存对应期限的名义利率与盈亏平衡通胀，并算出 `implied_real = DGS − T*YIE` 作交叉验算。
30 年期只有 2010-02 起：30 年 TIPS 2001 年停发、2010 年才重启。

**② 通胀预期有两个互不相干的世界，别混成一个数。**
- **市场口径**（投资者真金白银押的）：TIPS 盈亏平衡 `T5YIE`/`T10YIE`/`T30YIEM`，
  以及 5 年后 5 年远期 `T5YIFR`（剔除未来五年的短期通胀噪音，长期预期最干净的读数）。
- **模型口径**：克利夫兰联储 `EXPINF1YR/5YR/10YR/30YR`，把市场价格与调查数据一起入模。
- **消费者口径**（问卷问出来的）：密歇根大学 1 年期 `MICH`；纽约联储消费者预期调查
  （SCE）1/3/5 年中位数，从官网 xlsx 直接下载，公开无需授权。

消费者口径长期系统性高于市场口径一个百分点以上 —— 普通人对食品、油价、房租这些
高频可见价格更敏感，而市场定价的是一篮子 CPI 的加权平均。这个差不是谁错了，是两回事。

**② ERP 的日期约定。** Damodaran 表中标记为 `YYYY-MM-01` 的那一行，用的是**上月最后一个
交易日**的指数点位反解出来的。所以 `2026-08-01` 这一行描述的是 7 月底的市场状态。
这是原始数据的口径，本仓库不改写。

原始工作簿用的是 **1904 日期系统**，序列号必须以 1904-01-01 为原点；另有个别月份
（如 2024-09）日期被存成文本 `1-Sep-24`。两种情况脚本都已处理。

**③ 标普历史长度。** FRED 的 `SP500` 序列按授权只保留最近 10 年，因此本仓库标普
最早只能到 10 年前；纳指两条序列没有这个限制。

**⑥ GPU 指数没有 10 年历史。** Silicon Data 2025 年才发布该指数，且公开层只吐出
**滚动 7 天**窗口（付费 API 才有全历史）。因此这一类无法回补 —— 本仓库自
2026-08-23 起每日抓取累积，历史在仓库里逐日生长。H100 与 A100 同时公开
Neo-Cloud 与超大规模云两档，H200 / B200 / MI300X 只公开 Neo-Cloud 一档。

**⑦ 美银 FMS 只收派生数字，不搬原始材料。** BofA Global Fund Manager Survey 的完整报告与
图表版权归 BofA Global Research，原始存档在私有仓库 `soohucn-gif/bofa-fms`（含原图与报告
正文），**不对外分发**。本公开仓库只收录三类派生数字：月度头条指标（现金水位、情绪分、
净超配）、最拥挤交易与尾部风险的排名及占比、BofA 官方 Contrarian Trades 的文字标签 ——
即各家通讯社每月公开报道的那几个数。**不含任何 BofA 图表或报告正文。**

口径提醒：BofA 问卷**只问「最拥挤交易」，没有对称的「最冷门交易」**。看板里的"冷门"分三层：
官方 Contrarian Trades（最接近官方口径）、绝对仓位里净超配最低的品类、行业情绪里净超配为负的行业。

取数链路（**主路径走公开互联网，不依赖本机任何存档**）：

1. **主路径** — `macro5-fms-monthly` 定时任务（每月 16/18/20/22/24 号 09:40）从公开媒体
   （Reuters / CNBC / ZeroHedge / Mace News / hedgefundtips / 华尔街见闻 等）检索新一期结果，
   交叉验证后组成 JSON，经 `scripts/append_fms.py` **校验**写入。校验会挡住：缺出处、
   月份格式错、现金水位越界、拥挤交易缺失等情况 —— 没有出处的数字不进库。
   每期都记 `sources`（实际读过的 URL）与 `confidence`（high/medium/low）。
2. **校正路径** — `bofa-fms-monthly` 任务逐张读 BofA 原图（私有存档），比通稿转述更权威；
   若与主路径写入的数字有出入，用 `scripts/sync_bofa_fms.py` 按月覆盖该期并说明差异。
3. 云端 Actions 只是把已提交的 CSV 读进看板，不参与取数。

两条路径都是**按月幂等替换**，互不覆盖对方的月份。若超过 45 天没有新一期，看板面板会自己标出来。

## 运行

```bash
python3 scripts/fetch_all.py            # 增量
python3 scripts/fetch_all.py --full     # 全量回补
python3 scripts/build_dashboard.py      # 重建 index.html + dashboard.json + latest.md
python3 scripts/monthly_snapshot.py 2026-08
python3 scripts/append_fms.py payload.json   # 主路径：写入一期网络来源的 FMS（带校验）
python3 scripts/sync_bofa_fms.py            # 校正路径：用本机私有存档的原图读数覆盖
```

无第三方依赖，Python 3.8+ 即可。

## 自动化

`.github/workflows/update.yml`

- 每日 23:37 UTC（北京 07:37 次日）：抓六类 → 重建看板 → 提交推送
- 每月 2 号 12:23 UTC：额外生成上月月度快照
- 也可在 Actions 页手动触发，勾选「全量回补」或「月度快照」

单一数据源失败不会中断整轮：能抓到的照常落库提交，最后一步再把失败源标红，
GitHub 会就失败的 workflow 发通知。

数据仅供研究，不构成投资建议。
