# 用户指南（进阶）

> 这是二级文档，面向需要了解细节的用户与开发者。第一次使用请先看 [仓库首页 README](../README.md) 的「四步流程」与演示图。

## 目录

1. [连接与传输](#1-连接与传输)
2. [各标签页详解](#2-各标签页详解)
3. [预设与收藏](#3-预设与收藏)
4. [Venture 模拟器存档](#4-venture-模拟器存档)
5. [包名与兼容策略](#5-包名与兼容策略)
6. [存档结构与字段](#6-存档结构与字段)
7. [配置项完整表](#7-配置项完整表)
8. [生效原理、风险与回滚](#8-生效原理风险与回滚)
9. [常见问题](#9-常见问题)

---

## 1. 连接与传输

### 连接头显

- **USB（推荐）**：插数据线 → 头显点「允许 USB 调试」→ 程序点「刷新设备」→ 在设备下拉框选 `[USB]` 那台。
- **无线（可选）**：保持 USB 连接，点「USB→启用无线调试」自动部署（读取头显 IP → `adb tcpip 5555` → `adb connect` → 设置待机保持 Wi-Fi）；已开过无线调试时点「扫描局域网」，或填「无线 IP」后点「连接无线」。
- 待机掉线点「唤醒头显」；头显重启后 tcpip 模式可能失效，需重新用 USB 部署一次。

### 存档来源

界面「来源」一栏会写明当前存档来自哪里，并决定「②」按钮的文案与目标：

| 来源 | 「②」按钮文字 | 保存行为 |
|---|---|---|
| 头显导出快照 | `② 保存到本地` | 只改本地副本，需再点「③」回传头显才生效 |
| 手动选择的本地目录 | `② 保存到本地目录` | 直接写回该目录；要回头显仍需「③」 |
| Venture 模拟器 | `② 保存到 Venture 存档` | 直接写回 Venture 目录，不走 adb，保存前自动备份 |

### 回传链路

「③ 一键回传到头显」自动完成：**强制停止游戏 → 备份 → 推送 → `chmod 666` → md5 校验 → 冷启动重新读档**。
底部「回传前停止游戏并冷启动（必需）」请勿关闭；「只回传修改过的文件」可减少写入量。

---

## 2. 各标签页详解

界面共 7 个标签页，所有 adb 操作在后台线程执行，界面不卡死。

| 标签页 | 用途 |
|---|---|
| 快捷编辑 | 存档独有的 9 个数值（货币 / 肉 / 金属 / 芥末 / 经验 / 血量 / 游玩统计）+ 弹匣补满 |
| 商店编辑 | 列出全部货位，双击改出售物品 / 售价 / 分区；增删货位、打折、统一定价 |
| 仓库编辑 | 多页 12×8 网格：换物品、改位置与占格、清空组件、复制 / 删除 / 新增槽位 |
| ★ 收藏与预设 | 管理收藏、预设与自动应用；批量加入商店 / 仓库 |
| 全部参数（树） | 逐字段双击改值、右键增删节点，可按路径过滤 |
| 原始 JSON | 整段编辑当前文件的 JSON 文本 |
| 字段说明 | 按当前存档动态生成全部叶子字段的中文说明，可导出 JSON |

**快捷编辑字段**（对应文件见 [§6](#6-存档结构与字段)）：

| 字段 | 说明 |
|---|---|
| `Money` | 通用货币 |
| `Meat` / `Metal` / `Mustard` | 三种资源 |
| `Experience` | 经验值 XP（等级由 XP 换算） |
| `CurrentHealth` | 枢纽内玩家血量 |
| `PlaytimeSeconds` / `ShotsFired` / `Deaths` | 游玩时长 / 开火 / 死亡统计 |

> 设置菜单里能直接调整的项目（主音量、血腥效果、难度倍率、渲染档位等 43 项）
> 不放在「快捷编辑」栏；需要脚本化修改时到「全部参数（树）」或「原始 JSON」编辑 `Settings.json.gz`。

**商店编辑**：双击某行弹出物品选择器，可按中文名 / 英文名 / AssetKey 搜索，勾「只看 ★ 收藏」快速定位。
底部可「全部打折」（价格系数）、「统一售价」（应用）、增删货位。物品来自 `items_catalog.json`（v0.4.0 共 684 条，669 条引用已验证）。

**仓库编辑**：选仓库页 → 双击槽位换物品；「＋ 新增物品」自动找空格。可改占格、位置、清空组件、复制 / 删除槽位。

---

## 3. 预设与收藏

存档每次从设备重新导出都是设备上的新内容，之前改好的商店 / 仓库不会自动跟过来。
预设把「编辑内容」单独存到程序目录的 `presets.json`，与存档分离。

**使用流程**

1. 改好商店 / 仓库 → 点对应页的「保存当前为预设」。
2. 之后导出新存档 → 选中预设点「一键应用（替换）」还原；或在「★ 收藏与预设」页设为**自动应用**，导出完成时程序自动套用。
3. 「追加物品」用于在不删除现有货位 / 槽位的前提下批量加入预设物品。
4. 「导出预设 / 导入预设」可分享配置。

**`presets.json` 结构示例**

```json
{
  "version": 2,
  "settings": {"store_auto_preset": "我的常用商店", "store_auto_mode": "replace"},
  "store_presets": {
    "我的常用商店": {
      "store": "extref://footlong.base/Store/Store_Starter",
      "boxes": [{"item": "extref://footlong.base/M4A1", "sectionID": "basics", "price": 1}]
    }
  },
  "inventory_presets": {
    "常用补给": {"items": [{"item": "extref://footlong.base/Item/MapR", "size": [1, 1]}]}
  },
  "favorites": ["extref://footlong.base/Item/MapR"]
}
```

`item` 可填完整 `extref`，也可只填 `AssetKey`（如 `M4A1`）；`size` 是仓库占格 `[宽, 高]`。
文件写坏时程序会留 `.bad.<时间戳>` 副本并回退到默认配置。

**收藏**：在任意物品选择框点「★ 加入 / 取消收藏」或勾「只看 ★ 收藏」快速定位；收藏页可把选中（未选则全部）物品批量加入商店（左侧填统一售价）或仓库。

---

## 4. Venture 模拟器存档

[Venture](https://github.com/Villagers654/Venture) 把 Quest 游戏当普通 PC 程序跑，存档因此是**本机的普通目录**而不是头显上的 `/sdcard`：

```
%LOCALAPPDATA%\Venture\data\users\<账号 ID>\com.rustltd.h3vr2\external-data\files\SaveData\Profile0\footlong.base
```

1. 点「**查找 Venture 存档**」：程序按默认位置自动搜索（也在 Linux 的 XDG / Flatpak 位置找）；找到多份（多账号 / 多槽位）时弹列表，按「官方包名优先 + 最近写入优先」排序。
2. 载入后「来源」写明账号、槽位与目录，按钮变成「**② 保存到 Venture 存档**」——直接写回，不走 adb。
3. 保存前自动备份到 `backups/venture_<时间戳>/`，写盘后逐个回读校验。「恢复最近备份」会把最近一份备份复制回该目录。

> 模拟器与头显一样只在**启动时读档**：请先在 Venture 里退出游戏再保存。程序会提示「检测到相关进程正在运行」，但不会替你结束进程。

找不到时用「**手动选择存档目录…**」：选 `footlong.base`、`Profile0`、`SaveData`、账号目录甚至 Venture 根目录都能定位（逐层往下找，最多 8 层）。若在 Venture 数据目录内按 Venture 模式处理，否则按普通本地目录处理。也可在 `config.json` 的 `venture_root` 直接指定。

---

## 5. 包名与兼容策略

**默认且仅列出官方包名 `com.rustltd.h3vr2`。** 本仓库的源码、配置、文档与项目页面不预置、不列举、不推荐任何被修改包名后分发的第三方版本；对付费汉化及改包分发不提供支持、不鼓励、不宣传。请使用合法取得的游戏副本。

若设备通过其他渠道安装、包名与官方不同：点界面「**自动探测**」，程序枚举设备 `/sdcard/Android/data` 下真实存在的包名和存档槽（`Profile0` = Slot 1），列出后由你手动选中并「保存配置」。这是设备侧的通用兼容能力，**不是对任何第三方发行版的推荐**：

- 程序启动时**不会**静默枚举设备包名；
- 默认配置、下拉框初始值与 `package_fallbacks` 都只有官方包名；
- 配置里已指定包名时，导出 / 回传都不会在未经你操作的情况下自动切换目标。

---

## 6. 存档结构与字段

**设备端**：`/sdcard/Android/data/<包名>/files/SaveData/Profile0/footlong.base/*.json.gz`

**Venture（PC）**：`%LOCALAPPDATA%\Venture\data\users\<账号 ID>\<包名>\external-data\files\SaveData\Profile0\footlong.base\*.json.gz` —— 内容与设备端等价。

每个文件是**标准 gzip**（头 `1f8b 08 00 00000000 00 03`，即 .NET `GZipStream` 默认输出）包裹的 **UTF-8 紧凑 JSON**，统一 `{"Version":0,"Data":{...}}`。一次实测导出 18 个文件 / 7215 字节；物品引用形如 `extref://footlong.base/Item/xxx`（部分条目没有 `Item/` 中段，以物品目录里的真实引用为准）。

| 文件 | 主要内容 |
|---|---|
| `Economy.json.gz` | `Money` 货币、`Meat` 肉、`Metal` 金属、`Mustard` 芥末 |
| `Experience.json.gz` | `Experience` 经验值（等级由 XP 换算） |
| `Settings.json.gz` | 音量、血腥效果、难度倍率 `playerDamage` / `npcDamage` / `powerupDuration` 等 |
| `Stores.json.gz` | 商店货位：`item` 物品引用、`price` 售价、`sectionID` 分区 |
| `Inventory.json.gz` | 玩家仓库：`InventoryPages[]` → `items[]` 槽位 → `contents.Objects[]` 物件 |
| `PlayerHubState.json.gz` | 枢纽内玩家状态（含 `CurrentHealth`） |
| `PlayStats.json.gz` | 游玩时长、开火、死亡等统计 |
| 其余 | 挑战、工单、扫描清单、进度标记等 |

「字段说明」页按当前载入的存档动态生成全部叶子字段的中文说明，可导出 JSON（完整字段目录见程序内「导出完整字段目录」）。
**仓库与发布包均不含任何玩家存档数据。**

---

## 7. 配置项完整表

`config.json`（界面可直接改并保存）。仓库内是**脱敏模板**：`wifi_ip`、`lan_subnet` 留空，运行时自动推断本机网段 / 从 USB 读取头显 IP。

| 键 | 默认值 | 含义 |
|---|---|---|
| `adb_path` | `""` | adb 路径；留空自动查找（便携版为 `adb/adb.exe`） |
| `wifi_ip` / `wifi_port` | `""` / `5555` | 头显无线调试地址与端口 |
| `package` | `com.rustltd.h3vr2` | **官方包名**；见 [§5](#5-包名与兼容策略) |
| `package_fallbacks` | `["com.rustltd.h3vr2"]` | 设备目录枚举失败时的兜底候选 |
| `profile` / `save_subdir` | `Profile0` / `footlong.base` | 存档槽（Slot 1）与其下的目录名 |
| `lan_subnet` | `""` | 局域网扫描网段前三段；留空自动推断 |
| `lan_scan_enabled` / `lan_scan_port` / `lan_scan_timeout_ms` | `true` / `5555` / `400` | 局域网扫描开关、端口、超时 |
| `auto_backup` | `true` | 回传前先导出设备原档作回滚源 |
| `chmod_after_push` | `true` | **必须开启**，否则读档 EACCES 卡加载页 |
| `verify_after_push` | `true` | 推送后设备端 md5 校验 |
| `stop_game_before_push` | `true` | **必须开启**，否则运行中游戏写盘覆盖修改 |
| `relaunch_after_push` | `true` | 回传后冷启动重新读档 |
| `push_only_modified` | `true` | 只回传被修改过的文件 |
| `wake_before_action` / `connect_before_action` | `true` | 操作前唤醒头显 / 自动 `adb connect` |
| `export_root` / `backup_root` | `exports` / `backups` | 导出与备份根目录 |
| `items_catalog` / `presets_file` | `items_catalog.json` / `presets.json` | 物品目录 / 预设收藏文件 |
| `venture_root` | `""` | Venture 数据根目录；留空自动查 |
| `venture_auto_detect` | `true` | 启动时自动查找并载入 Venture 存档 |
| `venture_backup_on_save` | `true` | 写回 Venture 前自动备份原文件 |

---

## 8. 生效原理、风险与回滚

1. 游戏**只在启动时读档**；运行中界面数值来自内存，跑图、结算会把内存旧值写回文件。所以回传默认强制停止游戏并冷启动，请勿关闭底部开关。
2. 回传前自动备份，出问题点「恢复最近备份」回滚。**仍请自行留存完整原档**。
3. 物品请使用目录中标记为「已验证」的引用；编造不存在的 `extref` 可能导致货位读不出来或读档失败。复杂枪械建议用「复制槽位」后再换物品。
4. 游戏运行中购买、跑图、退出主菜单都会再次写盘，数值会随游戏行为变化。
5. 修改存档有风险，本工具按「现状」提供，不保证适配游戏的未来版本。

---

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| 改完没效果 | 确认底部「回传前停止游戏并冷启动」已开启；游戏只在启动读档 |
| 导出报 `Not a directory` 或只出现 `footlo` 空目录 | 使用 v0.2.0 及以上版本；该版让 adb 不接触本地路径，中文路径正常 |
| 游戏卡在加载页 | 多半是权限问题，确认 `chmod_after_push=true`；用「恢复最近备份」回滚 |
| 头显待机后失联 | 点「唤醒头显」或「扫描局域网」；重启头显后需 USB 重新部署无线调试 |
| GUI 打不开 | Python 必须自带 tkinter；便携版直接用 `启动存档编辑器.bat` |
| 商店 / 仓库改了又没了 | 重新导出的是设备新存档；用预设「一键应用」或开启自动应用 |
| 包名与默认不同 | 点「自动探测」选中真实包名并「保存配置」，见 [§5](#5-包名与兼容策略) |
| 找不到 Venture 存档 | 确认在 Venture 里装过并至少运行过一次；或填 `venture_root`；或「手动选择存档目录」选到 `footlong.base` |
| Venture 里改了没生效 | 先在 Venture 里退出游戏再「保存到 Venture 存档」，然后重新启动游戏 |
| 手选目录提示没有存档 | 选到 `footlong.base` 或其上层（`Profile0` / `SaveData`）；视频/图片目录里没有 `*.json.gz` |

---

## 开发者文档

- [物品表生成器用法](../tools/README.md) —— 游戏更新后从自己的安装包读取新物品（进阶工具）
- [贡献指南](../CONTRIBUTING.md) · [免责声明与 AI 辅助说明](../DISCLAIMER.md) · [更新日志](../CHANGELOG.md)
