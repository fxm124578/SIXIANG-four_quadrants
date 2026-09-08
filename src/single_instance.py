"""进程单实例：重复启动只唤醒已有实例，二次启动进程秒退。

Windows 实现：
- 命名 Mutex（Local\\SIXIANG.SingleInstance）判定主实例：CreateMutexW 返回
  ERROR_ALREADY_EXISTS 即存在主实例。
- 二次实例先 FindWindowW 按窗口标题「四象」找主窗口 → ShowWindow(SW_RESTORE/
  SW_SHOW) + SetForegroundWindow 直接唤醒；主窗口尚未创建完成的竞态用命名
  auto-reset 事件（Local\\SIXIANG.Activate）兜底：二次实例 SetEvent 后退出
  （exit code 0），主实例在窗口就绪后调用 set_activate_callback 注册回调，
  随后才启动后台等待线程消费事件。auto-reset 事件在无等待者时 SetEvent 会
  保持 signaled，注册回调后首个 WaitForSingleObject 立即返回，信号不丢失。
- 调试绕过：环境变量 SIXIANG_NO_SINGLE_INSTANCE=1 或命令行参数 --multi 时
  跳过单实例（便于开发多开与测试）。

非 win32（macOS 开发机）：模块可正常 import；acquire() 返回“无单实例语义”
的降级结果（is_primary=True 且不阻塞），保证 macOS 上测试与后续流程可跑。
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, Dict, List, Optional

# 命名对象（Local\\ 作用域：仅当前登录会话，安装级应用常用；多用户不串扰）
MUTEX_NAME = r"Local\SIXIANG.SingleInstance"
EVENT_NAME = r"Local\SIXIANG.Activate"
WINDOW_TITLE = "四象"

# win32 常量（仅 win32 路径使用；常量定义本身与平台无关，便于单测）
_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_SW_SHOW = 5
_SW_RESTORE = 9
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0
_WAIT_FAILED = 0xFFFFFFFF


def bypass_requested(argv: Optional[List[str]] = None,
                     environ: Optional[Dict[str, str]] = None) -> bool:
    """是否跳过单实例语义（调试/测试多开）。

    纯逻辑函数，argv/environ 均可注入以便单测；
    缺省分别取 sys.argv[1:] 与 os.environ。
    """
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    environ = dict(environ) if environ is not None else {}
    if (environ.get("SIXIANG_NO_SINGLE_INSTANCE") or "").strip():
        return True
    return "--multi" in argv


def find_window_by_title(title: str = WINDOW_TITLE) -> int:
    """win32：按窗口标题返回主窗口句柄（hwnd），找不到或非 win32 返回 0。

    托盘/热键等后台线程每次现查，避免持有跨重启（模式切换重建窗口）
    后失效的旧句柄。
    """
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        hwnd = user32.FindWindowW(None, title)
        return int(hwnd or 0)
    except (AttributeError, OSError):
        return 0


def activate_window_by_title(title: str = WINDOW_TITLE) -> bool:
    """win32：按窗口标题找主窗口，恢复显示并置前。

    ShowWindow(SW_RESTORE) 恢复最小化窗口；ShowWindow(SW_SHOW) 兜底恢复
    withdraw/隐藏（托盘常驻）状态；随后 SetForegroundWindow 置前。
    找不到窗口或非 win32 返回 False。SetForegroundWindow 受系统前台锁约束，
    个别情况只闪任务栏，属系统降级行为（手动验证清单已注明）。
    """
    if sys.platform != "win32":
        return False
    hwnd = find_window_by_title(title)
    if not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.ShowWindow(hwnd, _SW_SHOW)
        user32.SetForegroundWindow(hwnd)
        return True
    except (AttributeError, OSError):
        return False


class SingleInstance:
    """单实例守卫：acquire() 判定主/次，主实例持有 Mutex 直到进程退出。"""

    def __init__(self, mutex_name: str = MUTEX_NAME,
                 event_name: str = EVENT_NAME,
                 title: str = WINDOW_TITLE) -> None:
        # 仅保存参数，不在 __init__ 触碰任何系统调用（可安全构造与单测）
        self.mutex_name = mutex_name
        self.event_name = event_name
        self.title = title
        self.is_primary = True
        self._mutex_handle: Optional[int] = None
        self._event_handle: Optional[int] = None
        self._waiter_started = False
        self._activate_callback: Optional[Callable[[], None]] = None
        self._waiter: Optional[threading.Thread] = None

    # ------------------------------------------------------------ 主流程
    def acquire(self) -> bool:
        """判定单实例归属。

        返回 True 表示本进程是主实例（继续启动）；
        返回 False 表示已有主实例（本进程已尽力唤醒它，应退出，exit 0）。
        非 win32 / 调试绕过 / 系统调用异常 → 一律按主实例继续（不阻断启动）。
        """
        if sys.platform != "win32" or bypass_requested():
            self.is_primary = True
            return True
        return self._acquire_win32()

    def _acquire_win32(self) -> bool:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateEventW.restype = ctypes.c_void_p
        kernel32.OpenEventW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

        mutex = kernel32.CreateMutexW(None, False, self.mutex_name)
        if not mutex:
            # 创建失败（权限等极端情况）：降级为主实例继续，避免应用起不来
            self.is_primary = True
            return True
        if kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
            # 主实例：持有 Mutex（进程退出自动释放），并创建激活事件供二次实例
            self._mutex_handle = mutex
            event = kernel32.CreateEventW(None, False, False, self.event_name)
            self._event_handle = event if event else None
            self.is_primary = True
            return True
        # 二次实例：先直接唤醒主窗口；窗口尚未创建则 SetEvent 兜底
        kernel32.CloseHandle(mutex)
        self.is_primary = False
        if activate_window_by_title(self.title):
            return False
        event = kernel32.OpenEventW(
            _EVENT_MODIFY_STATE, False, self.event_name)
        if event:
            kernel32.SetEvent.argtypes = [ctypes.c_void_p]
            kernel32.SetEvent(event)
            kernel32.CloseHandle(event)
        return False

    def set_activate_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """注册「收到二次实例激活事件后执行」的回调（通常=显示主窗口）。

        仅主实例有效；回调注册后才启动后台等待线程——二次实例若在主窗口创建
        前 SetEvent，事件保持 signaled，启动后立即被消费（竞态兜底）。
        回调运行于守护等待线程，需线程安全（纯 user32 操作可跨线程）。
        """
        self._activate_callback = callback
        if sys.platform != "win32" or not self.is_primary:
            return
        if self._waiter_started or callback is None:
            return
        if not self._event_handle:
            return
        self._waiter_started = True
        self._waiter = threading.Thread(
            target=self._wait_loop,
            args=(self._event_handle,),
            daemon=True,
            name="sixiang-single-instance",
        )
        self._waiter.start()

    def _wait_loop(self, event_handle: int) -> None:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.WaitForSingleObject.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        while True:
            rc = kernel32.WaitForSingleObject(event_handle, _INFINITE)
            if rc not in (_WAIT_OBJECT_0,):
                return  # 句柄失效（进程退出前不会发生）
            callback = self._activate_callback
            if callback is None:
                continue
            try:
                callback()
            except Exception:
                # 回调异常不影响等待线程，下一次激活仍可触发
                continue

    def release(self) -> None:
        """释放持有的 Mutex（幂等）。进程退出前调用。

        注意：激活事件句柄不在此关闭——等待线程正阻塞在它上面，句柄关闭
        行为未定义；进程退出时由系统统一回收（守护线程随之终止）。
        """
        if not self._mutex_handle:
            return
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        try:
            kernel32.CloseHandle(self._mutex_handle)
        finally:
            self._mutex_handle = None


# ------------------------------------------------------------ 模块级单例入口
# 进程内至多一个守卫：main.py acquire 与引擎层 set_activate_callback 必须
# 命中同一实例，故提供模块级便捷函数（类仍保留，供参数化与单测）。
_guard: Optional[SingleInstance] = None


def acquire() -> bool:
    """模块级单实例入口：进程主入口最先调用（见 main.main()）。"""
    global _guard
    if _guard is None:
        _guard = SingleInstance()
    return _guard.acquire()


def set_activate_callback(callback: Optional[Callable[[], None]]) -> None:
    """模块级：注册激活回调（窗口就绪后调用；未 acquire 时安全 no-op）。"""
    if _guard is not None:
        _guard.set_activate_callback(callback)


def release() -> None:
    """模块级：释放守卫（幂等）。"""
    if _guard is not None:
        _guard.release()
