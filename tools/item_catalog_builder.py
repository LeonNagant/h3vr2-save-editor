# -*- coding: utf-8 -*-
"""H3VR2 物品表生成器  v1.0
=====================================================================
从你手里的游戏安装包 / 资源文件里读取 ItemSpawnerDef，生成（或增量更新）
存档修改器使用的 items_catalog.json。

支持三种输入（自动识别）：
  1. 安装包 .zip        —— 内含 <包名>/footlong.base.hdog
  2. footlong.base.hdog —— HDOG 容器（游戏资源包）
  3. _root_bundle       —— 已解出的 Unity 根包（最快，无需解 hdog）

工作原理：
  HDOG 容器的第 0 个数据块就是 Unity 根包（约 27~36 MB），里面有
  ItemSpawnerDef MonoBehaviour（_itemName / _itemType / _folders / _spriteRef）。
  _spriteRef._subAssetName 即AssetKey；再从根包所有对象里扫描 extref:// 字符串，
  得到每个 AssetKey 在存档里真实使用的引用（注意有的在 /Item/ 命名空间）。

依赖：Python 3.10+ 与 UnityPy（仅本工具需要；存档修改器本身零 pip 依赖）：
  py -3.10 -m pip install UnityPy
用法：
  py -3.10 item_catalog_builder.py <输入> [--merge 现有items_catalog.json] [-o 输出.json]
  py -3.10 item_catalog_builder.py --gui       # 图形界面
=====================================================================
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import struct
import sys
import zipfile

MAGIC = b"HDOG\x00"
ROOT_BUNDLE = "_root_bundle"

# ---------------------------------------------------------------- hdog 解析（自包含）

def hdog_entries(path: str):
    """返回 HDOG 容器的数据块列表 [(name, tag, off, size), ...]。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if f.read(5) != MAGIC:
            raise ValueError("不是 HDOG 容器（文件头不匹配）：" + path)
        f.seek(size - 8)
        count, footer_off = struct.unpack("<II", f.read(8))
        f.seek(footer_off)
        start, mlen = struct.unpack("<II", f.read(8))
        if start != 5:
            raise ValueError("HDOG 数据区起点异常：%d" % start)
        entries = []
        for _ in range(count - 1):
            nl = struct.unpack("<B", f.read(1))[0]
            name = f.read(nl).decode("ascii", "replace")
            tag = f.read(4).decode("ascii", "replace")
            off, sz = struct.unpack("<II", f.read(8))
            entries.append((name, tag, off, sz))
    return entries


def extract_root_bundle(src: str, workdir: str, log=print) -> str:
    """从 zip / hdog / 已解出的 root bundle 得到 _root_bundle 路径。"""
    os.makedirs(workdir, exist_ok=True)
    dest = os.path.join(workdir, ROOT_BUNDLE)

    if os.path.isfile(src) and src.lower().endswith(".zip"):
        log("打开安装包 zip：" + src)
        with zipfile.ZipFile(src) as z:
            cand = [n for n in z.namelist()
                    if n.lower().endswith("footlong.base.hdog")]
            if not cand:
                raise RuntimeError("zip 内未找到 footlong.base.hdog")
            hdog_path = os.path.join(workdir, "footlong.base.hdog")
            log("流式解出 hdog（%.0f MB）…" % (z.getinfo(cand[0]).file_size / 1e6))
            with z.open(cand[0]) as s, open(hdog_path, "wb") as d:
                while True:
                    chunk = s.read(1 << 22)
                    if not chunk:
                        break
                    d.write(chunk)
        src = hdog_path

    if os.path.isfile(src) and open(src, "rb").read(5) == MAGIC:
        entries = hdog_entries(src)
        if not entries:
            raise RuntimeError("HDOG 容器内没有数据块")
        name, tag, off, sz = entries[0]   # 第 0 块 = 根包
        log("HDOG 共 %d 块，提取第 0 块根包（%.1f MB）…" % (len(entries), sz / 1e6))
        with open(src, "rb") as f, open(dest, "wb") as d:
            f.seek(off)
            left = sz
            while left > 0:
                chunk = f.read(min(1 << 22, left))
                if not chunk:
                    break
                d.write(chunk)
                left -= len(chunk)
        return dest

    if os.path.isfile(src):
        log("直接使用已有资源文件：" + src)
        return src
    raise RuntimeError("无法识别输入：" + str(src))


