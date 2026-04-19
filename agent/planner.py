import json
import re
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


PLANNER_PROMPT = """You are the planning module of MARK XXV, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search for ANY information retrieval, research, or current data.
- Use file_controller to save content to disk.
- Use cmd_control to open files or run system commands.
- Max 5 steps. Use the minimum steps needed.

SMART TASK RULES:
- After opening an app with open_app, add a screen_process step to verify
  the app actually launched and is visible on screen.
- Before clicking or typing inside an app, use computer_control focus_window to
  ensure the correct window has focus.
- When the user asks to interact with a specific app (e.g. "find contact Doniyor
  in Telegram"), the plan MUST include:
  1) open_app to launch it
  2) screen_process to verify it opened
  3) computer_control with action "screen_click" (NOT "screen_find") to interact
  IMPORTANT: "screen_click" finds AND clicks. "screen_find" only returns coordinates.
- For multi-step UI interactions, use screen_process between steps to verify
  each action succeeded before proceeding.
- NEVER assume an app is installed. If open_app fails, report to the user
  instead of trying alternative workarounds via browser.
- The user may have MULTIPLE MONITORS. Always use focus_window and screen_process
  to verify which monitor the app is on.
- After youtube_video plays: NEVER add browser_control(close) or computer_settings(close).

ROUTING RULES:
- For ANY YouTube-related task (play video, play music, open YouTube, search YouTube),
  use ONLY the youtube_video tool with action="play". Do NOT use open_app at all.
  youtube_video opens the browser and navigates to YouTube automatically.
- "open YouTube and play music" = youtube_video(action="play", query="popular music mix")
- "play something on YouTube" = youtube_video(action="play", query="trending music playlist")
- browser_control launches the default browser automatically. NEVER use open_app
  to open a browser first. Just use browser_control with action "go_to" directly.
- For simple web navigation, use browser_control(action="go_to", url="...") directly.
- NEVER combine open_app + browser_control or open_app + youtube_video. Each tool
  handles its own app/browser launching internally.

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  direction: "up" | "down" (for scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file)

cmd_control
  task: string (required) — natural language description of what to do
  visible: boolean (optional)

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)

screen_process
  text: string (required) — what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required)
  platform: string (required)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

dev_agent
  description: string (required)
  language: string (optional)

bluetooth_control
  action: "power_on" | "power_off" | "set_color" | "set_brightness" (required)
  value: string (for set_color: "#RRGGBB" hex; for set_brightness: "0-100")
  device: string (optional) — If omitted, AI will autodiscover the most likely LED strip in the room.

EXAMPLES:

Goal: "makine mühendisliği hakkında araştırma yap ve not defterine kaydet"
Steps:
  1. web_search | query: "mechanical engineering overview definition history"
  2. web_search | query: "mechanical engineering applications and future trends"
  3. file_controller | action: write, path: desktop, name: makine_muhendisligi.txt, content: "MAKINE MUHENDISLIGI ARASTIRMASI\n\nBu dosya web arastirmasi sonuclari ile doldurulacak."
  4. cmd_control | task: "open makine_muhendisligi.txt on desktop with notepad"

Goal: "Bitcoin fiyatı nedir"
Steps:
  1. web_search | query: "Bitcoin price today USD"

Goal: "Masaüstündeki dosyaları listele ve en büyük 5 dosyayı bul"
Steps:
  1. file_controller | action: list, path: desktop
  2. file_controller | action: largest, path: desktop, count: 5

Goal: "WhatsApp'tan Ahmet'e yarın toplantı var de"
Steps:
  1. send_message | receiver: Ahmet, message_text: "Yarın toplantı var", platform: WhatsApp

Goal: "Saati aç ve 30 dakika sonraya hatırlatıcı kur"
Steps:
  1. reminder | date: [today], time: [now+30min], message: "Hatırlatıcı"

Goal: "open YouTube and play some music"
Steps:
  1. youtube_video | action: play, query: "popular music hits playlist 2025"

Goal: "YouTube'u aç ve müzik çal"
Steps:
  1. youtube_video | action: play, query: "popular music mix 2025"

Goal: "open google.com"
Steps:
  1. browser_control | action: go_to, url: "https://www.google.com"

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _fast_path_plan(goal: str) -> dict | None:
    """
    Fast-path: intercept obvious patterns and return a pre-built plan
    WITHOUT calling Gemini. Returns None if no pattern matches.
    """
    g = goal.lower().strip()

    # ── YouTube patterns ──
    yt_keywords = ["youtube", "ютуб", "ютюб"]
    play_keywords = ["play", "çal", "aç", "müzik", "music", "video", "watch",
                     "izle", "dinle", "listen", "song", "şarkı"]
    is_yt = any(k in g for k in yt_keywords)
    is_play = any(k in g for k in play_keywords)

    if is_yt and is_play:
        # Extract what to play — remove boilerplate words
        query = goal
        for remove in ["open", "youtube", "and", "play", "some", "me", "on",
                        "aç", "çal", "müzik", "dinle", "izle", "bana", "bir",
                        "şarkı", "ve", "YouTube'u", "youtube'u", "YouTube'da",
                        "youtube'da", "watch", "listen", "to"]:
            query = re.sub(rf"\b{re.escape(remove)}\b", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip()

        # If query is empty/vague, use a good default
        if not query or len(query) < 3 or query.lower() in ["music", "song", "video"]:
            query = "popular music hits playlist 2025"

        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "youtube_video",
                "description": f"Play YouTube: {query}",
                "parameters": {"action": "play", "query": query},
                "critical": True
            }]
        }

    # ── "open YouTube" without play → still use youtube_video ──
    if is_yt and any(w in g for w in ["open", "aç", "launch"]):
        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "youtube_video",
                "description": "Open YouTube with trending music",
                "parameters": {"action": "play", "query": "trending music 2025"},
                "critical": True
            }]
        }

    # ── Direct URL navigation ──
    url_match = re.search(r"(https?://[^\s]+)", goal)
    if url_match and any(w in g for w in ["open", "go to", "navigate", "aç", "git"]):
        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "browser_control",
                "description": f"Navigate to {url_match.group(1)}",
                "parameters": {"action": "go_to", "url": url_match.group(1)},
                "critical": True
            }]
        }

    return None


def create_plan(goal: str, context: str = "") -> dict:
    # ── Fast-path: skip Gemini for obvious patterns ──
    fast = _fast_path_plan(goal)
    if fast:
        print(f"[Planner] ⚡ Fast-path: {fast['steps'][0]['tool']}")
        return fast

    from core.gemini_client import ask

    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        text = ask(user_input, system_instruction=PLANNER_PROMPT)
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        if "steps" not in plan or not isinstance(plan["steps"], list):
            raise ValueError("Invalid plan structure")

        for step in plan["steps"]:
            if step.get("tool") in ("generated_code",):
                print(f"[Planner] ⚠️ generated_code detected in step {step.get('step')} — replacing with web_search")
                desc = step.get("description", goal)
                step["tool"] = "web_search"
                step["parameters"] = {"query": desc[:200]}

        # ── Post-plan sanitizer: remove redundant open_app steps ──
        tools_in_plan = {s.get("tool") for s in plan["steps"]}
        has_yt      = "youtube_video" in tools_in_plan
        has_browser = "browser_control" in tools_in_plan

        if has_yt or has_browser:
            original_count = len(plan["steps"])
            plan["steps"] = [
                s for s in plan["steps"]
                if not (s.get("tool") == "open_app" and
                        s.get("parameters", {}).get("app_name", "").lower()
                        in ("browser", "chrome", "edge", "firefox", "youtube",
                            "google chrome", "microsoft edge"))
            ]
            removed = original_count - len(plan["steps"])
            if removed:
                print(f"[Planner] Removed {removed} redundant open_app step(s)")
                for i, s in enumerate(plan["steps"], 1):
                    s["step"] = i

        print(f"[Planner] Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")

        return plan

    except json.JSONDecodeError as e:
        print(f"[Planner] ⚠️ JSON parse failed: {e}")
        return _fallback_plan(goal, str(e))
    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        return _fallback_plan(goal, str(e))


def _fallback_plan(goal: str, error_msg: str = "") -> dict:
    print(f"[Planner] 🚫 Planning failed. ({error_msg})")
    return {
        "goal": goal,
        "steps": [],
        "error": error_msg
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    from core.gemini_client import ask

    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        text = ask(prompt, system_instruction=PLANNER_PROMPT)
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        # generated_code kontrolü
        for step in plan.get("steps", []):
            if step.get("tool") == "generated_code":
                step["tool"] = "web_search"
                step["parameters"] = {"query": step.get("description", goal)[:200]}

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        return _fallback_plan(goal, str(e))