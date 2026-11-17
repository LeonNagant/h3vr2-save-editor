# -*- coding: utf-8 -*-
"""
H3VR2 存档修改器（GUI）
依赖：Python 3.8+ 且自带 tkinter；其余全部使用标准库，无需 pip 安装。
运行：py -3.10 h3vr2_save_editor.py   （或双击 run_editor.bat）
"""
from __future__ import annotations

import copy
import glob
import json
import os
import queue
import shutil
import sys
import threading
import traceback
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
except ImportError:
    print("缺少 tkinter。请使用自带 tkinter 的 Python（本机可用：py -3.10）。")
    sys.exit(1)

import save_core as core

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

FONT = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 9, "bold")
FONT_MONO = ("Consolas", 9)


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _item_choice_lines(app, kw: str, fav_only: bool):
    """物品目录 → (匹配项, 显示文本)：收藏项前加 ★，可只看收藏。"""
    favs = {core.asset_key(x) for x in core.favorite_refs(app.ud)}
    q = (kw or "").strip().lower()
    matches, lines = [], []
    for it in core.load_item_catalog():
        star = "★" if it["key"] in favs else "  "
        text = "%s %s  |  %s  |  %s%s" % (
            star, it.get("zh") or "—", it.get("en") or "—", it["key"],
            "" if it.get("verified") else "  [未验证引用]")
        if q and q not in text.lower():
            continue
        if fav_only and it["key"] not in favs:
            continue
        matches.append(it)
        lines.append(text)
    return matches, lines


