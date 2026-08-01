"""
图片浏览面板：缩略图网格 + 搜索栏 + 分页
"""

import tkinter as tk
from tkinter import ttk
import threading
import io
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageTk

from utils import make_thumbnail, extract_leaf_name, format_file_size
from obs_client import ObsError


# 缩略图显示尺寸
THUMB_W, THUMB_H = 140, 120
COLS = 3


class BrowserPanel(ttk.Frame):
    """图片浏览面板"""

    def __init__(self, parent, client_wrapper, bucket, on_select_image):
        super().__init__(parent)
        self._client = client_wrapper
        self._bucket = bucket
        self._on_select_image = on_select_image

        # 状态
        self._objects = []           # 当前页的对象列表
        self._thumbnails = {}        # key -> ImageTk.PhotoImage
        self._selected_key = None
        self._search_after_id = None
        self._current_marker = ""
        self._page_history = [""]    # marker 历史栈（支持返回上一页）
        self._page_size = 50
        self._prefix = ""

        # 线程池
        self._executor = ThreadPoolExecutor(max_workers=4)

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        # 搜索栏
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(search_frame, text="🔍").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_changed)
        self._search_entry = ttk.Entry(search_frame, textvariable=self._search_var)
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        ttk.Button(search_frame, text="清除", command=self._clear_search,
                   width=6).pack(side=tk.LEFT, padx=(4, 0))

        # 信息标签
        self._info_label = ttk.Label(self, text="")
        self._info_label.pack(fill=tk.X, padx=4)

        # 画布 + 滚动条（缩略图网格）
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self._canvas = tk.Canvas(canvas_frame, bg="#f0f0f0", highlightthickness=0)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 内部 frame
        self._grid_frame = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_frame, anchor=tk.NW)
        self._grid_frame.bind("<Configure>", self._on_grid_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)

        # 分页栏
        page_frame = ttk.Frame(self)
        page_frame.pack(fill=tk.X, padx=4, pady=4)

        self._prev_btn = ttk.Button(page_frame, text="◀ 上一页", command=self._prev_page)
        self._prev_btn.pack(side=tk.LEFT)

        self._page_label = ttk.Label(page_frame, text="")
        self._page_label.pack(side=tk.LEFT, padx=10)

        self._next_btn = ttk.Button(page_frame, text="下一页 ▶", command=self._next_page)
        self._next_btn.pack(side=tk.LEFT)

        ttk.Label(page_frame, text="每页:").pack(side=tk.RIGHT, padx=(10, 0))
        self._page_size_combo = ttk.Combobox(page_frame, values=["20", "50", "100"],
                                             width=5, state="readonly")
        self._page_size_combo.set(str(self._page_size))
        self._page_size_combo.bind("<<ComboboxSelected>>", self._on_page_size_changed)
        self._page_size_combo.pack(side=tk.RIGHT)

        # 进度条
        self._progress = ttk.Progressbar(self, mode="indeterminate")
        self._progress.pack(fill=tk.X, padx=4)

    # ---------- 搜索 ----------
    def _on_search_changed(self, *_):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(300, self._do_search)

    def _do_search(self):
        self._prefix = self._search_var.get().strip()
        self._current_marker = ""
        self._page_history = [""]
        self._load_page()

    def _clear_search(self):
        self._search_var.set("")
        self._prefix = ""
        self._current_marker = ""
        self._page_history = [""]
        self._load_page()

    # ---------- 分页 ----------
    def _prev_page(self):
        if len(self._page_history) >= 2:
            self._page_history.pop()  # 移除当前页
            self._current_marker = self._page_history[-1]
            self._load_page()

    def _next_page(self):
        # marker 已经在 _load_page 完成后更新
        self._load_page()

    def _on_page_size_changed(self, *_):
        self._page_size = int(self._page_size_combo.get())
        self._current_marker = ""
        self._page_history = [""]
        self._load_page()

    # ---------- 核心：加载页面 ----------
    def _load_page(self):
        self._set_loading(True)
        threading.Thread(target=self._do_list_objects, daemon=True).start()

    def _do_list_objects(self):
        try:
            result = self._client.list_images(
                self._bucket,
                prefix=self._prefix,
                marker=self._current_marker,
                max_keys=self._page_size
            )
            self.after(0, lambda: self._on_list_loaded(result))
        except ObsError as e:
            msg = str(e)
            self.after(0, lambda m=msg: self._on_list_error(m))

    def _on_list_loaded(self, result):
        self._objects = result["objects"]
        # 更新分页状态
        if result.get("next_marker") and result["next_marker"] != self._current_marker:
            self._current_marker = result["next_marker"]
            if not self._page_history or self._page_history[-1] != self._current_marker:
                self._page_history.append(self._current_marker)

        self._update_pagination_buttons(result)
        self._render_thumbnails()
        self._set_loading(False)

    def _on_list_error(self, error_msg):
        self._set_loading(False)
        self._info_label.configure(text=f"加载失败: {error_msg}")

    def _update_pagination_buttons(self, result):
        self._prev_btn.configure(state=tk.NORMAL if len(self._page_history) >= 2 else tk.DISABLED)
        self._next_btn.configure(state=tk.NORMAL if result.get("is_truncated") else tk.DISABLED)
        page_num = len(self._page_history)
        self._page_label.configure(text=f"第 {page_num} 页  ({len(self._objects)} 张图片)")

    def _render_thumbnails(self):
        # 清除旧缩略图
        for widget in self._grid_frame.winfo_children():
            widget.destroy()
        self._thumbnails.clear()

        if not self._objects:
            placeholder = ttk.Label(self._grid_frame, text="暂无图片", foreground="gray",
                                    font=("Microsoft YaHei", 12))
            placeholder.grid(row=0, column=0, padx=60, pady=40)
            self._info_label.configure(text="暂无图片")
            return

        self._info_label.configure(text=f"共找到 {len(self._objects)} 张图片，正在加载缩略图...")

        # 异步加载所有缩略图
        for i, obj in enumerate(self._objects):
            row, col = divmod(i, COLS)
            placeholder_text = extract_leaf_name(obj["key"])
            # 占位标签
            label = ttk.Label(self._grid_frame, text=placeholder_text + "\n加载中...",
                              relief=tk.RIDGE, anchor=tk.CENTER, width=18, background="#e0e0e0")
            label.grid(row=row, column=col, padx=3, pady=3, sticky=tk.NSEW)
            label.bind("<Button-1>", lambda e, k=obj["key"]: self._on_thumbnail_click(k))
            self._executor.submit(self._load_single_thumbnail, obj, i)

        # 更新画布滚动区域
        self._grid_frame.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _load_single_thumbnail(self, obj, index):
        try:
            image_bytes = self._client.get_object_bytes(self._bucket, obj["key"])
            thumb = make_thumbnail(image_bytes)
            if thumb:
                photo = ImageTk.PhotoImage(thumb)
                self.after(0, lambda: self._replace_thumbnail_photo(index, obj["key"], photo, obj))
            else:
                self.after(0, lambda: self._replace_thumbnail_text(index, obj["key"], "无法预览"))
        except Exception:
            self.after(0, lambda: self._replace_thumbnail_text(index, obj["key"], "加载失败"))

    def _replace_thumbnail_photo(self, index, key, photo, obj):
        row, col = divmod(index, COLS)
        # 销毁旧 widget
        for widget in self._grid_frame.grid_slaves(row=row, column=col):
            widget.destroy()

        # 创建新的缩略图卡片
        card = tk.Frame(self._grid_frame, relief=tk.RIDGE, bd=1, bg="white")
        card.grid(row=row, column=col, padx=3, pady=3, sticky=tk.NSEW)

        name = extract_leaf_name(key, 18)
        img_label = tk.Label(card, image=photo, bg="white")
        img_label.image = photo  # 保持引用
        img_label.pack(padx=2, pady=(2, 0))

        text_label = tk.Label(card, text=name, font=("Microsoft YaHei", 8),
                              bg="white", wraplength=130)
        text_label.pack(pady=(0, 2))

        # 绑定点击
        for w in (card, img_label, text_label):
            w.bind("<Button-1>", lambda e, k=key: self._on_thumbnail_click(k))

        self._thumbnails[key] = photo
        self._info_label.configure(text=f"共 {len(self._objects)} 张图片")

    def _replace_thumbnail_text(self, index, key, text):
        row, col = divmod(index, COLS)
        for widget in self._grid_frame.grid_slaves(row=row, column=col):
            widget.destroy()
        label = ttk.Label(self._grid_frame, text=f"{extract_leaf_name(key)}\n[{text}]",
                          relief=tk.RIDGE, anchor=tk.CENTER, width=18, background="#ffe0e0")
        label.grid(row=row, column=col, padx=3, pady=3, sticky=tk.NSEW)
        label.bind("<Button-1>", lambda e, k=key: self._on_thumbnail_click(k))

    # ---------- 事件 ----------
    def _on_thumbnail_click(self, key):
        self._selected_key = key
        self._on_select_image(key)

    def _on_grid_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _set_loading(self, loading):
        if loading:
            self._progress.start(10)
        else:
            self._progress.stop()

    def refresh(self):
        """外部调用：刷新列表"""
        self._load_page()

    def get_selected_key(self):
        return self._selected_key
