# -*- coding: utf-8 -*-
"""
H3VR2 存档修改器 —— 核心逻辑（无第三方依赖）

职责：
  1. adb 设备枚举 / 无线调试部署 / 局域网扫描
  2. 存档一键导出（pull）与一键回传（push + chmod + md5 校验 + 自动备份）
  3. gzip(UTF-8 JSON) 存档读写（字节级兼容 .NET GZipStream）
  4. 字段目录与中文说明、快捷字段、批量工具
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ---------------------------------------------------------------- 配置

DEFAULT_CONFIG = {
    "adb_path": "",                       # 空 = 自动查找 adb.exe
    "wifi_ip": "",                        # 留空 = 未配置；点「USB→启用无线调试」或「扫描局域网」自动获取
    "wifi_port": 5555,                    # adb tcpip 端口
    # 默认只列官方包名。设备上若存在其他安装版本，请由用户在界面点「自动探测」
    # 后从设备枚举结果里手动选择；程序不预置、不推荐任何非官方包名。
    "package": "com.rustltd.h3vr2",
    "package_fallbacks": ["com.rustltd.h3vr2"],
    "profile": "Profile0",                # 存档槽：Profile0 = Slot 1
    "save_subdir": "footlong.base",       # 槽位下的存档目录名
    "export_root": "exports",             # 导出根目录（相对本文件）
    "backup_root": "backups",             # 回传前自动备份目录
    "lan_scan_enabled": True,             # 允许扫描局域网 5555 端口
    "lan_subnet": "",                     # 留空 = 运行时自动推断本机局域网网段
    "lan_scan_port": 5555,
    "lan_scan_timeout_ms": 400,
    "auto_backup": True,                  # 回传前先 pull 设备存档作回滚源
    "chmod_after_push": True,             # push 后 chmod 666（必需，否则游戏读档 EACCES）
    "verify_after_push": True,            # push 后 md5 校验
    "wake_before_action": True,           # 操作前唤醒头显（应对闲置待机）
    "connect_before_action": True,        # 网络 serial 操作前自动 adb connect
    "push_only_modified": True,           # 只回传被修改过的文件
    "skip_invalid_files": [],             # 额外跳过的文件名（默认不跳过）
    "stop_game_before_push": True,        # 回传前 am force-stop（必需：运行中游戏会写盘覆盖修改）
    "relaunch_after_push": True,          # 回传后冷启动游戏，使其重新读档
    "items_catalog": "items_catalog.json",# 物品目录（AssetKey / 中文名 / 真实引用）
    "presets_file": "presets.json",       # 预设 / 收藏（可手工编辑，独立于存档）
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    p = path or CONFIG_PATH
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict, path: str | None = None) -> str:
    p = path or CONFIG_PATH
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return p


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def abs_local(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


# ---------------------------------------------------------------- adb 基础

def resolve_adb(cfg: dict) -> str:
    """优先使用本程序自带的 adb，其次系统 PATH，最后按配置项指定的路径。"""
    p = (cfg.get("adb_path") or "").strip().strip('"')
    if p:
        if not os.path.isabs(p):
            p = os.path.join(BASE_DIR, p)
        if os.path.isfile(p):
            return p
    bundled = [
        os.path.join(BASE_DIR, "adb", "adb.exe"),
        os.path.join(BASE_DIR, "adb.exe"),
    ]
    for c in bundled:
        if os.path.isfile(c):
            return c
    w = shutil.which("adb")
    if w:
        return w
    raise FileNotFoundError(
        "未找到 adb.exe：请把 adb.exe 放到本程序的 adb\\ 目录，"
        "或在 config.json 的 adb_path 中填写完整路径")


def _decode(b: bytes) -> str:
    return b.decode("utf-8", "replace").strip()


def _run(cmd: list[str], timeout: int = 60, binary: bool = False) -> dict:
    """binary=True 时 stdout 保留原始字节（用于 exec-out 读取二进制存档）。"""
    kw = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    env = os.environ.copy()
    env["MSYS2_ARG_CONV_EXCL"] = "*"   # 防止 Git Bash/MSYS 把 /sdcard/... 转换掉
    kw["env"] = env
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW，避免弹黑框
    cp = subprocess.run(cmd, **kw)
    return {"stdout": cp.stdout if binary else _decode(cp.stdout),
            "stderr": _decode(cp.stderr), "code": cp.returncode,
            "cmd": " ".join(cmd)}


def run_adb(cfg: dict, args: list[str], serial: str | None = None,
            timeout: int = 60, auto_connect: bool = True,
            binary: bool = False) -> dict:
    adb = resolve_adb(cfg)
    is_tcp = bool(serial and re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", serial))
    if is_tcp and auto_connect and cfg.get("connect_before_action", True):
        _run([adb, "connect", serial], timeout=15)
    cmd = [adb] + (["-s", serial] if serial else []) + list(args)
    return _run(cmd, timeout=timeout, binary=binary)


def list_devices(cfg: dict) -> list[dict]:
    r = run_adb(cfg, ["devices", "-l"], auto_connect=False, timeout=20)
    out = []
    for line in r["stdout"].splitlines():
        line = line.strip()
        if not line or line.startswith("*") or line.startswith("List of"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        info = " ".join(parts[2:])
        m = re.search(r"model:(\S+)", info)
        p = re.search(r"product:(\S+)", info)
        out.append({
            "serial": serial,
            "state": state,
            "model": m.group(1) if m else "",
            "product": p.group(1) if p else "",
            "kind": "tcp" if ":" in serial else "usb",
            "label": ("[无线] " if ":" in serial else "[USB] ") + serial +
                     (("  " + m.group(1)) if m else "") + ("  (" + state + ")" if state != "device" else ""),
        })
    return out


def wake_device(cfg: dict, serial: str) -> dict:
    """KEYCODE_WAKEUP=224，唤醒待机中的头显。"""
    return run_adb(cfg, ["shell", "input", "keyevent", "224"], serial=serial, timeout=20)


def get_device_ip(cfg: dict, serial: str) -> str:
    for cmd in ["ip -f inet addr show wlan0", "ip addr show wlan0"]:
        r = run_adb(cfg, ["shell", cmd], serial=serial, timeout=20)
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", r["stdout"])
        if m:
            return m.group(1)
    r = run_adb(cfg, ["shell", "getprop dhcp.wlan0.ipaddress"], serial=serial, timeout=20)
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", r["stdout"])
    return m.group(1) if m else ""


def connect_wifi(cfg: dict, ip: str | None = None, port: int | None = None) -> dict:
    """连接无线头显。未填 IP 时自动从 USB 已连接的头显读取 Wi-Fi IP。"""
    ip = (ip or cfg.get("wifi_ip") or "").strip()
    port = int(port or cfg.get("wifi_port", 5555))
    if not ip:
        try:
            for d in list_devices(cfg):
                if d["kind"] == "usb" and d["state"] == "device":
                    ip = get_device_ip(cfg, d["serial"])
                    if ip:
                        break
        except Exception:
            pass
    if not ip:
        return {"stdout": "", "cmd": "", "code": 1,
                "stderr": "未设置无线 IP，且未从 USB 设备读到 IP；请点「USB→启用无线调试」或「扫描局域网」，或在界面填写头显 IP"}
    adb = resolve_adb(cfg)
    return _run([adb, "connect", f"{ip}:{port}"], timeout=15)


def enable_wireless(cfg: dict, usb_serial: str, port: int | None = None) -> dict:
    """USB 已连接时：取 IP → adb tcpip → connect → 防止待机断 Wi-Fi。"""
    port = int(port or cfg["wifi_port"])
    ip = get_device_ip(cfg, usb_serial)
    if not ip:
        raise RuntimeError("无法读取头显 Wi-Fi IP，请确认头显已连接 Wi-Fi")
    r = run_adb(cfg, ["tcpip", str(port)], serial=usb_serial, auto_connect=False, timeout=20)
    if "restarting in TCP mode" not in r["stdout"] and r["code"] != 0:
        raise RuntimeError("adb tcpip 失败：" + (r["stderr"] or r["stdout"]))
    c = connect_wifi(cfg, ip, port)
    target = f"{ip}:{port}"
    # 尽量让 Wi-Fi 在待机时保持连接（2 = never）；失败不影响主流程
    run_adb(cfg, ["shell", "settings", "put", "global", "wifi_sleep_policy", "2"],
            serial=target, timeout=20)
    wake_device(cfg, target)
    return {"ip": ip, "port": port, "serial": target, "tcpip": r, "connect": c}


def _guess_lan_subnet() -> str:
    """按本机默认出口 IP 推断局域网前三段（UDP connect 不发包，仅取路由结果）。"""
    ip = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("223.5.5.5", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        pass
    if not ip or ip.startswith("127."):
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = ""
    parts = ip.split(".")
    return ".".join(parts[:3]) if len(parts) == 4 else ""


def scan_lan(cfg: dict, subnet: str | None = None, progress=None) -> list[str]:
    """并发探测网段内开放 5555 端口的主机；未配置网段时自动推断。"""
    subnet = (subnet or cfg.get("lan_subnet") or _guess_lan_subnet()).strip()
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$", subnet):
        raise RuntimeError("无法确定局域网网段；请在 config.json 的 lan_subnet 中填写本机局域网网段的前三段")
    port = int(cfg.get("lan_scan_port", 5555))
    timeout = max(100, int(cfg.get("lan_scan_timeout_ms", 400))) / 1000.0
    ips = [f"{subnet}.{i}" for i in range(1, 255)]

    def probe(ip):
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect((ip, port))
            return ip
        except Exception:
            return None
        finally:
            s.close()

    hits = []
    with ThreadPoolExecutor(max_workers=180) as ex:
        for i, res in enumerate(ex.map(probe, ips)):
            if res:
                hits.append(res)
            if progress and i % 40 == 0:
                progress(i + 1, len(ips))
    if progress:
        progress(len(ips), len(ips))
    return hits


# ---------------------------------------------------------------- 存档路径

DATA_ROOT = "/sdcard/Android/data"


def remote_save_root(pkg: str) -> str:
    return f"{DATA_ROOT}/{pkg}/files/SaveData"


def remote_save_path(cfg: dict, pkg: str | None = None, profile: str | None = None) -> str:
    pkg = pkg or cfg["package"]
    profile = profile or cfg["profile"]
    return f"{remote_save_root(pkg)}/{profile}/{cfg['save_subdir']}"


def discover_packages(cfg: dict, serial: str) -> list[str]:
    """扫描设备上所有 H3VR2 包名，按存档最近写入时间排序（活跃存档优先）。

    用一条 adb shell 命令批量检查各包的槽位与存档文件时间，减少来回等待。
    结果完全来自设备目录枚举，程序不预置任何非官方包名；只在用户点击
    「自动探测」按钮时展示，由用户手动选中后才会写入配置。
    """
    r = run_adb(cfg, ["shell", f"ls {DATA_ROOT}"], serial=serial, timeout=25)
    names = []
    for line in r["stdout"].splitlines():
        n = line.strip()
        if not n or "/" in n or ":" in n:
            continue
        if "h3vr2" in n.lower() or "rustltd" in n.lower():
            names.append(n)
    if not names:
        return list(cfg.get("package_fallbacks", []))
    cmds = []
    for n in names:
        root = remote_save_root(n)
        path = (f"{root}/{cfg.get('profile', 'Profile0')}/"
                f"{cfg.get('save_subdir', 'footlong.base')}")
        cmds.append(f"echo ==={n}; ls {root} 2>/dev/null; stat -c %Y {path}/*.json.gz 2>/dev/null")
    rr = run_adb(cfg, ["shell", " ; ".join(cmds)], serial=serial, timeout=40)
    seg: dict[str, dict] = {}
    cur = ""
    for line in rr["stdout"].splitlines():
        line = line.strip()
        if line.startswith("==="):
            cur = line[3:].strip()
            seg[cur] = {"has_profile": False, "ts": []}
        elif cur:
            if "Profile" in line:
                seg[cur]["has_profile"] = True
            seg[cur]["ts"].extend(int(x) for x in re.findall(r"\b\d{9,12}\b", line))
    valid = [n for n in names if seg.get(n, {}).get("has_profile")]
    if not valid:
        valid = names
    valid.sort(key=lambda n: max(seg.get(n, {}).get("ts") or [0]), reverse=True)
    return valid


def discover_profiles(cfg: dict, serial: str, pkg: str) -> list[str]:
    r = run_adb(cfg, ["shell", f"ls {remote_save_root(pkg)} 2>/dev/null"],
                serial=serial, timeout=20)
    out = []
    for line in r["stdout"].splitlines():
        n = line.strip()
        if n.startswith("Profile") and "/" not in n:
            out.append(n)
    return sorted(out) or [cfg["profile"]]


def resolve_package(cfg: dict, serial: str, pkg: str | None = None) -> str:
    """确定本次操作的目标包名：显式指定 > 配置里的包名（默认官方包名）。

    只有配置留空时才向设备探测。程序不会在用户未操作的情况下把目标静默切换成
    设备上的其他安装版本；需要切换时由用户点「自动探测」并手动选择。
    """
    if pkg:
        return pkg
    cur = (cfg.get("package") or "").strip()
    if cur:
        return cur
    try:
        found = discover_packages(cfg, serial)
    except Exception:
        return cur
    return found[0] if found else cur


# ---------------------------------------------------------------- 导出 / 回传

def _names_from_ls(out: str) -> list[str]:
    """解析 `adb shell ls -1 -p` 的输出，只留普通文件名（排除子目录/表头）。"""
    names = []
    for line in (out or "").splitlines():
        n = line.strip()
        if (not n or n in (".", "..") or n.startswith("total ")
                or "/" in n or n.endswith("/")):
            continue
        names.append(n)
    return names


def export_save(cfg: dict, serial: str, dest_parent: str | None = None,
                pkg: str | None = None, profile: str | None = None,
                log=print) -> dict:
    """一键导出：读设备文件字节 → Python 写盘到 exports/<时间戳>/footlong.base。

    自带的 adb 1.0.41(v37) 在 Windows 上处理**非 ASCII 本地路径**有缺陷：
    整目录 `adb pull <remote_dir> <local_dir>` 会按字节数截断目标目录名
    （footlong.base → footlo/footlong），报 Not a directory；中文字符更多时，
    连单文件 `adb pull` 也会报 No such file or directory。因此这里完全不让 adb
    接触本地路径：`exec-out cat <remote_file>` 取原始字节，由 Python 写文件；
    只有极老 adb 不支持 exec-out 时才回退到单文件 pull（本地路径为 ASCII 时可用）。
    """
    if cfg.get("wake_before_action", True):
        wake_device(cfg, serial)
    pkg = resolve_package(cfg, serial, pkg)
    remote = remote_save_path(cfg, pkg, profile)
    chk = run_adb(cfg, ["shell", f"ls -1 -p {remote}"], serial=serial, timeout=25)
    if "No such file" in (chk["stdout"] + chk["stderr"]) or not chk["stdout"].strip():
        # 个别设备的 ls 不支持 -p，退回普通 ls
        chk = run_adb(cfg, ["shell", f"ls {remote}"], serial=serial, timeout=25)
    if "No such file" in (chk["stdout"] + chk["stderr"]) or not chk["stdout"].strip():
        raise RuntimeError(f"设备上找不到存档目录：{remote}\n{chk['stderr']}")
    names = _names_from_ls(chk["stdout"])
    if not names:
        raise RuntimeError(f"设备存档目录为空：{remote}")
    tag = now_tag()
    dest_parent = dest_parent or os.path.join(BASE_DIR, cfg["export_root"], tag)
    local = os.path.join(dest_parent, cfg["save_subdir"])
    os.makedirs(local, exist_ok=True)   # 由 Python 建目录，不交给 adb（中文路径安全）

    msgs = []
    for name in names:
        rp, lp = f"{remote}/{name}", os.path.join(local, name)
        # 主路径：adb 只处理设备端命令，输出字节由 Python 落到任意 Unicode 路径
        r = run_adb(cfg, ["exec-out", f'cat "{rp}"'], serial=serial,
                    auto_connect=False, timeout=90, binary=True)
        err = r["stderr"] or ""
        if r["code"] == 0 and "error" not in err.lower():
            with open(lp, "wb") as f:
                f.write(r["stdout"])
            msgs.append(f"{name}: exec-out {len(r['stdout'])} B")
            continue
        # 回退：老版本 adb 没有 exec-out（本地路径为 ASCII 时可靠）
        p = run_adb(cfg, ["pull", rp, lp], serial=serial,
                    auto_connect=False, timeout=90)
        out = ((p["stdout"] if isinstance(p["stdout"], str) else "")
               + "\n" + (p["stderr"] or "")).strip()
        if p["code"] != 0 or "adb: error" in out.lower() or not os.path.isfile(lp):
            raise RuntimeError(
                f"导出失败（{name}）：exec-out={err.strip()}；pull={out}\n"
                f"设备：{rp}\n本地：{lp}")
        msgs.append(f"{name}: pull {os.path.getsize(lp)} B")
    files = sorted(glob.glob(os.path.join(local, "*.json.gz")))
    if not files:
        raise RuntimeError("导出失败，没有拉到任何 json.gz：\n" + "\n".join(msgs[-5:]))
    log(f"导出完成：{len(files)} 个存档文件（共读取 {len(names)} 个）→ {local}")
    raw = {"code": 0, "stdout": "\n".join(msgs), "stderr": "",
           "cmd": "adb exec-out cat (字节流 → Python 写盘，规避中文路径缺陷)"}
    return {"local_dir": local, "remote": remote, "files": files,
            "tag": tag, "raw": raw, "count": len(files)}


def import_save(cfg: dict, serial: str, local_dir: str,
                only_files: list[str] | None = None,
                pkg: str | None = None, profile: str | None = None,
                log=print) -> dict:
    """一键回传：停游戏 → 自动备份 → 逐文件 push → chmod 666 → md5 校验 → 冷启动读档。

    游戏运行中只在启动时读档，且结算/跑图会把内存旧值写回文件；
    因此必须先 am force-stop，push 完成后再重新启动游戏，改动才会生效。
    """
    if cfg.get("wake_before_action", True):
        wake_device(cfg, serial)
    pkg = resolve_package(cfg, serial, pkg)
    remote = remote_save_path(cfg, pkg, profile)
    tag = now_tag()

    stopped = False
    if cfg.get("stop_game_before_push", True):
        r = run_adb(cfg, ["shell", "am", "force-stop", pkg], serial=serial, timeout=30)
        stopped = r["code"] == 0
        log(("已停止游戏进程 " + pkg + "（避免运行中写盘覆盖修改）") if stopped
            else ("停止游戏失败：" + (r["stderr"] or r["stdout"])))

    backup_dir = None
    if cfg.get("auto_backup", True):
        parent = os.path.join(BASE_DIR, cfg["backup_root"], tag)
        b = export_save(cfg, serial, dest_parent=parent, pkg=pkg, profile=profile, log=log)
        backup_dir = b["local_dir"]
        log(f"已备份设备原存档：{backup_dir}")

    files = only_files or sorted(glob.glob(os.path.join(local_dir, "*.json.gz")))
    skip = set(cfg.get("skip_invalid_files", []))
    files = [f for f in files if os.path.basename(f) not in skip]
    if not files:
        raise RuntimeError("没有可回传的存档文件")

    pushed = []
    for f in files:
        name = os.path.basename(f)
        r = run_adb(cfg, ["push", os.path.abspath(f), f"{remote}/{name}"],
                    serial=serial, timeout=90)
        out = r["stdout"] + r["stderr"]
        if r["code"] != 0 or "error" in out.lower():
            raise RuntimeError(f"推送失败 {name}：{out}")
        pushed.append(name)
        log(f"  push {name} ({os.path.getsize(f)} B)")

    if cfg.get("chmod_after_push", True):
        r = run_adb(cfg, ["shell", f"chmod 666 {remote}/*.json.gz"],
                    serial=serial, timeout=30)
        log("chmod 666 完成" if r["code"] == 0 else "chmod 警告：" + r["stderr"])

    verify = None
    if cfg.get("verify_after_push", True):
        r = run_adb(cfg, ["shell", f"md5sum {remote}/*.json.gz"],
                    serial=serial, timeout=40)
        remote_md5 = {}
        for line in (r["stdout"] or "").splitlines():
            m = re.match(r"^([0-9a-fA-F]{32})\s+\S+/([^/\s]+)$", line.strip())
            if m:
                remote_md5[m.group(2)] = m.group(1).lower()
        local_md5 = {os.path.basename(f): md5_file(f) for f in files}
        bad = [n for n, h in local_md5.items() if remote_md5.get(n) != h]
        verify = {"checked": len(local_md5), "matched": len(local_md5) - len(bad), "bad": bad}
        if bad:
            raise RuntimeError("md5 校验不一致：" + ", ".join(bad))
        log(f"md5 校验通过（{len(local_md5)} 个文件）")

    relaunched = False
    if cfg.get("relaunch_after_push", True):
        r = run_adb(cfg, ["shell", "monkey", "-p", pkg,
                          "-c", "android.intent.category.LAUNCHER", "1"],
                    serial=serial, timeout=40)
        relaunched = launch_confirmed(r)
        log("已冷启动游戏（读档生效）" if relaunched
            else "冷启动未确认：" + (r["stdout"] + r["stderr"])[:200])

    return {"pushed": pushed, "remote": remote, "backup_dir": backup_dir,
            "verify": verify, "stopped": stopped, "relaunched": relaunched}


def launch_confirmed(r: dict) -> bool:
    """判断 monkey 冷启动是否真的注入成功（adb 输出形如 'Events injected: 1'）。"""
    out = (r.get("stdout", "") + r.get("stderr", "")).lower()
    return r.get("code") == 0 and ("events injected" in out or "injected: 1" in out)


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- gzip JSON

# 原存档头：1f8b 08 00 00000000 00 03（FLG=0, mtime=0, XFL=0, OS=3 / Unix）
_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"


def gzip_bytes(data: bytes) -> bytes:
    """生成与 .NET GZipStream 一致的 gzip（无文件名、mtime=0）。"""
    co = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = co.compress(data) + co.flush()
    return _GZIP_HEADER + body + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF,
                                              len(data) & 0xFFFFFFFF)


def load_save(local_dir: str) -> dict:
    """{文件名: JSON 对象}，按文件名排序。"""
    data = {}
    for p in sorted(glob.glob(os.path.join(local_dir, "*.json.gz"))):
        with open(p, "rb") as f:
            raw = f.read()
        data[os.path.basename(p)] = json.loads(gzip.decompress(raw).decode("utf-8"))
    return data


def write_save(local_dir: str, data: dict, only: set[str] | list[str] | None = None) -> list[str]:
    """把内存中的 JSON 写回本地存档目录（紧凑 UTF-8 JSON + 标准 gzip）。"""
    only = set(only) if only else None
    written = []
    for name, obj in data.items():
        if only is not None and name not in only:
            continue
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(local_dir, name), "wb") as f:
            f.write(gzip_bytes(txt.encode("utf-8")))
        written.append(name)
    return written


def copy_save(src_dir: str, dst_dir: str) -> str:
    os.makedirs(dst_dir, exist_ok=True)
    for p in glob.glob(os.path.join(src_dir, "*.json.gz")):
        shutil.copy2(p, os.path.join(dst_dir, os.path.basename(p)))
    return dst_dir


# ---------------------------------------------------------------- 字段目录

FIELD_DESC = {
    "Version": "存档结构版本号（保持 0，不建议改）",
    "Data": "该文件的数据主体",
    "Money": "通用货币，用于商店购买与基地升级",
    "Meat": "资源：肉（回收/采集、合成与工单）",
    "Metal": "资源：金属",
    "Mustard": "资源：芥末",
    "Experience": "经验值 XP；等级由 XP 换算，存档不直接存 Level",
    "HealthSaved": "是否保存了枢纽内血量状态",
    "CurrentHealth": "玩家当前血量（满值 100）",
    "Wearables": "身上穿戴物列表",
    "Pockets": "口袋内物品列表",
    "HoldingInHandLeft": "左手持有物",
    "HoldingInHandRight": "右手持有物",
    "TickTimer": "状态效果计时器（运行时相位，非难度数值）",
    "StatusEffects": "生效中的状态效果列表",
    "InventoryPages": "库存页列表（每页一个 12×8 网格）",
    "DumpQueue": "回收/转存队列",
    "gridSize": "网格尺寸 [宽, 高]",
    "items": "网格内的槽位项列表",
    "contents": "槽位内容（物件 + 附件绑定 + 自身网格）",
    "Objects": "该槽位内的实际物件列表",
    "ItemDef": "物品资产 ID（extref://footlong.base/<AssetKey>，指向 OBB 内定义）",
    "InstanceSeed": "物品实例随机种子（保持唯一，勿重复）",
    "Transform": "物品相对位置/旋转",
    "Position": "3D 位置 [x,y,z]",
    "Rotation": "四元数 [x,y,z,w]",
    "Components": "物品组件状态（枪机/弹匣/瞄具/口袋/箱子等）",
    "Id": "组件类型标识",
    "State": "组件状态数据",
    "Affixments": "复合物品绑定关系（如枪与已插入弹匣）",
    "ObjectIndices": "绑定的物件索引对",
    "IsMultiGrab": "是否多点抓取",
    "rectMin": "槽位在网格中的左上角坐标 [x,y]",
    "rectSize": "槽位占格尺寸 [w,h]",
    "position": "3D 摆放位置（UI 展示用）",
    "rotation": "3D 摆放旋转（四元数）",
    "Barrels": "枪管/弹膛状态数组",
    "Chamber": "弹膛",
    "LoadedRound": "膛内子弹 ID；null = 空膛",
    "Fired": "该弹是否已击发",
    "Bolts": "枪机状态数组",
    "PosNrm": "归一化位置",
    "VelNrm": "归一化速度",
    "AccelNrm": "归一化加速度",
    "RoundsOnBreeches": "枪机面上的子弹",
    "RoundsOnBreechesFired": "枪机面子弹的击发标记",
    "FCG": "击发控制组（Fire Control Group）机械状态",
    "SelectorPosNrm": "快慢机位置（归一化）",
    "TriggerPosNrm": "扳机位置",
    "HammerPosNrm": "击锤位置",
    "DisconnectorPosNrm": "阻铁分离器位置",
    "SearPosNrm": "阻铁位置",
    "AutoSearPosNrm": "自动阻铁位置",
    "OpenBoltSearPosNrm": "开膛阻铁位置",
    "SearDisconnectorPosNrm": "阻铁分离器联动位置",
    "HammerCanFire": "击锤可击发标记",
    "MaxReachedHammerPos": "击锤到达的最大位置",
    "DoubleActionHammerDisconnected": "双动击锤脱开标记",
    "StrikerDisconnected": "击针脱开标记",
    "LoadedRounds": "弹匣内的子弹列表（每项 ItemDef + Fired）",
    "ConnectedCompoundMagazineIndices": "并联弹匣索引",
    "MagazineObjectIndex": "已装弹匣对应的物件索引",
    "CompoundGroupIndex": "复合弹匣组索引",
    "CompoundMagazineIndex": "复合弹匣索引",
    "AttachedObjects": "挂载的附件列表",
    "Index": "菜单可视状态索引",
    "ReticleIndex": "瞄准镜分划样式索引",
    "ColorIndex": "分划颜色索引",
    "BrightnessIndex": "分划亮度档位",
    "Windage": "风偏调节量",
    "Elevation": "高程调节量",
    "BaseZeroState": "归零基准状态",
    "BaseZeroRange": "归零距离",
    "BaseZeroFirearmObjectIndex": "归零武器物件索引",
    "BaseZeroFirearmComponentIndex": "归零武器组件索引",
    "BaseZeroRound": "归零用弹种",
    "contentsQuantity": "商店箱内物品数量",
    "purchased": "商店箱是否已购买",
    "StoredItems": "CHIP 模块内存储的物品 ID 列表",
    "StoredApps": "CHIP 模块内存储的应用列表",
    "PlaytimeSeconds": "游玩时长（秒）",
    "Kills": "按敌人档案统计的击杀数",
    "GameModes": "各游戏模式累计时长",
    "ShotsFired": "累计开火次数",
    "Deaths": "累计死亡次数",
    "DamageTaken": "累计承受伤害",
    "TotalCurrencyCollected": "累计获得的四类资源",
    "FacilityCampaignStats": "设施战役模式统计",
    "FacilityFreePlayStats": "设施自由模式统计",
    "DeployCount": "部署次数",
    "ExtractCount": "成功撤离次数",
    "DeathCount": "死亡次数",
    "ItemsExtractedCount": "带出物品件数",
    "ItemsExtractedValue": "带出物品总价值",
    "SecurityAlertsTriggeredCount": "触发安保警报次数",
    "StealthExtractCount": "潜行撤离次数",
    "VisitCount": "访问次数",
    "Levels": "按关卡分组的统计",
    "Biomes": "按生态区分组的统计",
    "Runs": "设施跑图历史记录",
    "date": "跑图时间（ISO8601）",
    "depthBiome": "生态区索引（0 = 地堡）",
    "depthLevel": "深度层",
    "died": "本局是否死亡",
    "score": "本局得分",
    "Scores": "挑战最高分表",
    "Medals": "挑战奖牌档位（0/1/2）",
    "Activities": "通知/活动记录列表",
    "Timestamp": "时间戳",
    "Title": "通知标题",
    "Description": "通知描述 / 教程名",
    "Type": "记录类型",
    "Seen": "是否已读",
    "Dismissed": "是否已关闭",
    "ID": "记录 ID",
    "NAME": "记录名称",
    "OnDismissed": "关闭回调（通常为 null）",
    "CompletedLessons": "已完成教程列表",
    "ScannedScannables": "已扫描的设备 ID 列表",
    "Flags": "剧情/解锁标志表（值 1/2 为阶段）",
    "UploadedItems": "已上传到 VendOS 的物品 ID",
    "storeStates": "各商店的货位状态",
    "boxes": "商店货位列表",
    "item": "货位物品 ID",
    "sectionID": "货位分区",
    "price": "售价（可直接改低）",
    "objectStates": "枢纽场景散落物品状态",
    "EquippedCosmetics": "已装备外观列表",
    "Slot": "外观槽位（Gloves / Outfit）",
    "GloveHand": "手套手别",
    "CompletedObjectives": "已完成的工单目标",
    "UnlockedObjectives": "已解锁未完成目标",
    "ObjectiveProgress": "工单目标进度计数",
    "UnlockedWorkOrderGroups": "工单组解锁状态（1 解锁 / -1 未解锁）",
    "SeenWorkOrdersRefs": "已见工单",
    "CompletedWorkOrdersRefs": "已完成工单",
    "UnlockedWorkOrdersRefs": "已解锁工单",
    "RunningWorkOrdersRefs": "进行中工单",
    "TransientWorkOrdersProcTemplate": "临时工单生成模板",
    "template": "工单模板 ID",
    "identity": "NPC 身份 ID",
    "PlayerState": "枢纽玩家状态",
    "Settings": "设置表（含难度倍率）",
    "smoothLocomotion": "平滑移动开关",
    "teleportMode": "传送模式档位",
    "turnMode": "转向模式档位",
    "turnIncrement": "分段转向角度（度）",
    "crouching": "允许蹲下",
    "crouchToggle": "蹲下为切换式",
    "smoothMoveMode": "平滑移动模式档位",
    "stickOrientation": "摇杆方向基准档位",
    "vignette": "移动暗角",
    "smoothTurnSpeed": "平滑转向速度",
    "turnAnalog": "摇杆连续转向（Analog Turning）",
    "jumping": "允许跳跃",
    "sprintToggle": "疾跑为切换式",
    "seatedMode": "坐姿模式",
    "calibratedHeight": "校准身高（米）",
    "controllerFiltering": "控制器抖动过滤档位",
    "enableTwoHandFiltering": "双手持握过滤",
    "audioLanguage": "语音语言档位",
    "audioMaster": "主音量",
    "audioDialog": "对白音量",
    "audioMusic": "音乐音量",
    "audioSoundEffects": "音效音量",
    "distanceunit": "距离单位档位",
    "massunit": "质量单位档位",
    "barrellengthunit": "枪管长度单位档位",
    "ballisticvelocityunit": "弹道速度单位档位",
    "ballisticmassunit": "弹头质量单位档位",
    "ballisticenergyunit": "弹道动能单位档位",
    "bullettrails": "弹道曳光",
    "showhiddenitemsinspawner": "生成器中显示隐藏物品",
    "resolutionscale": "渲染分辨率档位",
    "ffr": "固定注视点渲染",
    "gore": "血腥效果档位",
    "showmusicintensity": "显示音乐强度",
    "playerDamage": "【难度】玩家造成的伤害倍率（1 = 标准）",
    "npcDamage": "【难度】NPC 对玩家造成的伤害倍率（1 = 标准，调小可降难度）",
    "powerupDuration": "【难度】强化道具持续时间倍率（1 = 标准）",
    "grid0": "背包网格 0",
    "grid1": "背包网格 1",
    "targetAlignPos": "口袋对齐位置",
    "targetAlignRot": "口袋对齐旋转",
    "targetAlignScl": "口袋对齐缩放",
    "spawnLock": "生成锁定",
    "harness": "背带标记",
}

CAUTION_KEYS = {"Version", "InstanceSeed", "ItemDef", "Id", "SectionID", "sectionID",
                "template", "identity", "NAME", "ID", "Type", "Timestamp", "date"}

QUICK_FIELDS = [
    # 只保留存档独有、游戏内设置菜单无法调整的数值。
    # Settings.json.gz 的全部字段（难度倍率 / 音量 / 血腥效果等）都能在游戏设置菜单里改，
    # 需要脚本化修改时请用「全部参数（树）」或「原始 JSON」页编辑 Settings.json.gz。
    ("Economy.json.gz", "Data.Money", "Money", "通用货币", "int"),
    ("Economy.json.gz", "Data.Meat", "Meat", "资源：肉", "int"),
    ("Economy.json.gz", "Data.Metal", "Metal", "资源：金属", "int"),
    ("Economy.json.gz", "Data.Mustard", "Mustard", "资源：芥末", "int"),
    ("Experience.json.gz", "Data.Experience", "Experience", "经验值 XP（等级由 XP 换算）", "int"),
    ("PlayerHubState.json.gz", "Data.PlayerState.CurrentHealth", "CurrentHealth", "枢纽内玩家血量", "float"),
    ("PlayStats.json.gz", "Data.PlaytimeSeconds", "PlaytimeSeconds", "总游玩时长（秒）", "float"),
    ("PlayStats.json.gz", "Data.ShotsFired", "ShotsFired", "累计开火次数", "int"),
    ("PlayStats.json.gz", "Data.Deaths", "Deaths", "累计死亡次数", "int"),
]


def _tokens_from_dot(path: str) -> list[tuple[str, object]]:
    """'Data.Settings.npcDamage' / 'Data.items[3].price' → token 列表。"""
    tokens = []
    for seg in path.split("."):
        m = re.match(r"^([^\[\]]+)((?:\[\d+\])*)$", seg)
        if not m:
            raise ValueError("非法路径：" + path)
        tokens.append(("k", m.group(1)))
        for idx in re.findall(r"\[(\d+)\]", m.group(2)):
            tokens.append(("i", int(idx)))
    return tokens


def get_by_tokens(obj, tokens):
    cur = obj
    for t, v in tokens:
        cur = cur[int(v)] if t == "i" else cur[v]
    return cur


def set_by_tokens(obj, tokens, value):
    cur = obj
    for t, v in tokens[:-1]:
        cur = cur[int(v)] if t == "i" else cur[v]
    t, v = tokens[-1]
    if t == "i":
        cur[int(v)] = value
    else:
        cur[v] = value


def quick_read(data: dict, file: str, dot_path: str):
    if file not in data:
        return None
    try:
        return get_by_tokens(data[file], _tokens_from_dot(dot_path))
    except Exception:
        return None


def quick_write(data: dict, file: str, dot_path: str, value) -> bool:
    if file not in data:
        return False
    try:
        set_by_tokens(data[file], _tokens_from_dot(dot_path), value)
        return True
    except Exception:
        return False


def describe(fname: str, tokens, value) -> tuple[str, bool]:
    """返回 (中文说明, 是否需谨慎)。"""
    last = None
    for t, v in reversed(tokens):
        if t == "k":
            last = v
            break
    key = str(last)
    if key.startswith("extref://"):
        return "引用键：指向 OBB 内的定义（数值为计数 / 进度 / 标志阶段）", True
    if re.search(r"[\u4e00-\u9fff]", key) and key not in FIELD_DESC:
        return "挑战/教程名称（界面文案），值为最高分或奖牌档位", False
    desc = FIELD_DESC.get(key)
    if desc is None:
        desc = "（未注释字段）可直接编辑原始值；数组/对象请在「原始 JSON」页修改"
    return desc, key in CAUTION_KEYS


def build_field_catalog(data: dict, file_filter: str | None = None) -> list[dict]:
    """叶子字段目录：路径 / 类型 / 值 / 中文说明 / 可编辑 / 谨慎标记 / 精确 tokens。"""
    rows = []

    def walk(node, fname, tokens, display):
        if isinstance(node, dict):
            for k, v in node.items():
                t2 = tokens + [("k", k)]
                d2 = f"{display}.{k}" if display else k
                walk(v, fname, t2, d2)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                t2 = tokens + [("i", i)]
                d2 = f"{display}[{i}]"
                walk(v, fname, t2, d2)
        else:
            desc, caution = describe(fname, tokens, node)
            rows.append({
                "file": fname,
                "path": display,
                "tokens": [[t, v] for t, v in tokens],
                "type": type(node).__name__ if node is not None else "null",
                "value": node,
                "desc": desc,
                "editable": True,
                "caution": caution,
            })

    for fname, obj in data.items():
        if file_filter and fname != file_filter:
            continue
        walk(obj, fname, [], "")
    return rows


def parse_value(text: str, old=None):
    """按原类型把输入文本转成值；支持 JSON 字面量。"""
    t = text.strip()
    if isinstance(old, bool):
        if t.lower() in ("true", "1", "yes", "on", "是"):
            return True
        if t.lower() in ("false", "0", "no", "off", "否"):
            return False
        raise ValueError("布尔值请输入 true / false")
    if isinstance(old, int):
        return int(t)
    if isinstance(old, float):
        return float(t)
    if old is None or isinstance(old, str):
        if t.lower() in ("null", "none"):
            return None
        if t.startswith(("[", "{", '"')):
            return json.loads(t)
        return t
    return json.loads(t)


# ---------------------------------------------------------------- 批量工具

def scale_store_prices(data: dict, factor: float) -> int:
    """所有商店货位价格乘以系数；返回改动数量。"""
    n = 0
    st = data.get("Stores.json.gz", {})
    for store in (st.get("Data", {}).get("storeStates", {}) or {}).values():
        for box in store.get("boxes", []) or []:
            if isinstance(box.get("price"), (int, float)):
                box["price"] = max(1, int(round(box["price"] * factor)))
                n += 1
    return n


def fill_magazines(data: dict, capacity: int = 7) -> int:
    """按弹匣内现有第一发子弹为模板，把所有弹匣补到 capacity 发。"""
    inv = data.get("Inventory.json.gz", {})
    pages = inv.get("Data", {}).get("InventoryPages", []) or []
    n = 0
    for page in pages:
        for it in page.get("items", []) or []:
            for o in (it.get("contents", {}) or {}).get("Objects", []) or []:
                for c in o.get("Components", []) or []:
                    if c.get("Id") != "Magazine":
                        continue
                    rounds = (c.get("State", {}) or {}).get("LoadedRounds", []) or []
                    if not rounds:
                        continue
                    template = dict(rounds[0])
                    while len(rounds) < capacity:
                        rounds.append(dict(template))
                        n += 1
    return n


# ---------------------------------------------------------------- 商店 / 物品目录

ITEMS_CATALOG_PATH = os.path.join(BASE_DIR, "items_catalog.json")
_ITEM_CATALOG_CACHE: list[dict] | None = None


def load_item_catalog() -> list[dict]:
    """物品目录：AssetKey / 中英文名 / 游戏内真实引用。文件缺失时返回空列表。"""
    global _ITEM_CATALOG_CACHE
    if _ITEM_CATALOG_CACHE is None:
        try:
            with open(ITEMS_CATALOG_PATH, "r", encoding="utf-8") as f:
                _ITEM_CATALOG_CACHE = json.load(f).get("items", [])
        except Exception:
            _ITEM_CATALOG_CACHE = []
    return _ITEM_CATALOG_CACHE


def asset_key(ref: str) -> str:
    """extref://footlong.base/Item/MapR → MapR"""
    return (ref or "").rstrip("/").rsplit("/", 1)[-1]


