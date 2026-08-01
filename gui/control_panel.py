"""
右侧控制面板：日志区 + 搜索结果 + 保存路径
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

from utils import filename_from_key, format_file_size
from obs_client import ObsError, ObsNetworkError


class ControlPanel(ttk.Frame):
    """右侧控制面板"""

    IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico"}

    def __init__(self, parent, client_wrapper, bucket, preview_panel, on_disconnect):
        super().__init__(parent, padding=6)
        self._client = client_wrapper
        self._bucket = bucket
        self._preview = preview_panel
        self._on_disconnect = on_disconnect
        self._results = []
        self._suppress_select = False

        self._build_ui()

    def _build_ui(self):
        # 连接信息
        top = ttk.Frame(self)
        top.pack(fill=tk.X, pady=(0, 4))
        self._bucket_label = ttk.Label(top, text=f"桶: {self._bucket}",
                                       font=("Microsoft YaHei", 9, "bold"))
        self._bucket_label.pack(side=tk.LEFT)
        ttk.Button(top, text="断开", command=self._on_disconnect, width=6).pack(side=tk.RIGHT)

        # 搜索
        sf = ttk.Frame(self)
        sf.pack(fill=tk.X, pady=(0, 4))
        self._search_entry = ttk.Entry(sf)
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._search_entry.bind("<Return>", lambda e: self._do_search())
        ttk.Button(sf, text="搜索", command=self._do_search, width=6).pack(side=tk.LEFT, padx=(4, 0))

        # 日志区
        logf = ttk.LabelFrame(self, text="日志", padding=2)
        logf.pack(fill=tk.X, pady=(0, 4))
        self._log_text = tk.Text(logf, height=4, wrap=tk.WORD, state=tk.DISABLED,
                                 font=("Microsoft YaHei", 8), bg="#f8f8f8", fg="#555")
        ls = ttk.Scrollbar(logf, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=ls.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ls.pack(side=tk.RIGHT, fill=tk.Y)

        # 搜索结果
        rf = ttk.LabelFrame(self, text="搜索结果", padding=2)
        rf.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        cols = ("name", "size")
        self._tree = ttk.Treeview(rf, columns=cols, show="headings", height=6, selectmode=tk.BROWSE)
        self._tree.heading("name", text="文件名")
        self._tree.heading("size", text="大小")
        self._tree.column("name", width=130, minwidth=80)
        self._tree.column("size", width=55, minwidth=50, anchor=tk.CENTER)
        self._tree.bind("<<TreeviewSelect>>", self._on_result_selected)
        ts = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=ts.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ts.pack(side=tk.RIGHT, fill=tk.Y)

        # 保存路径
        pf = ttk.LabelFrame(self, text="保存到本地", padding=2)
        pf.pack(fill=tk.X)
        pr = ttk.Frame(pf)
        pr.pack(fill=tk.X)
        self._path_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self._path_entry = ttk.Entry(pr, textvariable=self._path_var)
        self._path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(pr, text="浏览", command=self._browse_folder, width=6).pack(side=tk.RIGHT, padx=(4, 0))

    # ---------- 日志 ----------
    def _log(self, msg):
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, msg + "\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    # ---------- 搜索 ----------
    def _do_search(self):
        query = self._search_entry.get().strip()
        if not query:
            return
        self._log(f"> {query}")
        self._preview.show_status("搜索中...")
        threading.Thread(target=self._do_search_all, args=(query,), daemon=True).start()

    def _parse_obs_url(self, query):
        """obs://bucket/key → (bucket, key), key 不做任何截断"""
        if query.startswith("obs://"):
            path = query[6:]
            parts = path.split("/", 1)
            if len(parts) >= 2:
                return parts[0], parts[1]
            elif parts:
                return parts[0], ""
        return None, None

    def _do_search_all(self, query):
        url_bucket, url_key = self._parse_obs_url(query)
        if url_bucket and url_key:
            lower = url_key.lower()
            if any(lower.endswith(ext) for ext in self.IMG_EXTS):
                obj = {"key": url_key, "size": 0, "last_modified": ""}
                self.after(0, lambda: self._on_direct_hit(url_bucket, obj))
                return
            else:
                self.after(0, lambda: self._log("URL 不是图片文件"))
                return

        local_results = self._search_local(query)
        obs_results = None
        obs_error = None
        try:
            obs_results = self._client.search_images(self._bucket, query=query, max_keys=500)
        except Exception as ex:
            obs_error = str(ex)

        self.after(0, lambda: self._on_all_results(local_results, obs_results, obs_error, query))

    def _search_local(self, query):
        results = []
        base = self._path_var.get()
        if not os.path.isdir(base):
            return results
        q = query.strip().lower()
        seen = set()
        for root, dirs, files in os.walk(base):
            for f in files:
                lf = f.lower()
                if not any(lf.endswith(e) for e in self.IMG_EXTS):
                    continue
                if q not in lf:
                    continue
                if lf in seen:
                    continue
                seen.add(lf)
                fp = os.path.join(root, f)
                results.append({"key": f, "size": os.path.getsize(fp),
                                "local_path": fp, "source": "local"})
        return results

    def _on_direct_hit(self, bucket, obj):
        self._suppress_select = True
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._results = [obj]
        name = obj["key"].split("/")[-1]
        self._tree.insert("", tk.END, values=(name, ""))
        self._suppress_select = False

        if bucket and bucket != self._bucket:
            self._bucket = bucket
            self._bucket_label.configure(text=f"桶: {bucket}")

        self._log(f"命中: {name}")
        self._load_image_local_first(obj["key"])

    def _on_all_results(self, local_results, obs_results, obs_error, query):
        self._suppress_select = True
        for item in self._tree.get_children():
            self._tree.delete(item)

        self._results = []
        seen = set()

        for obj in local_results:
            name = obj["key"]
            self._results.append(obj)
            seen.add(name.lower())
            self._tree.insert("", tk.END, values=(f"[本地] {name}", format_file_size(obj["size"])))

        obs_count = 0
        if obs_results:
            for obj in obs_results["objects"]:
                name = filename_from_key(obj["key"])
                if name.lower() not in seen:
                    obs_count += 1
                    self._results.append(obj)
                    seen.add(name.lower())
                    self._tree.insert("", tk.END, values=(f"[OBS] {name}", format_file_size(obj["size"])))

        self._suppress_select = False

        parts = []
        if local_results:
            parts.append(f"本地 {len(local_results)}")
            # 默认展示第一个本地结果
            first = local_results[0]
            self._preview.load_local(first["local_path"], display_name=first["key"])
            self._log(f"自动加载: {first['key']}")
        if obs_count > 0:
            parts.append(f"OBS {obs_count}")
            # 没有本地结果时，默认加载第一个 OBS 结果
            if not local_results and obs_results and obs_results["objects"]:
                first_obs = obs_results["objects"][0]
                self._load_image_local_first(first_obs["key"])
        if obs_error and not parts:
            parts.append(f"OBS错误: {obs_error[:40]}")
        if not parts:
            parts.append(f"未找到 \"{query}\"")
            self._preview.show_status(f"未找到: {query}")

        self._log("，".join(parts))

    def _on_result_selected(self, event):
        if self._suppress_select:
            return
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        if 0 <= idx < len(self._results):
            obj = self._results[idx]
            if obj.get("source") == "local" and "local_path" in obj:
                fname = obj["key"]
                self._preview.load_local(obj["local_path"], display_name=fname)
                self._log(f"本地: {fname}")
                return
            self._load_image_local_first(obj["key"])

    # ---------- 加载：本地优先 ----------
    def _find_local_file(self, fname):
        base = self._path_var.get()
        if not os.path.isdir(base):
            return None
        for root, dirs, files in os.walk(base):
            for f in files:
                if f == fname:
                    return os.path.join(root, f)
        return None

    def _load_image_local_first(self, key):
        fname = filename_from_key(key)
        local_path = self._find_local_file(fname)
        if local_path:
            self._preview.load_local(local_path, display_name=fname)
            self._log(f"本地加载: {fname}")
            return

        self._log(f"下载: {fname}...")
        threading.Thread(target=self._download_and_show,
                         args=(key, os.path.join(self._path_var.get(), fname)),
                         daemon=True).start()

    def _download_and_show(self, key, local_path):
        fname = filename_from_key(key)
        bucket = self._bucket
        try:
            if os.path.isfile(local_path):
                self.after(0, lambda: self._preview.load_local(local_path, display_name=fname))
                self.after(0, lambda: self._log(f"本地已有: {fname}"))
                return

            self._client.download_file(bucket, key, local_path)
            self.after(0, lambda: self._preview.load_local(local_path, display_name=fname))
            self.after(0, lambda: self._log(f"下载完成: {fname}"))
        except Exception as ex:
            err = str(ex)
            if os.path.isfile(local_path):
                self.after(0, lambda: self._preview.load_local(local_path, display_name=fname))
                self.after(0, lambda: self._log(f"本地加载 (OBS失败)"))
                return
            detail = f"桶: {bucket}\nKey: {key}\n本地: {local_path}\n\n{err}"
            self.after(0, lambda d=detail: messagebox.showerror("OBS 访问失败", d))
            self.after(0, lambda: self._log(f"失败: {err[:40]}"))

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="选择保存目录")
        if folder:
            self._path_var.set(folder)

    def set_download_path(self, path: str):
        self._path_var.set(path)

    def get_download_path(self) -> str:
        return self._path_var.get()
