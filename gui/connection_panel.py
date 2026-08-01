"""
连接面板：配置表单，AK/SK 默认 ***** 隐藏
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from config import load_config, save_config
from obs_client import ObsClientWrapper, ObsAuthError, ObsNetworkError, ObsNotFoundError, ObsError


class ConnectionPanel(ttk.Frame):
    """OBS 连接配置面板"""

    def __init__(self, parent, on_connected):
        super().__init__(parent)
        self._on_connected = on_connected
        self._client_wrapper = ObsClientWrapper()
        self._show_ak = tk.BooleanVar(value=False)
        self._show_sk = tk.BooleanVar(value=False)
        self._config = load_config()

        self._build_ui()
        self._load_saved_config()

    def _build_ui(self):
        container = ttk.Frame(self, padding=40)
        container.pack(expand=True)

        ttk.Label(container, text="华为云 OBS 图片浏览器",
                  font=("Microsoft YaHei", 16, "bold")).pack(pady=(0, 24))

        form = ttk.Frame(container)
        form.pack(fill=tk.X)

        # AK
        ttk.Label(form, text="Access Key (AK):", font=("Microsoft YaHei", 9)).grid(
            row=0, column=0, sticky=tk.W, pady=5)
        ak_frame = ttk.Frame(form)
        ak_frame.grid(row=0, column=1, sticky=tk.EW, padx=(12, 0), pady=5)
        self._ak_entry = ttk.Entry(ak_frame, show="*", width=34)
        self._ak_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ak_frame, text="👁", width=3,
                   command=lambda: self._toggle_visibility("ak")).pack(side=tk.RIGHT, padx=(4, 0))

        # SK
        ttk.Label(form, text="Secret Key (SK):", font=("Microsoft YaHei", 9)).grid(
            row=1, column=0, sticky=tk.W, pady=5)
        sk_frame = ttk.Frame(form)
        sk_frame.grid(row=1, column=1, sticky=tk.EW, padx=(12, 0), pady=5)
        self._sk_entry = ttk.Entry(sk_frame, show="*", width=34)
        self._sk_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(sk_frame, text="👁", width=3,
                   command=lambda: self._toggle_visibility("sk")).pack(side=tk.RIGHT, padx=(4, 0))

        # Endpoint
        ttk.Label(form, text="Endpoint:", font=("Microsoft YaHei", 9)).grid(
            row=2, column=0, sticky=tk.W, pady=5)
        self._endpoint_entry = ttk.Entry(form, width=40)
        self._endpoint_entry.grid(row=2, column=1, sticky=tk.EW, padx=(12, 0), pady=5)

        # Bucket
        ttk.Label(form, text="Bucket:", font=("Microsoft YaHei", 9)).grid(
            row=3, column=0, sticky=tk.W, pady=5)
        self._bucket_entry = ttk.Entry(form, width=40)
        self._bucket_entry.grid(row=3, column=1, sticky=tk.EW, padx=(12, 0), pady=5)

        form.columnconfigure(1, weight=1)

        # 按钮
        btn_frame = ttk.Frame(container)
        btn_frame.pack(pady=(24, 0))

        self._connect_btn = ttk.Button(btn_frame, text="连接并浏览",
                                        command=self._connect_and_browse, width=14)
        self._connect_btn.pack(pady=3)

        self._status_label = ttk.Label(container, text="", foreground="gray",
                                        wraplength=350, justify=tk.CENTER)
        self._status_label.pack(pady=(12, 0), fill=tk.X)

        self._progress = ttk.Progressbar(container, mode="indeterminate", length=300)
        self._progress.pack(pady=(8, 0))

    def _load_saved_config(self):
        creds = self._config.get("credentials", {})
        self._ak_entry.insert(0, creds.get("ak", ""))
        self._sk_entry.insert(0, creds.get("sk", ""))
        self._endpoint_entry.insert(0, creds.get("endpoint", "obs.cn-north-4.myhuaweicloud.com"))
        self._bucket_entry.insert(0, creds.get("bucket", ""))

    def _get_form_values(self):
        return (
            self._ak_entry.get().strip(),
            self._sk_entry.get().strip(),
            self._endpoint_entry.get().strip(),
            self._bucket_entry.get().strip(),
        )

    def _toggle_visibility(self, field):
        if field == "ak":
            self._show_ak.set(not self._show_ak.get())
            self._ak_entry.configure(show="" if self._show_ak.get() else "*")
        else:
            self._show_sk.set(not self._show_sk.get())
            self._sk_entry.configure(show="" if self._show_sk.get() else "*")

    def _set_busy(self, busy: bool):
        state = tk.DISABLED if busy else tk.NORMAL
        self._connect_btn.configure(state=state)
        if busy:
            self._progress.start(10)
        else:
            self._progress.stop()

    def _show_status(self, message: str, color: str = "gray"):
        self._status_label.configure(text=message, foreground=color)

    def _connect_and_browse(self):
        ak, sk, endpoint, bucket = self._get_form_values()
        if not ak or not sk or not endpoint:
            messagebox.showwarning("提示", "请填写 Access Key、Secret Key 和 Endpoint")
            return
        if not bucket:
            messagebox.showwarning("提示", "请填写 Bucket 名称")
            return

        self._set_busy(True)
        self._show_status("正在连接...", "gray")
        threading.Thread(target=self._do_connect, args=(ak, sk, endpoint, bucket), daemon=True).start()

    def _do_connect(self, ak, sk, endpoint, bucket):
        try:
            self._client_wrapper.connect(ak, sk, endpoint, bucket)
            self._config["credentials"]["ak"] = ak
            self._config["credentials"]["sk"] = sk
            self._config["credentials"]["endpoint"] = endpoint
            self._config["credentials"]["bucket"] = bucket
            save_config(self._config)
            self.after(0, lambda b=bucket: self._on_connect_success(b))
        except ObsAuthError:
            msg = "认证失败，请检查 AK/SK"
            self.after(0, lambda m=msg: self._on_connect_fail(m))
        except ObsNetworkError:
            msg = "网络错误，请检查 Endpoint"
            self.after(0, lambda m=msg: self._on_connect_fail(m))
        except ObsNotFoundError:
            msg = "桶不存在，请检查 Bucket 名称"
            self.after(0, lambda m=msg: self._on_connect_fail(m))
        except Exception as ex:
            msg = f"连接失败: {ex}"
            self.after(0, lambda m=msg: self._on_connect_fail(m))

    def _on_connect_success(self, bucket):
        self._set_busy(False)
        self._show_status("✓ 已连接", "green")
        self._on_connected(self._client_wrapper, bucket)

    def _on_connect_fail(self, message: str):
        self._set_busy(False)
        self._show_status(f"✗ {message}", "red")
        messagebox.showerror("连接失败", message)

    def get_client(self):
        return self._client_wrapper
