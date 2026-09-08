"""系统层（单实例 / 托盘 / 全局热键）测试。

覆盖策略：
- 非 win32（macOS 开发机）：三个模块可 import、API 存在、降级路径行为正确
  （single_instance 视为主实例；tray/hotkey 为无操作）。
- 纯逻辑：热键 spec 解析/格式化往返、单实例调试绕过判断（参数化，不触系统）。
- Win32 专属路径（Mutex/Shell_NotifyIconW/RegisterHotKey 真实行为）无法在
  macOS 自动验证，对应手动清单见 plan/v2.0/s2-system-plan.md §9。
"""
from __future__ import annotations

import sys
import unittest

sys.platform  # noqa: B018 —— 断言以下测试运行在非 win32（本机 macOS）降级路径

import hotkey  # noqa: E402
import single_instance  # noqa: E402
import tray  # noqa: E402


# ---------------------------------------------------------------- 模块与 API
class ModuleImportTests(unittest.TestCase):
    """模块可 import 且关键 API 存在（macOS 降级路径的编译/形状检查）。"""

    def test_import_all_modules(self):
        self.assertTrue(callable(single_instance.SingleInstance))
        self.assertTrue(callable(tray.start))
        self.assertTrue(callable(hotkey.parse_hotkey))

    def test_single_instance_api_exposed(self):
        for name in ("MUTEX_NAME", "EVENT_NAME", "WINDOW_TITLE"):
            self.assertTrue(hasattr(single_instance, name), name)
        for name in ("bypass_requested", "find_window_by_title",
                     "activate_window_by_title"):
            self.assertTrue(callable(getattr(single_instance, name)), name)
        for name in ("acquire", "release", "set_activate_callback"):
            self.assertTrue(callable(getattr(single_instance, name)), name)
        for name in ("acquire", "set_activate_callback", "release"):
            self.assertTrue(
                callable(getattr(single_instance.SingleInstance, name)), name)
        inst = single_instance.SingleInstance()
        self.assertTrue(hasattr(inst, "is_primary"))

    def test_tray_api_exposed(self):
        for name in ("start", "stop"):
            self.assertTrue(callable(getattr(tray, name)), name)

    def test_hotkey_api_exposed(self):
        for name in ("DEFAULT_HOTKEY", "MOD_ALT", "MOD_CONTROL",
                     "MOD_SHIFT", "MOD_WIN"):
            self.assertTrue(hasattr(hotkey, name), name)
        for name in ("parse_hotkey", "format_hotkey", "register", "stop"):
            self.assertTrue(callable(getattr(hotkey, name)), name)

    def test_default_hotkey_value(self):
        self.assertEqual(hotkey.DEFAULT_HOTKEY, "Ctrl+Alt+S")


# ---------------------------------------------------------- 单实例降级路径
@unittest.skipIf(sys.platform == "win32", "win32 走真实 Mutex 路径，见手动清单")
class SingleInstanceDegradeTests(unittest.TestCase):
    """非 win32 下 acquire 返回主实例语义且不阻塞。"""

    def setUp(self):
        self.inst = single_instance.SingleInstance()

    def test_acquire_returns_primary(self):
        self.assertTrue(self.inst.acquire())
        self.assertTrue(self.inst.is_primary)

    def test_set_activate_callback_noop(self):
        self.assertTrue(self.inst.acquire())
        # 不抛即可（非 win32 不启动等待线程）
        self.inst.set_activate_callback(lambda: None)
        self.inst.set_activate_callback(None)

    def test_release_idempotent(self):
        self.inst.acquire()
        self.inst.release()
        self.inst.release()

    def test_module_level_acquire_returns_primary(self):
        # 模块级单例入口（main.py 与引擎接入层共用同一守卫）
        self.assertTrue(single_instance.acquire())
        # 不抛即可；随后可重复 release（幂等）
        single_instance.set_activate_callback(lambda: None)
        single_instance.release()

    def test_activate_window_by_title_noop(self):
        # 非 win32 恒 False 且不抛
        self.assertFalse(single_instance.activate_window_by_title("四象"))

    def test_find_window_by_title_noop(self):
        # 非 win32 恒 0 且不抛
        self.assertEqual(single_instance.find_window_by_title("四象"), 0)


class SingleInstanceBypassTests(unittest.TestCase):
    """调试绕过判断（纯逻辑，参数化 argv/environ，不触系统调用）。"""

    def _bypass(self, argv=None, env=None):
        return single_instance.bypass_requested(argv=argv or [],
                                                environ=env or {})

    def test_bypass_env_flag(self):
        self.assertTrue(
            self._bypass(env={"SIXIANG_NO_SINGLE_INSTANCE": "1"}))
        # 任意非空值都算（=1 / =true / 空串除外）
        self.assertTrue(
            self._bypass(env={"SIXIANG_NO_SINGLE_INSTANCE": "true"}))

    def test_bypass_empty_env_value_is_no(self):
        self.assertFalse(
            self._bypass(env={"SIXIANG_NO_SINGLE_INSTANCE": ""}))

    def test_bypass_argv_flag(self):
        self.assertTrue(self._bypass(argv=["--multi"]))
        self.assertTrue(self._bypass(argv=["python", "main.py", "--multi"]))
        # 其他参数不影响
        self.assertFalse(self._bypass(argv=["--debug"]))

    def test_bypass_defaults_false(self):
        self.assertFalse(self._bypass())

    def test_default_names(self):
        self.assertIn("Local\\", single_instance.MUTEX_NAME)
        self.assertIn("SIXIANG", single_instance.MUTEX_NAME)
        self.assertIn("Local\\", single_instance.EVENT_NAME)
        self.assertIn("SIXIANG", single_instance.EVENT_NAME)
        self.assertEqual(single_instance.WINDOW_TITLE, "四象")


