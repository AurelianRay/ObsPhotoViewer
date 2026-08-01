"""
下载面板：本地文件夹选择 + 下载队列 + 进度
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
from queue import Queue

from utils import filename_from_key, format_file_size
from obs_client import ObsError, ObsNetworkError


class DownloadPanel(ttk.Frame):
    """下载管理面板"""

    def __init__(self, parent, client_wrapper, bucket, get_selected_keys):
        super().__init__(parent)
        self._client = client_wrapper
        self._bucket = bucket
        self._get_selected_keys = get_selected_keys  # callback: 返回选中的 key 列表

        # 下载队列
        self._queue: list[tuple[str, str, str]] = []  # [(key, local_path, status), ...]
        self._queue_items = {}  # key -> tree item id
        self._download_running = False
        self._cancel_flag = threading.Event()

        self._build_ui()

    def _build_ui(self):
        # 本地文件夹
        folder_frame = ttk.LabelFrame(self, text="本地保存路径", padding=4)
        folder_frame.pack(fill=tk.X, padx=4, pady=4)

        path_frame = ttk.Frame(folder_frame)
        path_frame.pack(fill=tk.X)

        self._path_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self._path_entry = ttk.Entry(path_frame, textvariable=self._path_var)
        self._path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(path_frame, text="浏览...", command=self._browse_folder,
                   width=8).pack(side=tk.RIGHT, padx=(4, 0))

        # 下载队列列表
        queue_frame = ttk.LabelFrame(self, text="下载队列", padding=4)
        queue_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        columns = ("filename", "size", "status")
        self._tree = ttk.Treeview(queue_frame, columns=columns, show="headings",
                                  height=6, selectmode=tk.EXTENDED)
        self._tree.heading("filename", text="文件名")
        self._tree.heading("size", text="大小")
        self._tree.heading("status", text="状态")
        self._tree.column("filename", width=120, minwidth=80)
        self._tree.column("size", width=60, minwidth=50, anchor=tk.CENTER)
        self._tree.column("status", width=80, minwidth=60, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 底部控制
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill=tk.X, padx=4, pady=4)

        self._add_btn = ttk.Button(ctrl_frame, text="添加到队列", command=self._add_to_queue)
        self._add_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._download_btn = ttk.Button(ctrl_frame, text="开始下载", command=self._start_download)
        self._download_btn.pack(side=tk.LEFT, padx=4)

        self._cancel_btn = ttk.Button(ctrl_frame, text="取消", command=self._cancel_download,
                                      state=tk.DISABLED)
        self._cancel_btn.pack(side=tk.LEFT, padx=4)

        ttk.Button(ctrl_frame, text="清空队列", command=self._clear_queue,
                   width=8).pack(side=tk.RIGHT)

        # 进度条
        self._progress = ttk.Progressbar(self, mode="determinate", length=200)
        self._progress.pack(fill=tk.X, padx=4, pady=(0, 4))

        self._progress_label = ttk.Label(self, text="")
        self._progress_label.pack(padx=4)

    # ---------- 操作 ----------
    def _browse_folder(self):
        folder = filedialog.askdirectory(title="选择保存目录")
        if folder:
            self._path_var.set(folder)

    def _add_to_queue(self):
        keys = self._get_selected_keys()
        if not keys:
            # 尝试获取当前预览的单张图片
            messagebox.showinfo("提示", "请先在左侧缩略图列表中勾选要下载的图片")
            return

        folder = self._path_var.get()
        if not os.path.isdir(folder):
            messagebox.showwarning("提示", "请选择有效的本地保存路径")
            return

        added = 0
        for key in keys:
            if key in self._queue_items:
                continue  # 已在队列中
            local_path = os.path.join(folder, filename_from_key(key))
            item_id = self._tree.insert("", tk.END, values=(
                filename_from_key(key), "", "等待中"
            ))
            self._queue.append((key, local_path, "等待中"))
            self._queue_items[key] = item_id
            added += 1

        if added > 0:
            self._progress_label.configure(text=f"已添加 {len(self._queue)} 个任务到队列")

    def _get_selected_keys(self):
        """获取选中的 key 列表"""
        return self._get_selected_keys()

    def _start_download(self):
        if not self._queue:
            messagebox.showinfo("提示", "下载队列为空")
            return
        if self._download_running:
            return

        # 只下载等待中和失败的
        pending = [(k, p) for k, p, s in self._queue if s in ("等待中", "失败")]
        if not pending:
            messagebox.showinfo("提示", "没有需要下载的任务")
            return

        self._download_running = True
        self._cancel_flag.clear()
        self._download_btn.configure(state=tk.DISABLED)
        self._cancel_btn.configure(state=tk.NORMAL)
        self._progress.configure(maximum=len(pending), value=0)

        threading.Thread(target=self._do_download, args=(pending,), daemon=True).start()

    def _do_download(self, pending):
        success = 0
        fail = 0
        total = len(pending)

        for i, (key, local_path) in enumerate(pending):
            if self._cancel_flag.is_set():
                self.after(0, lambda: self._update_queue_status(key, "已取消"))
                break

            self.after(0, lambda k=key: self._update_queue_status(k, "下载中..."))
            self.after(0, lambda v=i: self._progress.configure(value=v))

            retry = 0
            while retry < 3:
                try:
                    self._client.download_file(self._bucket, key, local_path)
                    self.after(0, lambda k=key: self._update_queue_status(k, "✓ 完成"))
                    success += 1
                    break
                except ObsNetworkError:
                    retry += 1
                    if retry >= 3:
                        self.after(0, lambda k=key: self._update_queue_status(k, "失败"))
                        fail += 1
                    else:
                        time.sleep(2 ** retry)
                except Exception as e:
                    self.after(0, lambda k=key, e=str(e): self._update_queue_status(k, f"失败: {e[:20]}"))
                    fail += 1
                    break

            self.after(0, lambda v=i + 1: self._progress.configure(value=v))

        self.after(0, lambda: self._on_download_complete(success, fail, total))

    def _on_download_complete(self, success, fail, total):
        self._download_running = False
        self._download_btn.configure(state=tk.NORMAL)
        self._cancel_btn.configure(state=tk.DISABLED)
        self._progress_label.configure(text=f"完成: {success} 成功, {fail} 失败 (共 {total})")

    def _cancel_download(self):
        self._cancel_flag.set()
        self._cancel_btn.configure(state=tk.DISABLED)

    def _clear_queue(self):
        if self._download_running:
            self._cancel_download()
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._queue.clear()
        self._queue_items.clear()
        self._progress.configure(value=0)
        self._progress_label.configure(text="")

    def _update_queue_status(self, key, status):
        if key in self._queue_items:
            item_id = self._queue_items[key]
            values = list(self._tree.item(item_id, "values"))
            values[2] = status
            self._tree.item(item_id, values=values)

    def set_download_path(self, path: str):
        self._path_var.set(path)

    def get_download_path(self) -> str:
        return self._path_var.get()
