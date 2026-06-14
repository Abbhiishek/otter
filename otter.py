from __future__ import annotations

import argparse
import base64
import copy
import ctypes
from ctypes import wintypes
import json
import math
import os
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
USAGE_PATH = APP_DIR / "usage.json"
OTTER_ANIMATION_DIR = APP_DIR / "assets" / "otter_animations"
OTTER_FRAME_MS = 120
CLAUDE_LOG_DIRS = (
    Path.home() / ".claude" / "projects",
    Path.home() / ".claude" / "sessions",
)
CODEX_LOG_DIR = Path.home() / ".codex" / "sessions"
TRANSPARENT_COLOR = "#ff00ff"
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
LRESULT = getattr(wintypes, "LRESULT", wintypes.LPARAM)

DEFAULT_CONFIG = {
    "window": {
        "x": 1200,
        "y": 50,
        "width": 126,
        "height": 104,
    },
    "quota": {
        "weekly_quota_tokens": 1_000_000,
        "tokens_used": 0,
        "data_source": "combined_local",
        "poll_interval_sec": 30,
    },
    "appearance": {
        "otter_scale": 0.5,
        "show_percentage_badge": False,
    },
}


@dataclass(frozen=True)
class Mood:
    key: str
    label: str
    body: str
    outline: str
    bar: str
    face: str


@dataclass(frozen=True)
class UsageSnapshot:
    source_key: str
    source_label: str
    tokens_used: int
    quota: int | None
    records: int
    rate_limit_lines: tuple[str, ...] = ()


MOODS = {
    "furious": Mood("furious", "Furious", "#ffd0c2", "#dd4a35", "#dd4a35", "furious"),
    "sad": Mood("sad", "Sad", "#d8e8ff", "#4f79bd", "#4f79bd", "sad"),
    "neutral": Mood("neutral", "Neutral", "#eef0f2", "#7f8790", "#7f8790", "neutral"),
    "happy": Mood("happy", "Happy", "#d8f6db", "#3d9b61", "#3d9b61", "happy"),
    "overjoyed": Mood("overjoyed", "Overjoyed", "#fff0b8", "#de9f17", "#de9f17", "overjoyed"),
}

NORMAL_ANIMATION_CHOICES = ("idle",)
INTERACTION_ANIMATION_CHOICES = ("pat", "walk", "swim", "float", "celebrate")

ANIMATION_DURATIONS = {
    "idle": 2.4,
    "pat": 1.5,
    "walk": 2.3,
    "swim": 2.6,
    "float": 2.8,
    "celebrate": 2.0,
    "sleep": 2.8,
    "sip": 2.5,
}


