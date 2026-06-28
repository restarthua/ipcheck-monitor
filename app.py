"""IPCheck Monitor — Windows 系统托盘网络环境监控工具。

启动后最小化到托盘，定时检测网络环境，异常时弹窗提醒。
双击托盘图标显示主窗口，查看检测详情。
"""

import json
import sys
import os
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageDraw
import pystray

import webbrowser
from checker import run_check


def get_network_interfaces():
    """获取系统所有网络接口列表"""
    import re
    try:
        result = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True
        )
        stdout = result.stdout.decode("gbk", errors="replace")

        lines = stdout.split('\n')
        # 找到分隔线，确定接口名称列的起始位置
        sep_idx = None
        for idx, line in enumerate(lines):
            if line.strip().startswith('---'):
                sep_idx = idx
                break
        if sep_idx is None or sep_idx < 1:
            return ["WLAN", "以太网", "Ethernet", "Local Area Connection"]

        header = lines[sep_idx - 1]
        # 用最后一个列标题的位置确定接口名称列起始（适配中英文）
        col_start = -1
        for marker in ['Interface', '接口']:
            pos = header.find(marker)
            if pos >= 0:
                col_start = pos
                break
        if col_start < 0:
            # 回退：按 2+ 空格分列，取最后一列
            col_start = None

        interfaces = []
        skip_words = ['Loopback', 'Loop Back', '蓝牙', 'Bluetooth', 'Tunnel', 'Teredo']
        for line in lines[sep_idx + 1:]:
            if not line.strip():
                continue
            if col_start is not None:
                name = line[col_start:].strip()
            else:
                parts = re.split(r'\s{2,}', line.strip())
                name = parts[-1] if parts else ''
            if name and not any(s in name for s in skip_words):
                interfaces.append(name)

        return interfaces if interfaces else ["WLAN", "以太网", "Ethernet", "Local Area Connection"]
    except Exception:
        return ["WLAN", "以太网", "Ethernet", "Local Area Connection"]

VERSION = "1.2.2"


# ── 管理员权限 ─────────────────────────────────────────────
def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _elevate():
    """以管理员身份重新启动当前进程。"""
    import ctypes
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

# ── 配置 ──────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_APP_DIR, "config.json")

DEFAULT_CONFIG = {
    "check_interval": 40,
    "dns_primary": "1.1.1.2",
    "dns_secondary": "1.0.0.2",
    "net_card": "WLAN",
    "timezone": "",
    "proxy_mode": "system",
    "proxy_url": "http://127.0.0.1:10808",
}

TIMEZONE_OPTIONS = [
    "",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Australia/Sydney",
    "Pacific/Auckland",
]


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


config = load_config()


# ── 时区 ──────────────────────────────────────────────────
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def apply_timezone(tz: str):
    """设置用户级 TZ 环境变量，当前进程 + 永久生效。"""
    if tz:
        os.environ["TZ"] = tz
        subprocess.run(f'setx TZ "{tz}"', shell=True, capture_output=True,
                       creationflags=_NO_WINDOW)
    else:
        os.environ.pop("TZ", None)
        subprocess.run('reg delete "HKCU\\Environment" /v TZ /f',
                       shell=True, capture_output=True, creationflags=_NO_WINDOW)


if config.get("timezone"):
    apply_timezone(config["timezone"])


# ── 全局单例（Named Mutex，进程退出后内核自动释放）────────
_MUTEX_NAME = "Global\\IPCheckMonitor_SingleInstance"
_mutex_handle = None


def ensure_single_instance():
    global _mutex_handle
    import ctypes
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None, "监控已在运行中，请勿重复启动！", "IPCheck Monitor", 0x40
        )
        sys.exit(1)


# ── 托盘图标生成 ──────────────────────────────────────────
def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=color)
    return img


ICON_GREEN = make_icon((46, 160, 67))
ICON_RED = make_icon((220, 50, 50))
ICON_YELLOW = make_icon((220, 170, 30))