# ---------------------------------------------------------------- Unity 解析

def scan_bundle(root_path: str, log=print):
    """返回 (物品定义列表, 根包内所有 extref 集合)。"""
    try:
        import UnityPy
    except ImportError:
        raise RuntimeError(
            "缺少 UnityPy。请先安装：\n"
            "    py -3.10 -m pip install UnityPy\n"
            "（存档修改器本身不需要它，只有重新生成物品表时才需要。）")

    log("UnityPy 解析根包：" + root_path)
    env = UnityPy.load(root_path)
    scripts = {}
    for ob in env.objects:
        if ob.type.name == "MonoScript":
            try:
                tt = ob.read_typetree()
            except Exception:
                continue
            scripts[ob.path_id] = tt.get("m_ClassName") or "?"

    items, refs = [], set()
    extref_re = re.compile(r'extref://[^\s"\'<>]+')
    for ob in env.objects:
        if ob.type.name != "MonoBehaviour":
            continue
        try:
            tt = ob.read_typetree()
        except Exception:
            continue
        # 扫描所有 MonoBehaviour 字段里的 extref（含 _refId 等）
        try:
            blob = json.dumps(tt, ensure_ascii=False, default=str)
        except Exception:
            blob = ""
        for m in extref_re.finditer(blob):
            refs.add(m.group(0))

        if scripts.get(tt.get("m_Script", {}).get("m_PathID"), "?") != "ItemSpawnerDef":
            continue
        items.append({
            "key": tt.get("_spriteRef", {}).get("_subAssetName") or "",
            "en": tt.get("_itemName") or "",
            "zh": "",
            "type": tt.get("_itemType"),
            "hidden": tt.get("_isHidden") or 0,
            "category": "",
            "folders": [f.get("_refId", "") for f in tt.get("_folders", [])],
            "ref": "",
            "ref_alt": None,
            "verified": False,
        })
    log("解析到 %d 个 ItemSpawnerDef，%d 个 extref" % (len(items), len(refs)))
    return items, refs


def ref_for(key: str, refs: set[str]) -> str:
    """精确解析 AssetKey 的真实引用：根级优先，其次 /Item/ 命名空间。"""
    root = "extref://footlong.base/" + key
    if root in refs:
        return root
    item = "extref://footlong.base/Item/" + key
    if item in refs:
        return item
    # 兜底：任何以 /Key 结尾的引用（排除 Audio_ 等派生）
    hits = sorted(r for r in refs if r.endswith("/" + key))
    return hits[0] if hits else ""


def category_of(folders: list[str]) -> str:
    s = " ".join(folders)
    for seg, cat in [("/Firearms/", "Firearms"), ("/RoundContainers/", "RoundContainers"),
                     ("/Rounds/", "Rounds"), ("/Attachments/", "Attachments"),
                     ("/Sosig/", "Sosig"), ("/MeleeWeapons/", "MeleeWeapons"),
                     ("/Wearables/", "Wearables"), ("/Explosives/", "Explosives"),
                     ("/ToolsAndToys/", "ToolsAndToys")]:
        if seg in s:
            return cat
    return ""


# ---------------------------------------------------------------- 合并 / 输出

def looks_chinese(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (s or ""))


def merge_items(new: list[dict], refs: set[str], old_catalog: dict | None,
                log=print):
    """把扫描到的物品合并进现有 catalog：
       - 已有 key：保留原有 en/zh/ref/verified（不动真机验证过的引用）
       - 新 key：用扫描到的 ref，中文资源名作 zh，英文资源名作 en
       返回 (合并后的 catalog, 新增列表)。"""
    base = old_catalog or {
        "generated": "", "source": {}, "count": 0, "verified_count": 0, "items": []}
    old_by_key = {i.get("key"): i for i in base.get("items", [])}
    added = []
    for it in new:
        key = it.get("key")
        if not key:
            continue
        ref = it.get("ref") or ref_for(key, refs)
        if key in old_by_key:
            # 若旧条目缺引用而新扫描到了，补上（不覆盖已有引用）
            old = old_by_key[key]
            if not old.get("ref") and ref:
                old["ref"] = ref
                old["verified"] = True
            old_en, old_zh = old.get("en", ""), old.get("zh", "")
            if looks_chinese(it["en"]) and not old_zh:
                old["zh"] = it["en"]
            elif old_zh and not old_en:
                old["en"] = it["en"]
            continue
        name = it["en"] or key
        item = {
            "key": key,
            "en": "" if looks_chinese(name) else name,
            "zh": name if looks_chinese(name) else "",
            "type": it.get("type"),
            "hidden": it.get("hidden") or 0,
            "category": it.get("category") or category_of(it.get("folders", [])),
            "folders": it.get("folders", []),
            "ref": ref,
            "ref_alt": None,
            "verified": bool(ref),
        }
        base["items"].append(item)
        old_by_key[key] = item
        added.append(item)
    base["count"] = len(base["items"])
    base["verified_count"] = sum(1 for i in base["items"] if i.get("verified"))
    log("新增 %d 件，合计 %d 件" % (len(added), base["count"]))
    return base, added


