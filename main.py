import asyncio

try:
    import websockets.asyncio.client as _ws_client
except ImportError:
    try:
        import websockets.client as _ws_client
    except ImportError:
        import websockets as _ws_client

# Fix for websockets timing out on VPNs (default 10s is too short for some proxies)
_orig_ws_connect = _ws_client.connect
def _patched_ws_connect(*args, **kwargs):
    if 'open_timeout' not in kwargs:
        kwargs['open_timeout'] = 60
    return _orig_ws_connect(*args, **kwargs)
_ws_client.connect = _patched_ws_connect
import threading
import struct
import json
import re
import sys

import os
from pathlib import Path

def _get_user_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

DEBUG_LOG_FILE = _get_user_dir() / "JARVIS_DEBUG.log"

class _FileDebugWriter:
    def __init__(self, prefix=""):
        self.prefix = prefix
        self.buffer = ""
        # Create file if missing
        try:
            with open(DEBUG_LOG_FILE, "a+", encoding="utf-8") as f:
                f.write(f"\n--- MAIN MODULE BOOT: {self.prefix} ---\n")
        except Exception:
            pass

    def write(self, s):
        try:
            if isinstance(s, bytes): s = s.decode("utf-8", "ignore")
            self.buffer += s
            if "\n" in self.buffer:
                lines = self.buffer.split("\n")
                self.buffer = lines.pop()
                with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                    for line in lines:
                        if line.strip(): f.write(f"{self.prefix} {line}\n")
        except Exception:
            pass

    def flush(self):
        pass

    def reconfigure(self, *args, **kwargs):
        pass

# Force pipe everything to debug file if we are in .exe or can't reliably print
if getattr(sys, "frozen", False):
    sys.stdout = _FileDebugWriter("[STDOUT]")
    sys.stderr = _FileDebugWriter("[STDERR]")
else:
    try:
        print("", end="")
        _stdout_encoding = getattr(sys.stdout, 'encoding', None)
        if _stdout_encoding and hasattr(sys.stdout, 'reconfigure') and _stdout_encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        sys.stdout = _FileDebugWriter("[STDOUT]")
    
    try:
        print("", file=sys.stderr, end="")
    except Exception:
        sys.stderr = _FileDebugWriter("[STDERR]")
import traceback
from pathlib import Path
import urllib.request

# Fix for websockets timing out on Windows proxies due to local DNS blocking
_orig_getproxies = urllib.request.getproxies
def _patched_getproxies():
    p = _orig_getproxies()
    # Use socks5h to force REMOTE DNS resolution over the VPN proxy.
    # This bypasses local ISP DNS blocks that cause timeouts.
    for k, v in list(p.items()):
        if isinstance(v, str) and v.startswith("socks://"):
            p[k] = v.replace("socks://", "socks5h://")
    return p
urllib.request.getproxies = _patched_getproxies

from core.logger import logger

import pyaudio
from google import genai
from google.genai import types
import time 
from ui_web import JarvisUI
from memory.memory_manager import load_memory, update_memory, format_memory_for_prompt

from agent.task_queue import get_queue

from actions.flight_finder import flight_finder
from actions.open_app         import open_app
from actions.weather_report   import weather_action
from actions.send_message     import send_message
from actions.reminder         import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor import screen_process
from actions.youtube_video    import youtube_video
from actions.cmd_control      import cmd_control
from actions.desktop          import desktop_control
from actions.browser_control  import browser_control
from actions.file_controller  import file_controller
from actions.code_helper      import code_helper
from actions.dev_agent        import dev_agent
from actions.web_search       import web_search as web_search_action
from actions.computer_control import computer_control
from actions.bluetooth_control import bluetooth_control


class _SleepInterrupt(Exception):
    """Raised by _sleep_watcher to break the active session for sleep mode."""
    pass

class SessionRotationError(Exception):
    """Raised when the conversation turn limit is reached to force a token-clearing reconnection."""
    pass


def get_bundle_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def get_user_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BUNDLE_DIR      = get_bundle_dir()
USER_DIR        = get_user_dir()
BASE_DIR        = Path(__file__).resolve().parent

API_CONFIG_PATH = USER_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BUNDLE_DIR / "core" / "prompt.txt"
# LIVE_MODEL is now dynamic. We keep a default and load from config if available.
# LIVE_MODEL default
from core.gemini_client import ModelRegistry, _mark_model_exhausted, get_api_key
_DEFAULT_LIVE = "models/gemini-3.1-flash-live-preview"
FORMAT              = pyaudio.paInt16
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

pya = pyaudio.PyAudio()


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_memory_turn_counter  = 0
_memory_turn_lock     = threading.Lock()
_MEMORY_EVERY_N_TURNS = 5
_last_memory_input    = ""