def item_by_ref(ref: str) -> dict | None:
    k = asset_key(ref)
    for it in load_item_catalog():
        if it["key"] == k or it.get("ref") == ref or it.get("ref_alt") == ref:
            return it
    return None


def item_label(ref: str) -> str:
    it = item_by_ref(ref)
    return (it.get("zh") or it.get("en") or it["key"]) if it else ""


def store_keys(data: dict) -> list[str]:
    return sorted((data.get("Stores.json.gz", {}).get("Data", {})
                   .get("storeStates", {}) or {}).keys())


def _store_boxes(data: dict, store: str) -> list:
    return (data.get("Stores.json.gz", {}).get("Data", {})
            .get("storeStates", {}).get(store, {}).get("boxes", []) or [])


def list_store_boxes(data: dict, store: str) -> list[dict]:
    out = []
    for i, b in enumerate(_store_boxes(data, store)):
        ref = b.get("item", "")
        it = item_by_ref(ref)
        out.append({
            "index": i, "item": ref, "key": asset_key(ref),
            "zh": (it.get("zh") or it.get("en") or "") if it else "",
            "price": b.get("price"), "sectionID": b.get("sectionID", ""),
            "verified": bool(it and it.get("verified")),
        })
    return out


def get_store_box(data: dict, store: str, idx: int) -> dict | None:
    bs = _store_boxes(data, store)
    return bs[idx] if 0 <= idx < len(bs) else None


