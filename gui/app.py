"""
主窗口：连接页 → 主页面（左侧预览 + 右侧搜索/控制）
"""

import tkinter as tk
from tkinter import ttk, messagebox

from config import load_config, save_config
from gui.connection_panel import ConnectionPanel
from gui.preview_panel import PreviewPanel
from gui.control_panel import ControlPanel


class App(tk.Tk):
    """OBS 图片浏览器主窗口"""

    def __init__(self):
        super().__init__()

        self.title("华为云 OBS 图片浏览器")
        self.minsize(900, 600)

        self._config = load_config()

        # 恢复窗口位置
        geometry = self._config.get("preferences", {}).get("window_geometry", "1100x700")
        self.geometry(geometry)

        # 当前状态
        self._client_wrapper = None
        self._bucket = ""

        self._build_menu()
        self._show_connection_panel()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 菜单 ----------
    def _build_menu(self):
        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="切换连接", command=self._disconnect)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

    # ---------- 页面切换 ----------
    def _show_connection_panel(self):
        self._clear_main()
        self._connection_panel = ConnectionPanel(self, on_connected=self._on_connected)
        self._connection_panel.pack(fill=tk.BOTH, expand=True)

    def _show_main_page(self):
        self._clear_main()

        # 左右分栏
        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # 左侧：图片预览
        self._preview_panel = PreviewPanel(pw, self._client_wrapper, self._bucket)
        pw.add(self._preview_panel, weight=3)

        # 右侧：搜索 + 控制
        self._control_panel = ControlPanel(
            pw, self._client_wrapper, self._bucket,
            preview_panel=self._preview_panel,
            on_disconnect=self._disconnect
        )
        # 恢复上次的下载路径
        last_path = self._config.get("preferences", {}).get("last_download_path", "")
        if last_path:
            self._control_panel.set_download_path(last_path)
        pw.add(self._control_panel, weight=1)

    def _clear_main(self):
        for widget in self.winfo_children():
            widget.destroy()

    # ---------- 回调 ----------
    def _on_connected(self, client_wrapper, bucket):
        self._client_wrapper = client_wrapper
        self._bucket = bucket
        self.title(f"华为云 OBS 图片浏览器 - {bucket}")
        self._show_main_page()

    def _disconnect(self):
        if self._client_wrapper:
            self._client_wrapper.disconnect()
            self._client_wrapper = None
        self._bucket = ""
        self.title("华为云 OBS 图片浏览器")
        self._show_connection_panel()

    def _show_about(self):
        messagebox.showinfo("关于", "华为云 OBS 图片浏览器 v1.0\n\n"
                                     "功能：连接华为云 OBS，按名称搜索图片并预览/下载")

    def _on_close(self):
        try:
            geometry = self.geometry()
            self._config["preferences"]["window_geometry"] = geometry
            if hasattr(self, "_control_panel") and self._control_panel:
                self._config["preferences"]["last_download_path"] = self._control_panel.get_download_path()
            save_config(self._config)
        except Exception:
            pass

        if self._client_wrapper:
            self._client_wrapper.disconnect()

        self.destroy()
