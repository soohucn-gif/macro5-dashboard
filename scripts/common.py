#!/usr/bin/env python3
"""共用工具：HTTP、CSV 合并、路径。只用标准库，GitHub Actions 无需 pip install。"""
import csv
import gzip
import io
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def http_get(url, tries=4, timeout=60, headers=None, browser_ua=True):
    """带重试的 GET，返回 bytes。指数退避，最后一次失败才抛。

    browser_ua=False 时不发浏览器 UA —— FRED 对带浏览器 UA 的非浏览器请求会挂起到
    超时，反而是 urllib 默认 UA 秒回，所以 FRED 必须走这条路。
    """
    hdr = {"Accept-Encoding": "gzip"}
    if browser_ua:
        hdr["User-Agent"] = UA
    if headers:
        hdr.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as e:            # noqa: BLE001 — 上层统一处理
            last = e
            if i < tries - 1:
                time.sleep(2 ** i * 1.5)
    raise RuntimeError("GET failed after %d tries: %s (%s)" % (tries, url, last))


def read_csv(path):
    """读已有 CSV，不存在返回空列表。"""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def merge_csv(path, fields, key, new_rows):
    """按 key 合并进已有 CSV：新值覆盖同 key 老值，其余保留，按 key 排序落盘。

    key 是字段名元组。返回 (总行数, 新增行数)。
    """
    old = read_csv(path)
    idx = {tuple(r.get(k, "") for k in key): dict(r) for r in old}
    before = len(idx)
    for r in new_rows:
        r = {k: ("" if r.get(k) is None else str(r.get(k))) for k in fields}
        idx[tuple(r.get(k, "") for k in key)] = r
    rows = [idx[k] for k in sorted(idx)]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows), len(idx) - before


def parse_fred_csv(raw, colname):
    """FRED fredgraph.csv → [(date, float)]，'.' 表示缺测，跳过。"""
    out = []
    rdr = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    date_key = rdr.fieldnames[0]
    for row in rdr:
        v = (row.get(colname) or "").strip()
        if not v or v == ".":
            continue
        try:
            out.append((row[date_key].strip(), float(v)))
        except ValueError:
            continue
    return out