def set_store_box(data: dict, store: str, idx: int, *,
                  item: str | None = None, price=None, section: str | None = None) -> bool:
    """改货位：出售物品引用 / 售价 / 分区。返回是否命中该货位。"""
    b = get_store_box(data, store, idx)
    if b is None:
        return False
    if item is not None:
        b["item"] = item
    if price is not None:
        b["price"] = int(price)
    if section is not None:
        b["sectionID"] = section
    return True


def add_store_box(data: dict, store: str, item: str | None = None,
                  price: int = 1, section: str = "basics") -> int:
    st = (data.setdefault("Stores.json.gz", {}).setdefault("Data", {})
          .setdefault("storeStates", {}).setdefault(store, {"boxes": [], "Version": 0}))
    bs = st.setdefault("boxes", [])
    bs.append({"item": item or "extref://footlong.base/Item/MapR",
               "sectionID": section, "price": int(price)})
    return len(bs) - 1


def delete_store_box(data: dict, store: str, idx: int) -> bool:
    bs = _store_boxes(data, store)
    if not 0 <= idx < len(bs):
        return False
    bs.pop(idx)
    return True


def set_all_store_prices(data: dict, price: int, store: str | None = None) -> int:
    n = 0
    for k in ([store] if store else store_keys(data)):
        for b in _store_boxes(data, k):
            b["price"] = int(price)
            n += 1
    return n


