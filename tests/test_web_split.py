"""S3 测试：web 资源拆分完整性 + 本地静态服务加载 + 外置层回退。

全部用例可在 macOS 运行（不依赖 pywebview / Windows 平台）。
主题注入涉及 themes 目录写入，统一 mock 到临时目录，避免污染工作区。
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import webview_main  # noqa: E402

# 开发机常设 http_proxy 环境变量：本地回环请求显式绕过代理
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "web"

# app.js 原函数锚点（拆分零重构，函数名/ID 原样保留）
_JS_FUNCTION_ANCHORS = (
    "renderQuadrant", "openAdd", "openSettings", "applyTheme",
    "importThemeFile", "onDrop", "refreshAll", "quitApp",
)
# JS 模板字符串中动态生成的关键 DOM id
_JS_DOM_ANCHORS = ("dlg-title", "dlg-tags", "dlg-quads", "set-theme-select")


class _ThemeTmpMixin:
    """把 theme_loader.themes_dir / app_dir 指到临时目录，杜绝工作区副作用。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = pathlib.Path(self._tmp.name)
        patcher1 = mock.patch.object(
            webview_main.theme_loader, "themes_dir",
            lambda: self._tmp_path / "themes")
        patcher2 = mock.patch.object(
            webview_main.theme_loader, "app_dir",
            lambda: self._tmp_path)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self._tmp.cleanup)