def deep_merge(defaults: dict, loaded: dict) -> dict:
    merged = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> dict:
    if not path.exists():
        save_config(path, DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        backup = path.with_suffix(".broken.json")
        try:
            path.replace(backup)
        except OSError:
            pass
        save_config(path, DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    config = deep_merge(DEFAULT_CONFIG, raw if isinstance(raw, dict) else {})
    normalize_config(config)
    return config


def save_config(path: Path, config: dict) -> None:
    config = copy.deepcopy(config)
    normalize_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    tmp_path.replace(path)


def normalize_config(config: dict) -> None:
    window = config.setdefault("window", {})
    quota = config.setdefault("quota", {})
    appearance = config.setdefault("appearance", {})

    window["x"] = int_or_default(window.get("x"), DEFAULT_CONFIG["window"]["x"])
    window["y"] = int_or_default(window.get("y"), DEFAULT_CONFIG["window"]["y"])
    window["width"] = max(96, int_or_default(window.get("width"), DEFAULT_CONFIG["window"]["width"]))
    window["height"] = max(80, int_or_default(window.get("height"), DEFAULT_CONFIG["window"]["height"]))

    quota["weekly_quota_tokens"] = max(
        1,
        int_or_default(
            quota.get("weekly_quota_tokens"),
            DEFAULT_CONFIG["quota"]["weekly_quota_tokens"],
        ),
    )
    quota["tokens_used"] = max(
        0,
        int_or_default(quota.get("tokens_used"), DEFAULT_CONFIG["quota"]["tokens_used"]),
    )
    if quota.get("data_source") not in {
        "manual",
        "local_json",
        "auto_local",
        "combined_local",
        "claude_local",
        "codex_local",
        "claude_api",
    }:
        quota["data_source"] = "combined_local"
    quota["poll_interval_sec"] = max(
        1,
        int_or_default(quota.get("poll_interval_sec"), DEFAULT_CONFIG["quota"]["poll_interval_sec"]),
    )

    scale_value = appearance.get("otter_scale")
    if scale_value is None:
        scale_value = appearance.get("otto_scale")
    if scale_value is None:
        scale_value = appearance.get("pet_scale")
    appearance["otter_scale"] = float_or_default(
        scale_value,
        DEFAULT_CONFIG["appearance"]["otter_scale"],
    )
    appearance["otter_scale"] = min(1.0, max(0.25, appearance["otter_scale"]))
    appearance.pop("otto_scale", None)
    appearance.pop("pet_scale", None)
    appearance["show_percentage_badge"] = bool(
        appearance.get(
            "show_percentage_badge",
            DEFAULT_CONFIG["appearance"]["show_percentage_badge"],
        )
    )


def int_or_default(value: object, default: int) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


def float_or_default(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def current_week_start() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def parse_record_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def iter_recent_jsonl(paths: tuple[Path, ...], week_start: date):
    for root in paths:
        if not root.exists():
            continue
        try:
            files = root.rglob("*.jsonl")
            for path in files:
                try:
                    if datetime.fromtimestamp(path.stat().st_mtime).date() < week_start:
                        continue
                except OSError:
                    continue
                yield path
        except OSError:
            continue


def iter_jsonl_records(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield line_no, record
    except OSError:
        return


def usage_field_total(usage: dict, fields: tuple[str, ...]) -> int:
    total = 0
    for field in fields:
        total += max(0, int_or_default(usage.get(field), 0))
    return total


def claude_usage_total(usage: dict) -> int:
    total = usage_field_total(
        usage,
        (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ),
    )
    if total:
        return total
    return max(0, int_or_default(usage.get("total_tokens"), 0))


def codex_usage_total(usage: dict) -> int:
    total_tokens = int_or_default(usage.get("total_tokens"), 0)
    if total_tokens > 0:
        return total_tokens
    return usage_field_total(usage, ("input_tokens", "output_tokens"))


def scan_claude_usage(week_start: date) -> UsageSnapshot:
    tokens_used = 0
    records = 0
    seen_requests: set[str] = set()

    for path in iter_recent_jsonl(CLAUDE_LOG_DIRS, week_start):
        for line_no, record in iter_jsonl_records(path):
            record_day = parse_record_date(record.get("timestamp"))
            if record_day is not None and record_day < week_start:
                continue

            message = record.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue

            message_id = message.get("id")
            request_key = record.get("requestId") or message_id
            if request_key is None:
                request_key = f"{path}:{line_no}"
            request_key = str(request_key)
            if request_key in seen_requests:
                continue

            total = claude_usage_total(usage)
            if total <= 0:
                continue

            seen_requests.add(request_key)
            tokens_used += total
            records += 1

    return UsageSnapshot(
        source_key="claude_local",
        source_label="Claude local logs",
        tokens_used=tokens_used,
        quota=None,
        records=records,
    )


def scan_codex_usage(week_start: date) -> UsageSnapshot:
    tokens_used = 0
    records = 0
    latest_weekly_percent: float | None = None
    latest_weekly_percent_at = ""
    latest_rate_limits: dict | None = None
    latest_rate_limits_at = ""

    for path in iter_recent_jsonl((CODEX_LOG_DIR,), week_start):
        for _line_no, record in iter_jsonl_records(path):
            record_day = parse_record_date(record.get("timestamp"))
            if record_day is not None and record_day < week_start:
                continue

            if record.get("type") != "event_msg":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue

            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            last_usage = info.get("last_token_usage")
            if not isinstance(last_usage, dict):
                continue

            total = codex_usage_total(last_usage)
            if total > 0:
                tokens_used += total
                records += 1

            rate_limits = payload.get("rate_limits")
            if not isinstance(rate_limits, dict):
                continue
            timestamp = str(record.get("timestamp", ""))
            if timestamp >= latest_rate_limits_at:
                latest_rate_limits = rate_limits
                latest_rate_limits_at = timestamp

            weekly = rate_limits.get("secondary")
            if not isinstance(weekly, dict):
                continue
            if int_or_default(weekly.get("window_minutes"), 0) < 10080:
                continue
            used_percent = float_or_default(weekly.get("used_percent"), -1.0)
            if used_percent >= 0 and timestamp >= latest_weekly_percent_at:
                latest_weekly_percent = used_percent
                latest_weekly_percent_at = timestamp

    quota = None
    if tokens_used > 0 and latest_weekly_percent and latest_weekly_percent > 0:
        quota = max(tokens_used, math.ceil(tokens_used / (latest_weekly_percent / 100.0)))

    return UsageSnapshot(
        source_key="codex_local",
        source_label="Codex local logs",
        tokens_used=tokens_used,
        quota=quota,
        records=records,
        rate_limit_lines=build_rate_limit_lines(latest_rate_limits),
    )


def scan_local_usage(source: str, week_start: date) -> UsageSnapshot:
    if source == "claude_local":
        return scan_claude_usage(week_start)
    if source == "codex_local":
        return scan_codex_usage(week_start)

    claude = scan_claude_usage(week_start)
    codex = scan_codex_usage(week_start)
    if source == "auto_local":
        if codex.records and codex.quota:
            return UsageSnapshot(
                source_key="auto_local",
                source_label="Auto local logs (Codex)",
                tokens_used=codex.tokens_used,
                quota=codex.quota,
                records=codex.records,
                rate_limit_lines=codex.rate_limit_lines,
            )
        if claude.records and not codex.records:
            return UsageSnapshot(
                source_key="auto_local",
                source_label="Auto local logs (Claude)",
                tokens_used=claude.tokens_used,
                quota=claude.quota,
                records=claude.records,
                rate_limit_lines=claude.rate_limit_lines,
            )
        if codex.records and not claude.records:
            return UsageSnapshot(
                source_key="auto_local",
                source_label="Auto local logs (Codex)",
                tokens_used=codex.tokens_used,
                quota=codex.quota,
                records=codex.records,
                rate_limit_lines=codex.rate_limit_lines,
            )

    quota = codex.quota if claude.tokens_used == 0 else None
    return UsageSnapshot(
        source_key=source,
        source_label="Claude + Codex local logs",
        tokens_used=claude.tokens_used + codex.tokens_used,
        quota=quota,
        records=claude.records + codex.records,
        rate_limit_lines=codex.rate_limit_lines,
    )


def compute_mood(burn_pct: float) -> Mood:
    if burn_pct <= 10:
        return MOODS["furious"]
    if burn_pct <= 30:
        return MOODS["sad"]
    if burn_pct <= 65:
        return MOODS["neutral"]
    if burn_pct < 100:
        return MOODS["happy"]
    return MOODS["overjoyed"]


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def blend_color(a: str, b: str, t: float) -> str:
    t = min(1.0, max(0.0, t))
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return rgb_to_hex(
        (
            round(ar + (br - ar) * t),
            round(ag + (bg - ag) * t),
            round(ab + (bb - ab) * t),
        )
    )


def format_tokens(value: int) -> str:
    value = int(value)
    if value >= 1_000_000:
        amount = value / 1_000_000
        return f"{amount:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        amount = value / 1_000
        return f"{amount:.1f}K".replace(".0K", "K")
    return str(value)


def format_percent(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return f"{round(value)}%"
    return f"{value:.1f}%"


def format_reset_time(value: object) -> str:
    timestamp = int_or_default(value, 0)
    if timestamp <= 0:
        return ""
    reset_at = datetime.fromtimestamp(timestamp)
    return reset_at.strftime("%b %d %I:%M %p")


def first_number(data: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in data:
            continue
        value = float_or_default(data.get(key), -1.0)
        if value >= 0:
            return value
    return None


def format_compact_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    if abs(value - round(value)) < 0.05:
        return str(round(value))
    return f"{value:.1f}"


def format_rate_limit_window(label: str, window: object) -> str:
    if not isinstance(window, dict):
        return f"{label}: not reported"

    used_percent = float_or_default(window.get("used_percent"), -1.0)
    if used_percent >= 0:
        text = f"{label}: {format_percent(used_percent)} used"
    else:
        text = f"{label}: reported"

    reset_time = format_reset_time(window.get("resets_at"))
    if reset_time:
        text = f"{text}, resets {reset_time}"
    return text


def format_credit_limit(rate_limits: object) -> str:
    if not isinstance(rate_limits, dict):
        return "Credit limit: not reported"

    source = rate_limits.get("credits")
    if source is None:
        source = rate_limits.get("individual_limit")

    if isinstance(source, (int, float)):
        return f"Credit limit: {format_compact_number(float(source))}"

    if not isinstance(source, dict):
        return "Credit limit: not reported"

    used_percent = float_or_default(source.get("used_percent"), -1.0)
    if used_percent >= 0:
        text = f"Credit limit: {format_percent(used_percent)} used"
    else:
        used = first_number(source, ("used", "used_amount", "usage"))
        limit = first_number(source, ("limit", "total", "quota", "monthly_limit"))
        remaining = first_number(source, ("remaining", "remaining_amount", "available"))
        if used is not None and limit is not None:
            text = f"Credit limit: {format_compact_number(used)} / {format_compact_number(limit)} used"
        elif remaining is not None and limit is not None:
            text = f"Credit limit: {format_compact_number(remaining)} / {format_compact_number(limit)} left"
        else:
            text = "Credit limit: reported"

    reset_time = format_reset_time(source.get("resets_at"))
    if reset_time:
        text = f"{text}, resets {reset_time}"
    return text


def build_rate_limit_lines(rate_limits: object) -> tuple[str, ...]:
    if not isinstance(rate_limits, dict):
        return ()
    return (
        format_rate_limit_window("5 hr limit", rate_limits.get("primary")),
        format_rate_limit_window("1 week limit", rate_limits.get("secondary")),
        format_credit_limit(rate_limits),
    )


class Tooltip:
    def __init__(self, root: tk.Tk, text_callback):
        self.root = root
        self.text_callback = text_callback
        self.tip: tk.Toplevel | None = None

    def show(self, x: int, y: int) -> None:
        text = self.text_callback()
        if self.tip is None or not self.tip.winfo_exists():
            self.tip = tk.Toplevel(self.root)
            self.tip.overrideredirect(True)
            self.tip.attributes("-topmost", True)
            label = tk.Label(
                self.tip,
                text=text,
                bg="#1f2328",
                fg="#ffffff",
                padx=8,
                pady=5,
                font=("Segoe UI", 9),
                justify=tk.LEFT,
            )
            label.pack()
        else:
            label = self.tip.winfo_children()[0]
            if isinstance(label, tk.Label):
                label.configure(text=text)
        self.tip.geometry(f"+{x + 12}+{y + 16}")
        self.tip.deiconify()

    def hide(self) -> None:
        if self.tip is not None and self.tip.winfo_exists():
            self.tip.withdraw()

    def destroy(self) -> None:
        if self.tip is not None and self.tip.winfo_exists():
            self.tip.destroy()


class WindowsTrayIcon:
    NIM_ADD = 0
    NIM_MODIFY = 1
    NIM_DELETE = 2
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    WM_USER = 0x0400
    WM_TRAY = WM_USER + 20
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONDBLCLK = 0x0203
    WM_DESTROY = 0x0002
    IDI_APPLICATION = 32512

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uTimeoutOrVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class WNDCLASSW(ctypes.Structure):
        pass

    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    WNDCLASSW._fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

    def __init__(
        self,
        root: tk.Tk,
        on_show,
        on_hide,
        on_exit,
        on_settings,
    ):
        if os.name != "nt":
            raise RuntimeError("Windows tray icon is only available on Windows.")

        self.root = root
        self.on_show = on_show
        self.on_hide = on_hide
        self.on_exit = on_exit
        self.on_settings = on_settings
        self.user32 = ctypes.windll.user32
        self.shell32 = ctypes.windll.shell32
        self.kernel32 = ctypes.windll.kernel32
        self._configure_api()
        self.hwnd = None
        self.menu: tk.Menu | None = None
        self._class_name = f"OtterTrayWindow{os.getpid()}"
        self._wndproc = self.WNDPROC(self._handle_message)
        self._create_message_window()
        self._create_icon()
        self._create_menu()

    def _configure_api(self) -> None:
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        self.user32.RegisterClassW.argtypes = [ctypes.POINTER(self.WNDCLASSW)]
        self.user32.RegisterClassW.restype = wintypes.ATOM
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.DefWindowProcW.restype = LRESULT
        self.user32.DestroyWindow.argtypes = [wintypes.HWND]
        self.user32.DestroyWindow.restype = wintypes.BOOL
        self.user32.LoadIconW.restype = wintypes.HICON
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.user32.FindWindowW.restype = wintypes.HWND

        self.shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(self.NOTIFYICONDATAW),
        ]
        self.shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def _create_message_window(self) -> None:
        hinstance = self.kernel32.GetModuleHandleW(None)
        wndclass = self.WNDCLASSW()
        wndclass.lpfnWndProc = self._wndproc
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = self._class_name

        atom = self.user32.RegisterClassW(ctypes.byref(wndclass))
        if not atom:
            raise ctypes.WinError()

        hwnd = self.user32.CreateWindowExW(
            0,
            self._class_name,
            "Otter Tray Window",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError()
        self.hwnd = hwnd

    def _create_icon(self) -> None:
        hicon = self.user32.LoadIconW(None, self.IDI_APPLICATION)
        nid = self.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(self.NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = hicon
        nid.szTip = "Otter"

        if not self.user32.FindWindowW("Shell_TrayWnd", None):
            raise RuntimeError("Windows taskbar notification area is not available in this session.")

        if not self.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid)):
            raise ctypes.WinError()
        self._nid = nid

    def _create_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Show", command=self.on_show)
        self.menu.add_command(label="Hide", command=self.on_hide)
        self.menu.add_separator()
        self.menu.add_command(label="Settings...", command=self.on_settings)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.on_exit)

    def _handle_message(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_TRAY:
            event = int(lparam) & 0xFFFF
            if event == self.WM_RBUTTONUP:
                self.root.after(0, self.show_menu)
                return 0
            if event == self.WM_LBUTTONDBLCLK:
                self.root.after(0, self.on_show)
                self.root.after(0, self.on_settings)
                return 0
        if msg == self.WM_DESTROY:
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def show_menu(self) -> None:
        if self.menu is None:
            return

        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        self.user32.SetForegroundWindow(self.hwnd)
        self.menu.tk_popup(point.x, point.y)

    def destroy(self) -> None:
        try:
            if hasattr(self, "_nid"):
                self.shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._nid))
        finally:
            if self.hwnd:
                self.user32.DestroyWindow(self.hwnd)
                self.hwnd = None


class SettingsDialog:
    SOURCE_LABELS = {
        "Auto Local Logs": "auto_local",
        "Claude + Codex Local Logs": "combined_local",
        "Claude Local Logs": "claude_local",
        "Codex Local Logs": "codex_local",
        "Manual": "manual",
        "Local JSON File Watch": "local_json",
        "Claude API (Stretch)": "claude_api",
    }
    SOURCE_VALUES = {value: key for key, value in SOURCE_LABELS.items()}

    def __init__(self, app: "OtterApp"):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("Otter Settings")
        self.window.transient(app.root)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.save_and_close)

        quota = app.config["quota"]
        appearance = app.config["appearance"]

        self.weekly_quota_var = tk.StringVar(value=str(quota["weekly_quota_tokens"]))
        self.tokens_used_var = tk.StringVar(value=str(quota["tokens_used"]))
        self.tokens_scale_var = tk.DoubleVar(value=float(quota["tokens_used"]))
        self.data_source_var = tk.StringVar(
            value=self.SOURCE_VALUES.get(quota["data_source"], "Manual")
        )
        self.poll_interval_var = tk.StringVar(value=str(quota["poll_interval_sec"]))
        self.show_badge_var = tk.BooleanVar(value=appearance["show_percentage_badge"])
        self.status_var = tk.StringVar(value="")

        self._build()
        self._sync_scale_range()

        self.window.grab_set()
        self.window.update_idletasks()
        self._center_over_otter()
        self.window.focus_force()

    def _build(self) -> None:
        frame = ttk.Frame(self.window, padding=14)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Weekly Quota (tokens)").grid(row=0, column=0, sticky="w")
        quota_entry = ttk.Entry(frame, textvariable=self.weekly_quota_var, width=20)
        quota_entry.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=4)
        quota_entry.bind("<FocusOut>", lambda _event: self._sync_scale_range())
        quota_entry.bind("<Return>", lambda _event: self._sync_scale_range())

        ttk.Label(frame, text="Tokens Used This Week").grid(row=1, column=0, sticky="w")
        tokens_entry = ttk.Entry(frame, textvariable=self.tokens_used_var, width=20)
        tokens_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=4)
        tokens_entry.bind("<Return>", lambda _event: self._entry_tokens_changed())
        tokens_entry.bind("<FocusOut>", lambda _event: self._entry_tokens_changed())

        self.tokens_scale = ttk.Scale(
            frame,
            from_=0,
            to=max(1, self.app.config["quota"]["weekly_quota_tokens"]),
            variable=self.tokens_scale_var,
            command=self._scale_tokens_changed,
        )
        self.tokens_scale.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Data Source").grid(row=3, column=0, sticky="w")
        source = ttk.Combobox(
            frame,
            textvariable=self.data_source_var,
            values=list(self.SOURCE_LABELS.keys()),
            state="readonly",
            width=24,
        )
        source.grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=4)

        ttk.Label(frame, text="Poll Interval (sec)").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.poll_interval_var, width=20).grid(
            row=4,
            column=1,
            sticky="ew",
            padx=(12, 0),
            pady=4,
        )

        ttk.Label(frame, text="Usage appears on hover only.").grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(6, 4),
        )

        ttk.Label(frame, textvariable=self.status_var, foreground="#a33").grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(4, 0),
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Save", command=self.save_and_close).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.window.destroy).grid(row=0, column=1)

        frame.columnconfigure(1, weight=1)

    def _center_over_otter(self) -> None:
        root = self.app.root
        x = root.winfo_rootx() + 12
        y = root.winfo_rooty() + 24
        self.window.geometry(f"+{x}+{y}")

    def _parse_values(self) -> tuple[int, int, str, int] | None:
        weekly_quota = int_or_default(self.weekly_quota_var.get(), -1)
        tokens_used = int_or_default(self.tokens_used_var.get(), -1)
        poll_interval = int_or_default(self.poll_interval_var.get(), -1)
        data_source = self.SOURCE_LABELS.get(self.data_source_var.get(), "manual")

        if weekly_quota <= 0:
            self.status_var.set("Weekly quota must be greater than 0.")
            return None
        if tokens_used < 0:
            self.status_var.set("Tokens used cannot be negative.")
            return None
        if poll_interval <= 0:
            self.status_var.set("Poll interval must be greater than 0.")
            return None

        self.status_var.set("")
        return weekly_quota, tokens_used, data_source, poll_interval

    def _sync_scale_range(self) -> None:
        weekly_quota = max(1, int_or_default(self.weekly_quota_var.get(), 1))
        current_tokens = max(0, int_or_default(self.tokens_used_var.get(), 0))
        self.tokens_scale.configure(to=max(weekly_quota, current_tokens, 1))

    def _scale_tokens_changed(self, _value: str) -> None:
        tokens = int(round(self.tokens_scale_var.get()))
        self.tokens_used_var.set(str(tokens))
        self._apply_live_values()

    def _entry_tokens_changed(self) -> None:
        tokens = max(0, int_or_default(self.tokens_used_var.get(), 0))
        self.tokens_scale_var.set(tokens)
        self._sync_scale_range()
        self._apply_live_values()

    def _apply_live_values(self) -> None:
        values = self._parse_values()
        if values is None:
            return
        weekly_quota, tokens_used, data_source, poll_interval = values
        self.app.apply_settings(
            weekly_quota=weekly_quota,
            tokens_used=tokens_used,
            data_source=data_source,
            poll_interval=poll_interval,
            show_percentage_badge=self.show_badge_var.get(),
            save=False,
        )

    def save_and_close(self) -> None:
        values = self._parse_values()
        if values is None:
            return
        weekly_quota, tokens_used, data_source, poll_interval = values
        self.app.apply_settings(
            weekly_quota=weekly_quota,
            tokens_used=tokens_used,
            data_source=data_source,
            poll_interval=poll_interval,
            show_percentage_badge=self.show_badge_var.get(),
            save=True,
        )
        self.window.destroy()