# ------------------------------------------------------------ 热键 spec 纯逻辑
class HotkeyParseTests(unittest.TestCase):
    """parse_hotkey / format_hotkey：平台无关的纯解析逻辑。"""

    def test_parse_ctrl_alt_s(self):
        parsed = hotkey.parse_hotkey("Ctrl+Alt+S")
        self.assertEqual(parsed["mods"],
                         hotkey.MOD_CONTROL | hotkey.MOD_ALT)
        self.assertEqual(parsed["vk"], ord("S"))

    def test_parse_alias_and_case(self):
        # 别名 ctrl/control、全小写
        a = hotkey.parse_hotkey("control+shift+f5")
        b = hotkey.parse_hotkey("Ctrl+Shift+F5")
        self.assertEqual(a["mods"], b["mods"])
        self.assertEqual(a["vk"], b["vk"])
        self.assertEqual(a["vk"], 0x74)  # F5 = VK_F5 = 0x74

    def test_parse_order_insensitive(self):
        a = hotkey.parse_hotkey("Ctrl+Alt+S")
        b = hotkey.parse_hotkey("S+Alt+Ctrl")
        c = hotkey.parse_hotkey("alt+ctrl+s")
        for parsed in (a, b, c):
            self.assertEqual(parsed["mods"], a["mods"])
            self.assertEqual(parsed["vk"], a["vk"])

    def test_parse_digit(self):
        parsed = hotkey.parse_hotkey("Alt+0")
        self.assertEqual(parsed["vk"], ord("0"))
        self.assertEqual(parsed["mods"], hotkey.MOD_ALT)

    def test_parse_f12(self):
        parsed = hotkey.parse_hotkey("Ctrl+F12")
        self.assertEqual(parsed["vk"], 0x7B)  # VK_F12

    def test_parse_win_modifier(self):
        parsed = hotkey.parse_hotkey("Win+Alt+1")
        self.assertEqual(parsed["mods"],
                         hotkey.MOD_WIN | hotkey.MOD_ALT)
        self.assertEqual(parsed["vk"], ord("1"))

    def test_parse_invalid_raises(self):
        for bad in ("", "   ", "Ctrl+", "Unknown", "Ctrl+Alt+Unknown",
                    "Ctrl", "Alt+Ctrl", "Ctrl+Shift+Alt",
                    "Ctrl+Ctrl+S", "S+S+Alt"):
            with self.subTest(spec=bad):
                with self.assertRaises(ValueError):
                    hotkey.parse_hotkey(bad)

    def test_parse_modifier_after_key_ok(self):
        # 顺序不敏感：修饰符在主键之后同样合法（等价位或）
        parsed = hotkey.parse_hotkey("Ctrl+Alt+S+Shift")
        self.assertEqual(parsed["mods"],
                         hotkey.MOD_CONTROL | hotkey.MOD_ALT | hotkey.MOD_SHIFT)
        self.assertEqual(parsed["vk"], ord("S"))

    def test_format_roundtrip(self):
        parsed = hotkey.parse_hotkey("s+alt+ctrl")
        self.assertEqual(hotkey.format_hotkey(parsed), "Ctrl+Alt+S")
        # parse(format(parse(x))) 稳定
        again = hotkey.parse_hotkey(hotkey.format_hotkey(parsed))
        self.assertEqual(again["mods"], parsed["mods"])
        self.assertEqual(again["vk"], parsed["vk"])


# ------------------------------------------------------- tray/hotkey 降级路径
@unittest.skipIf(sys.platform == "win32", "win32 走真实托盘/热键路径，见手动清单")
class TrayDegradeTests(unittest.TestCase):
    """非 win32：tray 为 no-op，调用不抛且返回未启动。"""

    def test_start_noop(self):
        self.assertFalse(tray.start(lambda: 0, lambda: None))

    def test_start_noop_no_icon(self):
        self.assertFalse(tray.start(lambda: 0, lambda: None, icon_path="/x.ico"))

    def test_stop_noop(self):
        tray.stop()
        tray.stop()  # 幂等


@unittest.skipIf(sys.platform == "win32", "win32 走真实热键路径，见手动清单")
class HotkeyDegradeTests(unittest.TestCase):
    """非 win32：register 返回明确错误且不抛，stop no-op。"""

    def test_register_noop(self):
        ok, err = hotkey.register(hotkey.DEFAULT_HOTKEY, lambda: None)
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_register_noop_invalid_spec(self):
        ok, err = hotkey.register("bad spec !", lambda: None)
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_stop_noop(self):
        hotkey.stop()
        hotkey.stop()  # 幂等


@unittest.skipUnless(sys.platform == "win32", "需要真实托盘")
class TrayWin32StartTests(unittest.TestCase):
    """Python 3.13+ 无 wintypes.WNDCLASSW 时，托盘曾静默失败。"""

    def tearDown(self):
        tray.stop()

    def test_start_returns_true(self):
        import styles
        ok = tray.start(lambda: 0, lambda: None,
                        icon_path=styles.ensure_app_icon())
        self.assertTrue(ok)


@unittest.skipUnless(sys.platform == "win32", "需要真实热键")
class HotkeyWin32StartTests(unittest.TestCase):
    def tearDown(self):
        hotkey.stop()

    def test_register_returns_true(self):
        ok, err = hotkey.register("Ctrl+Alt+Shift+F9", lambda: None)
        self.assertTrue(ok, err)


if __name__ == "__main__":
    unittest.main()