# ── Token Economy: Conversation buffer for cross-session context ──
_conversation_buffer  = []          # list of {"user": ..., "jarvis": ...} dicts
_MAX_CONV_BUFFER      = 5           # Keep only last 5 exchanges
_last_session_summary = ""          # Compact summary injected on reconnect
_conv_buffer_lock     = threading.Lock()


def _append_conversation(user_text: str, jarvis_text: str) -> None:
    """Thread-safe append to conversation buffer (ring buffer, max 5)."""
    if not user_text and not jarvis_text:
        return
    with _conv_buffer_lock:
        _conversation_buffer.append({
            "user": (user_text or "")[:200],
            "jarvis": (jarvis_text or "")[:200],
        })
        while len(_conversation_buffer) > _MAX_CONV_BUFFER:
            _conversation_buffer.pop(0)


def _summarize_conversation() -> str:
    """
    Generates a compact 2-3 sentence summary of recent conversation.
    Called on session rotation to carry context across reconnections.
    Uses gemini-3.1-flash-lite for minimal cost.
    """
    global _last_session_summary
    with _conv_buffer_lock:
        if not _conversation_buffer:
            return _last_session_summary
        exchanges = list(_conversation_buffer)

    # Build a compact transcript
    lines = []
    for ex in exchanges:
        if ex["user"]:
            lines.append(f"User: {ex['user']}")
        if ex["jarvis"]:
            lines.append(f"Jarvis: {ex['jarvis']}")

    transcript = "\n".join(lines)
    if len(transcript) < 20:
        return _last_session_summary

    try:
        from core.gemini_client import ask
        summary = ask(
            f"Summarize conversation in 1-2 VERY short sentences. "
            f"Focus on the immediate context and pending tasks. "
            f"Transcript:\n{transcript}"
        )
        _last_session_summary = summary.strip()[:300]
        print(f"[TokenEconomy] 📝 Session summary: {_last_session_summary[:80]}...")
    except Exception as e:
        print(f"[TokenEconomy] ⚠️ Summary failed: {e}")

    return _last_session_summary


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    """
    Multilingual memory updater.
    Model  : gemini-3.1-flash-lite (lowest cost)
    Stage 1: Quick YES/NO check  → ~5 tokens output
    Stage 2: Full extraction     → only if Stage 1 says YES
    Result : ~80% fewer API calls vs original
    """
    global _memory_turn_counter, _last_memory_input

    with _memory_turn_lock:
        _memory_turn_counter += 1
        current_count = _memory_turn_counter

    if current_count % _MEMORY_EVERY_N_TURNS != 0:
        return

    text = user_text.strip()
    if len(text) < 10:
        return
    if text == _last_memory_input:
        return
    _last_memory_input = text

    try:
        from core.gemini_client import ask

        check = ask(
            f"Does this message contain personal facts about the user "
            f"(name, age, city, job, hobby, relationship, birthday, preference)? "
            f"Reply only YES or NO.\n\nMessage: {text[:300]}"
        )
        if "YES" not in check.upper():
            return

        raw = ask(
            f"Extract personal facts from this message. Any language.\n"
            f"Return ONLY valid JSON or {{}} if nothing found.\n"
            f"Extract: name, age, birthday, city, job, hobbies, preferences, relationships, language.\n"
            f"Skip: weather, reminders, search results, commands.\n\n"
            f"Format:\n"
            f'{{"identity":{{"name":{{"value":"..."}}}}}}, '
            f'"preferences":{{"hobby":{{"value":"..."}}}}, '
            f'"notes":{{"job":{{"value":"..."}}}}}}\n\n'
            f"Message: {text[:500]}\n\nJSON:"
        )

        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        if not raw or raw == "{}":
            return

        data = json.loads(raw)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ Updated: {list(data.keys())}")

    except json.JSONDecodeError:
        pass
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app or program. "
            "NEVER use this for YouTube — use youtube_video instead. "
            "NEVER use this for browser/Chrome/Edge — use browser_control instead. "
            "Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'Telegram', 'Spotify', 'WhatsApp')"
                }
            },
            "required": ["app_name"]
        }
    },
{
    "name": "web_search",
    "description": "Searches the web for any information.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":  {"type": "STRING", "description": "Search query"},
            "mode":   {"type": "STRING", "description": "search (default) or compare"},
            "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
            "aspect": {"type": "STRING", "description": "price | specs | reviews"}
        },
        "required": ["query"]
    }
},
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
    "name": "youtube_video",
    "description": (
        "Controls YouTube — opens browser and navigates automatically. "
        "Use for: playing videos/music, summarizing videos, showing trending, "
        "opening saved playlists/library. "
        "When user wants their saved playlists or library, use action='library'. "
        "NEVER use agent_task or browser_control for YouTube — this tool handles EVERYTHING. "
        "NEVER open browser or YouTube app first — this tool handles everything. "
        "After playing, do NOT close the browser — leave the video/music running."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "play | summarize | get_info | trending | open_home | library (default: open_home). Use 'library' when user wants saved playlists, liked videos, or their YouTube library."
            },
            "query":  {"type": "STRING", "description": "Search query — be SPECIFIC, never vague like 'some music'. Emtpy when open_home."},
            "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
            "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
            "url":    {"type": "STRING", "description": "Video URL for get_info action"},
        },
        "required": []
    }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {
                    "type": "STRING",
                    "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"
                },
                "text": {
                    "type": "STRING",
                    "description": "The question or instruction about the captured image"
                }
            },
            "required": ["text"]
        }
    },
    {
    "name": "computer_settings",
    "description": (
        "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
        "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
        "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
        "ALSO use for repeated actions: 'refresh 10 times', 'reload page 5 times' → action: reload_n, value: 10. "
        "Use for ANY single computer control command — even if repeated N times. "
        "NEVER route simple computer commands to agent_task."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "The action to perform (if known). For repeated reload: 'reload_n'"},
            "description": {"type": "STRING", "description": "Natural language description of what to do"},
            "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, number of times, etc."}
        },
        "required": []
    }
},
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, finding cheapest products, "
            "booking flights, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders. Use for: listing files, creating/deleting/moving/copying "
            "files, reading file contents, finding files by name or extension, checking disk usage, "
            "organizing the desktop, getting file info."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands by understanding natural language. "
            "Use when user wants to: find large files, check disk space, list processes, "
            "get system info, navigate folders, check network, find files by name, "
            "or do ANYTHING in the command line they don't know how to do themselves."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do. Example: 'find the 10 largest files on C drive'"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window so user can see. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": (
            "Controls the desktop. Use for: changing wallpaper, organizing desktop files, "
            "cleaning the desktop, listing desktop contents, or ANY other desktop-related task "
            "the user describes in natural language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language description of any desktop task"},
            },
            "required": ["action"]
        }
    },
    {
    "name": "code_helper",
    "description": (
        "Writes, edits, explains, runs, or self-builds code files. "
        "Use for ANY coding request: writing a script, fixing a file, "
        "editing existing code, running a file, or building and testing automatically."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
            "description": {"type": "STRING", "description": "What the code should do, or what change to make"},
            "language":    {"type": "STRING", "description": "Programming language (default: python)"},
            "output_path": {"type": "STRING", "description": "Where to save the file (full path or filename)"},
            "file_path":   {"type": "STRING", "description": "Path to existing file for edit / explain / run / build"},
            "code":        {"type": "STRING", "description": "Raw code string for explain"},
            "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
            "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
        },
        "required": ["action"]
    }
    },
    {
    "name": "dev_agent",
    "description": (
        "Builds complete multi-file projects from scratch. "
        "Plans structure, writes all files, installs dependencies, "
        "opens VSCode, runs the project, and fixes errors automatically. "
        "Use for any project larger than a single script."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description":  {"type": "STRING", "description": "What the project should do"},
            "language":     {"type": "STRING", "description": "Programming language (default: python)"},
            "project_name": {"type": "STRING", "description": "Optional project folder name"},
            "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
        },
        "required": ["description"]
    }
    },
    {
    "name": "agent_task",
    "description": (
        "Executes complex multi-step tasks that require MULTIPLE DIFFERENT tools. "
        "Always respond to the user in the language they spoke. "
        "Examples: 'research X and save to file', 'find files and organize them', "
        "'fill a form on a website', 'write and test code'. "
        "DO NOT use for simple computer commands like volume, refresh, close, scroll, "
        "minimize, screenshot, restart, shutdown — use computer_settings for those. "
        "DO NOT use if the task can be done with a single tool call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "Complete description of what needs to be accomplished"
            },
            "priority": {
                "type": "STRING",
                "description": "low | normal | high (default: normal)"
            }
        },
        "required": ["goal"]
    }
},
    {
    "name": "computer_control",
    "description": (
        "Direct computer control for interacting with ANY app currently on screen. "
        "IMPORTANT: Use 'screen_click' to find AND click elements (buttons, contacts, links, icons). "
        "Do NOT use 'screen_find' if you want to interact — it only returns coordinates without clicking. "
        "WORKFLOW for app interaction: 1) focus_window to bring app to front, "
        "2) screen_click to find and click the target element. "
        "Also supports: typing text, keyboard shortcuts, scrolling, mouse control, "
        "screenshots, form filling, and any direct computer interaction."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "screen_click (find+click element) | screen_find (find only, NO click) | type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | random_data | user_data"},
            "text":        {"type": "STRING", "description": "Text to type or paste"},
            "x":           {"type": "INTEGER", "description": "X coordinate for click/move"},
            "y":           {"type": "INTEGER", "description": "Y coordinate for click/move"},
            "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
            "key":         {"type": "STRING", "description": "Single key to press e.g. 'enter'"},
            "direction":   {"type": "STRING", "description": "Scroll direction: up | down | left | right"},
            "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
            "seconds":     {"type": "NUMBER", "description": "Seconds to wait"},
            "title":       {"type": "STRING", "description": "Window title for focus_window"},
            "description": {"type": "STRING", "description": "What to find/click on screen for screen_click/screen_find (e.g. 'Doniyor contact', 'Send button', 'search bar')"},
            "type":        {"type": "STRING", "description": "Data type for random_data: name|email|username|password|phone|birthday|address"},
            "field":       {"type": "STRING", "description": "Field for user_data: name|email|city"},
            "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            "path":        {"type": "STRING", "description": "Save path for screenshot"},
        },
        "required": ["action"]
    }
},

