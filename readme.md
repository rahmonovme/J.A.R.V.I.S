# J.A.R.V.I.S

**Just A Rather Very Intelligent System**  
An advanced AI personal assistant powered by Google Gemini Live API with real-time voice interaction, smart task execution, and multi-monitor awareness.

---

## ✨ Features

### 🗣️ Real-Time Voice Interaction
- Full-duplex audio: listen and speak simultaneously
- Gemini Live API integration for natural conversation
- Audio echo cancellation: mic auto-mutes during JARVIS playback to prevent feedback loops

### 🧠 Smart Task Execution (Agent System)
- Multi-step task planning with Gemini-powered planner
- Error recovery with auto-replanning
- **Multi-strategy app launcher** — tries direct subprocess, PATH, Windows Registry, Start Menu shortcuts before falling back to Windows Search with process verification
- Screen verification after critical actions (verifies apps actually launched)
- Multi-monitor awareness for screen analysis and interaction
- Cross-platform support for Windows, macOS, and Linux out of the box.

### 🖥️ Premium HUD Interface
- Arc-Reactor inspired JARVIS voice visualizer (cyan, circular)
- Frequency-bar circle microphone visualizer (amber)
- **Connection status indicators** — center animation changes color:
  - 🟦 **Cyan** = Online
  - 🟡 **Amber** = Connecting
  - 🟠 **Orange** = Reconnecting
  - 🔴 **Red** = Connection Failed
- Animated grid, scanline, rotating arcs, and pulse rings
- Corner HUD data readouts (uptime, system status)
- Real-time clock display

### ⚙️ Settings & Configuration
- **Close JARVIS** button — cleanly terminates all processes
- **Settings modal** with:
  - API key management (view/hide/edit/save)
  - Auto-start with system boot toggle
- First-launch API key setup wizard

### 🔧 Connection Stability
- Exponential backoff on connection failures (3s → 60s cap)
- Connection state tracking exposed to UI
- Automatic reconnection with failure counting
- Graceful handling of WebSocket errors

### 📱 Smart Messaging
- WhatsApp, Telegram, Instagram direct messaging
- pyperclip integration for Unicode contact names
- Platform-specific contact search patterns

---

## 🛠️ Installation

### 1. Install Python (If you don't have it)

If your machine does not already have Python installed, you must install the bare minimum system Python to run the automated setup script.

**🍎 For macOS:**
1. Open Terminal and install [Homebrew](https://brew.sh/) (if you don't have it):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. Install Python 3:
   ```bash
   brew install python3
   ```

**🪟 For Windows:**
1. Download the official installer from [python.org](https://www.python.org/downloads/).
2. **CRITICAL**: When running the installer, you **must** check the box at the very bottom that says **"Add python.exe to PATH"** before clicking Install.

**🐧 For Linux (Ubuntu/Debian):**
1. Open Terminal and run:
   ```bash
   sudo apt update && sudo apt install python3 python3-pip python3-venv
   ```

---

### 2. Setup J.A.R.V.I.S

```bash
# Clone the repository
git clone https://github.com/rahmonovme/J.A.R.V.I.S.git
cd J.A.R.V.I.S

# Run the automated cross-platform setup script
# (Automatically downloads Python 3.12 via uv if needed, creates a venv, and installs dependencies)
# 🪟 Windows:
python setup.py
# 🍎 Mac/🐧 Linux:
python3 setup.py

# Activate the virtual environment
# 🪟 Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# 🍎 Mac/🐧 Linux:
source venv/bin/activate

# Run JARVIS
# 🪟 Windows:
python main.py
# 🍎 Mac/🐧 Linux:
python3 main.py
```

On first launch, a setup wizard will prompt you for your Gemini API key.

---

## 📁 Project Structure

```text
J.A.R.V.I.S/
├── main.py                  # Entry point, audio streaming, Live API connection
├── ui.py                    # Premium HUD interface (tkinter canvas)
├── setup.py                 # Automated cross-platform environment bootstrapper
├── config/
│   └── api_keys.json        # API key storage (created on first run)
├── core/
│   ├── gemini_client.py     # Gemini API client wrapper
│   └── prompt.txt           # System prompt for JARVIS personality
├── memory/
│   ├── memory_manager.py    # Session & persistent memory tracking
│   └── config_manager.py    # Application config management
├── agent/
│   ├── executor.py          # Multi-step task executor
│   ├── planner.py           # Gemini-powered task planner
│   ├── error_handler.py     # Error recovery with auto-replanning
│   └── task_queue.py        # Background task queue
├── actions/
│   ├── open_app.py          # Smart multi-strategy app launcher
│   ├── browser_control.py   # Playwright browser automation
│   ├── computer_control.py  # Mouse/keyboard/screen control
│   ├── computer_settings.py # System settings (volume, brightness, etc.)
│   ├── screen_processor.py  # Multi-monitor screen analysis
│   ├── send_message.py      # WhatsApp/Telegram/Instagram messaging
│   ├── web_search.py        # Web search via DuckDuckGo
│   ├── file_controller.py   # File operations
│   ├── cmd_control.py       # Command-line execution
│   ├── code_helper.py       # Code writing/running
│   ├── dev_agent.py         # Development assistant
│   ├── youtube_video.py     # YouTube playback/summarization
│   ├── weather_report.py    # Weather reports
│   ├── flight_finder.py     # Flight search
│   ├── reminder.py          # Reminders
│   └── desktop.py           # Desktop management
```

---

## 🔑 API Configuration

JARVIS uses the Google Gemini API. You need a Gemini API key:

1. Get your key from [Google AI Studio](https://aistudio.google.com/)
2. Enter it on first launch, or update via Settings (⚙️ button)
3. Key is stored locally in `config/api_keys.json`

---

## 📝 License

This project is for educational and personal use.

---

*Built by [Rahmonov.me](https://www.instagram.com/rahmonov.me)*