def pick_item(parent, app, title="选择物品", current_ref="") -> str | None:
    """通用物品选择框：目录搜索 + 收藏筛选/加星 + 手填引用。返回 extref 或 None。"""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.geometry("840x610")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.columnconfigure(1, weight=1)
    dlg.rowconfigure(2, weight=1)
    result = {"ref": None}

    ttk.Label(dlg, text="搜索物品（中文名 / 英文名 / AssetKey）：", font=FONT_B).grid(
        row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))
    kw = tk.StringVar()
    ent = ttk.Entry(dlg, textvariable=kw, width=80)
    ent.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8)
    fav_only = tk.BooleanVar(value=False)
    ttk.Checkbutton(dlg, text="只看 ★ 收藏", variable=fav_only).grid(
        row=1, column=3, sticky="w", padx=6)

    refv = tk.StringVar(value=current_ref or "")
    lb = tk.Listbox(dlg, height=14, font=FONT, exportselection=False)
    lb.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8, pady=4)
    sb = ttk.Scrollbar(dlg, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    sb.grid(row=2, column=3, sticky="ns", pady=4)
    matches = []

    def refill(*_):
        lb.delete(0, "end")
        m, lines = _item_choice_lines(app, kw.get(), fav_only.get())
        matches[:] = m
        for t in lines:
            lb.insert("end", t)
        cur = refv.get().strip()
        for i, it in enumerate(matches):
            if (it.get("ref") == cur or it.get("ref_alt") == cur
                    or it["key"] == core.asset_key(cur)):
                lb.selection_set(i)
                lb.see(i)
                break
    kw.trace_add("write", refill)
    fav_only.trace_add("write", refill)

    ttk.Label(dlg, text="物品引用：").grid(row=3, column=0, sticky="w", padx=8, pady=(8, 2))
    ttk.Entry(dlg, textvariable=refv, font=FONT_MONO).grid(
        row=3, column=1, columnspan=3, sticky="ew", padx=8, pady=(8, 2))

    def on_pick(_=None):
        sel = lb.curselection()
        if not sel:
            return
        it = matches[sel[0]]
        refv.set(it.get("ref") or ("extref://footlong.base/Item/" + it["key"]))
    lb.bind("<<ListboxSelect>>", on_pick)

    def toggle_fav():
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个物品", parent=dlg)
            return
        it = matches[sel[0]]
        r = it.get("ref") or ("extref://footlong.base/Item/" + it["key"])
        state = core.toggle_favorite(app.ud, r)
        app._persist_ud()
        app._refresh_favorites()
        app.log(("已收藏 " if state else "已取消收藏 ") + it["key"])
        refill()

    bar = ttk.Frame(dlg)
    bar.grid(row=4, column=0, columnspan=4, sticky="w", padx=8, pady=6)
    ttk.Button(bar, text="★ 加入 / 取消收藏", command=toggle_fav).pack(side="left", padx=2)
    ttk.Button(bar, text="打开收藏页",
               command=lambda: app.nb.select(app.tab_favorites)).pack(side="left", padx=2)
    ttk.Label(bar, text="选中列表项会自动填入游戏内真实引用；也可手动粘贴任意 extref。",
              foreground="#777777").pack(side="left", padx=10)

    def ok():
        ref = refv.get().strip()
        if not ref.startswith("extref://"):
            messagebox.showerror("输入错误", "物品引用必须以 extref:// 开头", parent=dlg)
            return
        result["ref"] = ref
        dlg.destroy()

    lb.bind("<Double-1>", lambda e: (on_pick(e), ok()))
    bb = ttk.Frame(dlg)
    bb.grid(row=5, column=0, columnspan=4, sticky="e", padx=8, pady=8)
    ttk.Button(bb, text="取消", command=dlg.destroy).pack(side="right", padx=4)
    ttk.Button(bb, text="确定", command=ok).pack(side="right")
    refill()
    ent.focus_set()
    dlg.wait_window()
    return result["ref"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("H3VR2 存档编辑器 v0.3.0  ·  Slot 1 / Profile0")
        self.root.geometry("1400x940")
        self.root.minsize(1120, 720)

        if not os.path.isfile(core.CONFIG_PATH):
            core.save_config(core.DEFAULT_CONFIG)
        self.cfg = core.load_config()

        self.data: dict = {}
        self.local_dir: str | None = None
        self.dirty: set[str] = set()
        self.current_file: str | None = None
        self.tree_rows: dict[str, dict] = {}
        self.quick_entries: list[tuple] = []
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.devices: list[dict] = []
        self.dev_label_map: dict[str, str] = {}
        self.backup_dir: str | None = None
        # 存档来源：none / venture（模拟器本地目录）/ manual（手动选择）/ export（adb 导出快照）
        self.source_kind = "none"
        self.source_meta: dict = {}
        # 预设 / 收藏独立于存档，导出新存档后仍在本机
        self.ud_path = core.user_data_path(self.cfg)
        self.ud = core.load_user_data(self.ud_path)
        self.preset_bars: dict = {}
        self.inv_page_labels: dict = {}
        self.fav_list: list[dict] = []

        self._build_style()
        self._build_ui()
        self._refresh_devices(silent=True)
        # 启动时只列配置里的默认包名（官方包名）。设备上其他安装版本的包名，
        # 只有用户主动点「自动探测」后才会被枚举并进入下拉框供选择。
        self._load_latest_export()
        self._autoload_venture()
        self._startup_connect()
        # 即使尚未载入存档，也先把预设下拉与收藏列表填好
        self._preset_refresh()
        self._refresh_favorites()
        self.root.after(120, self._poll)

    def _startup_connect(self):
        """启动时自动 adb connect 已保存的无线头显；未配置 IP 时跳过，避免无效连接。"""
        if not (self.cfg.get("wifi_ip") or "").strip():
            self.q.put(("log", "未配置无线 IP，跳过启动时自动连接；USB 可直接使用，无线请点「USB→启用无线调试」或「扫描局域网」"))
            return
        def worker():
            try:
                r = core.connect_wifi(self.cfg)
                self.q.put(("log", "启动时自动连接无线：" + (r["stdout"] or r["stderr"])))
            except Exception as e:
                self.q.put(("log", "启动时无线连接失败（可点「连接无线」）：" + str(e)))
            self.q.put(("refresh", None))
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ 样式 / 布局
    def _build_style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("TButton", font=FONT, padding=4)
        s.configure("TLabel", font=FONT)
        s.configure("TLabelframe.Label", font=FONT_B)
        s.configure("Treeview", font=FONT, rowheight=22)
        s.configure("Treeview.Heading", font=FONT_B)

    def _build_ui(self):
        top = ttk.LabelFrame(self.root, text=" 设备连接 ", padding=6)
        top.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(top, text="设备：").grid(row=0, column=0, sticky="w")
        self.dev_var = tk.StringVar()
        self.dev_combo = ttk.Combobox(top, textvariable=self.dev_var, width=42,
                                      state="readonly", font=FONT)
        self.dev_combo.grid(row=0, column=1, sticky="w", padx=(2, 8))
        ttk.Button(top, text="刷新设备", command=lambda: self._refresh_devices()).grid(row=0, column=2, padx=2)
        ttk.Button(top, text="连接无线", command=self._connect_wifi).grid(row=0, column=3, padx=2)
        ttk.Button(top, text="扫描局域网", command=self._scan_lan).grid(row=0, column=4, padx=2)
        ttk.Button(top, text="USB→启用无线调试", command=self._enable_wireless).grid(row=0, column=5, padx=2)
        ttk.Button(top, text="唤醒头显", command=self._wake).grid(row=0, column=6, padx=2)
        self.dev_status = ttk.Label(top, text="未检测到设备", foreground="#b03030")
        self.dev_status.grid(row=0, column=7, sticky="w", padx=8)

        cfgf = ttk.LabelFrame(self.root, text=" 存档位置与配置 ", padding=6)
        cfgf.pack(fill="x", padx=8, pady=4)
        ttk.Label(cfgf, text="包名：").grid(row=0, column=0, sticky="w")
        self.pkg_var = tk.StringVar(value=self.cfg["package"])
        self.pkg_combo = ttk.Combobox(cfgf, textvariable=self.pkg_var, width=28, font=FONT,
                                      values=[self.cfg["package"]])
        self.pkg_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(cfgf, text="槽位：").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.prof_var = tk.StringVar(value=self.cfg["profile"])
        self.prof_combo = ttk.Combobox(cfgf, textvariable=self.prof_var, width=12, font=FONT)
        self.prof_combo.grid(row=0, column=3, sticky="w")
        ttk.Label(cfgf, text="无线 IP：").grid(row=0, column=4, sticky="w", padx=(10, 0))
        self.ip_var = tk.StringVar(value=self.cfg["wifi_ip"])
        ttk.Entry(cfgf, textvariable=self.ip_var, width=16, font=FONT).grid(row=0, column=5, sticky="w")
        ttk.Label(cfgf, text="端口：").grid(row=0, column=6, sticky="w", padx=(10, 0))
        self.port_var = tk.StringVar(value=str(self.cfg["wifi_port"]))
        ttk.Entry(cfgf, textvariable=self.port_var, width=7, font=FONT).grid(row=0, column=7, sticky="w")
        ttk.Button(cfgf, text="自动探测", command=self._auto_detect).grid(row=0, column=8, padx=4)
        ttk.Button(cfgf, text="保存配置", command=self._save_cfg).grid(row=0, column=9, padx=2)
        self.path_var = tk.StringVar()
        ttk.Label(cfgf, textvariable=self.path_var, foreground="#336699").grid(
            row=1, column=0, columnspan=10, sticky="w", pady=(5, 0))
        self._update_path_label()
        for v in (self.pkg_var, self.prof_var, self.ip_var, self.port_var):
            v.trace_add("write", lambda *_: self._update_path_label())

        # 存档来源：Venture 模拟器（PC 端，存档就是本机普通目录）或手动选择
        ttk.Label(cfgf, text="来源：").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(cfgf, text="查找 Venture 存档", command=self._venture_scan).grid(
            row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Button(cfgf, text="手动选择存档目录…", command=self._choose_dir).grid(
            row=2, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(cfgf, text="重新载入", command=self._reload_source).grid(
            row=2, column=4, sticky="w", pady=(6, 0))
        self.source_var = tk.StringVar(value="尚未载入存档")
        ttk.Label(cfgf, textvariable=self.source_var, foreground="#8a4b00",
                  wraplength=760, justify="left").grid(
            row=2, column=5, columnspan=5, sticky="w", padx=(10, 0), pady=(6, 0))

        logf = ttk.LabelFrame(self.root, text=" 日志 ", padding=4)
        logf.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.log_text = scrolledtext.ScrolledText(logf, height=5, font=FONT_MONO,
                                                  wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        bottom = ttk.LabelFrame(self.root, text=" 操作 ", padding=6)
        bottom.pack(side="bottom", fill="x", padx=8, pady=4)
        ttk.Button(bottom, text="① 一键导出存档", command=self._export).grid(row=0, column=0, padx=3)
        self.btn_save = ttk.Button(bottom, text="② 保存到本地", command=self._save_local)
        self.btn_save.grid(row=0, column=1, padx=3)
        ttk.Button(bottom, text="③ 一键回传到头显", command=self._push).grid(row=0, column=2, padx=3)
        ttk.Button(bottom, text="恢复最近备份", command=self._restore_backup).grid(row=0, column=3, padx=3)
        self.only_modified = tk.BooleanVar(value=bool(self.cfg.get("push_only_modified", True)))
        ttk.Checkbutton(bottom, text="只回传修改过的文件", variable=self.only_modified).grid(
            row=0, column=4, padx=8)
        self.stop_game = tk.BooleanVar(value=bool(self.cfg.get("stop_game_before_push", True)))
        ttk.Checkbutton(bottom, text="回传前停止游戏并冷启动（必需）",
                        variable=self.stop_game).grid(row=0, column=5, padx=8)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.status_var, foreground="#006600").grid(
            row=0, column=6, sticky="w", padx=8)


        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(body, width=250)
        body.add(left, weight=1)
        lf = ttk.LabelFrame(left, text=" 存档文件 ", padding=5)
        lf.pack(fill="both", expand=True)
        self.file_list = tk.Listbox(lf, font=FONT_MONO, activestyle="dotbox",
                                    exportselection=False)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.file_list.pack(side="left", fill="both", expand=True)
        self.file_list.bind("<<ListboxSelect>>", lambda e: self._on_file_select())
        ttk.Button(left, text="打开导出目录", command=self._open_dir).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="载入其他存档目录", command=self._choose_dir).pack(fill="x", pady=2)
        ttk.Button(left, text="导出完整字段目录", command=self._export_catalog).pack(fill="x")

        right = ttk.Frame(body)
        body.add(right, weight=6)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        self.tab_quick = ttk.Frame(self.nb)
        self.tab_store = ttk.Frame(self.nb)
        self.tab_inventory = ttk.Frame(self.nb)
        self.tab_favorites = ttk.Frame(self.nb)
        self.tab_tree = ttk.Frame(self.nb)
        self.tab_raw = ttk.Frame(self.nb)
        self.tab_desc = ttk.Frame(self.nb)
        self.nb.add(self.tab_quick, text=" 快捷编辑 ")
        self.nb.add(self.tab_store, text=" 商店编辑 ")
        self.nb.add(self.tab_inventory, text=" 仓库编辑 ")
        self.nb.add(self.tab_favorites, text=" ★ 收藏与预设 ")
        self.nb.add(self.tab_tree, text=" 全部参数（树） ")
        self.nb.add(self.tab_raw, text=" 原始 JSON ")
        self.nb.add(self.tab_desc, text=" 字段说明 ")
        self._build_quick()
        self._build_store()
        self._build_inventory()
        self._build_favorites()
        self._build_tree()
        self._build_raw()
        self._build_desc()

        self.log("H3VR2 存档修改器已启动。Python " + sys.version.split()[0] +
                 " / tkinter " + str(tk.TkVersion))
        self.log("提示：先「① 一键导出存档」，修改后「② 保存到本地」，再「③ 一键回传到头显」。")
        self.log("Venture 模拟器：点「查找 Venture 存档」直接找本机存档（无需 adb），"
                 "改完点「② 保存到 Venture 存档」即写回，保存前自动备份。")
        self.log("手动存档：点「手动选择存档目录…」，选 footlong.base / Profile0 / SaveData 均可。")
        self.log("预设 / 自动应用：在「★ 收藏与预设」页设好后，")
        self.log("　　　　　　每次导出新存档会自动还原编辑内容，无需重新编辑；物品选择框可勾「只看 ★ 收藏」。")

    def _quick_wheel(self, e):
        """快捷编辑页滚轮滚动。窗口变矮时靠它看到底部的说明文字。"""
        c = getattr(self, "quick_canvas", None)
        if c is None or self.nb.select() != str(self.tab_quick):
            return
        node = self.root.winfo_containing(e.x_root, e.y_root)
        inside = False
        while node is not None:
            if str(node) == str(self.tab_quick) or str(node).startswith(str(self.tab_quick) + "."):
                inside = True
                break
            try:
                node = node.master
            except Exception:
                break
        if not inside:
            return
        c.yview_scroll(-3 if getattr(e, "delta", 0) > 0 else 3, "units")

    # ------------------------------------------------------------ 快捷编辑页
    def _build_quick(self):
        outer = ttk.Frame(self.tab_quick)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        vs = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vs.set)
        canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        def _sync(_=None):
            # 内容高度变了就更新滚动区；同时让内容宽度跟随画布，避免右侧被裁
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win, width=max(1, canvas.winfo_width()))

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        self.quick_canvas = canvas
        # 滚轮滚动：窗口变矮时也能看到底部说明文字（原先只能拖小滚动条）
        self.root.bind_all("<MouseWheel>", self._quick_wheel)

        ttk.Label(inner, text="存档独有数值（改完点「应用快捷修改」）", font=FONT_B).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(2, 4))
        for i, (f, path, name, desc, typ) in enumerate(core.QUICK_FIELDS, start=1):
            ttk.Label(inner, text=name, font=FONT_MONO, width=20, anchor="w").grid(
                row=i, column=0, sticky="w", padx=(4, 8), pady=1)
            ttk.Label(inner, text=desc, width=42, anchor="w").grid(row=i, column=1, sticky="w", pady=1)
            e = ttk.Entry(inner, width=18, font=FONT)
            e.grid(row=i, column=2, sticky="w", padx=6, pady=1)
            self.quick_entries.append((f, path, typ, e))

        r = len(core.QUICK_FIELDS) + 2
        ttk.Button(inner, text="应用快捷修改", command=self._apply_quick).grid(
            row=r, column=0, sticky="w", padx=4, pady=(6, 2))

        sep = ttk.Separator(inner, orient="horizontal")
        sep.grid(row=r + 1, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(inner, text="批量工具", font=FONT_B).grid(row=r + 2, column=0, sticky="w", pady=2)
        ttk.Label(inner, text="弹匣补满至（发）：").grid(row=r + 3, column=0, sticky="w", padx=4, pady=2)
        self.mag_cap = tk.StringVar(value="7")
        ttk.Entry(inner, textvariable=self.mag_cap, width=10).grid(row=r + 3, column=1, sticky="w")
        ttk.Button(inner, text="补满所有弹匣", command=self._apply_mags).grid(
            row=r + 3, column=2, sticky="w", padx=6)
        ttk.Label(inner, text="难度倍率、音量、血腥效果、渲染档位等属于游戏内设置菜单项目，已从此栏移除；",
                  foreground="#777777").grid(row=r + 4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(inner, text="如需脚本化修改，请在「全部参数（树）」或「原始 JSON」页编辑 Settings.json.gz。",
                  foreground="#777777").grid(row=r + 5, column=0, columnspan=3, sticky="w")
        ttk.Label(inner, text="商店出售物品与价格请到「商店编辑」页；以上修改需再点「② 保存到本地」或「③ 一键回传」。",
                  foreground="#777777").grid(row=r + 6, column=0, columnspan=3, sticky="w", pady=(4, 2))

    # ------------------------------------------------------------ 参数树页
    def _build_tree(self):
        bar = ttk.Frame(self.tab_tree)
        bar.pack(fill="x", padx=4, pady=4)
        ttk.Label(bar, text="过滤：").pack(side="left")
        self.tree_filter = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.tree_filter, width=36, font=FONT)
        e.pack(side="left", padx=4)
        self.tree_filter.trace_add("write", lambda *_: self._refresh_tree())
        ttk.Label(bar, text="双击某行可编辑数值；右键可复制路径 / 新增 / 删除节点",
                  foreground="#777777").pack(side="left", padx=10)

        wrap = ttk.Frame(self.tab_tree)
        wrap.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        cols = ("path", "value", "type", "desc")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for c, w, anchor in [("path", 430, "w"), ("value", 170, "w"),
                             ("type", 70, "center"), ("desc", 470, "w")]:
            self.tree.heading(c, text={"path": "字段路径", "value": "当前值",
                                       "type": "类型", "desc": "含义"}[c])
            self.tree.column(c, width=w, anchor=anchor)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit_tree_row())
        self.tree.bind("<Button-3>", self._tree_menu)

    def _build_raw(self):
        bar = ttk.Frame(self.tab_raw)
        bar.pack(fill="x", padx=4, pady=4)
        ttk.Button(bar, text="应用文本修改（写回内存）", command=self._apply_raw).pack(side="left", padx=2)
        ttk.Button(bar, text="重新载入本文件", command=self._refresh_raw).pack(side="left", padx=2)
        ttk.Label(bar, text="可任意增删改字段；必须是合法 JSON", foreground="#777777").pack(side="left", padx=8)
        self.raw_text = scrolledtext.ScrolledText(self.tab_raw, font=FONT_MONO, wrap="none")
        self.raw_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    def _build_desc(self):
        bar = ttk.Frame(self.tab_desc)
        bar.pack(fill="x", padx=4, pady=4)
        ttk.Label(bar, text="当前文件的全部叶子字段说明（数量随存档内容变化，可导出 JSON）",
                  foreground="#555555").pack(side="left")
        self.desc_text = scrolledtext.ScrolledText(self.tab_desc, font=FONT_MONO, wrap="none")
        self.desc_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    # ------------------------------------------------------------ 通用工具
    def log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts()}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, msg: str):
        self.status_var.set(msg)

    def _update_path_label(self):
        try:
            if not self.pkg_var.get().strip():
                self.path_var.set("设备端：等待自动探测游戏包名…（也可点「自动探测」）")
                return
            p = core.remote_save_path({"package": self.pkg_var.get(),
                                       "profile": self.prof_var.get(),
                                       "save_subdir": self.cfg["save_subdir"]})
            self.path_var.set("设备端：" + p)
        except Exception:
            pass

    def _sync_cfg_from_ui(self):
        self.cfg["package"] = self.pkg_var.get().strip()
        self.cfg["profile"] = self.prof_var.get().strip()
        self.cfg["wifi_ip"] = self.ip_var.get().strip()
        try:
            self.cfg["wifi_port"] = int(self.port_var.get().strip())
        except ValueError:
            self.cfg["wifi_port"] = 5555
        self.cfg["push_only_modified"] = bool(self.only_modified.get())

    def _save_cfg(self):
        self._sync_cfg_from_ui()
        p = core.save_config(self.cfg)
        self.log("配置已保存：" + p)

    def _run_bg(self, name: str, fn, on_done=None, quiet: bool = False):
        if self.busy:
            if not quiet:
                messagebox.showinfo("请稍候", "还有任务正在执行")
            return
        self.busy = True
        self.set_status(name + " …")
        self.log("▶ " + name)

        def worker():
            try:
                res = fn(lambda m: self.q.put(("log", m)))
                self.q.put(("done", name, res, None, on_done, quiet))
            except Exception:
                self.q.put(("done", name, None, traceback.format_exc(), on_done, quiet))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    self.log(item[1])
                elif item[0] == "refresh":
                    self._refresh_devices(silent=True)
                elif item[0] == "done":
                    _, name, res, err, on_done, quiet = item
                    self.busy = False
                    if err:
                        self.set_status(name + " 失败")
                        self.log("✖ " + name + " 失败：\n" + err)
                        if not quiet:
                            messagebox.showerror(name + " 失败", err[-1600:])
                    else:
                        self.set_status(name + " 完成")
                        self.log("✔ " + name + " 完成")
                        if on_done:
                            try:
                                on_done(res)
                            except Exception:
                                self.log("回调异常：\n" + traceback.format_exc())
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _selected_serial(self) -> str:
        s = self.dev_var.get()
        if not s:
            raise RuntimeError("请先在「设备」下拉框选择一台头显（或点「刷新设备」）")
        if s in self.dev_label_map:
            return self.dev_label_map[s]
        return s.split("  ")[0].replace("[无线] ", "").replace("[USB] ", "").strip()

    # ------------------------------------------------------------ 设备动作
    def _refresh_devices(self, silent=False):
        try:
            self.devices = core.list_devices(self.cfg)
            online = [d for d in self.devices if d["state"] == "device"]
            labels = [d["label"] for d in online]
            self.dev_label_map = {d["label"]: d["serial"] for d in online}
            self.dev_combo.configure(values=labels)
            if labels:
                cur = self.dev_var.get()
                if cur not in labels:
                    self.dev_var.set(labels[0])
                self.dev_status.configure(text=f"已连接 {len(labels)} 台", foreground="#006600")
            else:
                self.dev_status.configure(text="未检测到设备", foreground="#b03030")
            if not silent:
                self.log(f"设备刷新：{len(labels)} 台在线 " + ", ".join(labels))
        except Exception as e:
            if not silent:
                messagebox.showerror("设备刷新失败", str(e))
            self.dev_status.configure(text="adb 不可用", foreground="#b03030")

    def _connect_wifi(self):
        self._sync_cfg_from_ui()
        def fn(log):
            r = core.connect_wifi(self.cfg)
            log("adb connect " + (self.cfg.get("wifi_ip") or "自动探测") + f":{self.cfg['wifi_port']} → " +
                (r["stdout"] or r["stderr"]))
            return r
        self._run_bg("连接无线调试", fn, lambda r: self._refresh_devices())

    def _scan_lan(self):
        if not self.cfg.get("lan_scan_enabled", True):
            messagebox.showinfo("已禁用", "config.json 中 lan_scan_enabled = false")
            return
        def fn(log):
            hits = core.scan_lan(self.cfg, progress=lambda a, b: None)
            log("局域网 5555 端口开放：" + (", ".join(hits) if hits else "无"))
            connected = []
            for ip in hits:
                r = core.connect_wifi(self.cfg, ip=ip)
                if "connected" in (r["stdout"] or ""):
                    connected.append(ip)
                    log(f"adb connect {ip}:{self.cfg['wifi_port']} 成功")
            return hits, connected
        self._run_bg("扫描局域网无线调试设备", fn, lambda r: self._refresh_devices())

    def _enable_wireless(self):
        usb = next((d["serial"] for d in self.devices
                    if d["kind"] == "usb" and d["state"] == "device"), None)
        if not usb:
            messagebox.showwarning("需要 USB", "未找到 USB 连接的头显。请插上 USB 后点「刷新设备」。")
            return
        self._sync_cfg_from_ui()
        def fn(log):
            log(f"在 USB 设备 {usb} 上启用 tcpip {self.cfg['wifi_port']}")
            r = core.enable_wireless(self.cfg, usb)
            log(f"头显 IP = {r['ip']}，无线 serial = {r['serial']}")
            return r
        def done(r):
            self.ip_var.set(r["ip"])
            self._sync_cfg_from_ui()
            core.save_config(self.cfg)
            self._refresh_devices()
            for d in self.devices:
                if d["serial"] == r["serial"]:
                    self.dev_var.set(d["label"])
            self.log("无线调试已部署；已设置 wifi_sleep_policy=2（待机保持 Wi-Fi）")
        self._run_bg("部署无线调试", fn, done)

    def _wake(self):
        try:
            s = self._selected_serial()
        except Exception as e:
            messagebox.showwarning("未选设备", str(e))
            return
        self._run_bg("唤醒头显", lambda log: core.wake_device(self.cfg, s))

    def _auto_detect(self, silent=False):
        try:
            s = self._selected_serial()
        except Exception:
            if not silent:
                self.log("自动探测跳过：尚未选择设备")
            return
        def fn(log):
            pkgs = core.discover_packages(self.cfg, s)
            log("发现存档包：" + ", ".join(pkgs))
            profiles = []
            if pkgs:
                profiles = core.discover_profiles(self.cfg, s, pkgs[0])
                log("发现存档槽：" + ", ".join(profiles) + "（Profile0 = Slot 1）")
            return pkgs, profiles
        def done(res):
            pkgs, profiles = res
            if pkgs:
                self.pkg_combo.configure(values=pkgs)
                cur = self.cfg.get("package", "").strip()
                # 未手动指定时选最近写入过的活跃存档包；用户手选的包保留
                self.pkg_var.set(cur if cur and cur in pkgs else pkgs[0])
            if profiles:
                self.prof_combo.configure(values=profiles)
                if self.cfg["profile"] in profiles:
                    self.prof_var.set(self.cfg["profile"])
            self._update_path_label()
        self._run_bg("自动探测存档位置", fn, done, quiet=silent)

    # ------------------------------------------------------------ 导出 / 载入
    def _export(self):
        self._sync_cfg_from_ui()
        s = self._selected_serial()
        def fn(log):
            return core.export_save(self.cfg, s, log=log)
        def done(r):
            self.log(f"存档来源：{r['remote']}")
            self._load_local(r["local_dir"], "export")
            self._auto_apply_presets()
            self.backup_dir = None
        self._run_bg("一键导出存档", fn, done)

    def _load_latest_export(self):
        d = core.latest_export_dir()
        if d:
            self._load_local(d, "export")
            self.log("已自动载入最近一次导出：" + d)

    # ------------------------------------------------------------ Venture / 手动目录
    def _autoload_venture(self):
        """启动时先找 Venture 存档：它是模拟器里正在用的存档，优先于旧导出快照。"""
        if not self.cfg.get("venture_auto_detect", True):
            return
        try:
            found = core.find_venture_saves(self.cfg, log=lambda m: None)
        except Exception:
            return
        if not found:
            return
        r = found[0]
        self._load_local(r["path"], "venture", r)
        self.log("已自动载入 Venture 模拟器存档：用户 %s／槽位 %s（%d 个文件，最后写入 %s）。"
                 % (r["user"][:10], r["profile"], r["count"], r["mtime"]))
        self.log("　　保存请用「② 保存到 Venture 存档」：直接写回该目录，保存前自动备份。")

    def _venture_scan(self):
        self._sync_cfg_from_ui()
        def fn(log):
            return core.find_venture_saves(self.cfg, log=log)
        def done(found):
            if not found:
                messagebox.showinfo(
                    "未找到 Venture 存档",
                    "没有在 Venture 目录里找到 H3VR2 存档。\n\n"
                    "· 确认 Venture 里装过游戏并至少运行过一次（存档在首次进枢纽后生成）；\n"
                    "· 或在 config.json 的 venture_root 填写 Venture 数据目录；\n"
                    "· 或点「手动选择存档目录…」直接选 footlong.base / SaveData 目录。\n\n"
                    "已搜索：\n" + "\n".join(core.venture_roots(self.cfg)
                                              or ["（未找到 Venture 安装目录）"]))
                return
            r = found[0] if len(found) == 1 else self._pick_venture_save(found)
            if r:
                self._open_venture(r)
        self._run_bg("查找 Venture 存档", fn, done)

    def _pick_dialog(self, title: str, hint: str, lines: list[str]) -> int | None:
        """通用单选对话框，返回下标（取消返回 None）。"""
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        top.grab_set()
        ttk.Label(top, text=hint, padding=(10, 8, 10, 4)).pack(anchor="w")
        lb = tk.Listbox(top, width=118, height=min(12, max(3, len(lines))),
                        font=FONT_MONO, activestyle="dotbox", exportselection=False)
        for line in lines:
            lb.insert("end", line)
        lb.selection_set(0)
        lb.pack(fill="both", expand=True, padx=10)
        out = {"i": None}

        def ok(_=None):
            sel = lb.curselection()
            out["i"] = sel[0] if sel else None
            top.destroy()

        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="载入", command=ok).pack(side="left")
        ttk.Button(bar, text="取消", command=top.destroy).pack(side="left", padx=6)
        lb.bind("<Double-Button-1>", ok)
        top.wait_window()
        return out["i"]

    def _pick_venture_save(self, found: list[dict]) -> dict | None:
        lines = ["{}{}/{}{} · {} 个文件 · {}  ·  {}".format(
            "" if r["official"] else "[非官方包名] ", r["user"][:10] or "-", r["profile"],
            "" if r["official"] else f"（{r['package']}）", r["count"], r["mtime"], r["path"])
            for r in found]
        i = self._pick_dialog("选择 Venture 存档",
                              "找到多份存档（不同账号 / 槽位），选一份载入：", lines)
        return found[i] if i is not None else None

    def _pick_paths(self, found: list[str]) -> str | None:
        lines = []
        for d in found:
            files = sorted(glob.glob(os.path.join(d, "*.json.gz")))
            mt = max((os.path.getmtime(f) for f in files), default=0)
            when = datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M") if mt else "-"
            lines.append(f"{len(files)} 个文件 · {when}  ·  {d}")
        i = self._pick_dialog("选择存档目录", "该目录下找到多个存档，选一个载入：", lines)
        return found[i] if i is not None else None

    def _open_venture(self, r: dict):
        if not r.get("official") and not messagebox.askyesno(
                "非官方包名",
                f"该存档来自非官方包名：{r['package']}\n\n"
                "本程序默认只认官方包名 com.rustltd.h3vr2；其他包名可能属于改过的安装版本，"
                "存档结构未必一致。仍要载入并允许写回吗？"):
            return
        self._load_local(r["path"], "venture", r)
        self._auto_apply_presets()
        self.log("Venture 存档：用户 %s／槽位 %s／包名 %s（最后写入 %s）"
                 % (r["user"], r["profile"], r["package"], r["mtime"]))

    def _load_local(self, path: str, kind: str = "manual", meta: dict | None = None):
        try:
            self.data = core.load_save(path)
        except Exception as e:
            messagebox.showerror("载入失败", str(e))
            return
        self.local_dir = path
        self.source_kind = kind if self.data else "none"
        self.source_meta = dict(meta or {})
        self.dirty.clear()
        self.file_list.delete(0, "end")
        for n in sorted(self.data):
            self.file_list.insert("end", n)
        if self.data:
            self.file_list.selection_set(0)
            self.current_file = sorted(self.data)[0]
        self._refresh_quick()
        self._refresh_store()
        self._refresh_inventory()
        self._refresh_favorites()
        self._preset_refresh()
        self._refresh_tree()
        self._refresh_raw()
        self._refresh_desc()
        self._update_source_label()
        self.set_status(f"已载入 {len(self.data)} 个存档文件")
        self.log(f"载入本地存档：{path}（{len(self.data)} 个文件）")

    def _update_source_label(self):
        d = self.local_dir or ""
        if self.source_kind == "venture" and d:
            m = self.source_meta or {}
            who = "用户 %s／槽位 %s／%s" % (m.get("user", "手动"), m.get("profile", "?"),
                                          m.get("package", self.cfg["package"]))
            self.source_var.set("Venture 模拟器存档（%s）——「② 保存到 Venture 存档」"
                                "直接写回，保存前自动备份\n%s" % (who, d))
            self.btn_save.configure(text="② 保存到 Venture 存档")
        elif self.source_kind == "export" and d:
            self.source_var.set("头显导出快照 ——「② 保存到本地」只改本地副本，"
                                "需再点「③ 一键回传到头显」才会生效\n" + d)
            self.btn_save.configure(text="② 保存到本地")
        elif self.source_kind == "manual" and d:
            self.source_var.set("手动选择的本地目录 ——「② 保存到本地目录」直接写回；"
                                "要回到头显再用「③ 一键回传到头显」\n" + d)
            self.btn_save.configure(text="② 保存到本地目录")
        else:
            self.source_var.set("尚未载入存档 —— 可点「查找 Venture 存档」「手动选择存档目录」"
                                "或「① 一键导出存档」")
            self.btn_save.configure(text="② 保存到本地")

    def _reload_source(self):
        if self.local_dir and os.path.isdir(self.local_dir):
            self._load_local(self.local_dir, self.source_kind, self.source_meta)
        else:
            messagebox.showinfo("提示", "尚未载入存档目录")

    def _choose_dir(self):
        d = filedialog.askdirectory(
            title="选择存档目录（footlong.base / Profile0 / SaveData / Venture 用户目录均可）")
        if not d:
            return
        found = core.find_save_dirs(d, self.cfg["save_subdir"], depth=2)
        if not found:
            # 玩家可能停在任意一层（external-data / 包名 / 账号目录 / Venture 根目录），
            # 放宽到 8 层；find_save_dirs 自带目录数上限，误选大目录也不会卡死。
            found = core.find_save_dirs(d, self.cfg["save_subdir"], depth=8)
        if not found:
            messagebox.showwarning("没有存档",
                                   "该目录下没有找到 *.json.gz 存档文件：\n" + d +
                                   "\n\n请选到 footlong.base 或它的上一层（Profile0 / SaveData）。")
            return
        path = found[0] if len(found) == 1 else self._pick_paths(found)
        if not path:
            return
        kind = "venture" if self._is_venture_dir(path) else "manual"
        meta = {"user": "手动", "profile": os.path.basename(os.path.dirname(path)),
                "package": self.pkg_var.get().strip() or self.cfg["package"]}
        self._load_local(path, kind, meta)
        self._auto_apply_presets()
        if kind == "venture":
            self.log("该目录位于 Venture 数据目录内，按 Venture 存档处理：保存会直接写回。")

    def _is_venture_dir(self, path: str) -> bool:
        low = os.path.normcase(os.path.abspath(path))
        for root in core.venture_roots(self.cfg):
            if low.startswith(os.path.normcase(os.path.abspath(root)) + os.sep):
                return True
        return "external-data" in low


    def _open_dir(self):
        if self.local_dir and os.path.isdir(self.local_dir):
            os.startfile(self.local_dir)
        else:
            messagebox.showinfo("提示", "尚未载入存档目录")

    def _on_file_select(self):
        sel = self.file_list.curselection()
        if not sel:
            return
        name = self.file_list.get(sel[0])
        if name == self.current_file:
            return
        if self._raw_dirty():
            if not messagebox.askyesno("未应用的修改", "原始 JSON 有未应用的修改，切换文件将丢弃，继续？"):
                self.file_list.selection_clear(0, "end")
                self.file_list.selection_set(sorted(self.data).index(self.current_file))
                return
        self.current_file = name
        self._refresh_tree()
        self._refresh_raw()
        self._refresh_desc()

    # ------------------------------------------------------------ 快捷编辑
    def _refresh_quick(self):
        for f, path, typ, e in self.quick_entries:
            v = core.quick_read(self.data, f, path)
            e.delete(0, "end")
            e.insert(0, "" if v is None else str(v))

    def _apply_quick(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        changed = 0
        for f, path, typ, e in self.quick_entries:
            txt = e.get().strip()
            if txt == "":
                continue
            old = core.quick_read(self.data, f, path)
            try:
                v = core.parse_value(txt, old)
            except Exception as ex:
                messagebox.showerror("输入错误", f"{path}：{ex}")
                return
            if v != old:
                core.quick_write(self.data, f, path, v)
                self.dirty.add(f)
                changed += 1
        self._refresh_tree()
        self._refresh_raw()
        self.log(f"快捷编辑应用：{changed} 个字段变更（尚未写盘）")
        self.set_status(f"{changed} 个字段已修改，请保存或回传")

    def _preset_easy(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        presets = [("Settings.json.gz", "Data.Settings.npcDamage", 0.25),
                   ("Settings.json.gz", "Data.Settings.playerDamage", 2.0),
                   ("Settings.json.gz", "Data.Settings.powerupDuration", 2.0)]
        for f, p, v in presets:
            core.quick_write(self.data, f, p, v)
            self.dirty.add(f)
        self._refresh_quick()
        self._refresh_tree()
        self._refresh_raw()
        self.log("已应用降难度预设：npcDamage=0.25 / playerDamage=2 / powerupDuration=2")
        self.set_status("降难度预设已应用")

    def _store_discount(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        try:
            factor = float(self.store_factor.get())
        except ValueError:
            messagebox.showerror("输入错误", "价格系数必须是数字")
            return
        n = core.scale_store_prices(self.data, factor)
        self._mark_stores_dirty()
        self.log("全部商店价格已乘 %s：%d 个货位" % (factor, n))

    def _store_fixed_price(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        try:
            v = int(self.store_fixed.get())
        except ValueError:
            messagebox.showerror("输入错误", "价格必须是整数")
            return
        n = core.set_all_store_prices(self.data, v, store=self.store_var.get() or None)
        self._mark_stores_dirty()
        self.log("当前商店 %d 个货位价格统一设为 %d" % (n, v))

    def _apply_mags(self):
        try:
            cap = int(self.mag_cap.get())
        except ValueError:
            messagebox.showerror("输入错误", "容量必须是整数")
            return
        n = core.fill_magazines(self.data, cap)
        self.dirty.add("Inventory.json.gz")
        self._refresh_tree()
        self._refresh_raw()
        self.log(f"弹匣补满：新增 {n} 发子弹")

    # ------------------------------------------------------------ 预设 / 收藏（通用）
    def _persist_ud(self):
        try:
            core.save_user_data(self.ud, self.ud_path)
        except Exception as e:
            self.log("保存 presets.json 失败：" + str(e))
            messagebox.showerror("保存失败", str(e))

    def _preset_bar(self, parent, kind: str):
        box = ttk.LabelFrame(parent, text=" 预设（保存在 presets.json，导出新存档后可一键还原） ", padding=5)
        box.pack(fill="x", padx=6, pady=(2, 4))
        var = tk.StringVar()
        combo = ttk.Combobox(box, textvariable=var, width=28, state="readonly", font=FONT)
        combo.pack(side="left", padx=3)
        ttk.Button(box, text="一键应用（替换）",
                   command=lambda: self._preset_apply(kind, "replace")).pack(side="left", padx=2)
        ttk.Button(box, text="追加物品",
                   command=lambda: self._preset_apply(kind, "append")).pack(side="left", padx=2)
        ttk.Button(box, text="保存当前为预设",
                   command=lambda: self._preset_save(kind)).pack(side="left", padx=2)
        ttk.Button(box, text="删除预设",
                   command=lambda: self._preset_delete(kind)).pack(side="left", padx=2)
        ttk.Separator(box, orient="vertical").pack(side="left", fill="y", padx=8)
        auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="导出/载入新存档时自动应用此预设", variable=auto,
                        command=lambda: self._preset_auto(kind, auto.get(), var.get())
                        ).pack(side="left", padx=2)
        ttk.Button(box, text="★ 收藏 / 管理预设",
                   command=lambda: self.nb.select(self.tab_favorites)).pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda e: self._preset_refresh(kind))
        self.preset_bars[kind] = {"combo": combo, "var": var, "auto": auto}
        return box

    def _preset_refresh(self, kind=None):
        s = self.ud.get("settings") or {}
        for k in ([kind] if kind else ["store", "inventory"]):
            bar = self.preset_bars.get(k)
            if not bar:
                continue
            names = (core.store_preset_names(self.ud) if k == "store"
                     else core.inventory_preset_names(self.ud))
            bar["combo"].configure(values=names)
            auto_name = str(s.get(k + "_auto_preset") or "")
            cur = bar["var"].get()
            if cur not in names:
                cur = auto_name if auto_name in names else (names[0] if names else "")
                bar["var"].set(cur)
            bar["auto"].set(bool(auto_name) and auto_name == cur)
        self._refresh_fav_settings()

    def _preset_auto(self, kind, enabled, name):
        label = "商店" if kind == "store" else "仓库"
        s = self.ud.setdefault("settings", {})
        if enabled and name:
            s[kind + "_auto_preset"] = name
            self.log("已开启自动应用：%s预设「%s」" % (label, name))
        else:
            s[kind + "_auto_preset"] = ""
            self.log("已关闭%s预设自动应用" % label)
        self._persist_ud()
        self._preset_refresh()

    def _preset_apply(self, kind, mode):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        bar = self.preset_bars.get(kind)
        name = bar["var"].get().strip() if bar else ""
        if not name:
            messagebox.showinfo("提示", "请先在下拉框选一个预设；也可点「保存当前为预设」新建")
            return
        label = "商店" if kind == "store" else "仓库"
        if mode == "replace" and not messagebox.askyesno(
                "确认替换", "将用预设「%s」%s，继续？" %
                (name, "重建商店全部货位" if kind == "store" else "清空并重建整个玩家仓库")):
            return
        if kind == "store":
            preset = core.get_store_preset(self.ud, name)
            store = self.store_var.get()
            if not preset or not store:
                messagebox.showerror("失败", "预设或商店不存在")
                return
            n = core.apply_store_preset(self.data, store, preset, mode)
            self._mark_stores_dirty()
        else:
            preset = core.get_inventory_preset(self.ud, name)
            if not preset:
                messagebox.showerror("失败", "预设不存在")
                return
            n = core.apply_inventory_preset(self.data, preset, mode)
            self._mark_inventory_dirty()
        self.log("%s预设「%s」已应用：%d 项（%s）" % (label, name, n, mode))
        self.set_status("预设已应用，请保存或回传")

    def _preset_save(self, kind):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        label = "商店" if kind == "store" else "仓库"
        name = simpledialog.askstring(
            "保存预设", "给这套%s内容起个名字：" % label,
            initialvalue=label + "预设_" + datetime.now().strftime("%m%d_%H%M"),
            parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        names = (core.store_preset_names(self.ud) if kind == "store"
                 else core.inventory_preset_names(self.ud))
        if name in names and not messagebox.askyesno("覆盖", "预设「%s」已存在，覆盖？" % name):
            return
        if kind == "store":
            store = self.store_var.get()
            if not store:
                messagebox.showerror("失败", "没有可保存的商店")
                return
            n = core.save_store_preset(self.ud, name, self.data, store)
        else:
            n = core.save_inventory_preset(self.ud, name, self.data)
        self._persist_ud()
        self.preset_bars[kind]["var"].set(name)
        self._preset_refresh()
        self._refresh_favorites()
        self.log("已保存%s预设「%s」：%d 项 → %s" % (label, name, n, self.ud_path))
        messagebox.showinfo("已保存",
                            "预设「%s」已写入 presets.json（%d 项）。\n"
                            "以后导出新存档后，选中它点「一键应用」即可还原。" % (name, n))

    def _preset_delete(self, kind):
        bar = self.preset_bars.get(kind)
        name = bar["var"].get().strip() if bar else ""
        if not name:
            return
        if not messagebox.askyesno("确认删除", "删除预设「%s」？" % name):
            return
        if core.delete_preset(self.ud, kind, name):
            s = self.ud.setdefault("settings", {})
            if str(s.get(kind + "_auto_preset") or "") == name:
                s[kind + "_auto_preset"] = ""
            self._persist_ud()
            self._preset_refresh()
            self._refresh_favorites()
            self.log("已删除预设「%s」" % name)

    def _auto_apply_presets(self):
        """导出 / 载入新存档后，按 presets.json 的设置自动还原上次编辑内容。"""
        self.ud = core.load_user_data(self.ud_path)
        done = core.apply_auto_presets(self.data, self.ud, log=self.log)
        s = self.ud.get("settings") or {}
        if str(s.get("store_auto_preset") or ""):
            self.dirty.add(core.STORES_FILE)
        if str(s.get("inventory_auto_preset") or ""):
            self.dirty.add(core.INVENTORY_FILE)
        self._refresh_store()
        self._refresh_inventory()
        self._refresh_tree()
        self._refresh_raw()
        self._preset_refresh()
        self._refresh_favorites()
        if done:
            self.log("已自动还原上次编辑内容；确认无误后点「② 保存到本地」或「③ 一键回传」")
            self.set_status("预设已自动应用，请保存或回传")

    # ------------------------------------------------------------ 仓库编辑页
    def _build_inventory(self):
        top = ttk.Frame(self.tab_inventory)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="仓库页：").pack(side="left")
        self.inv_page_var = tk.StringVar()
        self.inv_page_combo = ttk.Combobox(top, textvariable=self.inv_page_var, width=30,
                                           state="readonly", font=FONT)
        self.inv_page_combo.pack(side="left", padx=4)
        self.inv_page_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_inventory())
        ttk.Button(top, text="刷新", command=self._refresh_inventory).pack(side="left", padx=3)
        ttk.Label(top, text="双击槽位可改物品 / 位置 / 占格；新增物品自动找空格，页满会自动开新页",
                  foreground="#777777").pack(side="left", padx=12)

        self._preset_bar(self.tab_inventory, "inventory")

        mid = ttk.Frame(self.tab_inventory)
        mid.pack(fill="both", expand=True, padx=6)
        cols = ("idx", "pos", "size", "zh", "key", "objs", "comps", "verified")
        heads = {"idx": "#", "pos": "位置", "size": "占格", "zh": "主物品（中文）",
                 "key": "AssetKey", "objs": "物件数", "comps": "组件数", "verified": "引用"}
        widths = {"idx": 42, "pos": 80, "size": 70, "zh": 250, "key": 250,
                  "objs": 75, "comps": 75, "verified": 85}
        self.inv_tree = ttk.Treeview(mid, columns=cols, show="headings", height=14)
        for c in cols:
            self.inv_tree.heading(c, text=heads[c])
            self.inv_tree.column(c, width=widths[c], anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.inv_tree.yview)
        self.inv_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.inv_tree.pack(side="left", fill="both", expand=True)
        self.inv_tree.bind("<Double-1>", lambda e: self._edit_inventory_slot())

        bottom = ttk.Frame(self.tab_inventory)
        bottom.pack(fill="x", padx=6, pady=6)
        ttk.Button(bottom, text="编辑选中槽位", command=self._edit_inventory_slot).pack(side="left")
        ttk.Button(bottom, text="＋ 新增物品", command=self._add_inventory_item).pack(side="left", padx=4)
        ttk.Button(bottom, text="★ 从收藏添加", command=self._add_favorites_to_inventory).pack(side="left")
        ttk.Button(bottom, text="复制槽位", command=self._dup_inventory_slot).pack(side="left", padx=4)
        ttk.Button(bottom, text="删除选中槽位", command=self._del_inventory_slot).pack(side="left")
        ttk.Label(self.tab_inventory,
                  text="新增物件采用存档里简单物件的最小结构（Components 为空）；复杂枪械建议用「复制槽位」保留组件状态，或直接在游戏里获取。",
                  foreground="#777777").pack(fill="x", padx=6, pady=(0, 6))

    def _refresh_inventory(self):
        if not hasattr(self, "inv_tree"):
            return
        self.inv_tree.delete(*self.inv_tree.get_children())
        if not self.data:
            return
        pages = core.inventory_pages(self.data)
        labels = ["第 %d 页（%d 个槽位）" % (i + 1, len(pg.get("items", []) or []))
                  for i, pg in enumerate(pages)]
        self.inv_page_labels = {l: i for i, l in enumerate(labels)}
        self.inv_page_combo.configure(values=labels)
        cur = self.inv_page_var.get()
        if cur not in labels:
            cur = labels[0] if labels else ""
            self.inv_page_var.set(cur)
        if not cur:
            return
        pi = self.inv_page_labels[cur]
        for s in core.list_inventory_slots(self.data, pi):
            it = core.item_by_ref(s["ref"]) or {}
            self.inv_tree.insert("", "end", iid=str(s["index"]), values=(
                s["index"] + 1,
                "(%s,%s)" % (s["rectMin"][0], s["rectMin"][1]),
                "%sx%s" % (s["rectSize"][0], s["rectSize"][1]),
                s["zh"] or "（未译）", s["key"], s["count"], s["components"],
                "已验证" if it.get("verified") else "未验证"))

    def _mark_inventory_dirty(self):
        self.dirty.add(core.INVENTORY_FILE)
        self._refresh_inventory()
        self._refresh_tree()
        self._refresh_raw()
        self.set_status("仓库已修改，请保存或回传")

    def _selected_inv(self):
        if not hasattr(self, "inv_tree"):
            return None
        sel = self.inv_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个槽位（或双击该行）")
            return None
        pi = self.inv_page_labels.get(self.inv_page_var.get(), 0)
        return pi, int(sel[0])

    def _add_inventory_item(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        ref = pick_item(self.root, self, "选择要加入仓库的物品")
        if not ref:
            return
        pi = self.inv_page_labels.get(self.inv_page_var.get(), 0)
        r = core.add_inventory_object(self.data, ref, page_index=pi)
        self._mark_inventory_dirty()
        self.log("仓库新增物品：%s → 第 %d 页 槽位 #%d，位置 %s" %
                 (core.asset_key(ref), r["page"] + 1, r["index"] + 1, r["rectMin"]))

    def _add_favorites_to_inventory(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        refs = core.favorite_refs(self.ud)
        if not refs:
            messagebox.showinfo("提示", "收藏夹是空的，请到「★ 收藏与预设」页添加")
            return
        n = core.add_inventory_from_refs(self.data, refs)
        self._mark_inventory_dirty()
        self.log("已从收藏加入仓库：%d 件" % n)

    def _dup_inventory_slot(self):
        sel = self._selected_inv()
        if not sel:
            return
        r = core.duplicate_inventory_slot(self.data, sel[0], sel[1])
        if not r:
            return
        self._mark_inventory_dirty()
        self.log("已复制槽位 #%d → 第 %d 页 #%d（InstanceSeed 已重新生成）" %
                 (sel[1] + 1, r["page"] + 1, r["index"] + 1))

    def _del_inventory_slot(self):
        sel = self._selected_inv()
        if not sel:
            return
        if not messagebox.askyesno(
                "确认删除", "删除第 %d 页槽位 #%d？\n槽位内的所有物件会一起删除，建议先备份存档。" %
                (sel[0] + 1, sel[1] + 1)):
            return
        if core.delete_inventory_slot(self.data, sel[0], sel[1]):
            self._mark_inventory_dirty()
            self.log("已删除仓库槽位 #%d" % (sel[1] + 1))

    def _edit_inventory_slot(self):
        sel = self._selected_inv()
        if not sel:
            return
        pi, idx = sel
        slot = core.get_inventory_slot(self.data, pi, idx)
        if slot is None:
            return
        draft = copy.deepcopy(slot)
        objs = draft.setdefault("contents", {}).setdefault("Objects", [])
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑仓库槽位  第%d页 #%d" % (pi + 1, idx + 1))
        dlg.geometry("940x630")
        dlg.transient(self.root)
        dlg.grab_set()
        for c in range(4):
            dlg.columnconfigure(c, weight=1)
        dlg.rowconfigure(1, weight=1)

        ttk.Label(dlg, text="槽位内物件（「枪 + 弹匣」这类复合物品会分别列出）：",
                  font=FONT_B).grid(row=0, column=0, columnspan=5, sticky="w", padx=8, pady=(8, 4))
        lb = tk.Listbox(dlg, height=10, font=FONT_MONO, exportselection=False)
        lb.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=8)
        sb = ttk.Scrollbar(dlg, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.grid(row=1, column=4, sticky="ns")

        def refill_objs():
            lb.delete(0, "end")
            for j, o in enumerate(objs):
                ref = o.get("ItemDef", "")
                it = core.item_by_ref(ref) or {}
                lb.insert("end", "[%d] %s | %s | 组件 %d | %s" %
                          (j, it.get("zh") or "—", core.asset_key(ref),
                           len(o.get("Components") or []), ref))
            if objs:
                lb.selection_set(0)
        refill_objs()

        refv = tk.StringVar()

        def on_select(_=None):
            s = lb.curselection()
            if s:
                refv.set(objs[s[0]].get("ItemDef", ""))
        lb.bind("<<ListboxSelect>>", on_select)
        on_select()

        ttk.Label(dlg, text="物品引用：").grid(row=2, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Entry(dlg, textvariable=refv, font=FONT_MONO).grid(
            row=2, column=1, columnspan=4, sticky="ew", padx=8, pady=(8, 2))

        clear_comp = tk.BooleanVar(value=True)

        def apply_ref():
            s = lb.curselection()
            if not s:
                messagebox.showinfo("提示", "请先选中一个物件", parent=dlg)
                return
            r = refv.get().strip()
            if not r.startswith("extref://"):
                messagebox.showerror("输入错误", "物品引用必须以 extref:// 开头", parent=dlg)
                return
            objs[s[0]]["ItemDef"] = r
            if clear_comp.get():
                objs[s[0]]["Components"] = []
                draft["contents"]["Affixments"] = []
            refill_objs()
            lb.selection_set(s[0])
            on_select()

        def change():
            s = lb.curselection()
            if not s:
                messagebox.showinfo("提示", "请先选中一个物件", parent=dlg)
                return
            r = pick_item(dlg, self, "更换仓库物件", current_ref=objs[s[0]].get("ItemDef", ""))
            if not r:
                return
            refv.set(r)
            apply_ref()

        def clear():
            s = lb.curselection()
            if not s:
                return
            objs[s[0]]["Components"] = []
            draft["contents"]["Affixments"] = []
            refill_objs()
            lb.selection_set(s[0])

        bar = ttk.Frame(dlg)
        bar.grid(row=3, column=0, columnspan=5, sticky="w", padx=8, pady=6)
        ttk.Button(bar, text="从目录更换选中物件", command=change).pack(side="left")
        ttk.Button(bar, text="应用左侧引用", command=apply_ref).pack(side="left", padx=4)
        ttk.Button(bar, text="清空选中物件组件", command=clear).pack(side="left", padx=4)
        ttk.Checkbutton(bar, text="换物品时清空该物件组件（推荐）",
                        variable=clear_comp).pack(side="left", padx=10)

        gf = ttk.LabelFrame(dlg, text=" 槽位位置 / 占格 ", padding=6)
        gf.grid(row=4, column=0, columnspan=5, sticky="ew", padx=8, pady=6)
        vx = tk.StringVar(value=str(draft.get("rectMin", [0, 0])[0]))
        vy = tk.StringVar(value=str(draft.get("rectMin", [0, 0])[1]))
        vw = tk.StringVar(value=str(draft.get("rectSize", [1, 1])[0]))
        vh = tk.StringVar(value=str(draft.get("rectSize", [1, 1])[1]))
        for col, txt, var in [(0, "rectMin X：", vx), (2, "Y：", vy),
                              (4, "rectSize 宽：", vw), (6, "高：", vh)]:
            ttk.Label(gf, text=txt).grid(row=0, column=col, sticky="w", padx=(4, 0))
            ttk.Entry(gf, textvariable=var, width=7).grid(row=0, column=col + 1, sticky="w")
        ttk.Label(gf, text="网格 12×8；改占格时 contents.GridSize 会同步。请勿与其他槽位重叠。",
                  foreground="#777777").grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))

        def ok():
            try:
                w, h = int(vw.get()), int(vh.get())
                if w < 1 or h < 1:
                    raise ValueError
                draft["rectMin"] = [int(vx.get()), int(vy.get())]
                draft["rectSize"] = [w, h]
                draft["contents"]["GridSize"] = [w, h]
            except ValueError:
                messagebox.showerror("输入错误", "位置 / 占格必须是整数，且宽高 >= 1", parent=dlg)
                return
            core.inventory_pages(self.data)[pi]["items"][idx] = draft
            self._mark_inventory_dirty()
            self.log("已编辑第 %d 页仓库槽位 #%d（%d 个物件）" % (pi + 1, idx + 1, len(objs)))
            dlg.destroy()

        bb = ttk.Frame(dlg)
        bb.grid(row=5, column=0, columnspan=5, sticky="e", padx=8, pady=8)
        ttk.Button(bb, text="取消", command=dlg.destroy).pack(side="right", padx=4)
        ttk.Button(bb, text="确定", command=ok).pack(side="right")

    # ------------------------------------------------------------ 收藏与预设页
    def _build_favorites(self):
        top = ttk.Frame(self.tab_favorites)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Button(top, text="＋ 添加物品到收藏", command=self._fav_add).pack(side="left")
        ttk.Button(top, text="移除选中", command=self._fav_remove).pack(side="left", padx=4)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(top, text="收藏 → 商店", command=self._fav_to_store).pack(side="left")
        ttk.Label(top, text="售价：").pack(side="left", padx=(6, 0))
        self.fav_price = tk.StringVar(value="1")
        ttk.Entry(top, textvariable=self.fav_price, width=8).pack(side="left")
        ttk.Button(top, text="收藏 → 仓库", command=self._fav_to_inventory).pack(side="left", padx=8)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(top, text="打开 presets.json", command=self._fav_open_file).pack(side="left")
        ttk.Button(top, text="导出预设", command=self._fav_export).pack(side="left", padx=4)
        ttk.Button(top, text="导入预设", command=self._fav_import).pack(side="left")

        mid = ttk.Frame(self.tab_favorites)
        mid.pack(fill="both", expand=True, padx=6)
        cols = ("star", "zh", "en", "key", "ref", "verified")
        heads = {"star": "★", "zh": "中文名", "en": "英文名",
                 "key": "AssetKey", "ref": "物品引用", "verified": "引用"}
        widths = {"star": 40, "zh": 220, "en": 220, "key": 210, "ref": 430, "verified": 85}
        self.fav_tree = ttk.Treeview(mid, columns=cols, show="headings", height=10)
        for c in cols:
            self.fav_tree.heading(c, text=heads[c])
            self.fav_tree.column(c, width=widths[c], anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.fav_tree.yview)
        self.fav_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.fav_tree.pack(side="left", fill="both", expand=True)
        ttk.Label(self.tab_favorites,
                  text="在列表里选中若干项 → 只添加选中的；不选中 → 添加全部收藏。物品选择框里可勾「只看 ★ 收藏」快速定位。",
                  foreground="#777777").pack(fill="x", padx=6, pady=(4, 0))

        st = ttk.LabelFrame(self.tab_favorites,
                            text=" 导出 / 载入新存档时自动应用（这样就不用重新编辑） ", padding=6)
        st.pack(fill="x", padx=6, pady=6)
        self.auto_store_var = tk.StringVar()
        self.auto_inv_var = tk.StringVar()
        self.auto_store_mode = tk.StringVar(value="replace")
        self.auto_inv_mode = tk.StringVar(value="append")
        ttk.Label(st, text="商店预设：").grid(row=0, column=0, sticky="w", padx=4)
        self.auto_store_combo = ttk.Combobox(st, textvariable=self.auto_store_var, width=26,
                                             state="readonly", font=FONT)
        self.auto_store_combo.grid(row=0, column=1, sticky="w")
        ttk.Combobox(st, textvariable=self.auto_store_mode, width=11, state="readonly",
                     values=["replace", "append"]).grid(row=0, column=2, padx=4)
        ttk.Label(st, text="仓库预设：").grid(row=0, column=3, sticky="w", padx=(14, 4))
        self.auto_inv_combo = ttk.Combobox(st, textvariable=self.auto_inv_var, width=26,
                                           state="readonly", font=FONT)
        self.auto_inv_combo.grid(row=0, column=4, sticky="w")
        ttk.Combobox(st, textvariable=self.auto_inv_mode, width=11, state="readonly",
                     values=["append", "replace"]).grid(row=0, column=5, padx=4)
        ttk.Button(st, text="保存自动应用设置", command=self._fav_save_settings).grid(
            row=0, column=6, padx=10)
        ttk.Button(st, text="停用自动应用", command=self._fav_disable_auto).grid(row=0, column=7)
        ttk.Label(st, text="预设留空 = 不自动应用；replace = 覆盖现有内容，append = 追加（仓库追加会自动跳过已存在的同款物品）。",
                  foreground="#777777").grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))

    def _refresh_fav_settings(self):
        if not hasattr(self, "auto_store_combo"):
            return
        s = self.ud.get("settings") or {}
        self.auto_store_combo.configure(values=[""] + core.store_preset_names(self.ud))
        self.auto_inv_combo.configure(values=[""] + core.inventory_preset_names(self.ud))
        self.auto_store_var.set(str(s.get("store_auto_preset") or ""))
        self.auto_inv_var.set(str(s.get("inventory_auto_preset") or ""))
        self.auto_store_mode.set(str(s.get("store_auto_mode") or "replace"))
        self.auto_inv_mode.set(str(s.get("inventory_auto_mode") or "append"))

    def _refresh_favorites(self):
        if not hasattr(self, "fav_tree"):
            return
        self.fav_tree.delete(*self.fav_tree.get_children())
        self.fav_list = core.favorite_labels(self.ud)
        for i, f in enumerate(self.fav_list):
            self.fav_tree.insert("", "end", iid=str(i), values=(
                "★", f["zh"] or "—", f["en"] or "—", f["key"], f["ref"],
                "已验证" if f["verified"] else "未验证"))
        self._refresh_fav_settings()

    def _fav_selected_refs(self):
        sel = self.fav_tree.selection()
        if sel:
            return [self.fav_list[int(i)]["ref"] for i in sel]
        return core.favorite_refs(self.ud)

    def _fav_add(self):
        ref = pick_item(self.root, self, "添加物品到收藏")
        if not ref:
            return
        core.set_favorite(self.ud, ref, True)
        self._persist_ud()
        self._refresh_favorites()
        self.log("已加入收藏：" + core.asset_key(ref))

    def _fav_remove(self):
        sel = self.fav_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表里选中要移除的物品")
            return
        for i in sel:
            core.set_favorite(self.ud, self.fav_list[int(i)]["ref"], False)
        self._persist_ud()
        self._refresh_favorites()
        self.log("已移除 %d 个收藏" % len(sel))

    def _fav_to_store(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        store = self.store_var.get()
        if not store:
            messagebox.showerror("失败", "没有可用的商店")
            return
        try:
            price = int(self.fav_price.get())
        except ValueError:
            messagebox.showerror("输入错误", "售价必须是整数")
            return
        refs = self._fav_selected_refs()
        if not refs:
            messagebox.showinfo("提示", "收藏夹是空的")
            return
        section = str((self.ud.get("settings") or {}).get("default_section") or "basics")
        n = core.add_favorites_to_store(self.data, store, refs, price, section)
        self._mark_stores_dirty()
        self.log("已从收藏加入商店 %d 个货位（售价 %d / 分区 %s）" % (n, price, section))
        self.nb.select(self.tab_store)

    def _fav_to_inventory(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        refs = self._fav_selected_refs()
        if not refs:
            messagebox.showinfo("提示", "收藏夹是空的")
            return
        n = core.add_inventory_from_refs(self.data, refs)
        self._mark_inventory_dirty()
        self.log("已从收藏加入仓库 %d 件" % n)
        self.nb.select(self.tab_inventory)

    def _fav_save_settings(self):
        s = self.ud.setdefault("settings", {})
        s["store_auto_preset"] = self.auto_store_var.get().strip()
        s["store_auto_mode"] = self.auto_store_mode.get().strip() or "replace"
        s["inventory_auto_preset"] = self.auto_inv_var.get().strip()
        s["inventory_auto_mode"] = self.auto_inv_mode.get().strip() or "append"
        self._persist_ud()
        self._preset_refresh()
        self.log("自动应用设置已保存：商店=%s(%s) / 仓库=%s(%s)" %
                (s["store_auto_preset"] or "关闭", s["store_auto_mode"],
                 s["inventory_auto_preset"] or "关闭", s["inventory_auto_mode"]))

    def _fav_disable_auto(self):
        s = self.ud.setdefault("settings", {})
        s["store_auto_preset"] = ""
        s["inventory_auto_preset"] = ""
        self._persist_ud()
        self._preset_refresh()
        self.log("已停用所有自动应用预设")

    def _fav_open_file(self):
        if not os.path.isfile(self.ud_path):
            self._persist_ud()
        try:
            os.startfile(self.ud_path)
            self.log("已打开配置文件：" + self.ud_path)
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _fav_export(self):
        p = filedialog.asksaveasfilename(title="导出预设与收藏", defaultextension=".json",
                                         initialfile="h3vr2_presets.json",
                                         filetypes=[("JSON", "*.json")])
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.ud, f, ensure_ascii=False, indent=2)
        self.log("预设与收藏已导出：" + p)

    def _fav_import(self):
        p = filedialog.askopenfilename(title="导入预设与收藏",
                                       filetypes=[("JSON", "*.json")])
        if not p:
            return
        other = core.load_user_data(p)
        for k in ("store_presets", "inventory_presets"):
            for name, val in (other.get(k) or {}).items():
                if name in self.ud.setdefault(k, {}) and not messagebox.askyesno(
                        "覆盖", "预设「%s」已存在，覆盖？" % name):
                    continue
                self.ud[k][name] = val
        have = {core.asset_key(x) for x in core.favorite_refs(self.ud)}
        for r in core.favorite_refs(other):
            k = core.asset_key(r)
            if k not in have:
                self.ud.setdefault("favorites", []).append(r)
                have.add(k)
        self._persist_ud()
        self._preset_refresh()
        self._refresh_favorites()
        self.log("预设与收藏已导入：" + p)

    # ------------------------------------------------------------ 参数树
    # ------------------------------------------------------------ 商店编辑页
    def _build_store(self):
        top = ttk.Frame(self.tab_store)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="商店：").pack(side="left")
        self.store_var = tk.StringVar()
        self.store_combo = ttk.Combobox(top, textvariable=self.store_var, width=56,
                                        state="readonly", font=FONT)
        self.store_combo.pack(side="left", padx=4)
        self.store_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_store())
        ttk.Button(top, text="刷新", command=self._refresh_store).pack(side="left", padx=3)
        ttk.Label(top, text="双击某一行可改出售物品 / 售价 / 分区",
                  foreground="#777777").pack(side="left", padx=12)

        self._preset_bar(self.tab_store, "store")

        mid = ttk.Frame(self.tab_store)
        mid.pack(fill="both", expand=True, padx=6)
        cols = ("idx", "section", "zh", "key", "price", "verified")
        heads = {"idx": "#", "section": "分区", "zh": "物品（中文）",
                 "key": "AssetKey", "price": "售价", "verified": "引用"}
        widths = {"idx": 42, "section": 130, "zh": 230, "key": 230, "price": 90, "verified": 90}
        self.store_tree = ttk.Treeview(mid, columns=cols, show="headings", height=16)
        for c in cols:
            self.store_tree.heading(c, text=heads[c])
            self.store_tree.column(c, width=widths[c], anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.store_tree.yview)
        self.store_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.store_tree.pack(side="left", fill="both", expand=True)
        self.store_tree.bind("<Double-1>", lambda e: self._edit_store_box())

        bottom = ttk.Frame(self.tab_store)
        bottom.pack(fill="x", padx=6, pady=6)
        ttk.Button(bottom, text="编辑选中货位", command=self._edit_store_box).pack(side="left")
        ttk.Button(bottom, text="新增货位", command=self._add_store_box).pack(side="left", padx=4)
        ttk.Button(bottom, text="删除选中货位", command=self._del_store_box).pack(side="left")
        ttk.Separator(bottom, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bottom, text="价格系数：").pack(side="left")
        self.store_factor = tk.StringVar(value="0.1")
        ttk.Entry(bottom, textvariable=self.store_factor, width=7).pack(side="left")
        ttk.Button(bottom, text="全部打折", command=self._store_discount).pack(side="left", padx=4)
        ttk.Label(bottom, text="统一售价：").pack(side="left", padx=(10, 0))
        self.store_fixed = tk.StringVar(value="1")
        ttk.Entry(bottom, textvariable=self.store_fixed, width=8).pack(side="left")
        ttk.Button(bottom, text="应用", command=self._store_fixed_price).pack(side="left", padx=4)
        ttk.Label(self.tab_store,
                  text="物品目录 items_catalog.json：来自 OBB 与存档内真实引用 + 汉化中文名；「引用」列显示是否已验证路径。",
                  foreground="#777777").pack(fill="x", padx=6, pady=(0, 6))

    def _refresh_store(self):
        if not hasattr(self, "store_tree"):
            return
        self.store_tree.delete(*self.store_tree.get_children())
        if not self.data:
            return
        stores = core.store_keys(self.data)
        cur = self.store_var.get()
        self.store_combo.configure(values=stores)
        if cur not in stores:
            cur = stores[0] if stores else ""
            self.store_var.set(cur)
        if not cur:
            return
        for b in core.list_store_boxes(self.data, cur):
            self.store_tree.insert("", "end", iid=str(b["index"]),
                values=(b["index"] + 1, b["sectionID"], b["zh"] or "（未译）",
                        b["key"], b["price"], "已验证" if b["verified"] else "未验证"))

    def _mark_stores_dirty(self):
        self.dirty.add("Stores.json.gz")
        self._refresh_store()
        self._refresh_tree()
        self._refresh_raw()
        self.set_status("商店已修改，请保存或回传")

    def _selected_box_index(self):
        sel = self.store_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个货位（或双击该行）")
            return None
        return int(sel[0])

    def _edit_store_box(self):
        if not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        idx = self._selected_box_index()
        if idx is None:
            return
        store = self.store_var.get()
        box = core.get_store_box(self.data, store, idx)
        if box is None:
            return
        cat = core.load_item_catalog()
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑商店货位 #%d" % (idx + 1))
        dlg.geometry("780x570")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.columnconfigure(0, weight=1)
        dlg.rowconfigure(2, weight=1)

        ttk.Label(dlg, text="搜索物品（中文名 / 英文名 / AssetKey）：", font=FONT_B).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))
        kw = tk.StringVar()
        ent_kw = ttk.Entry(dlg, textvariable=kw, width=80)
        ent_kw.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8)
        fav_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(dlg, text="只看 ★ 收藏", variable=fav_only).grid(
            row=1, column=3, sticky="w", padx=6)
        lb = tk.Listbox(dlg, height=12, font=FONT, exportselection=False)
        lb.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8, pady=4)
        sb = ttk.Scrollbar(dlg, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.grid(row=2, column=3, sticky="ns", pady=4)
        matches = []

        def refill(*_):
            lb.delete(0, "end")
            matches.clear()
            m, lines = _item_choice_lines(self, kw.get(), fav_only.get())
            matches.extend(m)
            for t in lines:
                lb.insert("end", t)
            cur = box.get("item", "")
            for i, it in enumerate(matches):
                if (it.get("ref") == cur or it.get("ref_alt") == cur
                        or it["key"] == core.asset_key(cur)):
                    lb.selection_set(i)
                    lb.see(i)
                    break
        kw.trace_add("write", refill)
        fav_only.trace_add("write", refill)
        refill()

        ttk.Label(dlg, text="物品引用：").grid(row=3, column=0, sticky="w", padx=8, pady=(8, 2))
        refv = tk.StringVar(value=box.get("item", ""))
        ttk.Entry(dlg, textvariable=refv, font=FONT_MONO).grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=8, pady=(8, 2))

        def on_pick(_):
            sel = lb.curselection()
            if not sel:
                return
            it = matches[sel[0]]
            refv.set(it.get("ref") or ("extref://footlong.base/Item/" + it["key"]))
        lb.bind("<<ListboxSelect>>", on_pick)

        ttk.Label(dlg, text="售价：").grid(row=4, column=0, sticky="w", padx=8, pady=6)
        pv = tk.StringVar(value=str(box.get("price", 0)))
        ttk.Entry(dlg, textvariable=pv, width=16).grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(dlg, text="分区：").grid(row=4, column=2, sticky="e", padx=8)
        sv = tk.StringVar(value=str(box.get("sectionID", "")))
        ttk.Entry(dlg, textvariable=sv, width=22).grid(row=4, column=3, sticky="w", padx=8)
        ttk.Label(dlg, text="选中列表项会自动填入该物品在游戏资源中的真实引用；也可手动粘贴任意 extref。",
                  foreground="#777777", wraplength=740).grid(
            row=5, column=0, columnspan=4, sticky="w", padx=8, pady=8)

        bf = ttk.Frame(dlg)
        bf.grid(row=6, column=0, columnspan=4, sticky="e", padx=8, pady=8)

        def ok():
            try:
                price = int(pv.get().strip())
            except ValueError:
                messagebox.showerror("输入错误", "售价必须是整数", parent=dlg)
                return
            ref = refv.get().strip()
            if not ref.startswith("extref://"):
                messagebox.showerror("输入错误", "物品引用必须以 extref:// 开头", parent=dlg)
                return
            core.set_store_box(self.data, store, idx, item=ref, price=price,
                               section=sv.get().strip())
            self._mark_stores_dirty()
            self.log("商店货位 #%d：%s / 售价 %d / 分区 %s" %
                     (idx + 1, ref, price, sv.get().strip()))
            dlg.destroy()
        def toggle_fav():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo("提示", "请先选中一个物品", parent=dlg)
                return
            it = matches[sel[0]]
            r = it.get("ref") or ("extref://footlong.base/Item/" + it["key"])
            state = core.toggle_favorite(self.ud, r)
            self._persist_ud()
            self._refresh_favorites()
            self.log(("已收藏 " if state else "已取消收藏 ") + it["key"])
            refill()
        ttk.Button(bf, text="★ 加入/取消收藏", command=toggle_fav).pack(side="left", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="right", padx=4)
        ttk.Button(bf, text="确定", command=ok).pack(side="right")
        ent_kw.focus_set()

    def _add_store_box(self):
        if not self.data or not self.store_var.get():
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        idx = core.add_store_box(self.data, self.store_var.get())
        self._mark_stores_dirty()
        self.store_tree.selection_set(str(idx))
        self._edit_store_box()

    def _del_store_box(self):
        if not self.data:
            return
        idx = self._selected_box_index()
        if idx is None:
            return
        if not messagebox.askyesno("确认删除", "删除货位 #%d？" % (idx + 1)):
            return
        if core.delete_store_box(self.data, self.store_var.get(), idx):
            self._mark_stores_dirty()
            self.log("已删除商店货位 #%d" % (idx + 1))

    def _refresh_tree(self):
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        self.tree_rows.clear()
        if not self.current_file or not self.data:
            return
        kw = self.tree_filter.get().strip().lower() if hasattr(self, "tree_filter") else ""
        rows = core.build_field_catalog(self.data, self.current_file)
        for row in rows:
            if kw and kw not in (row["path"] + " " + row["desc"] + " " + str(row["value"])).lower():
                continue
            val = row["value"]
            val_s = "null" if val is None else (str(val) if len(str(val)) < 120 else str(val)[:117] + "…")
            iid = self.tree.insert("", "end", values=(row["path"], val_s, row["type"], row["desc"]))
            self.tree_rows[iid] = row
        self.set_status(f"{self.current_file}：{len(self.tree_rows)} 个可编辑字段")

    def _edit_tree_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.tree_rows.get(sel[0])
        if not row:
            return
        tokens = [(t, v) for t, v in row["tokens"]]
        old = row["value"]
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑字段")
        dlg.geometry("640x210")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text="路径：" + row["path"], font=FONT_MONO, wraplength=600).pack(
            anchor="w", padx=10, pady=(10, 2))
        ttk.Label(dlg, text="含义：" + row["desc"], wraplength=600).pack(anchor="w", padx=10)
        ttk.Label(dlg, text="类型：" + row["type"] + ("   ⚠ 谨慎修改" if row["caution"] else ""),
                  foreground="#a05000" if row["caution"] else "#333333").pack(anchor="w", padx=10, pady=(2, 6))
        var = tk.StringVar(value="" if old is None else str(old))
        ent = ttk.Entry(dlg, textvariable=var, width=80, font=FONT_MONO)
        ent.pack(fill="x", padx=10)
        ent.focus_set()
        ent.select_range(0, "end")

        def ok():
            try:
                new = core.parse_value(var.get(), old)
            except Exception as e:
                messagebox.showerror("输入错误", str(e), parent=dlg)
                return
            f = self.current_file
            core.set_by_tokens(self.data[f], tokens, new)
            self.dirty.add(f)
            dlg.destroy()
            self._refresh_quick()
            self._refresh_tree()
            self._refresh_raw()
            self.log(f"修改 {f} / {row['path']}: {old!r} → {new!r}")

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=10, pady=10)
        ttk.Button(bf, text="确定", command=ok).pack(side="right", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="right")
        dlg.bind("<Return>", lambda e: ok())

    def _tree_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        row = self.tree_rows.get(iid)
        if not row:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="编辑数值", command=self._edit_tree_row)
        menu.add_command(label="复制字段路径",
                         command=lambda: (self.root.clipboard_clear(),
                                          self.root.clipboard_append(row["path"]),
                                          self.log("已复制路径：" + row["path"])))
        menu.add_separator()
        menu.add_command(label="在同级新增一项", command=lambda: self._tree_add(row))
        menu.add_command(label="删除该项", command=lambda: self._tree_delete(row))
        menu.post(event.x_root, event.y_root)

    def _parent_container(self, row):
        tokens = [(t, v) for t, v in row["tokens"]]
        parent = core.get_by_tokens(self.data[self.current_file], tokens[:-1])
        return parent, tokens[-1]

    def _tree_add(self, row):
        try:
            parent, last = self._parent_container(row)
        except Exception as e:
            messagebox.showerror("失败", str(e))
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("新增同级项")
        dlg.geometry("420x150")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text="父路径：" + row["path"].rsplit(".", 1)[0][:70]).pack(anchor="w", padx=10, pady=6)
        ttk.Label(dlg, text="新键名 / 值（JSON 字面量）：").pack(anchor="w", padx=10)
        kv = tk.StringVar(value="newKey")
        vv = tk.StringVar(value="0")
        ttk.Entry(dlg, textvariable=kv, width=48).pack(padx=10, pady=2)
        ttk.Entry(dlg, textvariable=vv, width=48).pack(padx=10, pady=2)
        def ok():
            try:
                val = json.loads(vv.get())
            except Exception:
                val = vv.get()
            if isinstance(parent, dict):
                parent[kv.get()] = val
            elif isinstance(parent, list):
                parent.append(val)
            else:
                messagebox.showerror("失败", "父节点不是容器", parent=dlg)
                return
            dlg.destroy()
            self.dirty.add(self.current_file)
            self._refresh_tree()
            self._refresh_raw()
            self.log("已新增同级项")
        ttk.Button(dlg, text="确定", command=ok).pack(pady=6)
        dlg.bind("<Return>", lambda e: ok())

    def _tree_delete(self, row):
        if not messagebox.askyesno("确认删除", "删除字段：\n" + row["path"] + "\n\n建议先备份存档。"):
            return
        try:
            parent, last = self._parent_container(row)
            t, v = last
            if isinstance(parent, dict):
                del parent[v]
            elif isinstance(parent, list):
                del parent[int(v)]
            self.dirty.add(self.current_file)
            self._refresh_tree()
            self._refresh_raw()
            self.log("已删除：" + row["path"])
        except Exception as e:
            messagebox.showerror("删除失败", str(e))

    # ------------------------------------------------------------ 原始 JSON
    def _raw_dirty(self) -> bool:
        if not self.current_file or not self.data:
            return False
        try:
            return json.loads(self.raw_text.get("1.0", "end")) != self.data[self.current_file]
        except Exception:
            return True

    def _refresh_raw(self):
        if not hasattr(self, "raw_text"):
            return
        self.raw_text.delete("1.0", "end")
        if self.current_file and self.data:
            self.raw_text.insert("1.0", json.dumps(self.data[self.current_file],
                                                   ensure_ascii=False, indent=2))

    def _apply_raw(self):
        if not self.current_file:
            return
        try:
            obj = json.loads(self.raw_text.get("1.0", "end"))
        except Exception as e:
            messagebox.showerror("JSON 错误", str(e))
            return
        self.data[self.current_file] = obj
        self.dirty.add(self.current_file)
        self._refresh_quick()
        self._refresh_tree()
        self._refresh_desc()
        self.log("原始 JSON 修改已应用到内存：" + self.current_file)

    # ------------------------------------------------------------ 字段说明
    def _refresh_desc(self):
        if not hasattr(self, "desc_text"):
            return
        self.desc_text.delete("1.0", "end")
        if not self.current_file or not self.data:
            return
        rows = core.build_field_catalog(self.data, self.current_file)
        lines = [f"文件：{self.current_file}    叶子字段：{len(rows)}",
                 f"{'路径':<62}{'值':<22}{'类型':<9}含义", "-" * 130]
        for r in rows:
            v = "null" if r["value"] is None else str(r["value"])
            lines.append(f"{r['path'][:60]:<62}{v[:20]:<22}{r['type']:<9}{r['desc']}"
                         + ("  [谨慎]" if r["caution"] else ""))
        self.desc_text.insert("1.0", "\n".join(lines))

    def _export_catalog(self):
        if not self.data:
            messagebox.showinfo("提示", "请先载入存档")
            return
        p = os.path.join(core.BASE_DIR, "field_catalog.json")
        rows = core.build_field_catalog(self.data)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        self.log(f"字段目录已导出：{p}（{len(rows)} 个字段）")
        messagebox.showinfo("完成", f"已导出 {len(rows)} 个字段到\n{p}")

    # ------------------------------------------------------------ 保存 / 回传
    def _save_local(self):
        if not self.local_dir or not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        if self._raw_dirty():
            if not messagebox.askyesno("原始 JSON 未应用", "原始 JSON 页有未应用的修改，是否先应用？"):
                return
            self._apply_raw()
        if self.source_kind == "venture":
            self._save_to_venture()
            return
        n = core.write_save(self.local_dir, self.data)
        self.log(f"已写回本地存档：{len(n)} 个文件（{self.local_dir}）")
        self.set_status("本地已保存；可一键回传")
        self.dirty.clear()

    def _save_to_venture(self):
        """Venture 存档就是本机目录：确认 → 备份 → 写盘 → 回读校验，没有 adb 环节。"""
        running = core.venture_related_processes()
        warn = ""
        if running:
            warn = ("\n\n⚠ 检测到相关进程正在运行：" + "、".join(running) +
                    "\n请先在 Venture 里退出游戏：游戏存档时会把内存旧值写回文件，"
                    "覆盖本次修改。")
        if not messagebox.askyesno(
                "写回 Venture 存档",
                "将把修改后的存档直接写回模拟器存档目录：\n" + (self.local_dir or "") +
                "\n\n· 保存前自动备份原文件到 backups\\venture_<时间戳>\\\n"
                "· 写盘后逐个回读校验\n继续？" + warn):
            return
        backup = bool(self.cfg.get("venture_backup_on_save", True))
        if self._raw_dirty():
            if messagebox.askyesno("原始 JSON 未应用", "原始 JSON 页有未应用的修改，是否先应用？"):
                self._apply_raw()

        def fn(log):
            return core.save_venture(self.cfg, self.local_dir, self.data,
                                     backup=backup, log=log)

        def done(r):
            self.dirty.clear()
            self.backup_dir = r.get("backup_dir")
            self.log("写回 %d 个文件，回读校验通过" % len(r["written"]))
            if r.get("running"):
                self.log("⚠ 写入时仍有相关进程在运行（%s）：退出游戏后重新进入确认数值；"
                         "若被覆盖，用「恢复最近备份」回滚。" % "、".join(r["running"]))
            self.set_status("已写回 Venture 存档，进游戏确认数值")
        self._run_bg("写回 Venture 存档", fn, done)

    def _push(self):
        if not self.local_dir or not self.data:
            messagebox.showinfo("提示", "请先导出/载入存档")
            return
        if self._raw_dirty():
            if messagebox.askyesno("原始 JSON 未应用", "原始 JSON 页有未应用的修改，是否先应用？"):
                self._apply_raw()
        self._sync_cfg_from_ui()
        self.cfg["stop_game_before_push"] = bool(self.stop_game.get())
        try:
            s = self._selected_serial()
        except Exception as e:
            messagebox.showwarning("未选设备", str(e))
            return
        if not messagebox.askyesno("确认回传",
                "将把修改后的存档推送到头显：\n" + core.remote_save_path(self.cfg) +
                "\n\n回传前会强制停止游戏（避免运行中写盘覆盖），回传后自动冷启动游戏重新读档。"
                "\n设备原存档会先自动备份。\n继续？"):
            return
        core.write_save(self.local_dir, self.data)
        only = None
        if self.only_modified.get() and self.dirty:
            only = [os.path.join(self.local_dir, n) for n in sorted(self.dirty)
                    if os.path.isfile(os.path.join(self.local_dir, n))]
        self.cfg["push_only_modified"] = bool(self.only_modified.get())

        def fn(log):
            return core.import_save(self.cfg, s, self.local_dir, only_files=only, log=log)

        def done(r):
            self.backup_dir = r.get("backup_dir")
            self.dirty.clear()
            if self.backup_dir:
                self.log("回滚备份：" + self.backup_dir)
            self.log("回传 %d 个文件；md5 校验：%s" %
                     (len(r["pushed"]), "通过" if r.get("verify") else "未启用"))
            self.log("游戏停止：%s ／ 冷启动：%s（冷启动后游戏才会读到新存档）" %
                     ("成功" if r.get("stopped") else "未执行/失败",
                      "成功" if r.get("relaunched") else "未执行/失败"))
            self.set_status("回传完成，戴上头显查看生效结果")
        self._run_bg("一键回传到头显", fn, done)

    def _restore_backup(self):
        if self.source_kind == "venture" and self.local_dir and os.path.isdir(self.local_dir):
            self._restore_venture()
            return
        root = core.abs_local(self.cfg["backup_root"])
        if not os.path.isdir(root):
            messagebox.showinfo("提示", "暂无备份目录：" + root)
            return
        ds = sorted([d for d in os.listdir(root)
                     if os.path.isdir(os.path.join(root, d, self.cfg["save_subdir"]))])
        if not ds:
            messagebox.showinfo("提示", "暂无可用备份")
            return
        d = os.path.join(root, ds[-1], self.cfg["save_subdir"])
        self._sync_cfg_from_ui()
        try:
            s = self._selected_serial()
        except Exception as e:
            messagebox.showwarning("未选设备", str(e))
            return
        if not messagebox.askyesno("确认恢复", "将把最近一次备份回传到头显：\n" + d + "\n继续？"):
            return
        def fn(log):
            return core.import_save(self.cfg, s, d, log=log)
        self._run_bg("恢复最近备份", fn)

    def _restore_venture(self):
        """Venture 模式下的回滚：把 backups/ 里最近一份快照复制回存档目录。"""
        root = core.abs_local(self.cfg["backup_root"])
        slot = os.path.basename((self.local_dir or "").rstrip("\\/")) or self.cfg["save_subdir"]
        cands = []
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                d = os.path.join(root, name, slot)
                if os.path.isdir(d) and glob.glob(os.path.join(d, "*.json.gz")):
                    cands.append(d)
        if not cands:
            messagebox.showinfo("提示", "暂无可用备份：\n" + root)
            return
        d = cands[-1]
        if not messagebox.askyesno(
                "确认恢复",
                "将用备份覆盖模拟器存档目录：\n" + self.local_dir +
                "\n\n备份来源：\n" + d + "\n\n继续？"):
            return
        try:
            core.copy_save(d, self.local_dir)
        except Exception as e:
            messagebox.showerror("恢复失败", str(e))
            return
        self._load_local(self.local_dir, "venture", self.source_meta)
        self.log("已用备份覆盖 Venture 存档：" + d)
        self.set_status("已恢复备份")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
