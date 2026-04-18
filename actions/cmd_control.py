import subprocess
import sys
import json
import re
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_platform() -> str:
    if sys.platform == "win32":  return "windows"
    if sys.platform == "darwin": return "macos"
    return "linux"

WIN_COMMAND_MAP = [
    (["disk space", "disk usage", "storage", "free space", "c drive space"],
     "wmic logicaldisk get caption,freespace,size /format:list", False),
    (["running processes", "list processes", "show processes", "active processes", "tasklist"],
     "tasklist /fo table", False),
    (["ip address", "my ip", "network info", "ipconfig"],
     "ipconfig /all", False),
    (["ping", "internet connection", "connected to internet"],
     "ping -n 4 google.com", False),
    (["open ports", "listening ports", "netstat"],
     "netstat -an | findstr LISTENING", False),
    (["wifi networks", "available wifi", "wireless networks"],
     "netsh wlan show networks", False),
    (["system info", "computer info", "hardware info", "pc info", "specs"],
     "systeminfo", False),
    (["cpu usage", "processor usage"],
     "wmic cpu get loadpercentage", False),
    (["memory usage", "ram usage"],
     "wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value", False),
    (["windows version", "os version"],
     "ver", False),
    (["installed programs", "installed software", "installed apps"],
     "wmic product get name,version /format:table", False),
    (["battery", "battery level", "power status"],
     "powershell (Get-WmiObject -Class Win32_Battery).EstimatedChargeRemaining", False),
    (["current time", "what time", "system time"],
     "time /t", False),
    (["current date", "what date", "system date"],
     "date /t", False),
    (["desktop files", "files on desktop"],
     f'dir "{Path.home() / "Desktop"}"', False),
    (["downloads", "files in downloads"],
     f'dir "{Path.home() / "Downloads"}"', False),
    (["large files", "biggest files", "largest files"],
     'powershell "Get-ChildItem C:\\ -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 10 FullName,Length | Format-Table"', False),
]

MAC_COMMAND_MAP = [
    (["disk space", "disk usage", "storage", "free space"],
     "df -h", False),
    (["running processes", "list processes", "show processes", "active processes"],
     "ps aux | head -30", False),
    (["ip address", "my ip", "network info"],
     "ifconfig | grep inet", False),
    (["ping", "internet connection", "connected to internet"],
     "ping -c 4 google.com", False),
    (["open ports", "listening ports", "netstat"],
     "lsof -iTCP -sTCP:LISTEN -n -P", False),
    (["wifi networks", "available wifi", "wireless networks"],
     "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s", False),
    (["system info", "computer info", "hardware info", "pc info", "specs", "mac info"],
     "system_profiler SPHardwareDataType", False),
    (["cpu usage", "processor usage"],
     "top -l 1 | head -12", False),
    (["memory usage", "ram usage"],
     "vm_stat | head -10", False),
    (["os version", "mac version", "macos version"],
     "sw_vers", False),
    (["installed programs", "installed software", "installed apps"],
     "ls /Applications", False),
    (["battery", "battery level", "power status"],
     "pmset -g batt", False),
    (["current time", "what time", "system time"],
     "date '+%H:%M:%S'", False),
    (["current date", "what date", "system date"],
     "date '+%Y-%m-%d'", False),
    (["desktop files", "files on desktop"],
     f'ls -la "{Path.home() / "Desktop"}"', False),
    (["downloads", "files in downloads"],
     f'ls -la "{Path.home() / "Downloads"}"', False),
    (["large files", "biggest files", "largest files"],
     'find / -type f -exec du -h {} + 2>/dev/null | sort -rh | head -10', False),
]

def _find_hardcoded(task: str) -> str | None:
    task_lower = task.lower()
    plat = _get_platform()

    # Text editor shortcut
    if "notepad" in task_lower or any(ext in task_lower for ext in [".txt", ".log", ".md", ".csv"]):
        file_match = re.search(r'[\"\']?([\S]+\.(?:txt|log|md|csv|json|xml))[\"\']?', task, re.IGNORECASE)
        if file_match:
            filename = file_match.group(1)
            desktop  = Path.home() / "Desktop"
            filepath = Path(filename) if Path(filename).is_absolute() else desktop / filename
            if plat == "macos":
                return f'open -a TextEdit "{filepath}"'
            elif plat == "linux":
                return f'xdg-open "{filepath}"'
            return f'notepad "{filepath}"'
        if "notepad" in task_lower:
            if plat == "macos":  return 'open -a TextEdit'
            if plat == "linux":  return 'gedit'
            return "notepad"

    pip_match = re.search(r"install\s+([\w\-]+)", task_lower)
    if pip_match:
        package = pip_match.group(1)
        return f"pip install {package}"

    # Select the right command map for this OS
    cmd_map = MAC_COMMAND_MAP if plat == "macos" else WIN_COMMAND_MAP
    for keywords, command, _ in cmd_map:
        if command and any(kw in task_lower for kw in keywords):
            return command

    return None

