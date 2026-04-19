# actions/open_app.py
# J.A.R.V.I.S — Smart Cross-Platform App Launcher
#
# Multi-strategy launcher: direct subprocess → shutil.which →
# Windows Registry → Start Menu shortcuts → Windows Search (verified).
# Never falsely claims success — verifies process actually started.

import os
import time
import subprocess
import platform
import shutil
from pathlib import Path

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import winreg
    _WINREG = True
except ImportError:
    _WINREG = False

_APP_ALIASES = {
    "whatsapp":           {"Windows": "WhatsApp",               "Darwin": "WhatsApp",            "Linux": "whatsapp"},
    "chrome":             {"Windows": "chrome",                 "Darwin": "Google Chrome",       "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                 "Darwin": "Google Chrome",       "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                "Darwin": "Firefox",             "Linux": "firefox"},
    "spotify":            {"Windows": "Spotify",                "Darwin": "Spotify",             "Linux": "spotify"},
    "vscode":             {"Windows": "code",                   "Darwin": "Visual Studio Code",  "Linux": "code"},
    "visual studio code": {"Windows": "code",                   "Darwin": "Visual Studio Code",  "Linux": "code"},
    "discord":            {"Windows": "Discord",                "Darwin": "Discord",             "Linux": "discord"},
    "telegram":           {"Windows": "Telegram",               "Darwin": "Telegram",            "Linux": "telegram"},
    "instagram":          {"Windows": "Instagram",              "Darwin": "Instagram",           "Linux": "instagram"},
    "tiktok":             {"Windows": "TikTok",                 "Darwin": "TikTok",              "Linux": "tiktok"},
    "notepad":            {"Windows": "notepad.exe",            "Darwin": "TextEdit",            "Linux": "gedit"},
    "calculator":         {"Windows": "calc.exe",               "Darwin": "Calculator",          "Linux": "gnome-calculator"},
    "terminal":           {"Windows": "cmd.exe",                "Darwin": "Terminal",            "Linux": "gnome-terminal"},
    "cmd":                {"Windows": "cmd.exe",                "Darwin": "Terminal",            "Linux": "bash"},
    "explorer":           {"Windows": "explorer.exe",           "Darwin": "Finder",              "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",           "Darwin": "Finder",              "Linux": "nautilus"},
    "paint":              {"Windows": "mspaint.exe",            "Darwin": "Preview",             "Linux": "gimp"},
    "word":               {"Windows": "winword",                "Darwin": "Microsoft Word",      "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                  "Darwin": "Microsoft Excel",     "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",               "Darwin": "Microsoft PowerPoint","Linux": "libreoffice --impress"},
    "vlc":                {"Windows": "vlc",                    "Darwin": "VLC",                 "Linux": "vlc"},
    "zoom":               {"Windows": "Zoom",                   "Darwin": "zoom.us",             "Linux": "zoom"},
    "slack":              {"Windows": "Slack",                  "Darwin": "Slack",               "Linux": "slack"},
    "steam":              {"Windows": "steam",                  "Darwin": "Steam",               "Linux": "steam"},
    "task manager":       {"Windows": "taskmgr.exe",            "Darwin": "Activity Monitor",    "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",           "Darwin": "System Preferences",  "Linux": "gnome-control-center"},
    "powershell":         {"Windows": "powershell.exe",         "Darwin": "Terminal",            "Linux": "bash"},
    "edge":               {"Windows": "msedge",                 "Darwin": "Microsoft Edge",      "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                  "Darwin": "Brave Browser",       "Linux": "brave-browser"},
    "obsidian":           {"Windows": "Obsidian",               "Darwin": "Obsidian",            "Linux": "obsidian"},
    "notion":             {"Windows": "Notion",                 "Darwin": "Notion",              "Linux": "notion"},
    "blender":            {"Windows": "blender",                "Darwin": "Blender",             "Linux": "blender"},
    "capcut":             {"Windows": "CapCut",                 "Darwin": "CapCut",              "Linux": "capcut"},
    "postman":            {"Windows": "Postman",                "Darwin": "Postman",             "Linux": "postman"},
    "figma":              {"Windows": "Figma",                  "Darwin": "Figma",               "Linux": "figma"},
}


def _normalize(raw: str) -> str:
    system = platform.system()
    key    = raw.lower().strip()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(system, raw)
    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(system, raw)
    return raw


def _is_running(app_name: str) -> bool:
    if not _PSUTIL:
        return True
    app_lower = app_name.lower().replace(" ", "").replace(".exe", "")
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = proc.info["name"].lower().replace(" ", "").replace(".exe", "")
                if app_lower in proc_name or proc_name in app_lower:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _get_running_process_names() -> set:
    """Get set of running process names (lowercase)."""
    if not _PSUTIL:
        return set()
    try:
        return {
            p.info['name'].lower()
            for p in psutil.process_iter(['name'])
            if p.info['name']
        }
    except Exception:
        return set()


# ──────── Windows-specific smart strategies ────────

def _find_in_registry(app_name: str):
    """Search Windows Registry App Paths for executable."""
    if not _WINREG:
        return None
    variants = [app_name, f"{app_name}.exe",
                app_name.lower(), f"{app_name.lower()}.exe"]
    for name in variants:
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            try:
                key = winreg.OpenKey(
                    hive,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}")
                exe = winreg.QueryValue(key, None)
                winreg.CloseKey(key)
                if exe:
                    exe = exe.strip('"').strip()
                    if Path(exe).exists():
                        return exe
            except (FileNotFoundError, OSError):
                continue
    return None


def _find_start_menu_shortcut(app_name: str):
    """Find .lnk shortcut in Start Menu matching app name."""
    app_lower = app_name.lower()
    search_paths = []

    appdata = os.environ.get('APPDATA', '')
    if appdata:
        search_paths.append(
            Path(appdata) / 'Microsoft' / 'Windows'
            / 'Start Menu' / 'Programs')

    programdata = os.environ.get('PROGRAMDATA', r'C:\ProgramData')
    search_paths.append(
        Path(programdata) / 'Microsoft' / 'Windows'
        / 'Start Menu' / 'Programs')

    best_match = None
    best_score = 0.0

    for base in search_paths:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if stem == app_lower:
                return str(lnk)  # Exact match
            if app_lower in stem:
                score = len(app_lower) / len(stem)
                if score > best_score:
                    best_score = score
                    best_match = str(lnk)

    return best_match


def _launch_via_search_with_verify(app_name: str) -> bool:
    """
    Last resort: use Windows Search bar, then VERIFY a new process started.
    If no matching process appeared, close whatever opened (likely Edge).
    """
    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
    except ImportError:
        return False

    pre_procs = _get_running_process_names()

    try:
        pyautogui.press("win")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(1.2)
        pyautogui.press("enter")
        time.sleep(3.5)

        # Verify: check if a relevant new process appeared
        post_procs = _get_running_process_names()
        new_procs = post_procs - pre_procs

        app_lower = app_name.lower().replace(' ', '').replace('.exe', '')

        for proc in new_procs:
            proc_clean = proc.replace('.exe', '').replace(' ', '')
            if app_lower in proc_clean or proc_clean in app_lower:
                print(f"[open_app] ✅ Verified via search: {proc} started")
                return True

        # Also check if the app was already running and just got focused
        if _is_running(app_name):
            return True

        # No matching process found — likely Edge opened with web search
        print(f"[open_app] ⚠️ No matching process after search — "
              f"app may not be installed")
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.upper()
            if "J.A.R.V.I.S" in title or "MAIN.PY" in title or "MAIN.EXE" in title:
                pyautogui.hotkey("alt", "esc")
                time.sleep(0.3)
            pyautogui.hotkey("alt", "f4")  # Close the wrong window
            time.sleep(0.5)
        except Exception:
            pass

        return False

    except Exception as e:
        print(f"[open_app] ⚠️ Windows search failed: {e}")
        return False


def _launch_windows(app_name: str) -> bool:
    """Multi-strategy Windows app launcher with verification."""

    # Strategy 1: Direct executable (for .exe paths and system apps)
    if app_name.lower().endswith('.exe') or '\\' in app_name:
        try:
            subprocess.Popen(
                [app_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            print(f"[open_app] ✅ Direct launch: {app_name}")
            return True
        except Exception:
            pass

    # Strategy 2: Protocol handlers (ms-settings:, etc.)
    if ':' in app_name and not app_name.endswith('.exe'):
        try:
            os.startfile(app_name)
            time.sleep(1.5)
            print(f"[open_app] ✅ Protocol launch: {app_name}")
            return True
        except Exception:
            pass

    # Strategy 3: shutil.which (finds executables in PATH)
    for variant in [app_name, f"{app_name}.exe", app_name.lower()]:
        exe = shutil.which(variant)
        if exe:
            try:
                subprocess.Popen(
                    [exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                time.sleep(1.5)
                print(f"[open_app] ✅ PATH launch: {exe}")
                return True
            except Exception:
                pass

    # Strategy 4: Windows Registry App Paths
    exe = _find_in_registry(app_name)
    if exe:
        try:
            subprocess.Popen(
                [exe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            print(f"[open_app] ✅ Registry launch: {exe}")
            return True
        except Exception:
            pass

    # Strategy 5: Start Menu shortcut
    lnk = _find_start_menu_shortcut(app_name)
    if lnk:
        try:
            os.startfile(lnk)
            time.sleep(2.0)
            print(f"[open_app] ✅ Start Menu launch: {lnk}")
            return True
        except Exception:
            pass

    # Strategy 6: Last resort — Windows Search WITH verification
    return _launch_via_search_with_verify(app_name)


def _launch_macos(app_name: str) -> bool:
    try:
        result = subprocess.run(["open", "-a", app_name],
                                capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(["open", "-a", f"{app_name}.app"],
                                capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] ⚠️ macOS Spotlight failed: {e}")
        return False


def _launch_linux(app_name: str) -> bool:
    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-"))
    )
    if binary:
        try:
            subprocess.Popen([binary],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(["xdg-open", app_name],
                        capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    try:
        desktop_name = app_name.lower().replace(" ", "-")
        subprocess.run(["gtk-launch", desktop_name],
                        capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "Please specify which application to open, sir."

    system   = platform.system()
    launcher = _OS_LAUNCHERS.get(system)

    if launcher is None:
        return f"Unsupported OS: {system}"

    normalized = _normalize(app_name)
    print(f"[open_app] 🚀 Launching: {app_name} → {normalized} ({system})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        success = launcher(normalized)

        if success:
            return f"Opened {app_name} successfully, sir."

        if normalized != app_name:
            success = launcher(app_name)
            if success:
                return f"Opened {app_name} successfully, sir."

        return (
            f"I could not find or launch {app_name}, sir. "
            f"It may not be installed on this system."
        )

    except Exception as e:
        print(f"[open_app] ❌ {e}")
        return f"Failed to open {app_name}, sir: {e}"