def latest_export_dir() -> str | None:
    ds = sorted(glob.glob(os.path.join(BASE_DIR, "exports", "*")))
    for d in reversed(ds):
        if os.path.isdir(os.path.join(d, "footlong.base")):
            return os.path.join(d, "footlong.base")
    return None


# ---------------------------------------------------------------- 预设 / 收藏

USER_DATA_FILE = "presets.json"
USER_DATA_PATH = os.path.join(BASE_DIR, USER_DATA_FILE)
INVENTORY_FILE = "Inventory.json.gz"
STORES_FILE = "Stores.json.gz"


def default_user_data() -> dict:
    """预设与收藏的数据结构（用户可直接编辑 presets.json）。"""
    return {
        "version": 2,
        "settings": {
            "store_auto_preset": "",        # 载入新存档时自动套用的商店预设名，空 = 不自动
            "store_auto_mode": "replace",   # replace = 覆盖当前货位 / append = 追加
            "inventory_auto_preset": "",    # 自动套用的仓库预设名
            "inventory_auto_mode": "append",
            "default_store_price": 1,      # 从收藏一键加入商店时的默认售价
            "default_section": "basics",   # 从收藏一键加入商店时的默认分区
        },
        "store_presets": {},               # {名称: {note, store, boxes:[{item,sectionID,price}]}}
        "inventory_presets": {},           # {名称: {note, items:[{item,size}]}}
        "favorites": [],                   # [物品 extref / AssetKey]
    }


