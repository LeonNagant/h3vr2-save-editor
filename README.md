# H3VR2 存档编辑器

[![version](https://img.shields.io/badge/version-v0.3.0-blue)](#3-版本信息与下载) · [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE) · [![python](https://img.shields.io/badge/python-3.10%2B-blue)](#4-快速开始) · [项目页](https://leonnagant.github.io/h3vr2-save-editor/) · [下载 v0.3.0](https://github.com/LeonNagant/h3vr2-save-editor/releases/tag/v0.3.0)

面向 Meta Quest 上 **H3VR2 单机存档** 的非官方第三方编辑工具：可编辑存档内全部
参数、商店出售物品与价格、玩家仓库物品；一键从 USB / 无线 adb 导出存档，
一键回传并让改动真正生效。Windows 便携版自带 Python 运行时与 adb，
**无需安装任何依赖**。

> **注意 · 非官方项目**：与游戏开发者、发行方、平台方无任何关联，也未获授权或认可。
> 仅用于编辑你自己的单机离线存档。完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。

> **本项目使用 AI 生成辅助**：仓库中的源代码、物品目录、字段说明、技术文档、
> 使用说明、发布说明与 GitHub Pages 页面均由 AI 辅助生成，并经人工审阅、
> 单元测试（81/81 通过）与真机往返验证后发布。AI 生成内容可能有误，请以自己
> 导出的存档为准，操作前自行备份。详见 [DISCLAIMER.md §1](DISCLAIMER.md#1-关于-ai-生成辅助明确标注)。

---

## 目录

[1. 项目说明](#1-项目说明) · [2. 功能一览](#2-功能一览) · [3. 版本信息与下载](#3-版本信息与下载) ·
[4. 快速开始](#4-快速开始) · [5. 使用方法](#5-使用方法) · [6. 包名与兼容策略](#6-包名与兼容策略) ·
[7. 存档位置与结构](#7-存档位置与结构) · [8. 配置项](#8-配置项) ·
[9. 生效原理与风险](#9-生效原理风险与回滚) · [10. 常见问题](#10-常见问题) ·
[11. 开发与验证](#11-开发与验证) · [12. 文件说明](#12-文件说明) · [13. 声明](#13-声明)

---

## 1. 项目说明

H3VR2 的单机难度较高，而存档把资源、经验、商店货位、玩家仓库等数据以
gzip 压缩的 JSON 保存在头显上。本项目把这些文件解析成可读字段，提供一个
纯本地的图形界面来查看与修改，并解决「改了不生效」的实际问题：游戏只在
**启动时读档**，运行中会把内存旧值写回文件，所以回传必须配合停游戏与冷启动。

**设计原则**

| 原则 | 做法 |
|---|---|
| 不碰游戏本体 | 只读写存档 JSON，不改 APK / OBB，不注入、不绕过授权或内购 |
| 纯本地、零依赖 | Python 标准库 + tkinter；无账号、无遥测、无网络上报 |
| 默认只认官方包 | 默认且仅列出官方包名 `com.rustltd.h3vr2`，见 [§6](#6-包名与兼容策略) |
| 可回滚 | 回传前自动备份设备原档，提供「恢复最近备份」 |
| 编辑内容与存档分离 | 预设存在 `presets.json`，重新导出存档后仍可一键还原 |

## 2. 功能一览

| 功能 | 说明 |
|---|---|
| 编辑任意参数 | 「全部参数（树）」逐字段双击改值、右键增删节点；「原始 JSON」整段编辑 |
| 快捷编辑 | 只保留存档独有的 9 个数值（货币 / 三项资源 / 经验 / 血量 / 统计）+ 弹匣补满 |
| 商店编辑 | 列出全部货位，搜索 666 种物品改出售物品、售价、分区；增删货位、打折、统一定价 |
| 仓库编辑 | 多页 12×8 网格：换物品、改位置与占格、清空组件、复制 / 删除 / 新增槽位 |
| 预设 | 商店页 / 仓库页保存当前为预设、一键替换、追加物品、删除；可导出分享 |
| 自动还原 | 设为自动应用后，每次导出 / 载入新存档自动套用预设 |
| 收藏 | 「只看 ★ 收藏」快速定位；收藏可批量加入商店（统一售价）或仓库 |
| 一键导出 | 枚举 USB / 无线 adb 设备、扫描局域网 5555 端口，导出到 `exports/<时间戳>/` |
| 一键回传 | 强制停止游戏 → 备份 → 推送 → `chmod 666` → md5 校验 → 冷启动重新读档 |
| Venture 存档 | 自动查找 PC 端 Venture 模拟器里的 H3VR2 存档并直接读写，无需 adb；保存前自动备份 |
| 手动目录 | 自动查找失败或玩家自己从别处提取了存档时，手选 `footlong.base` / `Profile0` / `SaveData` 均可 |
| 回滚 | 「恢复最近备份」把 `backups/<时间戳>/` 的原档推回设备 |

界面共 **7 个标签页**：快捷编辑、商店编辑、仓库编辑、★ 收藏与预设、
全部参数（树）、原始 JSON、字段说明。所有 adb 操作在后台线程执行，界面不卡死。

> 设置菜单里能直接调整的项目（主音量、血腥效果、难度倍率、渲染档位等 43 项）
> 不放在「快捷编辑」栏；需要脚本化修改时到「全部参数（树）」或「原始 JSON」
> 编辑 `Settings.json.gz`。

## 3. 版本信息与下载

| 项目 | 内容 |
|---|---|
| 当前版本 | **v0.3.0** |
| 发布日期 | 2026-11-17 |
| 适用平台 | Windows 10/11 64 位 + Meta Quest（已开启开发者模式 / USB 调试）；含 PC 端 Venture 模拟器 |
| 运行环境 | 便携版自带 Python 3.10.5（含 tkinter）与 adb；零第三方 pip 依赖 |
| 下载 | [GitHub Releases · v0.3.0](https://github.com/LeonNagant/h3vr2-save-editor/releases/tag/v0.3.0) → `H3VR2-Save-Editor-v0.3.0-Windows-Portable.zip` |
| 项目页 | [GitHub Pages](https://leonnagant.github.io/h3vr2-save-editor/) |
| 更新日志 | [CHANGELOG.md](CHANGELOG.md) · [VERSION.txt](VERSION.txt) |

v0.3.0 由社区贡献者 Niko666233 通过 PR #1 新增 Venture 模拟器存档支持（自动
查找 / 手动选目录 / 直接写回 + 备份）；v0.2.0 新增预设 / 自动还原 / 仓库编辑 /
收藏，并修复了中文路径下导出失败的问题；详细条目见 [CHANGELOG.md](CHANGELOG.md)。

## 4. 快速开始

### 方式 A：Windows 便携版（推荐，普通用户）

1. 从 [Releases](https://github.com/LeonNagant/h3vr2-save-editor/releases/tag/v0.3.0)
   下载 `H3VR2-Save-Editor-v0.3.0-Windows-Portable.zip`。
   Release 资产使用 ASCII 文件名以兼容各平台；解压后的目录与包内说明均为中文。
2. **把整个压缩包解压到一个文件夹**（不要只解压单个文件；支持含中文的路径）。
3. 双击 `启动存档编辑器.bat`；若窗口没出现，改双击 `启动-调试模式.bat` 看报错。

不需要安装 Python，也不需要安装 adb。

### 方式 B：从源码运行（开发者）

```bash
git clone https://github.com/LeonNagant/h3vr2-save-editor.git
cd h3vr2-save-editor
py -3.10 h3vr2_save_editor.py        # Windows 也可双击 run_editor.bat
```

要求 Python 3.8+ 且**自带 tkinter**，`adb.exe` 在 PATH 中或写入 `config.json`
的 `adb_path`。注意部分 Python 3.13 发行版不含 tkinter，无法启动 GUI。

## 5. 使用方法

### 连接头显

- **USB（推荐）**：插数据线 → 头显里点「允许 USB 调试」→ 程序点「刷新设备」→
  在设备下拉框选 `[USB]` 那台。
- **无线（可选）**：保持 USB 连接，点「USB→启用无线调试」自动部署
  （读取头显 IP → `adb tcpip 5555` → `adb connect` → 设置待机保持 Wi-Fi）；
  已经开过无线调试时点「扫描局域网」，或填「无线 IP」后点「连接无线」。
- 头显待机掉线时点「唤醒头显」；头显重启后 tcpip 模式可能失效，需重新用 USB 部署一次。

### 改存档：三步

1. **① 一键导出存档** → 存档落到 `exports/<时间戳>/footlong.base/`。
2. **选择要改的内容**（右侧 7 个标签页），例如：
   - 快捷编辑：货币、肉、金属、芥末、经验、血量、游玩统计；
   - 商店编辑：双击货位 → 搜索中文物品名 → 改出售物品 / 售价 / 分区；
   - 仓库编辑：选仓库页 → 双击槽位换物品；「＋ 新增物品」自动找空格；
   - ★ 收藏与预设：管理收藏、预设与自动应用。
3. **② 保存到本地** → **③ 一键回传到头显**。程序自动完成
   强制停止游戏 → 备份 → 推送 → `chmod 666` → md5 校验 → 冷启动重新读档。

> 「③」会自动先把内存里的修改写盘，因此「②」可以跳过；但建议保留，
> 便于推送前用文件管理器核对。

### 在 Venture 模拟器上改存档（PC 端，不需要 adb）

[Venture](https://github.com/Villagers654/Venture) 把 Quest 游戏当普通 PC 程序跑，
存档因此是**本机的普通目录**而不是头显上的 `/sdcard`：

```
%LOCALAPPDATA%\Venture\data\users\<账号 ID>\com.rustltd.h3vr2\external-data\files\SaveData\Profile0\footlong.base
```

1. 点「**查找 Venture 存档**」。程序按上面的默认位置自动搜索（也在 Linux 的
   XDG / Flatpak 位置找）；找到多份（多账号 / 多槽位）时弹出列表让你选，
   按「官方包名优先 + 最近写入优先」排序。
2. 载入后「存档来源」一栏会写明账号、槽位与目录，按钮变成
   「**② 保存到 Venture 存档**」——直接写回该目录，不走 adb。
3. 保存前自动把原文件备份到 `backups/venture_<时间戳>/`，写盘后逐个回读校验。
   「恢复最近备份」会把最近一份备份复制回该目录。

> 模拟器与头显一样只在**启动时读档**：请先在 Venture 里退出游戏再保存。
> 程序会提示「检测到相关进程正在运行」，但不会替你结束进程。

找不到时用「**手动选择存档目录…**」：选 `footlong.base`、`Profile0`、`SaveData`、
账号目录甚至 Venture 根目录都能定位（程序逐层往下找，最多探 8 层并限制访问量）。
若目录在 Venture 数据目录内，自动按 Venture 模式处理；否则按普通本地目录处理
（保存只写本地，回头显仍需「③ 一键回传到头显」）。也可在 `config.json` 的
`venture_root` 直接指定 Venture 数据目录。

### 预设：导出新存档后不用重新编辑

存档每次从设备重新导出都是设备上的新内容，之前改好的商店 / 仓库不会自动跟过来。
预设把「编辑内容」单独存到程序目录的 `presets.json`：

1. 改好商店 / 仓库 → 点对应页的「保存当前为预设」。
2. 之后导出新存档 → 选中预设点「一键应用（替换）」还原；或在
   「★ 收藏与预设」页设为**自动应用**，导出完成时程序自动套用。
3. 「追加物品」用于在不删除现有货位 / 槽位的前提下批量加入预设物品。

`presets.json` 可用记事本直接编辑，也可在界面「导出预设 / 导入预设」分享：

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

`item` 可填完整 `extref`，也可只填 `AssetKey`（如 `M4A1`）；`size` 是仓库占格
`[宽, 高]`。文件写坏时程序会留 `.bad.<时间戳>` 副本并回退到默认配置。

### 收藏

在任意物品选择框点「★ 加入 / 取消收藏」或勾「只看 ★ 收藏」快速定位；
收藏页可把选中（未选则全部）物品批量加入商店（左侧填统一售价）或仓库。

## 6. 包名与兼容策略

**默认且仅列出官方包名 `com.rustltd.h3vr2`。** 本仓库的源码、配置、文档与
项目页面不预置、不列举、不推荐任何被修改包名后分发的第三方版本；对付费汉化
及改包分发不提供支持、不鼓励、不宣传。请使用合法取得的游戏副本。

若你的设备通过其他渠道安装、包名与官方不同：点界面「**自动探测**」，
程序会枚举设备 `/sdcard/Android/data` 下真实存在的游戏包名和存档槽
（`Profile0` = Slot 1），列出后由你手动选中并「保存配置」。这是设备侧的通用
兼容能力，**不是对任何第三方发行版的推荐**：

- 程序启动时**不会**静默枚举设备包名；
- 默认配置、下拉框初始值与 `package_fallbacks` 都只有官方包名；
- 配置里已指定包名时，导出 / 回传都不会在未经你操作的情况下自动切换目标。

## 7. 存档位置与结构

设备端：`/sdcard/Android/data/<包名>/files/SaveData/Profile0/footlong.base/*.json.gz`

Venture 模拟器（PC 端）：
`%LOCALAPPDATA%\Venture\data\users\<账号 ID>\<包名>\external-data\files\SaveData\Profile0\footlong.base\*.json.gz`
—— 内容与设备端完全等价，程序直接当本地目录读写。

每个文件是**标准 gzip**（头 `1f8b 08 00 00000000 00 03`，即 .NET `GZipStream`
默认输出）包裹的 **UTF-8 紧凑 JSON**，统一 `{"Version":0,"Data":{...}}`。
一次实测导出 18 个文件 / 7215 字节；物品引用形如
`extref://footlong.base/Item/xxx`（部分条目没有 `Item/` 中段，以物品目录里的
真实引用为准）。

| 文件 | 主要内容 |
|---|---|
| `Economy.json.gz` | `Money` 货币、`Meat` 肉、`Metal` 金属、`Mustard` 芥末 |
| `Experience.json.gz` | `Experience` 经验值（等级由 XP 换算） |
| `Settings.json.gz` | 音量、血腥效果、难度倍率 `playerDamage` / `npcDamage` / `powerupDuration` 等 |
| `Stores.json.gz` | 商店货位：`item` 物品引用、`price` 售价、`sectionID` 分区 |
| `Inventory.json.gz` | 玩家仓库：`InventoryPages[]` → `items[]` 槽位 → `contents.Objects[]` 物件（`ItemDef` / `InstanceSeed` / `Components`） |
| `PlayerHubState.json.gz` | 枢纽内玩家状态（含 `CurrentHealth`） |
| `PlayStats.json.gz` | 游玩时长、开火、死亡等统计 |
| 其余 | 挑战、工单、扫描清单、进度标记等 |

「字段说明」页按当前载入的存档动态生成全部叶子字段的中文说明，可导出 JSON。
**仓库与发布包均不含任何玩家存档数据。**

## 8. 配置项

`config.json`（界面可直接改并保存）。仓库内是**脱敏模板**：`wifi_ip`、
`lan_subnet` 留空，运行时自动推断本机网段 / 从 USB 读取头显 IP。

| 键 | 默认值 | 含义 |
|---|---|---|
| `adb_path` | `""` | adb 路径；留空自动查找（便携版为 `adb/adb.exe`） |
| `wifi_ip` / `wifi_port` | `""` / `5555` | 头显无线调试地址与端口 |
| `package` | `com.rustltd.h3vr2` | **官方包名**；其他安装版本见 [§6](#6-包名与兼容策略) |
| `package_fallbacks` | `["com.rustltd.h3vr2"]` | 设备目录枚举失败时的兜底候选 |
| `profile` / `save_subdir` | `Profile0` / `footlong.base` | 存档槽（Slot 1）与其下的目录名 |
| `lan_subnet` | `""` | 局域网扫描网段前三段；留空自动推断 |
| `lan_scan_enabled` / `lan_scan_port` / `lan_scan_timeout_ms` | `true` / `5555` / `400` | 局域网扫描开关、端口、超时 |
| `auto_backup` | `true` | 回传前先导出设备原档作回滚源 |
| `chmod_after_push` | `true` | **必须开启**，否则游戏读档 EACCES 卡加载页 |
| `verify_after_push` | `true` | 推送后设备端 md5 校验 |
| `stop_game_before_push` | `true` | **必须开启**，否则运行中游戏会写盘覆盖修改 |
| `relaunch_after_push` | `true` | 回传后冷启动游戏重新读档 |
| `push_only_modified` | `true` | 只回传被修改过的文件 |
| `wake_before_action` / `connect_before_action` | `true` | 操作前唤醒头显 / 自动 `adb connect` |
| `export_root` / `backup_root` | `exports` / `backups` | 导出与备份根目录 |
| `items_catalog` / `presets_file` | `items_catalog.json` / `presets.json` | 物品目录 / 预设收藏文件 |
| `venture_root` | `""` | Venture 数据根目录；留空自动查 `%LOCALAPPDATA%\Venture` 与 Linux 的 XDG / Flatpak 位置 |
| `venture_auto_detect` | `true` | 启动时自动查找并载入 Venture 存档（优先于上一次导出快照） |
| `venture_backup_on_save` | `true` | 写回 Venture 存档前自动备份原文件到 `backup_root/venture_<时间戳>/` |

## 9. 生效原理、风险与回滚

1. 游戏**只在启动时读档**；运行中界面数值来自内存，跑图、结算会把内存旧值
   写回文件。所以回传默认强制停止游戏并冷启动，请勿关闭底部
   「回传前停止游戏并冷启动」开关。
2. 回传前自动备份，出问题点「恢复最近备份」回滚。**仍请自行留存完整原档**。
3. 物品请使用目录中标记为「已验证」的引用；编造不存在的 `extref` 可能导致
   货位读不出来或读档失败。复杂枪械建议用「复制槽位」后再换物品。
4. 游戏运行中购买、跑图、退出主菜单都会再次写盘，数值会随游戏行为变化。
5. 修改存档有风险，本工具按「现状」提供，不保证适配游戏的未来版本。

## 10. 常见问题

| 现象 | 处理 |
|---|---|
| 改完没效果 | 确认底部「回传前停止游戏并冷启动」已开启；游戏只在启动读档 |
| 导出报 `Not a directory` 或只出现 `footlo` 空目录 | 使用 v0.2.0 及以上版本；该版让 adb 不接触本地路径，中文路径与中文文件名均正常 |
| 游戏卡在加载页 | 多半是权限问题，确认 `chmod_after_push=true`；用「恢复最近备份」回滚 |
| 头显待机后失联 | 点「唤醒头显」或「扫描局域网」；重启头显后需 USB 重新部署无线调试 |
| GUI 打不开 | Python 必须自带 tkinter；便携版直接用 `启动存档编辑器.bat` |
| 商店 / 仓库改了又没了 | 重新导出的是设备上的新存档；用预设「一键应用」或开启自动应用 |
| 包名与默认不同 | 点「自动探测」选中设备上的真实包名并「保存配置」，见 [§6](#6-包名与兼容策略) |
| 找不到 Venture 存档 | 确认在 Venture 里装过并至少运行过一次游戏；或 `config.json` 填 `venture_root`；或用「手动选择存档目录」选到 `footlong.base` |
| Venture 里改了没生效 | 游戏只在启动时读档：先在 Venture 里退出游戏再「保存到 Venture 存档」，然后重新启动游戏 |
| 手选的目录提示没有存档 | 选到 `footlong.base` 或它的上一层（`Profile0` / `SaveData`）；程序也会自己往下找，但视频/图片等杂物目录里没有 `*.json.gz` |

## 11. 开发与验证

```bash
py -3.10 test_core.py             # 仅单元测试（不碰设备）
py -3.10 test_core.py --device    # 单元 + 真机只读往返（回传原样内容）
```

**验证记录（v0.2.0）**

- 单元测试 **81/81 通过**：含 gzip/JSON 往返、字段读写、商店与仓库编辑、
  预设 / 收藏、中文路径导出 7 项回归、默认包名约束 6 项回归（含反例）。
  仓库不含任何玩家存档；在没有本地导出时，测试会自动生成一份**不含玩家数据
  的合成存档夹具**，因此 `git clone` 后可直接跑通，无需先连接设备。
- GUI 真实启动：7 个标签页、预设 1+1、收藏列表、默认包名下拉框只列官方包名；
  「自动探测」通用枚举设备包名的能力由假 adb 断言覆盖。
- 真机：商店价格与出售物品、仓库新增物件均经「停游戏 → 回传 → 冷启动 →
  重新导出」验证被游戏读档接受，验证后按原始字节恢复设备存档。
- 发布包：`testzip` OK、1959 条目 / 约 17.3 MB；脱敏扫描 0 命中
  （无设备序列号、局域网地址、本机路径、玩家存档）；全新中文目录解压后
  用自带 runtime 启动成功。

> VR 渲染层无法截屏，商店与仓库在游戏界面里的实际显示需在头显内肉眼确认；
> 文件层、读档层与冷启动回读均已验证。

**Venture 模拟器支持（v0.3.0 新增，社区贡献）**

- 单元测试 **98/98 通过**：新增 17 项 Venture 回归——目录自动发现（官方包名
  优先、最近写入优先、无关目录不入结果）、手动选路径在 `footlong.base` /
  槽位 / `SaveData` / 账号目录四层都能定位、写回生效、保存前备份是改动前原档、
  不影响其他账号的存档、目录不存在时报错可读。全部用仿真目录树覆盖，
  不依赖本机是否装了 Venture。
- GUI：见「存档来源」栏在真实 Venture 存档上启动即自动载入（17 个文件），
  按钮随来源切换文案；用临时副本走完「改货币 → 保存到 Venture 存档 →
  回读校验 → 恢复最近备份」全链路。
- 布局：默认 1400×940 下「快捷编辑」页三行说明文字不必滚动即可看全；窗口缩小时
  该页支持滚轮滚动（内容宽度跟随画布），底部「操作」栏与日志区改为从底部占位，
  不再被挤掉。
- **测试范围说明**：本轮只验证了 **Venture 模拟器存档**的查找、读取与写回；
  原「连接头显 / adb 导出与回传」这条链路本轮**未做真机测试**。相关函数
  （`export_save` / `import_save`）未改动，仅 GUI 载入时多记一个「来源」标记
  用于切换「②」按钮文案与保存目标。

详见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [DISCLAIMER.md](DISCLAIMER.md)。

## 12. 文件说明

```
├── README.md                 本文件（项目说明 / 使用方法 / 版本信息）
├── CHANGELOG.md              更新日志
├── VERSION.txt               当前版本摘要
├── DISCLAIMER.md             免责声明、包名政策、AI 生成辅助声明
├── CONTRIBUTING.md           贡献指南与内容边界
├── LICENSE                   MIT License（仅覆盖本仓库原创内容）
├── .gitignore                排除玩家存档、运行产物与本地配置
├── config.json               脱敏配置模板（默认官方包名）
├── presets.json              示例预设与收藏（不含任何用户数据）
├── items_catalog.json        666 条物品（651 条引用已验证）
├── save_core.py              核心：adb / 导出回传 / gzip / 字段 / 预设 / 仓库
├── h3vr2_save_editor.py      tkinter GUI 主程序
├── test_core.py              单元 + 真机测试
├── run_editor.bat            Windows 源码启动脚本
└── docs/
    ├── index.html            GitHub Pages 项目页
    └── .nojekyll             跳过 Jekyll 构建
```

## 13. 声明

- **AI 生成辅助**：本项目使用 AI 生成辅助，详见 [DISCLAIMER.md §1](DISCLAIMER.md#1-关于-ai-生成辅助明确标注)。
- **非官方**：与游戏开发者、发行方、平台方无关联；游戏名称与商标归各自权利人。
- **包名政策**：默认且仅列出官方包名 `com.rustltd.h3vr2`；不预置、不推荐、
  不宣传任何改包名分发的第三方版本或付费汉化，见 [§6](#6-包名与兼容策略)。
- **使用范围**：仅自己的单机离线存档；不修改游戏本体，不绕过授权或内购，
  不收集或上传任何数据。
- **风险**：按「现状」提供，操作前请自行备份；完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。
- **许可**：本仓库原创代码与文档为 [MIT](LICENSE)；便携版内附带的
  Python 3.10.5 与 adb 分别遵循 PSF License / Apache-2.0。

---

*最后更新：2026-11-17 · v0.3.0*