class OtterApp:
    def __init__(
        self,
        root: tk.Tk,
        config_path: Path = CONFIG_PATH,
        usage_path: Path = USAGE_PATH,
        enable_tray: bool = True,
    ):
        self.root = root
        self.config_path = config_path
        self.usage_path = usage_path
        self.config = load_config(config_path)
        self.width = self.config["window"]["width"]
        self.height = self.config["window"]["height"]

        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_origin_x = 0
        self.drag_origin_y = 0
        self.dragging = False
        self.drag_moved = False
        self.hovering_body = False
        self.rng = random.Random()

        self.current_mood = compute_mood(self.burn_pct)
        self.previous_mood = self.current_mood
        self.transition_start = 0.0
        self.transition_ms = 450.0
        self.animation_state = "idle"
        self.animation_started_at = time.monotonic()
        self.animation_duration = ANIMATION_DURATIONS["idle"]
        self.otter_frame_index = 0
        self.last_otter_frame_at = self.animation_started_at

        self.behavior_state = "idle"
        self.behavior_state_ends_at = self.animation_started_at + self.rng.uniform(3.0, 7.0)
        self.walk_direction = 1
        self.walk_speed = 3
        self.walk_target_x: int | None = None
        self.otter_frames_left: dict[str, list[tk.PhotoImage]] = {}
        self.last_usage_poll = 0.0
        self.last_usage_mtime = 0.0
        self.usage_source_label = ""
        self.rate_limit_lines: tuple[str, ...] = ()
        self.settings_dialog: SettingsDialog | None = None
        self.tray: WindowsTrayIcon | None = None
        self.tray_error: str | None = None
        self.closing = False
        self._after_ids: list[str] = []

        self._configure_window()
        self.canvas = tk.Canvas(
            root,
            width=self.width,
            height=self.height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.otter_frames = self._load_otter_frames()
        idle_frame = self.otter_frames["idle"][0]
        self.otter_display_width = idle_frame.width()
        self.otter_display_height = idle_frame.height()
        self.tooltip = Tooltip(root, self._tooltip_text)
        self.context_menu = self._build_context_menu()
        self._bind_events()

        if enable_tray:
            self._init_tray()

        self.refresh_usage(force=True)
        self.render()
        self.schedule(33, self.animate)
        self.schedule(1000, self.heartbeat)

    @property
    def tokens_used(self) -> int:
        return max(0, int(self.config["quota"]["tokens_used"]))

    @property
    def weekly_quota(self) -> int:
        return max(1, int(self.config["quota"]["weekly_quota_tokens"]))

    @property
    def burn_pct(self) -> float:
        return (self.tokens_used / self.weekly_quota) * 100.0

    def _configure_window(self) -> None:
        self.root.title("Otter")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
        except tk.TclError:
            pass
        x = self.config["window"]["x"]
        y = self.config["window"]["y"]
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

    def _init_tray(self) -> None:
        try:
            self.tray = WindowsTrayIcon(
                self.root,
                on_show=self.show,
                on_hide=self.hide,
                on_exit=self.quit,
                on_settings=self.open_settings,
            )
        except Exception as exc:
            self.tray_error = str(exc)

    def _build_context_menu(self) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Settings...", command=self.open_settings)
        menu.add_command(label="Reset Position", command=self.reset_position)
        menu.add_separator()
        menu.add_command(label="Quit", command=self.quit)
        return menu

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", self.on_leave)

    def body_bounds(self) -> tuple[float, float, float, float]:
        cx = self.width / 2
        cy = self.height * 0.50
        rx = max(18.0, self.otter_display_width * 0.48)
        ry = max(16.0, self.otter_display_height * 0.48)
        return cx, cy, rx, ry

    def is_body_hit(self, x: float, y: float) -> bool:
        cx, cy, rx, ry = self.body_bounds()
        if rx <= 0 or ry <= 0:
            return False
        body_hit = ((x - cx) ** 2 / (rx**2)) + ((y - cy) ** 2 / (ry**2)) <= 1.0
        return body_hit

    def play_random_interaction(self) -> None:
        state = self.rng.choice(INTERACTION_ANIMATION_CHOICES)
        self._start_interacting(state, ANIMATION_DURATIONS[state])

    def on_press(self, event) -> None:
        if not self.is_body_hit(event.x, event.y):
            return
        self._start_interacting("pat", 1.3)
        self.dragging = True
        self.drag_moved = False
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.drag_origin_x = self.root.winfo_x()
        self.drag_origin_y = self.root.winfo_y()

    def on_drag(self, event) -> None:
        if not self.dragging:
            return
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        if abs(dx) > 3 or abs(dy) > 3:
            self.drag_moved = True
        self.root.geometry(f"+{self.drag_origin_x + dx}+{self.drag_origin_y + dy}")

    def on_release(self, _event) -> None:
        if not self.dragging:
            return
        self.dragging = False
        if not self.drag_moved:
            self.play_random_interaction()
        self.persist_position()

    def on_double_click(self, event) -> None:
        if self.is_body_hit(event.x, event.y):
            self.open_settings()

    def on_right_click(self, event) -> None:
        if not self.is_body_hit(event.x, event.y):
            return
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def on_motion(self, event) -> None:
        if self.is_body_hit(event.x, event.y):
            if (
                not self.hovering_body
                and self.behavior_state in {"idle", "pausing"}
            ):
                self.play_random_interaction()
            self.hovering_body = True
            self.canvas.configure(cursor="hand2")
            self.tooltip.show(event.x_root, event.y_root)
        elif self.hovering_body:
            self.hovering_body = False
            self.canvas.configure(cursor="")
            self.tooltip.hide()

    def on_leave(self, _event) -> None:
        self.hovering_body = False
        self.canvas.configure(cursor="")
        self.tooltip.hide()

    def _tooltip_text(self) -> str:
        lines = [
            f"Tokens this week: {format_tokens(self.tokens_used)} / {format_tokens(self.weekly_quota)} ({format_percent(self.burn_pct)})"
        ]
        if self.rate_limit_lines:
            lines.extend(self.rate_limit_lines)
        else:
            lines.extend(
                (
                    "5 hr limit: not reported",
                    f"1 week limit: {format_percent(self.burn_pct)} token quota",
                    "Credit limit: not reported",
                )
            )
        if self.usage_source_label:
            lines.append(self.usage_source_label)
        return "\n".join(lines)

    def persist_position(self) -> None:
        self.config["window"]["x"] = int(self.root.winfo_x())
        self.config["window"]["y"] = int(self.root.winfo_y())
        save_config(self.config_path, self.config)

    def apply_settings(
        self,
        *,
        weekly_quota: int,
        tokens_used: int,
        data_source: str,
        poll_interval: int,
        show_percentage_badge: bool,
        save: bool,
    ) -> None:
        self.config["quota"]["weekly_quota_tokens"] = max(1, int(weekly_quota))
        self.config["quota"]["tokens_used"] = max(0, int(tokens_used))
        self.config["quota"]["data_source"] = data_source
        self.config["quota"]["poll_interval_sec"] = max(1, int(poll_interval))
        self.config["appearance"]["show_percentage_badge"] = bool(show_percentage_badge)
        self.refresh_usage(force=True)
        self.update_mood()
        self.render()
        if save:
            save_config(self.config_path, self.config)

    def refresh_usage(self, force: bool = False) -> None:
        source = self.config["quota"]["data_source"]
        if source == "local_json":
            self._refresh_usage_file(force=force)
        elif source in {"auto_local", "combined_local", "claude_local", "codex_local"}:
            self._refresh_local_log_usage(force=force)
        elif source == "manual":
            self.rate_limit_lines = ()
            self.usage_source_label = "Manual entry"
        elif source == "claude_api":
            self.rate_limit_lines = ()
            self.usage_source_label = "Claude API is not configured"
        self.update_mood()

    def _refresh_local_log_usage(self, force: bool = False) -> None:
        now = time.monotonic()
        interval = self.config["quota"]["poll_interval_sec"]
        if not force and now - self.last_usage_poll < interval:
            return
        self.last_usage_poll = now

        week_start = date.fromisoformat(current_week_start())
        snapshot = scan_local_usage(self.config["quota"]["data_source"], week_start)
        quota = snapshot.quota or self.weekly_quota
        changed = (
            self.config["quota"]["tokens_used"] != snapshot.tokens_used
            or self.config["quota"]["weekly_quota_tokens"] != quota
        )
        self.config["quota"]["tokens_used"] = snapshot.tokens_used
        self.config["quota"]["weekly_quota_tokens"] = quota
        self.rate_limit_lines = snapshot.rate_limit_lines
        self.usage_source_label = f"{snapshot.source_label}: {snapshot.records} records this week"
        if changed:
            save_config(self.config_path, self.config)

    def _refresh_usage_file(self, force: bool = False) -> None:
        now = time.monotonic()
        interval = self.config["quota"]["poll_interval_sec"]
        if not force and now - self.last_usage_poll < interval:
            return
        self.last_usage_poll = now

        if not self.usage_path.exists():
            self.rate_limit_lines = ()
            self.usage_source_label = f"Waiting for {self.usage_path.name}"
            return

        try:
            mtime = self.usage_path.stat().st_mtime
            if not force and mtime == self.last_usage_mtime:
                return
            with self.usage_path.open("r", encoding="utf-8") as fh:
                usage = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self.rate_limit_lines = ()
            self.usage_source_label = f"Could not read {self.usage_path.name}"
            return

        if not isinstance(usage, dict):
            self.rate_limit_lines = ()
            self.usage_source_label = f"Invalid {self.usage_path.name}"
            return

        week_start = str(usage.get("week_start", ""))
        tokens_used = max(0, int_or_default(usage.get("tokens_used"), 0))
        quota = max(1, int_or_default(usage.get("quota"), self.weekly_quota))
        current_week = current_week_start()

        if week_start != current_week:
            week_start = current_week
            tokens_used = 0
            usage = {
                "week_start": week_start,
                "tokens_used": tokens_used,
                "quota": quota,
            }
            try:
                with self.usage_path.open("w", encoding="utf-8") as fh:
                    json.dump(usage, fh, indent=2)
                    fh.write("\n")
                mtime = self.usage_path.stat().st_mtime
            except OSError:
                pass

        changed = (
            self.config["quota"]["tokens_used"] != tokens_used
            or self.config["quota"]["weekly_quota_tokens"] != quota
        )
        self.config["quota"]["tokens_used"] = tokens_used
        self.config["quota"]["weekly_quota_tokens"] = quota
        self.last_usage_mtime = mtime
        self.rate_limit_lines = build_rate_limit_lines(usage.get("rate_limits"))
        self.usage_source_label = f"Local JSON: {self.usage_path.name}"
        if changed:
            save_config(self.config_path, self.config)

    def update_mood(self) -> None:
        new_mood = compute_mood(self.burn_pct)
        if new_mood.key != self.current_mood.key:
            self.previous_mood = self.current_mood
            self.current_mood = new_mood
            self.transition_start = time.monotonic()

    def play_animation(self, state: str, duration: float | None = None) -> None:
        if state not in ANIMATION_DURATIONS:
            state = "idle"
        now = time.monotonic()
        self.animation_state = state
        self.animation_started_at = now
        self.animation_duration = duration or ANIMATION_DURATIONS[state]
        self.otter_frame_index = 0
        self.last_otter_frame_at = now

    def _advance_animation(self, now: float) -> None:
        state_ends_at = self.animation_started_at + self.animation_duration
        if self.animation_state not in {"idle", "walk"} and now >= state_ends_at:
            self.animation_state = "idle"
            self.animation_started_at = now
            self.animation_duration = ANIMATION_DURATIONS["idle"]

    def _advance_behavior(self, now: float) -> None:
        if self.behavior_state == "interacting":
            if now >= self.behavior_state_ends_at:
                self._start_idling(now)
            return

        if self.dragging:
            return

        if now < self.behavior_state_ends_at:
            if self.behavior_state == "walking":
                self._move_during_walk(now)
            return

        if self.behavior_state == "idle":
            if self.rng.random() < 0.55:
                self._start_walking(now)
            else:
                self._start_pausing(now)
        elif self.behavior_state == "walking":
            self._start_pausing(now)
        elif self.behavior_state == "pausing":
            if self.rng.random() < 0.55:
                self._start_walking(now)
            else:
                self._start_idling(now)
        else:
            self._start_idling(now)

    def _start_idling(self, now: float) -> None:
        self.behavior_state = "idle"
        self.animation_state = "idle"
        self.animation_started_at = now
        self.animation_duration = ANIMATION_DURATIONS["idle"]
        self.behavior_state_ends_at = now + self.rng.uniform(3.0, 8.0)
        self.walk_target_x = None

    def _start_walking(self, now: float) -> None:
        screen_w = self.root.winfo_screenwidth()
        current_x = self.root.winfo_x()

        # Prefer walking toward the opposite edge of the screen.
        if self.walk_direction > 0:
            self.walk_target_x = screen_w - self.width - 10
        else:
            self.walk_target_x = 10

        # If already close to the target edge, turn around.
        if abs(current_x - self.walk_target_x) < self.width:
            self.walk_direction *= -1
            if self.walk_direction > 0:
                self.walk_target_x = screen_w - self.width - 10
            else:
                self.walk_target_x = 10

        self.behavior_state = "walking"
        self.animation_state = "walk"
        self.animation_started_at = now
        self.animation_duration = 86400.0  # keep walking until behavior ends
        self.behavior_state_ends_at = now + self.rng.uniform(4.0, 12.0)

    def _start_pausing(self, now: float) -> None:
        self.behavior_state = "pausing"
        self.walk_target_x = None
        if self.rng.random() < 0.35 and "sip" in self.otter_frames:
            self.animation_state = "sip"
            self.animation_started_at = now
            self.animation_duration = ANIMATION_DURATIONS["sip"]
        else:
            self.animation_state = "idle"
            self.animation_started_at = now
            self.animation_duration = ANIMATION_DURATIONS["idle"]
        self.behavior_state_ends_at = now + self.rng.uniform(2.0, 5.0)

    def _move_during_walk(self, now: float) -> None:
        if self.walk_target_x is None:
            return
        current_x = self.root.winfo_x()
        current_y = self.root.winfo_y()
        remaining = self.walk_target_x - current_x
        if abs(remaining) <= self.walk_speed:
            self.root.geometry(f"+{self.walk_target_x}+{current_y}")
            self.behavior_state_ends_at = now
            return
        step = self.walk_speed if remaining > 0 else -self.walk_speed
        self.walk_direction = 1 if step > 0 else -1
        self.root.geometry(f"+{current_x + step}+{current_y}")

    def _start_interacting(self, state: str, duration: float) -> None:
        now = time.monotonic()
        self.behavior_state = "interacting"
        self.play_animation(state, duration=duration)
        self.behavior_state_ends_at = now + duration

    def schedule(self, delay_ms: int, callback) -> str | None:
        if self.closing:
            return None
        after_id = self.root.after(delay_ms, callback)
        self._after_ids.append(after_id)
        return after_id

    def cancel_scheduled_callbacks(self) -> None:
        for after_id in self._after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self._after_ids.clear()

    def animate(self) -> None:
        if self.closing:
            return
        self.render()
        self.schedule(33, self.animate)

    def heartbeat(self) -> None:
        if self.closing:
            return
        self.refresh_usage()
        self.schedule(1000, self.heartbeat)

    def render(self) -> None:
        self.canvas.delete("all")
        now = time.monotonic()
        self._advance_animation(now)
        self._advance_behavior(now)
        transition_t = 1.0
        if self.transition_start:
            elapsed_ms = (now - self.transition_start) * 1000.0
            transition_t = min(1.0, elapsed_ms / self.transition_ms)
            if elapsed_ms >= self.transition_ms:
                self.transition_start = 0.0

        bar_color = blend_color(self.previous_mood.bar, self.current_mood.bar, transition_t)
        self._draw_otter(now)
        if self.config["appearance"]["show_percentage_badge"]:
            self._draw_badge(self.width, self.height, bar_color)

    def _otter_frame_subsample(self) -> int:
        scale = max(0.25, min(1.0, self.config["appearance"]["otter_scale"]))
        return max(1, min(4, round(1.0 / scale)))

    @staticmethod
    def _prepare_otter_frame(pil_img: "Image.Image", scale: float) -> "Image.Image":
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")

        # Remove the magenta background and any magenta-tinged fringe pixels
        # before resizing, so LANCZOS can't bleed magenta into the otter or props.
        data = list(pil_img.getdata())
        clean_data = []
        for r, g, b, a in data:
            distance_from_magenta = ((r - 255) ** 2 + g ** 2 + (b - 255) ** 2) ** 0.5
            if distance_from_magenta < 120:
                clean_data.append((r, g, b, 0))
            else:
                clean_data.append((r, g, b, a))
        pil_img.putdata(clean_data)

        if scale != 1.0:
            new_size = (
                max(1, round(pil_img.width * scale)),
                max(1, round(pil_img.height * scale)),
            )
            pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)
            # Clean up any residual magenta halo created by the resize.
            data = list(pil_img.getdata())
            clean_data = []
            for r, g, b, a in data:
                distance_from_magenta = ((r - 255) ** 2 + g ** 2 + (b - 255) ** 2) ** 0.5
                if distance_from_magenta < 120 and a > 0:
                    clean_data.append((r, g, b, 0))
                else:
                    clean_data.append((r, g, b, a))
            pil_img.putdata(clean_data)

        return pil_img

    def _load_otter_frames(self) -> dict[str, list[tk.PhotoImage]]:
        frames_by_state: dict[str, list[tk.PhotoImage]] = {}
        self.otter_frames_left = {}
        scale = self.config["appearance"]["otter_scale"]

        for state in ANIMATION_DURATIONS:
            state_dir = OTTER_ANIMATION_DIR / state
            if not state_dir.exists():
                continue
            frame_paths = sorted(state_dir.glob("*.gif"))
            if not frame_paths:
                continue

            frames = []
            left_frames = []
            for path in frame_paths:
                if PIL_AVAILABLE:
                    pil_img = Image.open(path)
                    frame_img = self._prepare_otter_frame(pil_img, scale)
                    frame = ImageTk.PhotoImage(frame_img)
                    left_frame = ImageTk.PhotoImage(
                        frame_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    )
                else:
                    frame = tk.PhotoImage(
                        data=base64.b64encode(path.read_bytes()).decode("ascii"),
                        format="gif",
                    )
                    subsample = self._otter_frame_subsample()
                    if subsample > 1:
                        frame = frame.subsample(subsample, subsample)
                    left_frame = frame

                frames.append(frame)
                left_frames.append(left_frame)

            frames_by_state[state] = frames
            self.otter_frames_left[state] = left_frames

        if "idle" not in frames_by_state:
            raise FileNotFoundError(f"Missing otter GIF frames in {OTTER_ANIMATION_DIR}")
        return frames_by_state

    def _current_otter_frames(self) -> list[tk.PhotoImage]:
        state = self.animation_state
        if state not in self.otter_frames:
            state = "idle"
        if self.walk_direction < 0 and state in self.otter_frames_left:
            return self.otter_frames_left[state]
        return self.otter_frames[state]

    def _advance_otter_frame(self, now: float, frame_count: int) -> None:
        if frame_count <= 1:
            self.otter_frame_index = 0
            return
        elapsed_ms = (now - self.last_otter_frame_at) * 1000.0
        if elapsed_ms < OTTER_FRAME_MS:
            return
        steps = max(1, int(elapsed_ms // OTTER_FRAME_MS))
        self.otter_frame_index = (self.otter_frame_index + steps) % frame_count
        self.last_otter_frame_at = now

    def _draw_otter(self, now: float) -> None:
        frames = self._current_otter_frames()
        self._advance_otter_frame(now, len(frames))
        frame = frames[self.otter_frame_index % len(frames)]
        self.canvas.create_image(
            self.width / 2,
            self.height * 0.50,
            image=frame,
            anchor=tk.CENTER,
        )

    def _draw_badge(self, w: int, h: int, color: str) -> None:
        display_pct = min(125, max(0, round(self.burn_pct)))
        text = f"{display_pct}%"
        x1 = w * 0.38
        y1 = h * 0.80
        x2 = w * 0.62
        y2 = y1 + 24
        self._rounded_rect(x1, y1, x2, y2, 12, fill=color, outline="")
        self.canvas.create_text(
            w / 2,
            y1 + 12,
            text=text,
            fill="#ffffff",
            font=("Segoe UI", 10, "bold"),
        )

    def _rounded_rect(self, x1, y1, x2, y2, radius, **kwargs) -> None:
        radius = min(radius, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
        self.canvas.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, style=tk.PIESLICE, **kwargs)
        self.canvas.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, style=tk.PIESLICE, **kwargs)
        self.canvas.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, style=tk.PIESLICE, **kwargs)
        self.canvas.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, style=tk.PIESLICE, **kwargs)
        self.canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, **kwargs)
        self.canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, **kwargs)

    def open_settings(self) -> None:
        if self.settings_dialog and self.settings_dialog.window.winfo_exists():
            self.settings_dialog.window.lift()
            self.settings_dialog.window.focus_force()
            return
        self.settings_dialog = SettingsDialog(self)

    def reset_position(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - self.width) // 2)
        y = max(0, (screen_h - self.height) // 2)
        self.root.geometry(f"+{x}+{y}")
        self.persist_position()

    def show(self) -> None:
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()

    def hide(self) -> None:
        self.persist_position()
        self.root.withdraw()

    def quit(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.persist_position()
        self.cancel_scheduled_callbacks()
        self.tooltip.destroy()
        if self.tray is not None:
            self.tray.destroy()
        self.root.destroy()


class FakeEvent:
    def __init__(self, x: int, y: int, x_root: int, y_root: int):
        self.x = x
        self.y = y
        self.x_root = x_root
        self.y_root = y_root


def run_self_test() -> int:
    expected = [
        (0, "furious"),
        (10, "furious"),
        (11, "sad"),
        (30, "sad"),
        (31, "neutral"),
        (65, "neutral"),
        (66, "happy"),
        (99, "happy"),
        (100, "overjoyed"),
        (125, "overjoyed"),
    ]
    for pct, mood_key in expected:
        actual = compute_mood(pct).key
        assert actual == mood_key, f"{pct}% produced {actual}, expected {mood_key}"

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        usage_path = Path(tmp) / "usage.json"
        save_config(config_path, DEFAULT_CONFIG)

        root = tk.Tk()
        app = OtterApp(root, config_path=config_path, usage_path=usage_path, enable_tray=False)
        root.update()

        start_x = root.winfo_x()
        start_y = root.winfo_y()
        otter_x = app.width // 2
        otter_y = app.height // 2
        app.on_press(FakeEvent(otter_x, otter_y, 400, 400))
        app.on_drag(FakeEvent(otter_x, otter_y, 460, 445))
        app.on_release(FakeEvent(otter_x, otter_y, 460, 445))
        root.update()
        assert root.winfo_x() == start_x + 60
        assert root.winfo_y() == start_y + 45

        lines = build_rate_limit_lines(
            {
                "primary": {"used_percent": 23, "window_minutes": 300},
                "secondary": {"used_percent": 79, "window_minutes": 10080},
                "credits": None,
            }
        )
        assert lines == (
            "5 hr limit: 23% used",
            "1 week limit: 79% used",
            "Credit limit: not reported",
        )

        seen = []
        for tokens in (0, 150_000, 500_000, 800_000, 1_000_000):
            app.apply_settings(
                weekly_quota=1_000_000,
                tokens_used=tokens,
                data_source="manual",
                poll_interval=30,
                show_percentage_badge=True,
                save=False,
            )
            seen.append(app.current_mood.key)
            root.update()
        assert seen == ["furious", "sad", "neutral", "happy", "overjoyed"]

        app.open_settings()
        root.update()
        assert app.settings_dialog is not None
        assert app.settings_dialog.window.winfo_exists()
        app.settings_dialog.window.destroy()
        root.update()

        app.quit()
        root.update()

    print("self-test passed: dragging, mood transitions, settings popup")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Otter - Windows desktop quota otter")
    parser.add_argument("--self-test", action="store_true", help="run a local GUI smoke test and exit")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    root = tk.Tk()
    app = OtterApp(root)
    if app.tray_error:
        messagebox.showwarning(
            "Otter tray unavailable",
            "Otter is running, but Windows tray setup failed. "
            f"Right-click Otter for Settings and Quit.\n\n{app.tray_error}",
        )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