def user_data_path(cfg: dict | None = None) -> str:
    name = (cfg or {}).get("presets_file") or USER_DATA_FILE
    return name if os.path.isabs(name) else os.path.join(BASE_DIR, name)


def load_user_data(path: str | None = None) -> dict:
    """读取预设/收藏；文件缺失或格式损坏时返回默认结构并留一份坏文件副本。"""
    p = path or USER_DATA_PATH
    ud = default_user_data()
    if not os.path.isfile(p):
        return ud
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("presets.json 根节点必须是对象")
        for k, v in raw.items():
            if k == "settings" and isinstance(v, dict):
                ud["settings"].update({a: b for a, b in v.items() if a in ud["settings"]})
            elif k in ("store_presets", "inventory_presets") and isinstance(v, dict):
                ud[k] = v
            elif k == "favorites" and isinstance(v, list):
                ud[k] = [str(x) for x in v if x]
            elif k == "version":
                ud[k] = v
        return ud
    except Exception:
        try:
            shutil.copy2(p, p + ".bad." + now_tag())
        except Exception:
            pass
        return default_user_data()


def save_user_data(ud: dict, path: str | None = None) -> str:
    """原子写入，避免写一半损坏。"""
    p = path or USER_DATA_PATH
    out = dict(ud)
    out["version"] = 2
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def normalize_item_ref(ref: str) -> str:
    """目录里的 AssetKey 或 extref → 游戏内真实引用（前缀不统一，必须按目录还原）。"""
    s = (ref or "").strip()
    if not s:
        return ""
    if s.startswith("extref://"):
        return s
    for it in load_item_catalog():
        if it["key"] == s:
            return it.get("ref") or ("extref://footlong.base/Item/" + s)
    return "extref://footlong.base/Item/" + s