{
    "name": "flight_finder",
    "description": (
        "Searches for flights on Google Flights and speaks the best options. "
        "Use when user asks about flights, plane tickets, uçuş, bilet, etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "origin":       {"type": "STRING",  "description": "Departure city or airport code"},
            "destination":  {"type": "STRING",  "description": "Arrival city or airport code"},
            "date":         {"type": "STRING",  "description": "Departure date (any format)"},
            "return_date":  {"type": "STRING",  "description": "Return date for round trips"},
            "passengers":   {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
            "cabin":        {"type": "STRING",  "description": "economy | premium | business | first"},
            "save":         {"type": "BOOLEAN", "description": "Save results to Notepad"},
        },
        "required": ["origin", "destination", "date"]
    }
},
{
    "name": "bluetooth_control",
        "description": (
            "Controls Bluetooth devices, specifically room RGB lights and LEDs. "
            "Use for: turning lights ON or OFF, changing colors (RGB), or controlling "
            "any Bluetooth-enabled smart home devices. "
            "Supports specific models like 'QHM-04D5' and generic Bluetooth LEDs. "
            "If the user asks to turn off/on room lights or change room color, use this tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "on | off | rgb | toggle (default: toggle)"
                },
                "device": {
                    "type": "STRING",
                    "description": "Name or keyword for the device (e.g. 'QHM-04D5', 'Room Light', 'LED'). Default: 'Room Light'"
                },
                "value": {
                    "type": "STRING",
                    "description": "Color value for 'rgb' action (e.g. '#FF0000' or 'red', 'blue', etc.)"
                }
            },
            "required": ["action"]
        }
    }
]

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_executing_tool = False
        self._bg_tasks_active   = 0     # Track background agent_task count
        self._interaction_count  = 0    # Token economy turn counter

    def speak(self, text: str):
        """Thread-safe bare-metal speak — forces AI to relay system notifications aloud."""
        if not self._loop or not self.session:
            return
            
        directive = (
            f"[SYSTEM NOTIFICATION]\n"
            f"Relay the following message aloud to the user immediately, "
            f"translating it to {self.ui.spoken_language} if necessary. "
            f"Do not add any other commentary or ask questions. Message:\n"
            f"\"{text}\""
        )
        
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": directive}]},
                turn_complete=True
            ),
            self._loop
         )
    
    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime 

        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)

        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders. "
            f"If user says 'in 2 minutes', add 2 minutes to this time.\n\n"
        )

        if mem_str:
            sys_prompt = time_ctx + mem_str + "\n\n" + sys_prompt
        else:
            sys_prompt = time_ctx + sys_prompt

        # ── Token Economy: Inject previous session summary for cross-session context ──
        if _last_session_summary:
            sys_prompt += (
                f"\n\n[PREVIOUS SESSION CONTEXT]\n"
                f"Here is a summary of the recent conversation before this session reconnected:\n"
                f"{_last_session_summary}\n"
                f"Use this context to maintain continuity. Do NOT mention session rotation to the user."
            )

        sys_prompt += (
            f"\n\n[LANGUAGE DIRECTIVE — ABSOLUTE PRIORITY]"
            f"\nThe user has selected '{self.ui.spoken_language}' as the communication language."
            f"\n1. You MUST speak exclusively in {self.ui.spoken_language}."
            f"\n2. ALL tool call arguments (descriptions, text fields, queries) MUST be in {self.ui.spoken_language} — NEVER in English."
            f"\n   Example: screen_process text must be '{self.ui.spoken_language}', NOT English."
            f"\n3. When transcribing the user's speech, ALWAYS use LATIN script (a-z characters)."
            f"\n   NEVER use Arabic, Cyrillic, or other non-Latin scripts for {self.ui.spoken_language}."
            f"\n   Example: Write 'Salom' NOT 'سلام', write 'Telegramni och' NOT 'تلگرامنی اوچ'."
        )

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=sys_prompt,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon" 
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 TOOL: {name}  ARGS: {args}")

        loop   = asyncio.get_event_loop()
        result = "Done."

        self._is_executing_tool = True
        if self.ui:
            self.ui.status_text = "PROCESSING"

        try:
            if name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Opened {args.get('app_name')} successfully."

            elif name == "weather_report":
                r = await loop.run_in_executor(
                    None, lambda: weather_action(parameters=args, player=self.ui)
                )
                result = r or f"Weather report for {args.get('city')} delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(parameters=args, player=self.ui)
                )
                result = r or "Browser action completed."

            elif name == "file_controller":
                r = await loop.run_in_executor(
                    None, lambda: file_controller(parameters=args, player=self.ui)
                )
                result = r or "File operation completed."

            elif name == "send_message":
                r = await loop.run_in_executor(
                    None, lambda: send_message(
                        parameters=args, response=None,
                        player=self.ui, session_memory=None
                    )
                )
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(
                    None, lambda: reminder(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Reminder set for {args.get('date')} at {args.get('time')}."

            elif name == "youtube_video":
                r = await loop.run_in_executor(
                    None, lambda: youtube_video(parameters=args, response=None, player=self.ui)
                )
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = (
                    "Vision module activated and will speak the answer directly to the user via audio. "
                    "You MUST NOT generate ANY audio response. Do NOT speak. Do NOT say anything. "
                    "Remain COMPLETELY SILENT. The vision module handles the entire reply."
                )

            elif name == "computer_settings":
                r = await loop.run_in_executor(
                    None, lambda: computer_settings(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Done."

            elif name == "cmd_control":
                r = await loop.run_in_executor(
                    None, lambda: cmd_control(parameters=args, player=self.ui)
                )
                result = r or "Command executed."

            elif name == "desktop_control":
                r = await loop.run_in_executor(
                    None, lambda: desktop_control(parameters=args, player=self.ui)
                )
                result = r or "Desktop action completed."
            elif name == "code_helper":
                r = await loop.run_in_executor(
                    None, lambda: code_helper(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak 
                    )
                )
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(
                    None, lambda: dev_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."
            elif name == "agent_task":
                goal         = args.get("goal", "")
                priority_str = args.get("priority", "normal").lower()

                from agent.task_queue import get_queue, TaskPriority
                priority_map = {
                    "low":    TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high":   TaskPriority.HIGH,
                }
                priority = priority_map.get(priority_str, TaskPriority.NORMAL)

                queue   = get_queue()
                self._bg_tasks_active += 1

                def _on_task_done(task_id_done, result_done):
                    self._bg_tasks_active = max(0, self._bg_tasks_active - 1)
                    if self._bg_tasks_active == 0 and not self._is_executing_tool:
                        self.ui.status_text = "ONLINE"

                def _ui_status_cb(msg):
                    self.ui.status_text = msg

                task_id = queue.submit(
                    goal=goal,
                    priority=priority,
                    speak=self.speak,
                    on_complete=_on_task_done,
                    ui_status_callback=_ui_status_cb,
                )
                result = f"Task started (ID: {task_id}). I'll update you as I make progress, sir."

            elif name == "web_search":
                r = await loop.run_in_executor(
                    None, lambda: web_search_action(parameters=args, player=self.ui)
                    )
                result = r or "Search completed."
            elif name == "computer_control":
                r = await loop.run_in_executor(
                    None, lambda: computer_control(parameters=args, player=self.ui)
                )
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(
                    None, lambda: flight_finder(parameters=args, player=self.ui)
                )
                result = r or "Done."

            elif name == "bluetooth_control":
                r = await loop.run_in_executor(
                    None, lambda: bluetooth_control(parameters=args)
                )
                result = r or "Done."

            else:
                result = f"Unknown tool: {name}"
            
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
        finally:
            self._is_executing_tool = False

        print(f"[JARVIS] 📤 {name} → {result[:80]}")

        return types.FunctionResponse(
            id=fc.id,
            name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            if self.ui.is_sleeping:
                return
            try:
                msg = await asyncio.wait_for(self.out_queue.get(), timeout=0.5)
                # Avoid deprecated media_chunks; use typed audio stream with explicit MIME type
                await self.session.send_realtime_input(
                    audio={'data': msg, 'mime_type': f'audio/pcm;rate={SEND_SAMPLE_RATE}'}
                )
            except asyncio.TimeoutError:
                continue

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        silence_frames = 0
        try:
            while True:
                if self.ui.is_sleeping:
                    print("[JARVIS] 🎤 Mic stopped (sleep)")
                    return
                
                if self.ui.mobile_connected:
                    try:
                        data = await asyncio.wait_for(self.ui.mobile_mic_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                else:
                    data = await asyncio.to_thread(
                        stream.read, CHUNK_SIZE, exception_on_overflow=False
                    )
                
                rms = 0.0
                
                # Echo cancellation: strictly suppress microphone if speaker has recently output acoustic energy
                # A robust 1.0 second decay padding guarantees trailing hardware DAC buffers won't loop back in.
                # AND strictly suppress if an automated Tool is actively processing!
                if self._is_executing_tool or getattr(self.ui, 'is_building', False) or (self.ui and time.time() - self.ui.last_audio_played_time < 1.0):
                    data = b'\x00' * len(data)
                    self.ui.mic_level = 0.0
                else:
                    # Calculate mic level for UI visualizer and noise gating
                    try:
                        n = len(data) // 2
                        if n > 0:
                            samples = struct.unpack(f'<{n}h', data)
                            rms = (sum(s * s for s in samples) / n) ** 0.5 / 32768.0
                            
                            # Implacable Active Noise Gate (Aggressively filters ambient music and static)
                            if rms < 0.015:
                                data = b'\x00' * len(data)
                                
                            self.ui.mic_level = min(1.0, rms * 5.0)
                    except Exception:
                        pass
                
                if rms < 0.005:
                    silence_frames += 1
                else:
                    silence_frames = 0
                    
                # Drop the explicit noise gate packet-drop. 
                # Dropping packets causes Gemini server VAD starvation (it thinks network is lagging) -> extremely slow response times!
                # We unconditionally send PCM (even if muted 0x00) so Gemini VAD can instantly detect silence and reply!
                await self.out_queue.put(data)

        except Exception as e:
            print(f"[JARVIS] ❌ Mic error: {e}")
            raise
        finally:
            stream.close()

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf = []
        in_buf  = []

        try:
            while True:
                if self.ui.is_sleeping:
                    print("[JARVIS] 👂 Recv stopped (sleep)")
                    return
                turn = self.session.receive()
                async for response in turn:

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)
                                self.ui.status_text = "PROCESSING"

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)
                                self.ui.status_text = "RESPONDING"

                        if sc.turn_complete:
                            full_in  = " ".join(in_buf).strip() if in_buf else ""
                            full_out = ""

                            if full_in:
                                self.ui.write_log(f"You: {full_in}")

                            in_buf = []

                            if out_buf:
                                full_out = " ".join(out_buf).strip()
                                if full_out:
                                    self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []

                            # Token Economy: Track conversation for cross-session context
                            if full_in or full_out:
                                _append_conversation(full_in, full_out)

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                            # Turn is over — return to ONLINE state or PROCESSING if working
                            # FIX: Don't overwrite granular status (e.g. "Step 1/3") with generic "PROCESSING"
                            if not self._is_executing_tool and self._bg_tasks_active == 0:
                                self.ui.status_text = "ONLINE"
                            elif self._bg_tasks_active > 0 or self._is_executing_tool:
                                if self.ui.status_text in ("ONLINE", "RESPONDING", "CONNECTING", "SPEAKING"):
                                    self.ui.status_text = "PROCESSING"
                            self._interaction_count += 1
                            if self._interaction_count >= 10:
                                self._interaction_count = 0
                                # Summarize before disconnecting so next session has context
                                threading.Thread(
                                    target=_summarize_conversation,
                                    daemon=True
                                ).start()
                                # Small delay to allow last audio chunk to hit the card buffers
                                await asyncio.sleep(0.3)
                                raise SessionRotationError("Token Limit Rotation")

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 Tool call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[JARVIS] ❌ Recv error: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        try:
            while True:
                if self.ui.is_sleeping:
                    print("[JARVIS] 🔊 Play stopped (sleep)")
                    return
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(), timeout=0.3
                    )
                except asyncio.TimeoutError:
                    if self.ui.speaking:
                        # Allow UI visuals to decay only if hardware buffer is completely 100% finished
                        if (time.time() - self.ui.last_audio_played_time) > 0.8:
                            self.ui.speaking = False
                            self.ui.jarvis_level = 0.0
                            if not self._is_executing_tool and self._bg_tasks_active == 0:
                                self.ui.status_text = "ONLINE"
                            elif self._bg_tasks_active > 0 or self._is_executing_tool:
                                self.ui.status_text = "PROCESSING"
                    continue
                
                if self.ui:
                    self.ui.last_audio_played_time = time.time()
                self.ui.speaking = True
                self.ui.status_text = "RESPONDING"
                # Calculate JARVIS voice level for UI visualizer
                try:
                    n = len(chunk) // 2
                    if n > 0:
                        samples = struct.unpack(f'<{n}h', chunk)
                        rms = (sum(s * s for s in samples) / n) ** 0.5 / 32768.0
                        self.ui.jarvis_level = min(1.0, rms * 5.0)
                except Exception:
                    pass
                
                if self.ui.mobile_connected:
                    self.ui.mobile_out_queue.put_nowait(chunk)
                else:
                    if not getattr(self.ui, 'mobile_locked', False):
                        await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Play error: {e}")
            raise
        finally:
            stream.close()

    async def _check_restart(self):
        while True:
            if getattr(self.ui, "needs_restart", False):
                self.ui.needs_restart = False
                raise SessionRotationError("Config changed")
            await asyncio.sleep(0.5)

    async def run(self):
        backoff = 3
        max_backoff = 60
        consecutive_failures = 0

        # Threading event — set by wake_up(), waited by sleep gate
        self._woken = threading.Event()
        self.ui._woken_event = self._woken

        while True:
            # ── SLEEP GATE: if sleeping, block until woken ──
            if self.ui.is_sleeping:
                print("[JARVIS] 😴 Session sleeping — starting wake listener...")
                self._woken.clear()
                self._start_wake_listener()
                # Block in a thread-safe way (doesn't depend on asyncio loop health)
                await asyncio.to_thread(self._woken.wait)
                print("[JARVIS] ☀️ Wake signal received — unblocking main engine...")
                # Ensure state is updated before continuing
                await asyncio.sleep(0.5) 
                continue

            try:
                # 1. Initialize fresh GenAI client
                api_key = get_api_key()
                client = genai.Client(api_key=api_key)
                
                self.ui.conn_state = "CONNECTING"
                self.ui.status_text = "CONNECTING"
                
                # 2. Get prioritized model chain
                models_to_try = ModelRegistry.get_voice_chain(_DEFAULT_LIVE)
                config = self._build_config()
                
                for idx, m in enumerate(models_to_try):
                    try:
                        logger.log("LIVE", f"Connecting to {m}...", level="LIVE")
                        
                        # Fix: Ensure we use the correct async context manager syntax for the SDK
                        async with client.aio.live.connect(model=m, config=config) as session:
                            self.session        = session
                            self._loop          = asyncio.get_event_loop() 
                            self.audio_in_queue = asyncio.Queue()
                            self.out_queue      = asyncio.Queue(maxsize=10)

                            # Connection successful — reset backoff
                            backoff = 3
                            consecutive_failures = 0
                            logger.state(f"Connected to {m}.", icon="✅")
                            self.ui.conn_state = "ONLINE"
                            self.ui.status_text = "ONLINE"
                            self.ui.write_log(f"SYS: JARVIS online ({m}).")

                            # Running tasks — if sleep/Error occurs, this exits the 'async with'
                            tasks = [
                                asyncio.create_task(self._send_realtime()),
                                asyncio.create_task(self._listen_audio()),
                                asyncio.create_task(self._receive_audio()),
                                asyncio.create_task(self._play_audio()),
                                asyncio.create_task(self._check_restart()),
                            ]
                            done, pending = await asyncio.wait(
                                tasks, return_when=asyncio.FIRST_COMPLETED
                            )
                            # Cancel remaining tasks
                            for t in pending: t.cancel()
                            try:
                                await asyncio.wait_for(
                                    asyncio.gather(*pending, return_exceptions=True),
                                    timeout=2.0
                                )
                            except asyncio.TimeoutError:
                                print("[JARVIS] ⚠️ Force-cancelled stuck tasks")
                            
                            # Re-raise if any finished task had a real error
                            for t in done:
                                try:
                                    exc = t.exception()
                                except asyncio.CancelledError:
                                    exc = None
                                if exc: raise exc
                            
                            # If we get here, tasks finished normally (e.g. is_sleeping)
                            break # Success — exit the model rotation loop

                    except Exception as e:
                        err_msg = str(e).lower()
                        if "429" in err_msg or "quota" in err_msg or "exhausted" in err_msg:
                            _mark_model_exhausted(m)
                            self.ui.write_log(f"SYS: {m} exhausted. Rotating...")
                            if idx < len(models_to_try) - 1:
                                continue # Try next model
                        raise # Permanent failure or other error

                # If we exited the session because of sleep, skip error handling
                if self.ui.is_sleeping:
                    print("[JARVIS] 😴 Session disconnected for sleep.")
                    continue

            except SessionRotationError:
                print("[JARVIS] ♻️ Token economy: Rotating Live API session to clear memory overhead...")
                consecutive_failures = 0
                backoff = 3
                continue

            except Exception as e:
                consecutive_failures += 1
                print(f"[JARVIS] ⚠️  Error: {e}")
                traceback.print_exc()

            # ── Exponential backoff with connection state ──
            if self.ui.is_sleeping:
                continue  # Skip backoff, go straight to sleep gate

            if consecutive_failures >= 5:
                self.ui.conn_state = "FAILED"
                self.ui.status_text = "FAILED"
                self.ui.write_log(
                    f"SYS: Connection failed ({consecutive_failures} attempts). "
                    f"Retrying in {max_backoff}s...")
                backoff = max_backoff
            else:
                self.ui.conn_state = "RECONNECTING"
                self.ui.status_text = f"RETRY {consecutive_failures}"

            print(f"[JARVIS] 🔄 Reconnecting in {backoff}s "
                  f"(attempt {consecutive_failures})...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    def _start_wake_listener(self):
        """Start a background thread that listens for 'wake up' using speech_recognition."""
        threading.Thread(
            target=self._wake_listener_loop,
            daemon=True,
            name="WakeWordListener"
        ).start()

    def _wake_listener_loop(self):
        """Lightweight wake-word detection using speech_recognition + Google."""
        try:
            import speech_recognition as sr
        except ImportError:
            print("[WAKE] ⚠️ speech_recognition not installed. Cannot listen for wake word.")
            print("[WAKE] Install with: pip install SpeechRecognition")
            return

        class MobileAudioSource(sr.AudioSource):
            def __init__(self, queue):
                self.queue = queue
                self.SAMPLE_RATE = 16000
                self.SAMPLE_WIDTH = 2
                self.CHUNK = 1024
                self.stream = None
            def __enter__(self):
                class Stream:
                    def __init__(self, q):
                        self.q = q
                        self._buf = b""
                    def read(self, size):
                        data = b""
                        while len(data) < size:
                            if not self._buf:
                                try:
                                    self._buf = self.q.get(timeout=0.1)
                                except Exception:
                                    break
                            take = size - len(data)
                            data += self._buf[:take]
                            self._buf = self._buf[take:]
                        return data if data else b'\x00' * size
                self.stream = Stream(self.queue)
                return self
            def __exit__(self, *args):
                self.stream = None

        # Balanced sensitivity: 500 is reliable for most laptop/desktop mics.
        # Dynamic threshold re-enabled with constraints to adapt to environment.
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 500
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_adjustment_ratio = 1.5
        recognizer.pause_threshold = 0.8

        mic_desktop = sr.Microphone()
        
        # Calibrate once at startup for ambient noise baseline
        try:
            with mic_desktop as source:
                recognizer.adjust_for_ambient_noise(source, duration=1.0)
                print(f"[WAKE] 🔧 Calibrated energy threshold: {recognizer.energy_threshold:.0f}")
        except Exception as e:
            print(f"[WAKE] ⚠️ Calibration error: {e}")

        print("[WAKE] 🎤 Wake listener active — say 'wake up' to resume...")

        _heartbeat_counter = 0

        while self.ui.is_sleeping:
            # ── Mobile connected → skip STT, wake button handles it via WebSocket ──
            if getattr(self.ui, 'mobile_connected', False):
                _heartbeat_counter += 1
                if _heartbeat_counter % 12 == 0:
                    print("[WAKE] 📱 Mobile connected — waiting for wake button press...")
                time.sleep(0.5)
                continue

            # ── No mobile → use laptop mic + speech recognition ──
            try:
                with mic_desktop as source:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)

                # Try recognition
                text = None
                try:
                    text = recognizer.recognize_google(audio, language="en-US").lower().strip()
                except sr.UnknownValueError:
                    # Don't spam logs — only log occasionally
                    _heartbeat_counter += 1
                    if _heartbeat_counter % 6 == 0:
                        print(f"[WAKE] 💓 Still listening... (threshold: {recognizer.energy_threshold:.0f})")
                    continue
                except sr.RequestError as e:
                    print(f"[WAKE] ⚠️ Google API error: {e} — retrying...")
                    time.sleep(2)
                    continue

                if text:
                    print(f"[WAKE] 👂 Heard: '{text}'")

                    # Flexible wake phrase matching (exact, partial, and fuzzy)
                    wake_exact = ["wake up", "wake", "wakeup", "hey jarvis", "jarvis",
                                  "wake up jarvis", "jarvis wake up", "hey wake up"]
                    # Direct match
                    if any(w in text for w in wake_exact):
                        print("[WAKE] ✅ Wake word detected!")
                        self.ui.wake_up()
                        return
                    # Fuzzy partial match (handles "wait up", "make up" misrecognitions)
                    fuzzy_parts = ["wake", "jarv", "woke"]
                    if any(p in text for p in fuzzy_parts):
                        print(f"[WAKE] ✅ Fuzzy wake match: '{text}'")
                        self.ui.wake_up()
                        return

            except sr.WaitTimeoutError:
                # No speech detected — normal during sleep
                _heartbeat_counter += 1
                if _heartbeat_counter % 6 == 0:
                    print(f"[WAKE] 💓 Still listening... (threshold: {recognizer.energy_threshold:.0f})")
                continue
            except Exception as e:
                print(f"[WAKE] ⚠️ Listener error: {e}")
                time.sleep(1)

        print("[WAKE] 🔇 Wake listener stopped (no longer sleeping)")


def main():
    ui = JarvisUI()

    def runner():
        ui.wait_for_api_key()
        
        # Initial scan models on startup
        from core.gemini_client import ModelRegistry
        logger.log("SYS", "Initial boot: Force-scanning available models...", level="SYS")
        ui.write_log("SYS: Scanning available models via API...")
        ModelRegistry.scan_models()
        ModelRegistry.auto_align_roles()
        
        jarvis = JarvisLive(ui)
        try:
            logger.state("Handshake confirmed. Starting JARVIS engine...", icon="⚡")
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            logger.state("Shutting down...", icon="🔴")

    threading.Thread(target=runner, daemon=True).start()
    ui.mainloop()

if __name__ == "__main__":
    main()