BLOCKED_PATTERNS = [
    r"\brm\s+-rf\b", r"\brmdir\s+/s\b", r"\bdel\s+/[fqs]",
    r"\bformat\b", r"\bdiskpart\b", r"\bfdisk\b",
    r"\breg\s+(delete|add)\b", r"\bbcdedit\b",
    r"\bnet\s+localgroup\b",
    r"\bshutdown\b", r"\brestart-computer\b",
    r"\bstop-process\b", r"\bkill\s+-9\b", r"\btaskkill\b",
    r"\beval\b", r"\b__import__\b",
]
_BLOCKED_RE = re.compile("|".join(BLOCKED_PATTERNS), re.IGNORECASE)


def _is_safe(command: str) -> tuple[bool, str]:
    match = _BLOCKED_RE.search(command)
    if match:
        return False, f"Blocked pattern: '{match.group()}'"
    return True, "OK"

def _ask_gemini(task: str) -> str:
    try:
        from core.gemini_client import ask
        plat = _get_platform()

        if plat == "macos":
            shell_info = "macOS zsh/bash terminal command"
        elif plat == "linux":
            shell_info = "Linux bash terminal command"
        else:
            shell_info = "Windows CMD command"

        prompt = (
            f"Convert this request to a single {shell_info}.\n"
            f"The OS is: {plat}.\n"
            f"Output ONLY the command. No explanation, no markdown, no backticks.\n"
            f"If unsafe or impossible, output: UNSAFE\n\n"
            f"Request: {task}\n\nCommand:"
        )
        command = ask(prompt, model="gemini-2.5-flash-lite")
        command = command.strip("`").strip()
        if command.startswith("```"):
            lines   = command.split("\n")
            command = "\n".join(lines[1:-1]).strip()
        return command
    except Exception as e:
        return f"ERROR: {e}"

def _run_silent(command: str, timeout: int = 20) -> str:
    try:
        platform = _get_platform()
        if platform == "windows":
            is_ps = command.strip().lower().startswith("powershell")
            if is_ps:
                cmd_inner = re.sub(r'^powershell\s+"?', '', command, flags=re.IGNORECASE).rstrip('"')
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd_inner],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout
                )
            else:
                result = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True, text=True,
                    encoding="cp1252", errors="replace",
                    timeout=timeout, cwd=str(Path.home())
                )
        else:
            shell = "/bin/zsh" if platform == "macos" else "/bin/bash"
            result = subprocess.run(
                command, shell=True, executable=shell,
                capture_output=True, text=True,
                errors="replace", timeout=timeout,
                cwd=str(Path.home())
            )

        output = result.stdout.strip()
        error  = result.stderr.strip()
        if output:  return output[:2000]
        if error:   return f"[stderr]: {error[:500]}"
        return "Command executed with no output."

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as e:
        return f"Execution error: {e}"


def _run_visible(command: str) -> None:
    try:
        platform = _get_platform()
        if platform == "windows":
            subprocess.Popen(
                f'cmd /k "{command}"',
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        elif platform == "macos":
            subprocess.Popen(["osascript", "-e",
                f'tell application "Terminal" to do script "{command}"'])
        else:
            for term in ["gnome-terminal", "xterm", "konsole"]:
                try:
                    subprocess.Popen([term, "--", "bash", "-c", f"{command}; exec bash"])
                    break
                except FileNotFoundError:
                    continue
    except Exception as e:
        print(f"[CMD] ⚠️ Terminal open failed: {e}")


def cmd_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    task    = (parameters or {}).get("task", "").strip()
    command = (parameters or {}).get("command", "").strip()
    visible = (parameters or {}).get("visible", True)

    if not task and not command:
        return "Please describe what you want to do, sir."

    if not command:
        command = _find_hardcoded(task)
        if command:
            print(f"[CMD] ⚡ Hardcoded: {command[:80]}")
        else:
            print(f"[CMD] 🤖 Gemini fallback for: {task}")
            command = _ask_gemini(task)
            print(f"[CMD] ✅ Generated: {command[:80]}")
            if command == "UNSAFE":
                return "I cannot generate a safe command for that request, sir."
            if command.startswith("ERROR:"):
                return f"Could not generate command: {command}"

    safe, reason = _is_safe(command)
    if not safe:
        return f"Blocked for safety: {reason}"

    if player:
        player.write_log(f"[CMD] {command[:60]}")

    if any(x in command.lower() for x in ["notepad", "explorer", "start "]):
        subprocess.Popen(command, shell=True)
        return f"Opened: {command}"

    if visible:
        _run_visible(command)
        output = _run_silent(command)
        return f"Terminal opened.\n\nOutput:\n{output}"
    else:
        return _run_silent(command)