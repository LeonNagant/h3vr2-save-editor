# 物品表生成器（item_catalog_builder.py）

一个独立小工具：从你手里的**游戏安装包 / 资源文件**里读取物品定义，生成或增量更新
存档修改器用的 `items_catalog.json`。当游戏更新、加入新枪新物件时，用它就能让
修改器识别并编辑新物品，不必等作者手动更新。

## 它解决什么问题

存档修改器的「商店编辑 / 仓库编辑」靠 `items_catalog.json` 列出可选物品。
游戏一更新，新物品不在表里就选不到。本工具直接从游戏资源里把物品定义读出来：

1. 找到资源包 `footlong.base.hdog`（在安装包里，或已装好的游戏数据目录）。
2. 读 HDOG 容器索引，取出第 0 块 Unity 根包（约 27–36 MB，无需解包整个 2.5 GB）。
3. 用 UnityPy 解析 `ItemSpawnerDef`，得到物品名、类型、分类文件夹、AssetKey。
4. 扫描根包内的 `extref://` 字符串，拿到每个物品在存档里**真实使用的引用**
   （注意有的物品在 `/Item/` 命名空间，不能一律套同一个前缀）。
5. 与现有 `items_catalog.json` 合并：已有物品保留原样（含真机验证过的引用），
   只追加新物品。

## 依赖

- Python 3.10 或更高。
- UnityPy（**仅本工具需要**；存档修改器本身零 pip 依赖）：

```bat
py -3.10 -m pip install UnityPy
```

## 用法

命令行：

```bat
:: 增量更新：从安装包读取新物品，合并进现有表
py -3.10 tools\item_catalog_builder.py "你的安装包.zip" ^
    --merge "items_catalog.json" -o "items_catalog_new.json"

:: 也可以直接喂 hdog 文件或已解出的 _root_bundle（后者最快）
py -3.10 tools\item_catalog_builder.py "footlong.base.hdog" --merge "items_catalog.json"
py -3.10 tools\item_catalog_builder.py "_root_bundle" --merge "items_catalog.json"

:: 图形界面
py -3.10 tools\item_catalog_builder.py --gui
```

图形界面里依次选择「输入文件」「要合并的现有表（可留空表示从零生成）」「输出文件」，
点「生成物品表」即可，日志框会列出新增了哪些物品。

生成后，把输出的 json 覆盖掉修改器目录里的 `items_catalog.json`，重启修改器即可
在选择物品的弹窗里看到新物品。

## 参数说明

| 参数 | 含义 |
|---|---|
| `src` | 输入：`.zip` 安装包 / `footlong.base.hdog` / 已解出的 `_root_bundle` |
| `--merge` | 现有 `items_catalog.json` 路径；提供则只追加新物品，不改动已验证条目 |
| `-o` / `--out` | 输出 json 路径，默认 `items_catalog_new.json` |
| `--workdir` | 解包临时目录，默认在输入文件同目录的 `_catalog_work/` |
| `--gui` | 启动图形界面 |

## 输出字段

每个物品条目与修改器现有格式一致：`key`（AssetKey）、`en` / `zh`（中英文名）、
`type`（物品类型码）、`hidden`、`category`、`folders`、`ref`（真实引用）、
`ref_alt`、`verified`。如果资源本身是中文版，`_itemName` 会直接作为 `zh`。

## 限制

- 只能读取**资源里已定义的物品**。游戏更新后若新物品不在 ItemSpawnerDef 里，
  工具也读不到。
- `verified` 只表示引用在资源中被扫描到，不等于真机存档已验证；写入前请自行备份存档。
- 本工具不会修改游戏本体，只读取资源文件。
