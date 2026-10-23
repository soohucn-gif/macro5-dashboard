#!/usr/bin/env python3
"""fetch_gpu：单个档位缺数或 indexes 为空时只警告，不失败整轮。

不访问网络，也不写 data/gpu_rental.csv。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_all  # noqa: E402


def _page(gpu, seg, indexes_body):
    """拼一段和线上 RSC 载荷同形的片段。indexes_body 为 '' 表示空对象。"""
    return (
        '{"data":{"ending_date":"","gpu":"%s","indexes\\":{%s},"starting_date":""},'
        '"initialMainTab\\":\\"%s"' % (gpu, indexes_body, seg)
    ).encode()


def _points_body(n, price):
    days = []
    for i in range(n):
        days.append('\\"2026-09-%02d\\":\\"%s\\"' % (i + 1, price))
    return ",".join(days)


class FetchGpuSkipTest(unittest.TestCase):
    def test_empty_indexes_parse_as_no_points(self):
        seg, pts = fetch_all._gpu_page(_page("mi300x", "neo-cloud", ""))
        self.assertEqual(seg, "neo-cloud")
        self.assertEqual(pts, [])

    def test_populated_indexes_still_parse(self):
        raw = _page("h100", "neo-cloud",
                    '\\"2026-10-20\\":\\"2.85\\",\\"2026-10-21\\":\\"2.86\\"')
        seg, pts = fetch_all._gpu_page(raw)
        self.assertEqual(seg, "neo-cloud")
        self.assertEqual(pts, [("2026-10-20", "2.85"), ("2026-10-21", "2.86")])

    def test_missing_index_block_still_raises(self):
        with self.assertRaises(ValueError):
            fetch_all._gpu_page(b"<html>error page</html>")

    def test_one_empty_slot_warns_and_keeps_the_rest(self):
        """2026-10-21 的形状：mi300x/neo-cloud 空，其余 6 档各 30 点，共 180。"""
        captured = {}

        def fake_http(url, parse=None, **kw):
            gpu = url.split("gpu=")[1].split("&")[0]
            seg = url.split("mainTab=")[1]
            if gpu == "mi300x":
                return parse(_page(gpu, seg, ""))
            return parse(_page(gpu, seg, _points_body(30, "1.23")))

        def fake_merge(path, fields, key, rows):
            captured["path"] = path
            captured["rows"] = rows
            return 400, len(rows)

        buf = io.StringIO()
        with mock.patch.object(fetch_all, "http_get", fake_http), \
                mock.patch.object(fetch_all, "merge_csv", fake_merge), \
                redirect_stderr(buf):
            res = fetch_all.fetch_gpu()

        self.assertEqual(res[0], "gpu_rental")
        self.assertEqual(res[1], 400)
        self.assertEqual(res[3], "2026-09-30")
        self.assertIn("mi300x/neo-cloud", res[4])
        self.assertTrue(captured["path"].endswith("gpu_rental.csv"))
        gpus = {r["gpu"] for r in captured["rows"]}
        self.assertNotIn("MI300X", gpus)
        self.assertEqual(gpus, {"H100", "H200", "A100", "B200"})
        self.assertEqual(len(captured["rows"]), 180)
        text = buf.getvalue()
        self.assertIn("[warn]", text)
        self.assertIn("mi300x/neo-cloud", text)
        self.assertIn("已跳过", text)
        self.assertIn("180", text)

    def test_fetch_error_on_one_slot_is_also_a_skip(self):
        captured = {}

        def fake_http(url, parse=None, **kw):
            if "gpu=h200" in url:
                raise RuntimeError("GET failed after 4 tries: %s (ValueError: no index points in page)" % url)
            seg = url.split("mainTab=")[1]
            return seg, [("2026-10-21", "2.00")]

        def fake_merge(path, fields, key, rows):
            captured["rows"] = rows
            return 10, len(rows)

        buf = io.StringIO()
        with mock.patch.object(fetch_all, "http_get", fake_http), \
                mock.patch.object(fetch_all, "merge_csv", fake_merge), \
                redirect_stderr(buf):
            res = fetch_all.fetch_gpu()
        self.assertEqual(res[0], "gpu_rental")
        self.assertNotIn("H200", {r["gpu"] for r in captured["rows"]})
        self.assertIn("h200/neo-cloud", buf.getvalue())
        self.assertIn("h200/neo-cloud", res[4])

    def test_every_slot_empty_still_fails_and_does_not_write(self):
        def fake_http(url, parse=None, **kw):
            gpu = url.split("gpu=")[1].split("&")[0]
            seg = url.split("mainTab=")[1]
            return parse(_page(gpu, seg, ""))

        with mock.patch.object(fetch_all, "http_get", fake_http), \
                mock.patch.object(fetch_all, "merge_csv") as merge:
            with self.assertRaises(RuntimeError) as ctx:
                fetch_all.fetch_gpu()
        merge.assert_not_called()
        msg = str(ctx.exception)
        self.assertIn("0 points parsed", msg)
        self.assertIn("mi300x/neo-cloud", msg)
        self.assertIn("h100/hyperscaler", msg)


if __name__ == "__main__":
    unittest.main()