# ---------------------------------------------------------------- 收藏

def favorite_refs(ud: dict) -> list[str]:
    out, seen = [], set()
    for r in (ud.get("favorites") or []):
        r = normalize_item_ref(str(r))
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def is_favorite(ud: dict, ref: str) -> bool:
    k = asset_key(normalize_item_ref(ref))
    return bool(k) and any(asset_key(x) == k for x in favorite_refs(ud))


def toggle_favorite(ud: dict, ref: str) -> bool:
    """切换收藏，返回切换后的状态（True = 已收藏）。"""
    r = normalize_item_ref(ref)
    if not r:
        return False
    favs = favorite_refs(ud)
    k = asset_key(r)
    if any(asset_key(x) == k for x in favs):
        ud["favorites"] = [x for x in favs if asset_key(x) != k]
        return False
    favs.append(r)
    ud["favorites"] = favs
    return True


def set_favorite(ud: dict, ref: str, value: bool) -> bool:
    if bool(value) != is_favorite(ud, ref):
        toggle_favorite(ud, ref)
    return is_favorite(ud, ref)


def favorite_labels(ud: dict) -> list[dict]:
    out = []
    for r in favorite_refs(ud):
        it = item_by_ref(r) or {}
        out.append({"ref": r, "key": asset_key(r),
                    "zh": it.get("zh") or "", "en": it.get("en") or "",
                    "verified": bool(it.get("verified")),
                    "label": "%s  |  %s  |  %s" %
                             (it.get("zh") or "—", it.get("en") or "—", asset_key(r))})
    return out