class TestSplitIntegrity(unittest.TestCase):
    """拆分文件存在性与锚点完整性。"""

    def test_files_exist(self):
        for name in ("index.html", "app.css", "app.js"):
            path = WEB_DIR / name
            self.assertTrue(path.is_file(), f"{name} 缺失")
            self.assertGreater(path.stat().st_size, 0, f"{name} 为空")

    def test_css_split_integrity(self):
        css = (WEB_DIR / "app.css").read_text(encoding="utf-8")
        self.assertIn("/*__THEMES_CSS__*/", css, "主题占位符应保留在 app.css")
        self.assertIn(":root{", css, "程序级布局变量缺失")
        self.assertIn(".grid{", css, "四象限骨架样式缺失")
        self.assertNotIn("renderQuadrant", css, "app.css 不应残留业务 JS")
        self.assertNotIn("<script", css)

    def test_html_split_integrity(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        # 骨架关键 DOM
        for dom_id in ("splash", "grid", "tasks-0", "today-date",
                       "tag-panel", "count-0", "lock-btn"):
            self.assertIn(f'id="{dom_id}"', html, f"静态 DOM {dom_id} 缺失")
        self.assertIn("pywebview-drag-region", html)
        self.assertIn('data-quadrant="3"', html)
        # 模块化引用与注入占位
        self.assertIn('<link rel="stylesheet" href="app.css">', html)
        self.assertIn('<script src="app.js"></script>', html)
        self.assertIn("/*__THEMES_META__*/", html, "meta 注入占位应保留在 index.html")
        # 不含大段业务 JS
        self.assertNotIn("renderQuadrant", html)
        self.assertNotIn("pywebviewready", html)
        self.assertNotIn("<style>", html, "布局 CSS 应全部移入 app.css")

    def test_js_split_integrity(self):
        js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        for fn in _JS_FUNCTION_ANCHORS:
            self.assertIn(fn, js, f"函数 {fn} 未随业务 JS 迁入 app.js")
        self.assertGreaterEqual(
            sum(1 for fn in _JS_FUNCTION_ANCHORS if fn in js), 5,
            "关键函数锚点不足 5 个")
        for dom_id in _JS_DOM_ANCHORS:
            self.assertIn(dom_id, js, f"JS 内 DOM id {dom_id} 缺失")
        self.assertNotIn("<style", js)
        self.assertNotIn("/*__THEMES_CSS__*/", js)
        self.assertNotIn("/*__THEMES_META__*/", js, "meta 占位不应留在 app.js")


class TestRendering(_ThemeTmpMixin, unittest.TestCase):
    """服务端渲染：占位符注入正确、无逃逸。"""

    def test_render_index_injects_meta(self):
        html = webview_main.render_index_page()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("window.__PROMATHEMES__ = [", html, "主题清单注入失败")
        self.assertIn('"id": "paper"', html)
        self.assertIn('<script src="app.js"></script>', html)
        self.assertNotIn("/*__THEMES_META__*/", html, "占位符应已被替换")

    def test_render_css_injects_themes(self):
        css = webview_main.render_style_sheet()
        self.assertIn(".grid{", css, "程序布局样式丢失")
        self.assertIn("body.paper{", css, "内置主题 CSS 未注入")
        self.assertIn("/* ============ 主题（themes/ 目录可插拔） ============ */",
                      css)
        self.assertNotIn("/*__THEMES_CSS__*/", css, "占位符应已被替换")

    def test_meta_injection_no_script_breakout(self):
        """注入逃逸回归：meta JSON 内 </ 已转义，闭合标签数量不增。"""
        html = webview_main.render_index_page()
        # 合法闭合仅两处：注入占位 script 块 + app.js 引用标签
        self.assertEqual(html.count("</script>"), 2,
                         "主题清单注入疑似产生未转义的 </script>")


class TestResourceResolution(_ThemeTmpMixin, unittest.TestCase):
    """外置 web 层优先级与内置兜底。"""

    def test_no_outer_layer_falls_back_to_builtin(self):
        # tmp 下无 web/ → 命中内置 src/web
        path = webview_main._resolve_web_file("app.css")
        self.assertIsNotNone(path)
        self.assertEqual(path.resolve(), (WEB_DIR / "app.css").resolve())

    def test_outer_layer_wins(self):
        outer = self._tmp_path / "web"
        outer.mkdir(parents=True)
        probe = outer / "app.css"
        probe.write_text("/* OUTER-MARKER */", encoding="utf-8")
        path = webview_main._resolve_web_file("app.css")
        self.assertEqual(path.resolve(), probe.resolve())

    def test_missing_outer_file_falls_back(self):
        outer = self._tmp_path / "web"
        outer.mkdir(parents=True)
        (outer / "index.html").write_text("<html>x</html>", encoding="utf-8")
        # 外置层缺 app.js → 回退内置
        path = webview_main._resolve_web_file("app.js")
        self.assertEqual(path.resolve(), (WEB_DIR / "app.js").resolve())


class TestLocalServer(_ThemeTmpMixin, unittest.TestCase):
    """本地静态服务 smoke：端点、Content-Type、注入、404。"""

    def _start_server(self):
        server = webview_main._LocalWebServer()
        self.addCleanup(server.shutdown)
        return server

    def _get(self, base_url: str, path: str):
        try:
            resp = _NO_PROXY.open(base_url + path.lstrip("/"), timeout=5)
            body = resp.read()
            ctype = resp.headers.get("Content-Type")
            resp.close()
            return resp.status, ctype, body
        except urllib.error.HTTPError as exc:
            exc.close() if hasattr(exc, "close") else None
            return exc.code, exc.headers.get("Content-Type"), b""

    def test_root_serves_rendered_index(self):
        server = self._start_server()
        status, ctype, body = self._get(server.base_url, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"window.__PROMATHEMES__ = [", body, "meta 未注入")
        self.assertIn(b'<script src="app.js">', body)
        self.assertEqual(body.count(b"</script>"), 2, "注入逃逸")

    def test_index_html_alias(self):
        server = self._start_server()
        status, _, body = self._get(server.base_url, "/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"<!DOCTYPE html>", body)

    def test_css_endpoint_injects_themes(self):
        server = self._start_server()
        status, ctype, body = self._get(server.base_url, "/app.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        self.assertIn(b"body.paper{", body, "主题 CSS 未注入")
        self.assertIn(b".grid{", body)
        self.assertNotIn(b"/*__THEMES_CSS__*/", body)

    def test_js_endpoint_serves_business_logic(self):
        server = self._start_server()
        status, ctype, body = self._get(server.base_url, "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", ctype)
        self.assertIn(b"renderQuadrant", body)
        self.assertIn(b"openAdd", body)

    def test_unknown_path_404(self):
        server = self._start_server()
        status, _, _ = self._get(server.base_url, "/nope.css")
        self.assertEqual(status, 404)
        status2, _, _ = self._get(server.base_url, "/../app.js")
        self.assertEqual(status2, 404, "路径穿越不得命中资源")

    def test_no_store_header(self):
        server = self._start_server()
        resp = _NO_PROXY.open(server.base_url, timeout=5)
        try:
            self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        finally:
            resp.close()


class TestPlatformGuard(unittest.TestCase):
    """macOS 无 pywebview 时模块可 import，run() 安全返回。"""

    def test_module_importable_without_webview(self):
        self.assertTrue(hasattr(webview_main, "web_base_url"))

    def test_run_returns_when_webview_missing(self):
        if webview_main.webview is not None:
            self.skipTest("本机已安装 pywebview，守卫不生效")
        self.assertEqual(webview_main.run(), 2)


if __name__ == "__main__":
    unittest.main()
