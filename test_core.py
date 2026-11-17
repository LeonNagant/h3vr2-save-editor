# -*- coding: utf-8 -*-
"""
H3VR2 存档修改器 —— 无头测试

  py -3.10 test_core.py            仅单元测试（不碰设备）
  py -3.10 test_core.py --device   单元 + 真机导出/回传往返验证（回传原样内容，不改数值）
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import shutil
import sys
import tempfile

import save_core as core

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# 干净仓库（clone 后）里没有玩家存档，单元测试仍需自给自足。
# 这份合成夹具只含格式结构，不含任何玩家数据，可用作无设备回归基线。
SYNTHETIC_FILES = [
    "Activities.json.gz", "Challenges.json.gz", "Cosmetics.json.gz",
    "Economy.json.gz", "Experience.json.gz", "FacilityRunHistory.json.gz",
    "Flags.json.gz", "HubItemsAutosave.json.gz", "Inventory.json.gz",
    "Lessons.json.gz", "PlayStats.json.gz", "PlayerHubState.json.gz",
    "ScanData.json.gz", "Settings.json.gz", "Stores.json.gz",
    "VendOS.json.gz", "WorkOrders.json.gz", "经验.json.gz",
]


def make_synthetic_save(dirpath: str) -> str:
    """生成一份最小合成存档：18 个 gzip JSON，结构与游戏存档一致。"""
    os.makedirs(dirpath, exist_ok=True)
    store_key = "extref://footlong.base/Store/Store_Starter"
    mapr = "extref://footlong.base/Item/MapR"
    docs = {name: {"Version": 0, "Data": {}} for name in SYNTHETIC_FILES}
    # 用足够多的叶子字段覆盖「字段目录 >= 1000」这条断言
    docs["Activities.json.gz"] = {
        "Version": 0, "Data": {"f%04d" % i: i for i in range(1100)}}
    docs["Economy.json.gz"] = {
        "Version": 0, "Data": {"Money": 100, "Meat": 10, "Metal": 10, "Mustard": 0}}
    docs["Experience.json.gz"] = {"Version": 0, "Data": {"Experience": 100}}
    docs["Settings.json.gz"] = {
        "Version": 0, "Data": {"Settings": {
            "npcDamage": 1, "playerDamage": 1, "powerupDuration": 1}}}
    docs["PlayerHubState.json.gz"] = {"Version": 0, "Data": {"CurrentHealth": 100.0}}
    docs["PlayStats.json.gz"] = {
        "Version": 0, "Data": {"PlaytimeSeconds": 0, "ShotsFired": 0, "Deaths": 0}}
    docs["Stores.json.gz"] = {"Version": 0, "Data": {"storeStates": {
        store_key: {"Version": 0, "boxes": [
            {"item": mapr, "sectionID": "basics", "price": 50}
            for _ in range(12)]}}}}
    docs["Inventory.json.gz"] = {"Version": 0, "Data": {"InventoryPages": [{
        "gridSize": [12, 8],
        "items": [{
            "rectMin": [0, 0], "rectSize": [1, 1],
            "contents": {"GridSize": [1, 1], "Objects": [{
                "ItemDef": mapr, "InstanceSeed": 123456, "Affixments": [],
                "Components": [{"Id": "Magazine",
                                "State": {"LoadedRounds": [{"Round": "sample"}]}}],
            }]},
        }],
    }]}}
    for name, doc in docs.items():
        raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with open(os.path.join(dirpath, name), "wb") as f:
            f.write(core.gzip_bytes(raw))   # 与游戏一致的 gzip 头
    return dirpath


def unit_tests():
    print("\n== 单元测试 ==")
    cfg = core.load_config()
    check("配置读取", len(cfg) >= 18, f"{len(cfg)} 项")

    src = core.latest_export_dir()
    fixture_root = None
    if not src:
        fixture_root = tempfile.mkdtemp(prefix="h3vr2_fixture_")
        src = make_synthetic_save(os.path.join(fixture_root, "footlong.base"))
        print("  [info] 未发现本机导出，使用合成存档夹具（不含任何玩家数据）")
    check("找到测试用存档", bool(src), src or "")
    data = core.load_save(src)
    check("载入存档文件数", len(data) == 18, f"{len(data)} 个")

    # gzip 字节级兼容
    orig = open(os.path.join(src, "Economy.json.gz"), "rb").read()
    packed = core.gzip_bytes(json.dumps(data["Economy.json.gz"], ensure_ascii=False,
                                        separators=(",", ":")).encode("utf-8"))
    check("gzip 头与 .NET 一致", orig[:10] == packed[:10], orig[:10].hex())
    check("gzip 解压内容一致", gzip.decompress(orig) == gzip.decompress(packed))

    # 写盘往返
    tmp = tempfile.mkdtemp(prefix="h3vr2_unit_")
    work = os.path.join(tmp, "footlong.base")
    shutil.copytree(src, work)
    written = core.write_save(work, data)
    check("write_save 文件数", len(written) == 18)
    check("写盘后 JSON 等价", core.load_save(work) == data)

    # 字段目录
    cat = core.build_field_catalog(data)
    check("叶子字段总数", len(cat) >= 1000, f"{len(cat)} 个")
    check("字段说明覆盖", all(r["desc"] for r in cat))
    check("tokens 可精确定位",
          core.get_by_tokens(data[cat[0]["file"]],
                             [(t, v) for t, v in cat[0]["tokens"]]) == cat[0]["value"])

    # 快捷读写
    old_money = core.quick_read(data, "Economy.json.gz", "Data.Money")
    core.quick_write(data, "Economy.json.gz", "Data.Money", 99999)
    check("快捷字段写入", core.quick_read(data, "Economy.json.gz", "Data.Money") == 99999)
    core.quick_write(data, "Economy.json.gz", "Data.Money", old_money)
    check("快捷字段还原", core.quick_read(data, "Economy.json.gz", "Data.Money") == old_money)

    # 嵌套数组 tokens
    v = core.quick_read(data, "Inventory.json.gz", "Data.InventoryPages[0].gridSize[0]")
    check("数组路径读取", v == 12, str(v))
    check("数组路径写入",
          core.quick_write(data, "Inventory.json.gz", "Data.InventoryPages[0].gridSize[0]", 12))

    # 值解析
    check("parse_value bool", core.parse_value("false", True) is False)
    check("parse_value int", core.parse_value("42", 1) == 42)
    check("parse_value float", core.parse_value("0.25", 1.0) == 0.25)
    check("parse_value null", core.parse_value("null", "x") is None)

    # 批量工具（在副本上，不污染 data）
    d2 = core.load_save(src)
    boxes_before = core.list_store_boxes(d2, core.store_keys(d2)[0])
    n1 = core.scale_store_prices(d2, 0.1)
    n2 = core.fill_magazines(d2, 7)
    check("商店打折工具", n1 == len(boxes_before), f"{n1} 个货位")
    mags = []
    for pg in d2["Inventory.json.gz"]["Data"]["InventoryPages"]:
        for it in pg.get("items", []):
            for o in (it.get("contents") or {}).get("Objects", []):
                for c in o.get("Components", []):
                    if c.get("Id") == "Magazine":
                        mags.append(len((c.get("State") or {}).get("LoadedRounds", [])))
    # 空弹匣（无弹种模板）按设计跳过；原本有弹的都补到 >= capacity
    check("弹匣补满工具", bool(mags) and all(x == 0 or x >= 7 for x in mags),
          f"新增 {n2} 发 / {len(mags)} 个弹匣")

    # set_by_tokens 深层写入
    import copy
    d3 = copy.deepcopy(d2)
    tk2 = core._tokens_from_dot("Data.Settings.npcDamage")
    core.set_by_tokens(d3["Settings.json.gz"], tk2, 0.25)
    check("深层字段写入",
          core.get_by_tokens(d3["Settings.json.gz"], tk2) == 0.25)

    # 物品目录与商店编辑
    cat = core.load_item_catalog()
    check("物品目录已载入", len(cat) >= 600, "%d 条" % len(cat))
    check("物品目录含中文名", sum(1 for x in cat if x.get("zh")) >= 600,
          "%d 条有中文名" % sum(1 for x in cat if x.get("zh")))
    check("商店 9 个物品引用可还原",
          all(core.item_by_ref(r) and core.item_by_ref(r)["key"] == core.asset_key(r)
              for r in ["extref://footlong.base/Item/MapR",
                        "extref://footlong.base/M1911A1",
                        "extref://footlong.base/Item/UtilityRig",
                        "extref://footlong.base/USAS12"]))
    d4 = core.load_save(src)
    stores = core.store_keys(d4)
    check("商店列表", len(stores) >= 1, ", ".join(stores))
    boxes = core.list_store_boxes(d4, stores[0])
    nb = len(boxes)
    check("货位数量", nb >= 1, "%d 个" % nb)
    check("货位含中文名与价格",
          all(b["zh"] and isinstance(b["price"], int) for b in boxes),
          "%d/%d 有中文名" % (sum(1 for b in boxes if b["zh"]), len(boxes)))
    old_price = boxes[0]["price"]
    old_item = boxes[0]["item"]
    check("改售价", core.set_store_box(d4, stores[0], 0, price=1) and
          core.list_store_boxes(d4, stores[0])[0]["price"] == 1)
    check("改出售物品", core.set_store_box(d4, stores[0], 0,
          item="extref://footlong.base/Item/Belt_Tac_Veteran") and
          core.list_store_boxes(d4, stores[0])[0]["item"].endswith("Belt_Tac_Veteran"))
    check("分区可改", core.set_store_box(d4, stores[0], 0, section="test") and
          core.list_store_boxes(d4, stores[0])[0]["sectionID"] == "test")
    core.set_store_box(d4, stores[0], 0, item=old_item, price=old_price, section="basics")
    check("统一售价", core.set_all_store_prices(d4, 7, store=stores[0]) == nb)
    check("新增货位", core.add_store_box(d4, stores[0]) == nb)
    check("删除货位", core.delete_store_box(d4, stores[0], nb) and
          len(core.list_store_boxes(d4, stores[0])) == nb)
    check("快捷栏无设置菜单项",
          all(f != "Settings.json.gz" for f, *_ in core.QUICK_FIELDS),
          "%d 个快捷字段" % len(core.QUICK_FIELDS))
    check("冷启动成功判定（真机输出样本）",
          core.launch_confirmed({"code": 0, "stdout": "Events injected: 1", "stderr": ""}) is True)
    check("冷启动失败判定",
          core.launch_confirmed({"code": 1, "stdout": "", "stderr": "error"}) is False and
          core.launch_confirmed({"code": 0, "stdout": "no activity", "stderr": ""}) is False)
    check("新配置项存在",
          cfg.get("stop_game_before_push") is True and cfg.get("relaunch_after_push") is True)

    # 商店改动写盘后仍可正确读回
    d5 = core.load_save(src)
    core.set_store_box(d5, stores[0], 11, price=1)
    core.write_save(work, d5, only={"Stores.json.gz"})
    check("商店改动 gzip/JSON 往返",
          core.load_save(work)["Stores.json.gz"]["Data"]["storeStates"][stores[0]]
          ["boxes"][11]["price"] == 1)

    # ---------------- v0.2.0：预设 / 收藏 / 玩家仓库 ----------------
    st = stores[0]
    ud_path = os.path.join(tmp, "presets_test.json")
    ud = core.default_user_data()
    check("默认用户数据结构",
          {"settings", "store_presets", "inventory_presets", "favorites"} <= set(ud))
    core.save_user_data(ud, ud_path)
    check("presets.json 写读往返", core.load_user_data(ud_path) == ud)
    with open(ud_path, "w", encoding="utf-8") as f:
        f.write("{broken json")
    check("损坏的预设文件可容错",
          core.load_user_data(ud_path) == core.default_user_data())

    ud = core.default_user_data()
    r_map = core.normalize_item_ref("MapR")
    check("AssetKey → 游戏真实引用",
          r_map.startswith("extref://") and r_map.endswith("MapR"), r_map)
    check("extref 原样保留", core.normalize_item_ref("extref://a/b") == "extref://a/b")
    check("收藏切换", core.toggle_favorite(ud, "MapR") is True and core.is_favorite(ud, r_map))
    check("重复收藏不叠加",
          core.set_favorite(ud, "MapR", True) and len(core.favorite_refs(ud)) == 1)
    check("取消收藏", core.toggle_favorite(ud, r_map) is False and not core.favorite_refs(ud))
    core.set_favorite(ud, "MapR", True)
    core.set_favorite(ud, "M4A1", True)
    check("收藏标签含中文名", len(core.favorite_labels(ud)) == 2 and
          all(f["label"] and f["key"] for f in core.favorite_labels(ud)))

    # 商店预设：保存 → 改动 → 一键还原
    d6 = core.load_save(src)
    nb = len(core.list_store_boxes(d6, st))
    check("保存当前商店为预设",
          core.save_store_preset(ud, "我的商店", d6, st) == nb and
          len(core.get_store_preset(ud, "我的商店")["boxes"]) == nb)
    saved_boxes = [dict(b) for b in core.list_store_boxes(d6, st)]
    d7 = core.load_save(src)
    core.set_all_store_prices(d7, 999, store=st)
    n = core.apply_store_preset(d7, st, core.get_store_preset(ud, "我的商店"), "replace")
    check("一键还原商店编辑内容", n == nb and core.list_store_boxes(d7, st) == saved_boxes,
          "%d 个货位" % n)
    check("追加模式不覆盖原货位",
          core.apply_store_preset(d7, st, core.get_store_preset(ud, "我的商店"), "append") == nb
          and len(core.list_store_boxes(d7, st)) == 2 * nb)
    d8 = core.load_save(src)
    check("收藏一键加入商店",
          core.add_favorites_to_store(d8, st, core.favorite_refs(ud), 3) == 2 and
          len(core.list_store_boxes(d8, st)) == nb + 2)

    # 仓库：读取 / 新增 / 改物品 / 改占格 / 删除 / 复制
    d9 = core.load_save(src)
    pages = core.inventory_pages(d9)
    check("玩家仓库可读（多页）", len(pages) >= 1 and all("items" in p for p in pages),
          "%d 页" % len(pages))
    slots = core.list_inventory_slots(d9, 0)
    check("槽位列表含物件与中文名",
          bool(slots) and all(s["objects"] and s["key"] for s in slots),
          "%d 个槽位" % len(slots))
    check("网格可找空位", core.find_free_rect(d9, 0, 1, 1) is not None)
    seeds0 = core.inventory_seeds(d9)
    r = core.add_inventory_object(d9, "MapR", page_index=0)
    check("新增仓库物品返回位置", bool(r) and {"page", "index", "rectMin"} <= set(r or {}))
    slots2 = core.list_inventory_slots(d9, r["page"])
    raw = core.get_inventory_slot(d9, r["page"], r["index"])
    check("新槽位结构合法",
          raw["contents"]["Objects"][0]["ItemDef"].endswith("MapR") and
          raw["contents"]["GridSize"] == [1, 1] and
          raw["contents"]["Objects"][0]["Components"] == [] and
          raw["rectMin"] == r["rectMin"])
    check("新增物件 InstanceSeed 唯一",
          len(core.inventory_seeds(d9)) == len(seeds0) + 1)
    check("改仓库物件引用",
          core.set_inventory_object(d9, r["page"], r["index"], 0, "M4A1", True) and
          core.get_inventory_slot(d9, r["page"], r["index"])
          ["contents"]["Objects"][0]["ItemDef"].endswith("M4A1"))
    check("改仓库槽位占格",
          core.set_inventory_rect(d9, r["page"], r["index"], [0, 0], [2, 2]) and
          core.get_inventory_slot(d9, r["page"], r["index"])["contents"]["GridSize"] == [2, 2])
    check("删除仓库槽位",
          core.delete_inventory_slot(d9, r["page"], r["index"]) and
          len(core.list_inventory_slots(d9, r["page"])) == len(slots2) - 1)
    seeds_before_dup = len(core.inventory_seeds(d9))
    check("复制槽位并重生成 seed",
          core.duplicate_inventory_slot(d9, 0, 0) is not None and
          len(core.inventory_seeds(d9)) > seeds_before_dup)

    # 仓库预设 + 写盘往返
    d10 = core.load_save(src)
    n_items = core.save_inventory_preset(ud, "我的仓库", d10)
    check("保存当前仓库为预设", n_items >= 1 and
          len(core.get_inventory_preset(ud, "我的仓库")["items"]) == n_items,
          "%d 件" % n_items)
    d11 = core.load_save(src)
    inv_preset = core.get_inventory_preset(ud, "我的仓库")
    added = core.apply_inventory_preset(d11, inv_preset, "append")
    check("一键增加仓库预设物品", added == n_items, "新增 %d 件" % added)
    d14 = core.load_save(src)
    core.add_inventory_object(d14, "MapR")
    core.write_save(work, d14, only={core.INVENTORY_FILE})
    back = core.load_save(work)
    check("仓库改动 gzip/JSON 往返",
          any(s["key"] == "MapR"
              for pg in range(len(core.inventory_pages(back)))
              for s in core.list_inventory_slots(back, pg)))

    # 载入新存档时自动应用（含幂等）
    auto_ud = core.default_user_data()
    auto_ud["inventory_presets"]["P"] = inv_preset
    auto_ud["settings"]["inventory_auto_preset"] = "P"
    auto_ud["settings"]["inventory_auto_mode"] = "append"
    d12 = core.load_save(src)
    for pg in core.inventory_pages(d12):
        pg["items"] = []          # 模拟一份仓库为空的新存档
    lines = core.apply_auto_presets(d12, auto_ud, log=lambda m: None)
    count1 = sum(len(p.get("items", [])) for p in core.inventory_pages(d12))
    check("载入新存档自动应用仓库预设",
          len(lines) == 1 and count1 == n_items, "%d 件" % count1)
    core.apply_auto_presets(d12, auto_ud, log=lambda m: None)
    check("自动应用重复不堆叠",
          sum(len(p.get("items", [])) for p in core.inventory_pages(d12)) == count1)
    auto_ud2 = core.default_user_data()
    auto_ud2["store_presets"]["S"] = {
        "boxes": [{"item": "MapR", "sectionID": "basics", "price": 1}]}
    auto_ud2["settings"]["store_auto_preset"] = "S"
    d13 = core.load_save(src)
    lines2 = core.apply_auto_presets(d13, auto_ud2, log=lambda m: None)
    check("载入新存档自动还原商店",
          len(lines2) == 1 and len(core.list_store_boxes(d13, st)) == 1 and
          core.list_store_boxes(d13, st)[0]["price"] == 1)
    check("预设可删除", core.delete_preset(ud, "inventory", "我的仓库") and
          "我的仓库" not in core.inventory_preset_names(ud))

    # ---------------- 发布约束：默认只列官方包名 ----------------
    # 断言里不写任何非官方包名，避免出现「代码里预置了它」的反效果。
    OFFICIAL = "com.rustltd.h3vr2"
    check("默认配置为官方包名", core.DEFAULT_CONFIG["package"] == OFFICIAL)
    check("兜底候选只含官方包名",
          core.DEFAULT_CONFIG["package_fallbacks"] == [OFFICIAL])
    all_pkgs = ([core.DEFAULT_CONFIG["package"]] +
                list(core.DEFAULT_CONFIG["package_fallbacks"]))
    check("默认配置不含其他包名", all(p == OFFICIAL for p in all_pkgs), str(all_pkgs))

    # 配置已指定包名时不做静默探测；只有留空才向设备枚举。
    detect_calls = [0]
    real_discover = core.discover_packages
    other_pkg = "com.example.other.h3vr2"      # 中性的假包名，仅用于验证枚举能力
    def spy(c, s):
        detect_calls[0] += 1
        return [other_pkg]
    core.discover_packages = spy
    try:
        check("已配置包名时不静默探测",
              core.resolve_package(core.DEFAULT_CONFIG, "dev") == OFFICIAL
              and detect_calls[0] == 0, "探测调用 %d 次" % detect_calls[0])
        blank = dict(core.DEFAULT_CONFIG)
        blank["package"] = ""
        check("配置留空时才探测",
              core.resolve_package(blank, "dev") == other_pkg
              and detect_calls[0] == 1)
    finally:
        core.discover_packages = real_discover

    # 「自动探测」仍须通用枚举设备上真实存在的安装版本，供用户手动选择；
    # 名字来自设备目录，不来自源码常量。
    real_run_adb = core.run_adb
    custom_pkg = "com.example.custom.h3vr2"
    def fake_adb(c, args, serial=None, timeout=60, auto_connect=True, binary=False):
        if args[0] == "shell" and args[1].startswith("ls /sdcard/Android/data"):
            out = OFFICIAL + "\r\n" + custom_pkg + "\r\n"
        elif args[0] == "shell":
            out = ("===%s\r\nProfile0\r\n1700000000\r\n"
                   "===%s\r\nProfile0\r\n1600000000\r\n" % (custom_pkg, OFFICIAL))
        else:
            out = ""
        return {"code": 0, "stdout": out, "stderr": "", "cmd": " ".join(args)}
    core.run_adb = fake_adb
    try:
        found = core.discover_packages(core.DEFAULT_CONFIG, "dev")
        check("自动探测通用枚举设备包名",
              OFFICIAL in found and custom_pkg in found, ", ".join(found))
    finally:
        core.run_adb = real_run_adb

    venture_tests(tmp)
    export_path_tests(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    if fixture_root:
        shutil.rmtree(fixture_root, ignore_errors=True)


def venture_tests(tmp: str):
    """Venture 模拟器：存档目录自动发现、手动路径解析、写回与备份。

    用一棵仿真的 `data/users/<账号>/<包名>/external-data/files/SaveData/...`
    目录树覆盖，不依赖本机是否装了 Venture。
    """
    print("\n-- Venture 模拟器存档 --")
    root = os.path.join(tmp, "venture_home")
    users = os.path.join(root, "data", "users")
    OFFICIAL = core.DEFAULT_CONFIG["package"]
    other_pkg = "com.example.custom.h3vr2"

    def make_save(user, pkg, profile, mtime=None):
        d = os.path.join(users, user, pkg, "external-data", "files", "SaveData",
                         profile, "footlong.base")
        make_synthetic_save(d)
        if mtime:
            for n in os.listdir(d):
                os.utime(os.path.join(d, n), (mtime, mtime))
        return d

    old = make_save("aaaa1111bbbb", OFFICIAL, "Profile0", 1600000000)
    new = make_save("cccc2222dddd", OFFICIAL, "Profile1", 1700000000)
    odd = make_save("eeee3333ffff", other_pkg, "Profile0", 1800000000)
    os.makedirs(os.path.join(users, "gggg4444", "com.other.game", "external-data"),
                exist_ok=True)   # 没有 SaveData 的杂物目录，不该被当成存档

    cfg = dict(core.DEFAULT_CONFIG)
    cfg["venture_root"] = root
    cfg["backup_root"] = os.path.join(tmp, "vbak")
    check("Venture 根目录取自配置", core.venture_roots(cfg)[0] == os.path.abspath(root),
          core.venture_roots(cfg)[0])

    # 只扫这棵仿真目录树，避免把本机真实安装的 Venture 也算进来
    found = core.find_venture_saves(cfg, roots=[root], log=lambda m: None)
    paths = [r["path"] for r in found]
    check("扫描到全部 Venture 存档", len(found) == 3, "%d 份" % len(found))
    check("官方包名最近写入排第一",
          bool(found) and found[0]["path"] == new,
          found[0]["path"] if found else "无")
    check("非官方包名排在最后并标记",
          bool(found) and found[-1]["path"] == odd and not found[-1]["official"])
    check("账号 / 槽位 / 文件数解析正确",
          found[0]["user"] == "cccc2222dddd" and found[0]["profile"] == "Profile1"
          and found[0]["count"] == 18 and bool(found[0]["mtime"]),
          "%s/%s %d 个文件 %s" % (found[0]["user"], found[0]["profile"],
                                  found[0]["count"], found[0]["mtime"]))
    check("无存档的目录不入结果", not any("com.other.game" in p for p in paths))

    probes = [(new, "footlong.base"), (os.path.dirname(new), "槽位目录"),
              (os.path.dirname(os.path.dirname(new)), "SaveData"),
              (os.path.join(users, "cccc2222dddd"), "账号目录")]
    for probe, label in probes:
        got = core.resolve_save_dir(probe, "footlong.base")
        check("手动选路径可定位（%s）" % label, got == new, got or "None")
    check("无存档目录返回空",
          core.resolve_save_dir(os.path.join(tmp, "nowhere"), "footlong.base") is None)

    # 写回：自动备份 → 写盘 → 回读校验
    data = core.load_save(new)
    data["Economy.json.gz"]["Data"]["Money"] = 777
    r = core.save_venture(cfg, new, data, log=lambda m: None)
    check("写回到 Venture 存档", len(r["written"]) == 18, "%d 个文件" % len(r["written"]))
    check("写回后数值生效",
          core.quick_read(core.load_save(new), "Economy.json.gz", "Data.Money") == 777)
    check("保存前自动备份原文件",
          bool(r["backup_dir"]) and os.path.isfile(
              os.path.join(r["backup_dir"] or "", "Economy.json.gz")),
          r["backup_dir"] or "")
    baks = core.load_save(r["backup_dir"]) if r["backup_dir"] else {}
    check("备份是改动前的原档",
          core.quick_read(baks, "Economy.json.gz", "Data.Money") == 100)
    check("不影响其他账号的存档",
          core.quick_read(core.load_save(old), "Economy.json.gz", "Data.Money") == 100)

    msg = ""
    try:
        core.save_venture(cfg, os.path.join(tmp, "missing"), data, backup=False,
                          log=lambda m: None)
    except RuntimeError as e:
        msg = str(e)
    check("目录不存在时报错可读", "不存在" in msg, msg[:60])

def export_path_tests(tmp: str):
    """回归：adb 1.0.41(v37) 处理非 ASCII 本地路径会截断路径。

    用假的 adb 复现该缺陷，确认导出不让 adb 接触本地路径
    （exec-out 取字节 + Python 写盘），中文本地路径与中文文件名都能落地；
    exec-out 不可用时能回退，且失败信息可定位到具体文件。
    """
    print("\n-- 导出路径回归（中文目录 / 中文文件名 / adb v37 缺陷）--")
    parent = os.path.join(tmp, "中文目录_存档编辑器")
    os.makedirs(parent, exist_ok=True)
    names = ["Activities.json.gz", "Economy.json.gz", "经验.json.gz"]
    remote = "/sdcard/Android/data/pkg/files/SaveData/Profile0/footlong.base"
    cfg = dict(core.DEFAULT_CONFIG)
    cfg["wake_before_action"] = False
    cfg["connect_before_action"] = False
    whole_dir_pulls: list[tuple[str, str]] = []
    exec_out_calls: list[str] = []
    real_run_adb = core.run_adb
    fail_on = [None]

    def fake_run_adb(c, args, serial=None, timeout=60, auto_connect=True,
                     binary=False):
        if args[0] == "shell":
            return {"code": 0, "stdout": "\r\n".join(names), "stderr": "",
                    "cmd": " ".join(args)}
        if args[0] == "exec-out":
            rp = args[1].split('"')[1]
            exec_out_calls.append(rp)
            n = rp.rsplit("/", 1)[-1]
            if n == fail_on[0]:
                return {"code": 1, "stdout": b"",
                        "stderr": "adb: unknown command exec-out",
                        "cmd": " ".join(args)}
            return {"code": 0, "stdout": ("GZ:" + n).encode("utf-8"),
                    "stderr": "", "cmd": " ".join(args)}
        if args[0] == "pull":
            src, dst = args[1], args[2]
            if src.rstrip("/").endswith("footlong.base"):
                # 模拟 adb v37：目标目录被截断后写文件失败
                whole_dir_pulls.append((src, dst))
                return {"code": 1, "stdout": "",
                        "stderr": ("adb: error: cannot create '%s\\footlong.base\\"
                                   "Activities.json.gz': Not a directory\n"
                                   "pull: building file list..." % dst),
                        "cmd": " ".join(args)}
            n = src.rsplit("/", 1)[-1]
            if n == fail_on[0]:
                return {"code": 1, "stdout": "",
                        "stderr": "adb: error: cannot create '" + dst + "': permission denied",
                        "cmd": " ".join(args)}
            with open(dst, "wb") as f:
                f.write(("GZ:" + n).encode("utf-8"))
            return {"code": 0, "stdout": "", "stderr": "1 file pulled",
                    "cmd": " ".join(args)}
        return {"code": 0, "stdout": "", "stderr": "", "cmd": " ".join(args)}

    core.run_adb = fake_run_adb
    try:
        r = core.export_save(cfg, "1.2.3.4:5555", dest_parent=parent,
                             pkg="pkg", log=lambda m: None)
        check("中文路径导出不触发整目录 pull",
              not whole_dir_pulls, f"整目录 pull 次数 {len(whole_dir_pulls)}")
        check("adb 只收到设备端路径（exec-out）",
              len(exec_out_calls) == len(names)
              and all(x.startswith("/sdcard/") and ":\\" not in x
                      for x in exec_out_calls),
              f"{len(exec_out_calls)} 次")
        check("中文路径导出落地全部文件",
              r["count"] == len(names) and len(r["files"]) == len(names),
              f"{r['count']} 个")
        check("导出目录名完整未被截断",
              os.path.basename(r["local_dir"]) == "footlong.base"
              and "中文" in r["local_dir"]
              and sorted(os.listdir(r["local_dir"])) == sorted(names),
              os.path.basename(r["local_dir"]))
        check("中文文件名内容正确",
              open(os.path.join(r["local_dir"], "经验.json.gz"), "rb").read()
              == "GZ:经验.json.gz".encode("utf-8"))
        check("导出结果保留 raw/remote 契约",
              r["raw"]["code"] == 0 and r["remote"] == remote and bool(r["tag"]))

        fail_on[0] = "Economy.json.gz"
        msg = ""
        try:
            core.export_save(cfg, "1.2.3.4:5555", dest_parent=parent,
                             pkg="pkg", log=lambda m: None)
        except RuntimeError as e:
            msg = str(e)
        check("exec-out 不可用可回退且失败可定位",
              fail_on[0] in msg and "permission denied" in msg
              and "exec-out" in msg, msg[:110])
    finally:
        core.run_adb = real_run_adb


def device_tests():
    print("\n== 真机集成测试（回传原样内容，不修改任何数值）==")
    cfg = core.load_config()
    cfg["stop_game_before_push"] = False
    cfg["relaunch_after_push"] = False
    target = f"{cfg['wifi_ip']}:{cfg['wifi_port']}"

    r = core.connect_wifi(cfg)
    check("adb connect 无线", "connected" in (r["stdout"] or "").lower() or
          "already connected" in (r["stdout"] or "").lower(), r["stdout"])

    devs = core.list_devices(cfg)
    labels = [d["serial"] for d in devs if d["state"] == "device"]
    check("设备枚举包含无线头显", target in labels, ", ".join(labels))

    pkgs = core.discover_packages(cfg, target)
    check("自动发现存档包", cfg["package"] in pkgs, ", ".join(pkgs))
    profiles = core.discover_profiles(cfg, target, cfg["package"])
    check("自动发现存档槽", cfg["profile"] in profiles, ", ".join(profiles))

    remote = core.remote_save_path(cfg)
    check("存档路径正确", remote.endswith("Profile0/footlong.base"), remote)

    # 1) 导出
    exp = core.export_save(cfg, target, log=lambda m: print("    " + m))
    check("一键导出", exp["count"] == 18, f"{exp['count']} 个文件")
    before = {os.path.basename(p): core.md5_file(p) for p in exp["files"]}

    # 2) 回传（原样内容）
    imp = core.import_save(cfg, target, exp["local_dir"], log=lambda m: print("    " + m))
    check("一键回传文件数", len(imp["pushed"]) == 18, f"{len(imp['pushed'])} 个")
    check("自动备份已生成", bool(imp["backup_dir"]) and os.path.isdir(imp["backup_dir"] or ""),
          imp["backup_dir"] or "")
    check("md5 校验通过", bool(imp["verify"]) and not imp["verify"]["bad"],
          str(imp["verify"]))

    # 3) 权限
    ls = core.run_adb(cfg, ["shell", f"ls -l {remote}"], serial=target)
    check("设备端可读可写 (rw-rw-rw-)", "-rw-rw-rw-" in ls["stdout"],
          ls["stdout"].splitlines()[1] if len(ls["stdout"].splitlines()) > 1 else "")

    # 4) 再导出比对
    exp2 = core.export_save(cfg, target, log=lambda m: print("    " + m))
    after = {os.path.basename(p): core.md5_file(p) for p in exp2["files"]}
    check("往返后 18 个文件 md5 全同", before == after,
          f"{sum(1 for k in before if before.get(k) == after.get(k))}/18")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="store_true", help="执行真机导出/回传往返验证")
    args = ap.parse_args()
    unit_tests()
    if args.device:
        try:
            device_tests()
        except Exception as e:
            global FAIL
            FAIL += 1
            print("  [FAIL] 真机测试异常：" + repr(e))
            import traceback
            traceback.print_exc()
    print(f"\n结果：PASS={PASS}  FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