# ---------------------------------------------------------------- 商店预设

def store_preset_names(ud: dict) -> list[str]:
    return sorted((ud.get("store_presets") or {}).keys())


def get_store_preset(ud: dict, name: str) -> dict | None:
    p = (ud.get("store_presets") or {}).get(name)
    return p if isinstance(p, dict) else None


def save_store_preset(ud: dict, name: str, data: dict, store: str, note: str = "") -> int:
    """把当前商店的全部货位（含改过的物品/价格/分区）保存成预设。"""
    boxes = list_store_boxes(data, store)
    ud.setdefault("store_presets", {})[name] = {
        "note": note or "", "store": store,
        "boxes": [{"item": b["item"], "sectionID": b["sectionID"],
                   "price": b["price"]} for b in boxes],
    }
    return len(boxes)


def apply_store_preset(data: dict, store: str, preset: dict, mode: str = "replace") -> int:
    """replace = 清空后按预设重建；append = 把预设货位追加到末尾。"""
    if not isinstance(preset, dict):
        return 0
    st = (data.setdefault(STORES_FILE, {}).setdefault("Data", {})
          .setdefault("storeStates", {})
          .setdefault(store, {"boxes": [], "Version": 0}))
    cur = st.setdefault("boxes", [])
    if mode == "replace":
        cur.clear()
    n = 0
    for b in (preset.get("boxes") or []):
        ref = normalize_item_ref(b.get("item", ""))
        if not ref:
            continue
        cur.append({"item": ref,
                    "sectionID": str(b.get("sectionID") or "basics"),
                    "price": int(b.get("price") or 1)})
        n += 1
    return n


def add_favorites_to_store(data: dict, store: str, refs: list[str],
                           price: int = 1, section: str = "basics") -> int:
    for r in refs:
        add_store_box(data, store, item=normalize_item_ref(r),
                      price=int(price), section=section)
    return len(refs)


def delete_preset(ud: dict, kind: str, name: str) -> bool:
    key = "store_presets" if kind == "store" else "inventory_presets"
    d = ud.setdefault(key, {})
    if name not in d:
        return False
    del d[name]
    return True


# ---------------------------------------------------------------- 玩家仓库

def inventory_pages(data: dict) -> list:
    pages = (data.get(INVENTORY_FILE, {}).get("Data", {}) or {}).get("InventoryPages", [])
    return pages if isinstance(pages, list) else []


def _grid_size(page: dict) -> tuple[int, int]:
    try:
        g = page.get("gridSize") or [12, 8]
        return int(g[0]), int(g[1])
    except Exception:
        return 12, 8


def list_inventory_slots(data: dict, page_index: int = 0) -> list[dict]:
    """列出某页的所有槽位及其中的物件（一个槽位可能是「枪 + 弹匣」等多个物件）。"""
    pages = inventory_pages(data)
    if not 0 <= page_index < len(pages):
        return []
    out = []
    for i, it in enumerate(pages[page_index].get("items", []) or []):
        objs = (it.get("contents") or {}).get("Objects", []) or []
        rows = []
        for j, o in enumerate(objs):
            ref = o.get("ItemDef", "")
            cit = item_by_ref(ref) or {}
            rows.append({"obj_index": j, "ref": ref, "key": asset_key(ref),
                         "zh": cit.get("zh") or cit.get("en") or "",
                         "components": len(o.get("Components") or [])})
        main = rows[0] if rows else {"ref": "", "key": "", "zh": "", "components": 0}
        out.append({"index": i, "page": page_index,
                    "rectMin": list(it.get("rectMin") or [0, 0]),
                    "rectSize": list(it.get("rectSize") or [1, 1]),
                    "objects": rows, "count": len(rows),
                    "ref": main["ref"], "key": main["key"], "zh": main["zh"],
                    "components": main["components"]})
    return out


def get_inventory_slot(data: dict, page_index: int, slot_index: int) -> dict | None:
    pages = inventory_pages(data)
    if not 0 <= page_index < len(pages):
        return None
    items = pages[page_index].setdefault("items", [])
    return items[slot_index] if 0 <= slot_index < len(items) else None


def set_inventory_object(data: dict, page_index: int, slot_index: int,
                         obj_index: int, ref: str, clear_components: bool = False) -> bool:
    slot = get_inventory_slot(data, page_index, slot_index)
    if slot is None:
        return False
    objs = (slot.setdefault("contents", {}).setdefault("Objects", []))
    if not 0 <= obj_index < len(objs):
        return False
    objs[obj_index]["ItemDef"] = normalize_item_ref(ref)
    if clear_components:
        objs[obj_index]["Components"] = []
        (slot["contents"])["Affixments"] = []
    return True


def set_inventory_rect(data: dict, page_index: int, slot_index: int,
                       rect_min=None, rect_size=None) -> bool:
    slot = get_inventory_slot(data, page_index, slot_index)
    if slot is None:
        return False
    if rect_min is not None:
        slot["rectMin"] = [int(v) for v in rect_min[:2]]
    if rect_size is not None:
        w, h = int(rect_size[0]), int(rect_size[1])
        slot["rectSize"] = [w, h]
        (slot.setdefault("contents", {}))["GridSize"] = [w, h]
    return True


def delete_inventory_slot(data: dict, page_index: int, slot_index: int) -> bool:
    pages = inventory_pages(data)
    if not 0 <= page_index < len(pages):
        return False
    items = pages[page_index].setdefault("items", [])
    if not 0 <= slot_index < len(items):
        return False
    items.pop(slot_index)
    return True


def inventory_seeds(data: dict) -> set[int]:
    s = set()
    for pg in inventory_pages(data):
        for slot in pg.get("items", []) or []:
            for o in (slot.get("contents") or {}).get("Objects", []) or []:
                try:
                    s.add(int(o.get("InstanceSeed")))
                except Exception:
                    pass
    return s


def new_instance_seed(existing=()) -> int:
    import random
    ex = set(existing)
    for _ in range(2000):
        v = random.randint(-2147483648, 2147483647)
        if v not in ex:
            return v
    return random.randint(1, 2147483647)


def find_free_rect(data: dict, page_index: int, w: int = 1, h: int = 1) -> tuple | None:
    """在 12×8 网格里按行优先找一块空位；没有则交给调用方新建一页。"""
    pages = inventory_pages(data)
    if not 0 <= page_index < len(pages):
        return None
    gw, gh = _grid_size(pages[page_index])
    if w > gw or h > gh:
        return None
    occ = [[False] * gw for _ in range(gh)]
    for it in pages[page_index].get("items", []) or []:
        try:
            x, y = [int(v) for v in (it.get("rectMin") or [0, 0])[:2]]
            ww, hh = [int(v) for v in (it.get("rectSize") or [1, 1])[:2]]
        except Exception:
            continue
        for yy in range(max(0, y), min(gh, y + hh)):
            for xx in range(max(0, x), min(gw, x + ww)):
                occ[yy][xx] = True
    for y in range(0, gh - h + 1):
        for x in range(0, gw - w + 1):
            if all(not occ[yy][xx] for yy in range(y, y + h) for xx in range(x, x + w)):
                return (x, y)
    return None