def build(src: str, merge_path: str | None, out: str, workdir: str, log=print):
    root = extract_root_bundle(src, workdir, log)
    items, refs = scan_bundle(root, log)
    old = None
    if merge_path and os.path.isfile(merge_path):
        with open(merge_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        log("合并现有物品表：" + merge_path)
    catalog, added = merge_items(items, refs, old, log)
    catalog["generated"] = "item_catalog_builder v1.0"
    if old is None:
        catalog["source"] = {
            "items": "游戏资源内 ItemSpawnerDef 定义",
            "translations": "资源内物品名（中文资源直接作 zh）",
            "refs": "根包内 extref 字符串扫描",
        }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    log("已写出：" + out)
    log("新增物品：")
    for i in added:
        log("  + %-40s %s" % (i["key"], i["ref"] or "(无引用)"))
    return catalog, added


# ---------------------------------------------------------------- GUI（可选）

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("H3VR2 物品表生成器 v1.0")
    root.geometry("820x520")
    src_v = tk.StringVar()
    merge_v = tk.StringVar()
    out_v = tk.StringVar(value="items_catalog_new.json")

    def pick(var, mode="file"):
        p = (filedialog.askopenfilename if mode == "file"
             else filedialog.askdirectory)(title="选择")
        if p:
            var.set(p)

    def do():
        if not src_v.get():
            messagebox.showwarning("提示", "请先选择安装包 / hdog / 根包")
            return
        def work(log):
            return build(src_v.get(), merge_v.get() or None,
                         out_v.get(), os.path.join(os.path.dirname(os.path.abspath(
                         src_v.get())), "_catalog_work"), log)
        def run():
            try:
                work(lambda m: txt.insert("end", str(m) + "\n"))
                messagebox.showinfo("完成", "物品表已生成：" + out_v.get())
            except Exception as e:
                messagebox.showerror("失败", str(e))
        txt.insert("end", "开始生成…\n")
        root.after(50, run)

    f = ttk.Frame(root, padding=12)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text="安装包 / hdog / _root_bundle：").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Entry(f, textvariable=src_v, width=64).grid(row=0, column=1, sticky="w")
    ttk.Button(f, text="浏览…", command=lambda: pick(src_v)).grid(row=0, column=2)
    ttk.Label(f, text="合并到现有 items_catalog.json（可选）：").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(f, textvariable=merge_v, width=64).grid(row=1, column=1, sticky="w")
    ttk.Button(f, text="浏览…", command=lambda: pick(merge_v)).grid(row=1, column=2)
    ttk.Label(f, text="输出文件：").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(f, textvariable=out_v, width=64).grid(row=2, column=1, sticky="w")
    ttk.Button(f, text="生成物品表", command=do).grid(row=3, column=1, sticky="w", pady=10)
    txt = tk.Text(f, height=18, wrap="word")
    txt.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    f.rowconfigure(4, weight=1)
    f.columnconfigure(1, weight=1)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="H3VR2 物品表生成器")
    ap.add_argument("src", nargs="?", help="zip / hdog / _root_bundle 路径")
    ap.add_argument("--merge", help="合并到现有 items_catalog.json")
    ap.add_argument("-o", "--out", default="items_catalog_new.json", help="输出 json")
    ap.add_argument("--workdir", default=None, help="临时解包目录")
    ap.add_argument("--gui", action="store_true", help="图形界面")
    a = ap.parse_args()
    if a.gui or not a.src:
        run_gui()
        return
    workdir = a.workdir or os.path.join(os.path.dirname(os.path.abspath(a.src)),
                                        "_catalog_work")
    build(a.src, a.merge, a.out, workdir)


if __name__ == "__main__":
    main()
