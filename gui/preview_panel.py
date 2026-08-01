"""
预览面板：全尺寸图片预览 + 图片信息
"""

import tkinter as tk
from tkinter import ttk
import threading
import io
from PIL import Image, ImageTk

from utils import filename_from_key, format_file_size


class PreviewPanel(ttk.Frame):
    """图片预览面板"""

    def __init__(self, parent, client_wrapper, bucket):
        super().__init__(parent)
        self._client = client_wrapper
        self._bucket = bucket
        self._current_key = None
        self._original_image = None   # PIL.Image
        self._displayed_photo = None  # ImageTk.PhotoImage
        self._zoom_scale = 1.0
        self._fit_mode = True         # 当前是否处于"适应窗口"模式

        self._build_ui()

    def _build_ui(self):
        # 顶部信息栏
        self._info_frame = ttk.Frame(self)
        self._info_frame.pack(fill=tk.X, padx=4, pady=2)

        self._filename_label = ttk.Label(self._info_frame, text="",
                                         font=("Microsoft YaHei", 10, "bold"))
        self._filename_label.pack(side=tk.LEFT)

        self._size_label = ttk.Label(self._info_frame, text="", foreground="gray")
        self._size_label.pack(side=tk.RIGHT, padx=(10, 0))

        self._dim_label = ttk.Label(self._info_frame, text="", foreground="gray")
        self._dim_label.pack(side=tk.RIGHT)

        # 分隔线
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=2)

        # 预览画布
        self._canvas = tk.Canvas(self, bg="#2d2d2d", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._canvas.bind("<MouseWheel>", self._on_zoom)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # 底部操作栏
        action_frame = ttk.Frame(self)
        action_frame.pack(fill=tk.X, padx=4, pady=2)

        self._zoom_label = ttk.Label(action_frame, text="100%", width=6)
        self._zoom_label.pack(side=tk.LEFT)

        ttk.Button(action_frame, text="放大", command=self._zoom_in, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_frame, text="缩小", command=self._zoom_out, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_frame, text="适应", command=self._zoom_fit, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_frame, text="原始", command=self._zoom_reset, width=6).pack(side=tk.LEFT, padx=2)

        # 首次加载提示
        self._show_placeholder("选择左侧图片进行预览")

    # ---------- 加载图片（OBS）----------
    def load_image(self, object_key: str):
        """从 OBS 加载指定 key 的图片"""
        if object_key == self._current_key:
            return

        self._current_key = object_key
        self._original_image = None
        self._displayed_photo = None
        self._zoom_scale = 1.0

        self._canvas.delete("all")
        self._show_placeholder("正在从 OBS 加载...")
        self._filename_label.configure(text=filename_from_key(object_key))
        self._size_label.configure(text="")
        self._dim_label.configure(text="")

        threading.Thread(target=self._do_load_obs, args=(object_key,), daemon=True).start()

    def _do_load_obs(self, object_key):
        try:
            image_bytes = self._client.get_object_bytes(self._bucket, object_key)
            img = Image.open(io.BytesIO(image_bytes))
            self.after(0, lambda: self._on_image_loaded(img, object_key))
        except Exception as e:
            msg = f"OBS 加载失败: {e}"
            self.after(0, lambda m=msg: self._show_placeholder(m))

    # ---------- 加载本地文件 ----------
    def load_local(self, filepath: str, display_name: str = ""):
        """从本地文件加载图片"""
        self._current_key = display_name or filepath
        self._original_image = None
        self._displayed_photo = None
        self._zoom_scale = 1.0

        self._canvas.delete("all")
        self._show_placeholder("正在加载本地图片...")
        name = display_name or filepath.replace("\\", "/").split("/")[-1]
        self._filename_label.configure(text=name)
        self._size_label.configure(text="本地文件")
        self._dim_label.configure(text="")

        threading.Thread(target=self._do_load_local, args=(filepath,), daemon=True).start()

    def _do_load_local(self, filepath):
        try:
            img = Image.open(filepath)
            self.after(0, lambda: self._on_image_loaded(img, filepath))
        except Exception as e:
            msg = f"本地加载失败: {e}"
            self.after(0, lambda m=msg: self._show_placeholder(m))

    def _on_image_loaded(self, img, source):
        self._original_image = img
        self._size_label.configure(text="")
        self._dim_label.configure(text=f"{img.width} × {img.height}")
        self._zoom_fit()

    # ---------- 缩放 ----------
    def _zoom_in(self):
        self._fit_mode = False
        self._zoom_scale *= 1.25
        self._apply_zoom()

    def _zoom_out(self):
        self._fit_mode = False
        self._zoom_scale *= 0.8
        self._apply_zoom()

    def _zoom_fit(self):
        """等比缩放使图片占画布 80%（小图放大，大图缩小）"""
        if not self._original_image:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        # 可用区域为画布的 80%，留 10% 边距
        avail_w = int(cw * 0.8)
        avail_h = int(ch * 0.8)
        iw, ih = self._original_image.size
        self._zoom_scale = min(avail_w / iw, avail_h / ih)
        self._fit_mode = True
        self._apply_zoom()

    def _zoom_reset(self):
        """回到 100% 原始尺寸"""
        self._zoom_scale = 1.0
        self._fit_mode = False
        self._apply_zoom()

    def _on_zoom(self, event):
        """鼠标滚轮等比缩放"""
        if not self._original_image:
            return
        self._fit_mode = False
        if event.delta > 0:
            self._zoom_scale *= 1.1
        else:
            self._zoom_scale *= 0.9
        self._zoom_scale = max(0.05, min(10.0, self._zoom_scale))
        self._apply_zoom()

    def _apply_zoom(self):
        """等比缩放并居中显示"""
        if not self._original_image:
            return
        iw, ih = self._original_image.size
        new_w = int(iw * self._zoom_scale)
        new_h = int(ih * self._zoom_scale)

        # 等比例缩放
        resized = self._original_image.resize((new_w, new_h), Image.LANCZOS)
        self._displayed_photo = ImageTk.PhotoImage(resized)

        self._canvas.delete("all")
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        # 居中显示
        x = max((cw - new_w) // 2, 0)
        y = max((ch - new_h) // 2, 0)
        self._canvas.create_image(x, y, anchor=tk.NW, image=self._displayed_photo)

        pct = int(self._zoom_scale * 100)
        self._zoom_label.configure(text=f"{pct}%")

    def _on_canvas_resize(self, event):
        """窗口大小变化时，若处于适应模式则自动重新适配"""
        if self._original_image and self._fit_mode:
            self._zoom_fit()

    # ---------- 辅助 ----------
    def _show_placeholder(self, text: str):
        self._canvas.delete("all")
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 10:
            cw, ch = 400, 300
        # 在中间画文字
        self._canvas.create_text(
            cw // 2, ch // 2, text=text,
            fill="#888888", font=("Microsoft YaHei", 12)
        )

    def show_status(self, text: str):
        """在预览区中央显示临时状态文字"""
        if self._original_image and self._displayed_photo:
            return  # 有图片时不覆盖
        self._show_placeholder(text)

    def get_current_key(self):
        """返回当前预览的图片 key"""
        return self._current_key

    def clear(self):
        self._current_key = None
        self._original_image = None
        self._displayed_photo = None
        self._canvas.delete("all")
        self._show_placeholder("选择左侧图片进行预览")
        self._filename_label.configure(text="")
        self._size_label.configure(text="")
        self._dim_label.configure(text="")
