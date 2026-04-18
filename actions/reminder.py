# actions/reminder.py
# Cross-platform reminder: Windows Task Scheduler / macOS launchd+osascript / Linux at

import subprocess
import os
import sys
import platform
from datetime import datetime


def _set_reminder_windows(target_dt: datetime, safe_message: str,
                          task_name: str, player=None) -> str:
    """Windows: uses Task Scheduler + win10toast notification."""
    python_exe = sys.executable
    if python_exe.lower().endswith("python.exe"):
        pythonw = python_exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw):
            python_exe = pythonw

    temp_dir      = os.environ.get("TEMP", "C:\\Temp")
    notify_script = os.path.join(temp_dir, f"{task_name}.pyw")
    project_root  = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )

    script_code = f'''import sys, os, time
sys.path.insert(0, r"{project_root}")

try:
    import winsound
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 200)
        time.sleep(0.1)
except Exception:
    pass

try:
    from win10toast import ToastNotifier
    ToastNotifier().show_toast(
        "MARK Reminder",
        "{safe_message}",
        duration=15,
        threaded=False
    )
except Exception:
    try:
        import subprocess
        subprocess.run(["msg", "*", "/TIME:30", "{safe_message}"], shell=True)
    except Exception:
        pass

time.sleep(3)
try:
    os.remove(__file__)
except Exception:
    pass
'''
    with open(notify_script, "w", encoding="utf-8") as f:
        f.write(script_code)

    xml_content = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>MARK Reminder: {safe_message}</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{notify_script}"</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
</Task>'''

    xml_path = os.path.join(temp_dir, f"{task_name}.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml_content)

    result = subprocess.run(
        f'schtasks /Create /TN "{task_name}" /XML "{xml_path}" /F',
        shell=True, capture_output=True, text=True
    )

    try:
        os.remove(xml_path)
    except Exception:
        pass

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        print(f"[Reminder] schtasks failed: {err}")
        try:
            os.remove(notify_script)
        except Exception:
            pass
        return "I couldn't schedule the reminder due to a system error."

    return None  # success


def _set_reminder_macos(target_dt: datetime, safe_message: str,
                        task_name: str, player=None) -> str:
    """macOS: uses 'at' command + osascript notification."""
    # Create the notification script
    notify_script = f'/tmp/{task_name}.sh'
    script_code = (
        f'#!/bin/bash\n'
        f'osascript -e \'display notification "{safe_message}" '
        f'with title "JARVIS Reminder" sound name "Glass"\'\n'
        f'rm -f "{notify_script}"\n'
    )

    with open(notify_script, "w") as f:
        f.write(script_code)
    os.chmod(notify_script, 0o755)

    # Schedule using 'at' command
    at_time = target_dt.strftime("%H:%M %m/%d/%Y")
    try:
        result = subprocess.run(
            f'echo "{notify_script}" | at {at_time}',
            shell=True, capture_output=True, text=True
        )
        if result.returncode != 0:
            # Fallback: use launchd plist
            return _set_reminder_macos_launchd(
                target_dt, safe_message, task_name, notify_script)
    except Exception:
        return _set_reminder_macos_launchd(
            target_dt, safe_message, task_name, notify_script)

    return None  # success


def _set_reminder_macos_launchd(target_dt: datetime, safe_message: str,
                                task_name: str, notify_script: str) -> str:
    """Fallback: use launchd plist for scheduling on macOS."""
    plist_path = os.path.expanduser(
        f"~/Library/LaunchAgents/com.jarvis.{task_name}.plist"
    )

    plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.{task_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{notify_script}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Month</key>
        <integer>{target_dt.month}</integer>
        <key>Day</key>
        <integer>{target_dt.day}</integer>
        <key>Hour</key>
        <integer>{target_dt.hour}</integer>
        <key>Minute</key>
        <integer>{target_dt.minute}</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>'''

    try:
        with open(plist_path, "w") as f:
            f.write(plist_content)
        subprocess.run(["launchctl", "load", plist_path],
                       capture_output=True, timeout=5)
        return None  # success
    except Exception as e:
        return f"Could not schedule reminder: {e}"


def _set_reminder_linux(target_dt: datetime, safe_message: str,
                        task_name: str, player=None) -> str:
    """Linux: uses 'at' command + notify-send."""
    at_time = target_dt.strftime("%H:%M %Y-%m-%d")
    cmd = f'echo \'notify-send "JARVIS Reminder" "{safe_message}"\' | at {at_time}'
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return f"'at' command failed: {result.stderr.strip()}"
        return None  # success
    except Exception as e:
        return f"Could not schedule reminder: {e}"


def reminder(
    parameters: dict,
    response: str | None = None,
    player=None,
    session_memory=None
) -> str:
    """
    Sets a timed reminder (cross-platform).

    parameters:
        - date    (str) YYYY-MM-DD
        - time    (str) HH:MM
        - message (str)

    Returns a result string — Live API voices it automatically.
    """

    date_str = parameters.get("date")
    time_str = parameters.get("time")
    message  = parameters.get("message", "Reminder")

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

        if target_dt <= datetime.now():
            return "That time is already in the past."

        task_name    = f"MARKReminder_{target_dt.strftime('%Y%m%d_%H%M')}"
        safe_message = message.replace('"', '').replace("'", "").strip()[:200]

        system = platform.system()
        if system == "Windows":
            error = _set_reminder_windows(target_dt, safe_message, task_name, player)
        elif system == "Darwin":
            error = _set_reminder_macos(target_dt, safe_message, task_name, player)
        else:
            error = _set_reminder_linux(target_dt, safe_message, task_name, player)

        if error:
            return error

        if player:
            player.write_log(f"[reminder] set for {date_str} {time_str}")

        return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."

    except ValueError:
        return "I couldn't understand that date or time format."

    except Exception as e:
        return f"Something went wrong while scheduling the reminder: {str(e)[:80]}"