# ── DNS 修复 ──────────────────────────────────────────────
def fix_dns():
    net_card = config["net_card"]
    dns1 = config["dns_primary"]
    dns2 = config["dns_secondary"]
    try:
        subprocess.run(
            f'netsh interface ip delete dns "{net_card}" all',
            shell=True, capture_output=True, creationflags=_NO_WINDOW,
        )
        subprocess.run(
            f'netsh interface ip set dns "{net_card}" static {dns1}',
            shell=True, capture_output=True, creationflags=_NO_WINDOW,
        )
        subprocess.run(
            f'netsh interface ip add dns "{net_card}" {dns2} index=2',
            shell=True, capture_output=True, creationflags=_NO_WINDOW,
        )
        return True
    except Exception:
        return False


# ── 主应用 ────────────────────────────────────────────────
class IPCheckApp:
    def __init__(self):
        self.last_result = None
        self.running = True
        self.root = None
        self.tray_icon = None
        self.last_alert_state = None
        self._last_dns_cn = None
        self._dns_prompt_showing = False
        self._baseline_mismatch = False

        self._build_window()
        self._build_tray()
        self._start_checker()

    # ── tkinter 窗口 ──────────────────────────────────────
    def _build_window(self):
        self.root = tk.Tk()
        self.root.title(f"IPCheck Monitor v{VERSION}")
        self.root.geometry("520x660")
        self.root.resizable(True, True)
        self.root.minsize(480, 500)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_window)

        style = ttk.Style()
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 11))
        style.configure("Item.TLabel", font=("Segoe UI", 10))
        style.configure("Safe.TLabel", font=("Segoe UI", 12, "bold"), foreground="#2ea043")
        style.configure("Danger.TLabel", font=("Segoe UI", 12, "bold"), foreground="#dc3232")
        style.configure("Small.TButton", font=("Segoe UI", 9))

        main = ttk.Frame(self.root, padding=20)
        main.pack(fill="both", expand=True)

        header_frame = ttk.Frame(main)
        header_frame.pack(fill="x")
        ttk.Label(header_frame, text="IPCheck Monitor", style="Header.TLabel").pack(side="left")
        self.time_label = ttk.Label(header_frame, text="", font=("Segoe UI", 9), foreground="#999")
        self.time_label.pack(side="right", anchor="e")
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(8, 12))

        self.status_label = ttk.Label(main, text="等待首次检测...", style="Status.TLabel")
        self.status_label.pack(anchor="w")

        self.overall_label = ttk.Label(main, text="", style="Safe.TLabel")
        self.overall_label.pack(anchor="w", pady=(4, 8))

        detail_frame = ttk.LabelFrame(main, text="检测详情", padding=10)
        detail_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.detail_text = tk.Text(
            detail_frame, font=("Consolas", 10), wrap="word",
            state="disabled", bg="#fafafa", relief="flat",
            highlightthickness=0,
        )
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.tag_configure("ok", foreground="#2ea043")
        self.detail_text.tag_configure("warn", foreground="#d29922")
        self.detail_text.tag_configure("bad", foreground="#dc3232")
        self.detail_text.tag_configure("label", foreground="#666666")

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x")

        self.check_btn = ttk.Button(btn_frame, text="立即检测", command=self._manual_check)
        self.check_btn.pack(side="left")

        self.fix_dns_btn = ttk.Button(btn_frame, text="修复 DNS", command=self._fix_dns)
        self.fix_dns_btn.pack(side="left", padx=(8, 0))

        self.baseline_btn = ttk.Button(btn_frame, text="导入基线", command=self._import_baseline)
        self.baseline_btn.pack(side="left", padx=(8, 0))

        self.settings_btn = ttk.Button(btn_frame, text="设置", command=self._open_settings)
        self.settings_btn.pack(side="left", padx=(8, 0))

        self.about_btn = ttk.Button(btn_frame, text="关于", command=self._open_about)
        self.about_btn.pack(side="left", padx=(8, 0))

        self.root.withdraw()

    # ── 系统托盘 ──────────────────────────────────────────
    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", self._show_window, default=True),
            pystray.MenuItem("立即检测", self._tray_check),
            pystray.MenuItem("修复 DNS", self._tray_fix_dns),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )
        self.tray_icon = pystray.Icon(
            "IPCheckMonitor", ICON_YELLOW, "IPCheck Monitor - 等待检测", menu
        )

    # ── 窗口显示/隐藏 ────────────────────────────────────
    def _show_window(self, *args):
        self.root.after(0, self._do_show)

    def _do_show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _hide_window(self):
        self.root.withdraw()

    # ── 检测线程 ──────────────────────────────────────────
    def _start_checker(self):
        t = threading.Thread(target=self._check_loop, daemon=True)
        t.start()

    def _check_loop(self):
        time.sleep(2)
        while self.running:
            self._do_check()
            time.sleep(config["check_interval"])

    def _do_check(self):
        proxy_mode = config.get("proxy_mode", "system")
        proxy_url = config.get("proxy_url", "")
        _proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
        saved_env = {}
        if proxy_mode == "custom" and proxy_url:
            for k in _proxy_keys:
                saved_env[k] = os.environ.get(k)
                os.environ[k] = proxy_url
        try:
            result = run_check()
        except Exception as e:
            result = {
                "overall_safe": False,
                "conclusions": [("bad", f"检测异常: {e}")],
            }
        finally:
            if proxy_mode == "custom" and proxy_url:
                for k in _proxy_keys:
                    if saved_env[k] is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = saved_env[k]
        self.last_result = result
        self.root.after(0, self._update_ui, result)

        if not result["overall_safe"]:
            if self.last_alert_state is not False:
                self._notify_alert(result)
            self.last_alert_state = False
        else:
            if self.last_alert_state is False:
                self._notify_recovery()
            self.last_alert_state = True

        diffs = self._check_baseline(result)
        if diffs and not self._baseline_mismatch:
            self.root.after(0, self._notify_baseline_change, diffs)
        self._baseline_mismatch = bool(diffs)

    def _manual_check(self):
        self.check_btn.configure(state="disabled")
        self.status_label.configure(text="检测中...")

        def do():
            self._do_check()
            self.root.after(0, lambda: self.check_btn.configure(state="normal"))

        threading.Thread(target=do, daemon=True).start()

    def _tray_check(self, *args):
        threading.Thread(target=self._do_check, daemon=True).start()

    # ── UI 更新 ───────────────────────────────────────────
    def _update_ui(self, r):
        now = time.strftime("%H:%M:%S")
        self.time_label.configure(text=f"上次检测: {now}")

        if r.get("overall_safe"):
            self.overall_label.configure(text="✓ 当前环境安全", style="Safe.TLabel")
            self.status_label.configure(text="环境正常")
            self.tray_icon.icon = ICON_GREEN
            self.tray_icon.title = "IPCheck - 环境正常"
        else:
            self.overall_label.configure(text="⚠ 检测到风险", style="Danger.TLabel")
            self.status_label.configure(text="发现异常，请查看详情")
            self.tray_icon.icon = ICON_RED
            self.tray_icon.title = "IPCheck - 发现异常!"

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")

        lines = []
        if "lan_ip" in r:
            lines.append(("label", "局域网 IP:  "))
            lines.append(("ok", r["lan_ip"] + "\n"))

        if "ipv6" in r:
            lines.append(("label", "IPv6:      "))
            if r["ipv6_leaked"]:
                lines.append(("bad", f"{r['ipv6']} (泄露!)\n"))
            else:
                lines.append(("ok", "已禁用\n"))

        if "dns_servers" in r and r["dns_servers"]:
            lines.append(("label", "DNS:       "))
            tag = "bad" if r.get("dns_cn") else "ok"
            lines.append((tag, ", ".join(r["dns_servers"])))
            if r.get("dns_cn"):
                lines.append(("bad", " (国内!)"))
            lines.append(("ok", "\n"))

        if r.get("public_ip"):
            lines.append(("label", "公网 IP:   "))
            lines.append(("ok", f"{r['public_ip']}\n"))
            lines.append(("label", "位置:      "))
            lines.append(("ok", f"{r.get('country', '')} / {r.get('region', '')} / {r.get('city', '')}\n"))
            lines.append(("label", "ISP:       "))
            lines.append(("ok", f"{r.get('isp', '')}\n"))

        if r.get("risk_display"):
            lines.append(("label", "IP 风险:   "))
            score = r.get("risk_score")
            tag = "ok" if score and score < 30 else ("warn" if score and score < 70 else "bad")
            lines.append((tag, f"{r['risk_display']}\n"))

        if r.get("cli_timezone"):
            lines.append(("label", "CLI 时区:  "))
            lines.append(("ok", f"{r['cli_timezone']}\n"))
            lines.append(("label", "IP 时区:   "))
            lines.append(("ok", f"{r.get('ip_timezone', '未知')}\n"))
            lines.append(("label", "时区匹配:  "))
            if r.get("tz_matched") is True:
                lines.append(("ok", "一致\n"))
            elif r.get("tz_matched") is False:
                lines.append(("bad", "不一致!\n"))
            else:
                lines.append(("warn", "无法比对\n"))

        baseline = config.get("baseline")
        if baseline:
            lines.append(("label", "\n─── 基线对比 ───\n"))
            diffs = self._check_baseline(r)
            if diffs:
                for d in diffs:
                    lines.append(("bad", f"  ✗ {d}\n"))
            else:
                lines.append(("ok", "  ✓ 与基线一致\n"))

        lines.append(("label", "\n─── 结论 ───\n"))
        for level, msg in r.get("conclusions", []):
            prefix = {"ok": "✓", "warn": "!", "bad": "✗"}.get(level, "-")
            lines.append((level, f"  {prefix} {msg}\n"))

        for tag, text in lines:
            self.detail_text.insert("end", text, tag)

        self.detail_text.configure(state="disabled")

        # DNS 异常自动提示
        dns_cn_now = r.get("dns_cn", False)
        if dns_cn_now and self._last_dns_cn is not True:
            self._prompt_fix_dns()
        self._last_dns_cn = dns_cn_now

    # ── 子窗口居中 ────────────────────────────────────────
    def _center_on_parent(self, win, w, h):
        win.update_idletasks()
        px = self.root.winfo_x()
        py = self.root.winfo_y()
        pw = self.root.winfo_width()
        ph = self.root.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

    # ── 基线 ──────────────────────────────────────────────
    def _import_baseline(self):
        baseline = config.get("baseline")
        if baseline:
            self._open_baseline_view()
        else:
            self._do_import_baseline()

    def _do_import_baseline(self):
        if not self.last_result or not self.last_result.get("public_ip"):
            messagebox.showinfo("导入基线", "请先完成一次检测", parent=self.root)
            return
        r = self.last_result
        baseline = {
            "country": r.get("country", ""),
            "region": r.get("region", ""),
            "city": r.get("city", ""),
            "isp": r.get("isp", ""),
            "cli_timezone": r.get("cli_timezone", ""),
        }
        config["baseline"] = baseline
        save_config(config)
        self._baseline_mismatch = False
        messagebox.showinfo(
            "导入基线",
            f"已保存当前环境为基线:\n"
            f"位置: {baseline['country']} / {baseline['region']} / {baseline['city']}\n"
            f"ISP: {baseline['isp']}\n"
            f"时区: {baseline['cli_timezone']}",
            parent=self.root,
        )

    def _open_baseline_view(self):
        baseline = config.get("baseline", {})
        win = tk.Toplevel(self.root)
        win.title("基线配置")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self._center_on_parent(win, 380, 280)

        frame = ttk.Frame(win, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="当前基线", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(6, 10))

        fields = [
            ("国家", baseline.get("country", "")),
            ("地区", baseline.get("region", "")),
            ("城市", baseline.get("city", "")),
            ("ISP", baseline.get("isp", "")),
            ("时区", baseline.get("cli_timezone", "")),
        ]
        info_frame = ttk.Frame(frame)
        info_frame.pack(fill="x")
        for i, (label, value) in enumerate(fields):
            ttk.Label(info_frame, text=f"{label}:", font=("Segoe UI", 10),
                      foreground="#666").grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(info_frame, text=value or "（空）", font=("Segoe UI", 10)).grid(
                row=i, column=1, sticky="w", padx=(12, 0), pady=2)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=(16, 0))

        def reimport():
            win.destroy()
            self._do_import_baseline()

        def clear():
            config.pop("baseline", None)
            save_config(config)
            self._baseline_mismatch = False
            win.destroy()

        ttk.Button(btn_frame, text="重新导入", command=reimport).pack(side="left")
        ttk.Button(btn_frame, text="清除基线", command=clear).pack(side="left", padx=(8, 0))
        ttk.Button(btn_frame, text="关闭", command=win.destroy).pack(side="left", padx=(8, 0))

    def _check_baseline(self, r):
        baseline = config.get("baseline")
        if not baseline or not r.get("public_ip"):
            return []
        diffs = []
        for key, label in [
            ("country", "国家"),
            ("region", "地区"),
            ("city", "城市"),
            ("isp", "ISP"),
            ("cli_timezone", "时区"),
        ]:
            old = baseline.get(key, "")
            new = r.get(key, "")
            if old and new and old != new:
                diffs.append(f"{label}: {old} → {new}")
        return diffs

    def _notify_baseline_change(self, diffs):
        body = "\n".join(diffs[:5])
        self.tray_icon.notify(body, "IPCheck - 网络环境变化")

    # ── 通知 ──────────────────────────────────────────────
    def _notify_alert(self, r):
        problems = [msg for level, msg in r.get("conclusions", []) if level in ("bad", "warn")]
        title = "IPCheck - 环境异常!"
        body = "\n".join(problems[:3]) if problems else "检测到网络环境风险"
        self.tray_icon.notify(body, title)

    def _notify_recovery(self):
        self.tray_icon.notify("网络环境已恢复正常", "IPCheck - 已恢复")

    # ── DNS 修复 ──────────────────────────────────────────
    def _topmost_msgbox(self, func, title, message, **kwargs):
        """弹出全局置顶的 messagebox，完成后恢复窗口状态。"""
        self.root.attributes("-topmost", True)
        self.root.deiconify()
        self.root.lift()
        try:
            return func(title, message, parent=self.root, **kwargs)
        finally:
            self.root.attributes("-topmost", False)
            if not self.root.winfo_viewable():
                self.root.withdraw()

    def _prompt_fix_dns(self):
        """检测到国内 DNS 时弹窗询问是否立即修复（主线程调用）。"""
        if self._dns_prompt_showing:
            self.tray_icon.notify("仍在使用国内 DNS，请尽快修复", "IPCheck - DNS 异常")
            return
        dns1 = config["dns_primary"]
        dns2 = config["dns_secondary"]
        self._dns_prompt_showing = True
        try:
            ans = self._topmost_msgbox(
                messagebox.askyesno,
                "DNS 异常",
                f"检测到正在使用国内 DNS，可能暴露真实位置。\n\n"
                f"是否立即切换为安全 DNS？\n  主: {dns1}\n  备: {dns2}",
            )
            if ans:
                self._fix_dns()
        finally:
            self._dns_prompt_showing = False

    def _fix_dns(self):
        if fix_dns():
            self._topmost_msgbox(
                messagebox.showinfo, "DNS 修复",
                f"已切换为安全 DNS:\n{config['dns_primary']}\n{config['dns_secondary']}",
            )
            self._manual_check()
        else:
            self._topmost_msgbox(messagebox.showerror, "DNS 修复", "修复失败，请以管理员身份运行")

    def _tray_fix_dns(self, *args):
        self.root.after(0, self._fix_dns)

    # ── 关于 ──────────────────────────────────────────────
    def _open_about(self):
        REPO_URL = "https://github.com/restarthua/ipcheck-monitor"
        win = tk.Toplevel(self.root)
        win.title("关于")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self._center_on_parent(win, 360, 200)

        frame = ttk.Frame(win, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="IPCheck Monitor", font=("Segoe UI", 14, "bold")).pack()
        ttk.Label(frame, text=f"v{VERSION}", font=("Segoe UI", 10), foreground="#666").pack(pady=(4, 12))
        ttk.Label(frame, text="Windows 系统托盘网络环境监控工具", font=("Segoe UI", 10)).pack()
        ttk.Label(
            frame, text="基于 ai-ipcheck · by stormzhang",
            font=("Segoe UI", 9), foreground="#999",
        ).pack(pady=(2, 12))

        link = ttk.Label(frame, text="GitHub", font=("Segoe UI", 10, "underline"), foreground="#0969da", cursor="hand2")
        link.pack()
        link.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))

    # ── 设置 ──────────────────────────────────────────────
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self._center_on_parent(win, 420, 400)

        frame = ttk.Frame(win, padding=20)
        frame.pack(fill="both", expand=True)

        # 获取网卡列表
        network_interfaces = get_network_interfaces()
        fields = [
            ("检测间隔（秒）", "check_interval", str(config["check_interval"])),
            ("网卡名称", "net_card", config["net_card"], network_interfaces),
            ("主 DNS", "dns_primary", config["dns_primary"]),
            ("备 DNS", "dns_secondary", config["dns_secondary"]),
        ]

        entries = {}
        net_card_row = None
        for i, (label, key, default, *options) in enumerate(fields):
            ttk.Label(frame, text=label, font=("Segoe UI", 10)).grid(
                row=i, column=0, sticky="w", pady=4,
            )
            if key == "net_card" and options:
                net_card_row = i
                iface_list = list(options[0])
                if default and default not in iface_list:
                    iface_list.insert(0, default)
                var = tk.StringVar(value=default)
                combo = ttk.Combobox(
                    frame, textvariable=var, values=iface_list, width=21,
                )
                combo.grid(row=i, column=1, sticky="e", padx=(12, 0), pady=4)
                entries[key] = var
                ttk.Button(
                    frame, text="↻", command=lambda: refresh_interfaces(),
                    width=3, style="Small.TButton",
                ).grid(row=i, column=2, padx=(4, 0), pady=4)
            else:
                var = tk.StringVar(value=default)
                entry = ttk.Entry(frame, textvariable=var, width=24)
                entry.grid(row=i, column=1, columnspan=2, sticky="e", padx=(12, 0), pady=4)
                entries[key] = var

        row_tz = len(fields)
        ttk.Label(frame, text="时区", font=("Segoe UI", 10)).grid(
            row=row_tz, column=0, sticky="w", pady=4,
        )
        tz_var = tk.StringVar(value=config.get("timezone", ""))
        tz_combo = ttk.Combobox(
            frame, textvariable=tz_var, values=TIMEZONE_OPTIONS, width=21,
        )
        tz_combo.grid(row=row_tz, column=1, sticky="e", padx=(12, 0), pady=4)

        def on_apply_tz():
            tz = tz_var.get().strip()
            apply_timezone(tz)
            config["timezone"] = tz
            save_config(config)
            label = tz if tz else "（已清除）"
            messagebox.showinfo("时区", f"已应用: {label}", parent=win)

        ttk.Button(frame, text="应用", command=on_apply_tz, width=6).grid(
            row=row_tz, column=2, padx=(4, 0), pady=4,
        )

        # 代理设置
        _proxy_label_to_mode = {"系统代理": "system", "自定义代理": "custom"}
        _proxy_mode_to_label = {"system": "系统代理", "custom": "自定义代理"}
        row_proxy = row_tz + 1
        ttk.Label(frame, text="代理模式", font=("Segoe UI", 10)).grid(
            row=row_proxy, column=0, sticky="w", pady=4,
        )
        proxy_mode_var = tk.StringVar(
            value=_proxy_mode_to_label.get(config.get("proxy_mode", "system"), "系统代理")
        )
        proxy_mode_combo = ttk.Combobox(
            frame, textvariable=proxy_mode_var,
            values=["系统代理", "自定义代理"], width=21, state="readonly",
        )
        proxy_mode_combo.grid(row=row_proxy, column=1, sticky="e", padx=(12, 0), pady=4)

        row_proxy_url = row_proxy + 1
        ttk.Label(frame, text="代理地址", font=("Segoe UI", 10)).grid(
            row=row_proxy_url, column=0, sticky="w", pady=4,
        )
        proxy_url_var = tk.StringVar(value=config.get("proxy_url", "http://127.0.0.1:10808"))
        proxy_url_entry = ttk.Entry(frame, textvariable=proxy_url_var, width=24)
        proxy_url_entry.grid(row=row_proxy_url, column=1, columnspan=2, sticky="e", padx=(12, 0), pady=4)
        if config.get("proxy_mode", "system") != "custom":
            proxy_url_entry.configure(state="disabled")

        def on_proxy_mode_change(*_):
            if proxy_mode_var.get() == "自定义代理":
                proxy_url_entry.configure(state="normal")
            else:
                proxy_url_entry.configure(state="disabled")

        proxy_mode_var.trace_add("write", on_proxy_mode_change)

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

        def refresh_interfaces():
            interfaces = get_network_interfaces()
            current_value = entries["net_card"].get()
            if current_value and current_value not in interfaces:
                interfaces.insert(0, current_value)
            for widget in frame.grid_slaves(row=net_card_row, column=1):
                widget.destroy()
            for widget in frame.grid_slaves(row=net_card_row, column=2):
                widget.destroy()

            var = tk.StringVar(value=current_value)
            combo = ttk.Combobox(
                frame, textvariable=var, values=interfaces, width=21,
            )
            combo.grid(row=net_card_row, column=1, sticky="e", padx=(12, 0), pady=4)
            entries["net_card"] = var
            ttk.Button(
                frame, text="↻", command=lambda: refresh_interfaces(),
                width=3, style="Small.TButton",
            ).grid(row=net_card_row, column=2, padx=(4, 0), pady=4)

        def on_save():
            try:
                interval = int(entries["check_interval"].get())
                if interval < 10:
                    interval = 10
            except ValueError:
                messagebox.showwarning("输入错误", "检测间隔必须是数字", parent=win)
                return

            config["check_interval"] = interval
            config["net_card"] = entries["net_card"].get().strip()
            config["dns_primary"] = entries["dns_primary"].get().strip()
            config["dns_secondary"] = entries["dns_secondary"].get().strip()
            tz = tz_var.get().strip()
            config["timezone"] = tz
            config["proxy_mode"] = _proxy_label_to_mode.get(proxy_mode_var.get(), "system")
            config["proxy_url"] = proxy_url_var.get().strip()
            save_config(config)
            win.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row_proxy_url + 1, column=0, columnspan=3, pady=(16, 0))
        ttk.Button(btn_frame, text="保存", command=on_save).pack(side="left")
        ttk.Button(btn_frame, text="取消", command=win.destroy).pack(side="left", padx=(8, 0))

    # ── 退出 ──────────────────────────────────────────────
    def _quit(self, *args):
        self.running = False
        self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ── 启动 ──────────────────────────────────────────────
    def run(self):
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()
        self.root.mainloop()


def main():
    if sys.platform == "win32" and not _is_admin():
        _elevate()
        return
    ensure_single_instance()
    app = IPCheckApp()
    app.run()


if __name__ == "__main__":
    main()