def new_inventory_slot(ref: str, rect_min=(0, 0), size=(1, 1), seed: int | None = None) -> dict:
    """构造一个最小合法的仓库槽位（与存档里简单物件的结构一致，Components 为空）。"""
    w, h = int(size[0]), int(size[1])
    x, y = int(rect_min[0]), int(rect_min[1])
    if seed is None:
        seed = new_instance_seed()
    return {
        "contents": {
            "Objects": [{
                "ItemDef": normalize_item_ref(ref),
                "Transform": {"Position": [0.0, 0.0, 0.0],
                              "Rotation": [0.0, 0.0, 0.0, 1.0]},
                "InstanceSeed": int(seed),
                "Components": [],
            }],
            "Affixments": [], "GridSize": [w, h], "Version": 0,
        },
        "rectMin": [x, y], "rectSize": [w, h],
        "position": [round((x - 5.5) * 0.08, 6), round((3.5 - y) * 0.09, 6), 0.0],
        "rotation": [0.0, 0.7071068, 0.0, 0.7071068],
    }


def add_inventory_object(data: dict, ref: str, page_index: int | None = None,
                         size=(1, 1)) -> dict | None:
    """在仓库里新增一个物品槽位：优先当前页空格，全满时自动新建一页。"""
    inv = data.setdefault(INVENTORY_FILE,
                          {"Version": 0, "Data": {"InventoryPages": [], "DumpQueue": []}})
    pages = inv.setdefault("Data", {}).setdefault("InventoryPages", [])
    if not pages:
        pages.append({"gridSize": [12, 8], "items": []})
    w, h = int(size[0]), int(size[1])
    # 指定了页就先试该页，再试其他页，最后才新开一页
    candidates = (list(range(len(pages))) if page_index is None else
                  ([page_index] + [i for i in range(len(pages)) if i != page_index]
                   if 0 <= page_index < len(pages) else list(range(len(pages)))))
    for pi in candidates:
        spot = find_free_rect(data, pi, w, h)
        if spot:
            slot = new_inventory_slot(ref, spot, (w, h),
                                      seed=new_instance_seed(inventory_seeds(data)))
            pages[pi].setdefault("items", []).append(slot)
            return {"page": pi, "index": len(pages[pi]["items"]) - 1,
                    "rectMin": list(spot)}
    pages.append({"gridSize": [12, 8], "items": []})
    pi = len(pages) - 1
    slot = new_inventory_slot(ref, (0, 0), (w, h),
                              seed=new_instance_seed(inventory_seeds(data)))
    pages[pi]["items"].append(slot)
    return {"page": pi, "index": 0, "rectMin": [0, 0]}


def duplicate_inventory_slot(data: dict, page_index: int, slot_index: int) -> dict | None:
    """复制一个已有槽位（保留组件/弹药状态），重新生成 InstanceSeed 避免重复。"""
    import copy
    src = get_inventory_slot(data, page_index, slot_index)
    if src is None:
        return None
    slot = copy.deepcopy(src)
    used = inventory_seeds(data)
    for o in (slot.get("contents") or {}).get("Objects", []) or []:
        seed = new_instance_seed(used)
        used.add(seed)
        o["InstanceSeed"] = seed
    try:
        w, h = [int(v) for v in (slot.get("rectSize") or [1, 1])[:2]]
    except Exception:
        w, h = 1, 1
    spot = None
    for pi in range(len(inventory_pages(data))):
        spot = find_free_rect(data, pi, w, h)
        if spot:
            break
    if spot is None:
        pages = inventory_pages(data)
        pages.append({"gridSize": [12, 8], "items": []})
        pi, spot = len(pages) - 1, (0, 0)
    slot["rectMin"] = [int(spot[0]), int(spot[1])]
    inventory_pages(data)[pi].setdefault("items", []).append(slot)
    return {"page": pi, "index": len(inventory_pages(data)[pi]["items"]) - 1,
            "rectMin": list(spot)}


# ---------------------------------------------------------------- 仓库预设

def inventory_preset_names(ud: dict) -> list[str]:
    return sorted((ud.get("inventory_presets") or {}).keys())


def get_inventory_preset(ud: dict, name: str) -> dict | None:
    p = (ud.get("inventory_presets") or {}).get(name)
    return p if isinstance(p, dict) else None


def save_inventory_preset(ud: dict, name: str, data: dict, note: str = "") -> int:
    """把当前仓库各槽位的主物件（含占格尺寸）保存成预设。"""
    items = []
    for pi in range(len(inventory_pages(data))):
        for s in list_inventory_slots(data, pi):
            if s["ref"]:
                items.append({"item": s["ref"], "size": s["rectSize"]})
    ud.setdefault("inventory_presets", {})[name] = {"note": note or "", "items": items}
    return len(items)


def apply_inventory_preset(data: dict, preset: dict, mode: str = "append",
                           skip_existing: bool = False) -> int:
    """append = 把预设物品补进仓库（手动「追加物品」不去重）；
    skip_existing=True 时按同款物品已有数量补齐，供自动应用幂等使用；
    replace = 先清空所有页再按预设重建。"""
    from collections import Counter
    if not isinstance(preset, dict):
        return 0
    items = preset.get("items") or []
    pages = inventory_pages(data)
    if mode == "replace":
        for pg in pages:
            pg["items"] = []
    have = Counter()
    if skip_existing:
        for pi in range(len(pages)):
            for s in list_inventory_slots(data, pi):
                if s["ref"]:
                    have[normalize_item_ref(s["ref"])] += 1
    used = Counter()
    n = 0
    for e in items:
        ref = normalize_item_ref(e.get("item", ""))
        if not ref:
            continue
        used[ref] += 1
        if skip_existing and used[ref] <= have.get(ref, 0):
            continue
        try:
            sz = e.get("size") or [1, 1]
            size = (max(1, int(sz[0])), max(1, int(sz[1])))
        except Exception:
            size = (1, 1)
        if add_inventory_object(data, ref, size=size):
            n += 1
    return n


def add_inventory_from_refs(data: dict, refs: list[str], size=(1, 1)) -> int:
    n = 0
    for r in refs:
        if add_inventory_object(data, normalize_item_ref(r), size=size):
            n += 1
    return n


# ---------------------------------------------------------------- 载入存档时自动套用

def apply_auto_presets(data: dict, ud: dict, log=print) -> list[str]:
    """按 presets.json 的 settings 自动套用商店 / 仓库预设，返回人类可读的结果。"""
    done = []
    s = ud.get("settings") or {}
    sp = str(s.get("store_auto_preset") or "").strip()
    if sp and STORES_FILE in data:
        preset = get_store_preset(ud, sp)
        stores = store_keys(data)
        if preset and stores:
            mode = str(s.get("store_auto_mode") or "replace")
            n = apply_store_preset(data, stores[0], preset, mode)
            done.append("商店预设「%s」自动应用：%d 个货位（%s）" % (sp, n, mode))
    ip = str(s.get("inventory_auto_preset") or "").strip()
    if ip and INVENTORY_FILE in data:
        preset = get_inventory_preset(ud, ip)
        if preset:
            mode = str(s.get("inventory_auto_mode") or "append")
            # 自动应用可能随反复载入触发，append 时按已有数量补齐，避免越堆越多
            n = apply_inventory_preset(data, preset, mode,
                                       skip_existing=(mode == "append"))
            done.append("仓库预设「%s」自动应用：新增 %d 件（%s）" % (ip, n, mode))
    for line in done:
        log(line)
    return done
