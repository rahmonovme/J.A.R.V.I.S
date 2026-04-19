# J.A.R.V.I.S

**Just A Rather Very Intelligent System**  
An advanced AI personal assistant powered by Google Gemini Live API with real-time voice interaction, smart task execution, multi-monitor awareness, and voice-activated wake word detection.

---

## ✨ Features

### 🗣️ Real-Time Voice Interaction
- Full-duplex audio: listen and speak simultaneously
- Gemini Live API integration for natural conversation
- Audio echo cancellation: mic auto-mutes during JARVIS playback to prevent feedback loops
- **Multi-language support** — select your spoken language at boot (Uzbek, Turkish, English, etc.)
- Latin-script transcription enforcement for non-Latin languages

### 😴 Sleep & Wake Mode
- **One-click sleep** — moon button in header disconnects AI and minimizes the window
- **Voice-activated wake** — say "wake up" to restore the window and reconnect
- Lightweight wake-word listener using Google Speech Recognition (no API quota consumed)
- Automatic session reconnection after wake

### 🧠 Smart Task Execution (Agent System)
- Multi-step task planning with Gemini-powered planner
- Error recovery with auto-replanning
- **Multi-strategy app launcher** — tries direct subprocess, PATH, Windows Registry, Start Menu shortcuts before falling back to Windows Search with process verification
- Screen verification after critical actions (verifies apps actually launched)
- Multi-monitor awareness for screen analysis and interaction
- Cross-platform support for Windows, macOS, and Linux out of the box.

### 🖥️ Premium Web-Native HUD Interface
- High-performance glassmorphism UI rendered via WebViews (Flask backend).
- Arc-Reactor inspired JARVIS voice visualizer (cyan, circular).
- Frequency-bar circle microphone visualizer (amber).
- **Connection status indicators** — center animation changes color:
  - 🟣 **Violet** = Idle
  - 🟦 **Cyan** = Processing
  - 💜 **Lavender** = Speaking
  - 🟡 **Amber** = Connecting
  - 🟠 **Orange** = Reconnecting
  - 🔴 **Red** = Connection Failed
  - 🌙 **Dim Violet** = Sleeping
- Animated grid, scanline, rotating arcs, and pulse rings
- Corner HUD data readouts (uptime, system status)
- Real-time clock display

### ⚙️ Desktop Deployment & Settings
- **Compiled Binary Support** — Full support for headless execution and `.exe` auto-boot pipelines.
- **Settings modal** with:
  - API key management (view/hide/edit/save)
  - Auto-start with system boot toggle
- First-launch API key setup wizard.

### 🧠 Advanced Quota & Error Management
- **Intelligent API Fallback** — Instant failsafe routing across parallel Google Quota limits to prevent daily exhaustion.
- **Local Tracker Cache** — Permanently skips exhausted endpoints using physical local JSON tracking.
- Exponential backoff on connection failures (3s → 60s cap).
- Graceful handling of WebSocket keep-alive network errors.

### 📱 Smart Messaging & Media
- WhatsApp, Telegram, Instagram direct messaging
- pyperclip integration for Unicode contact names
- Platform-specific contact search patterns
- **YouTube controller** — play, search, summarize, trending, and open saved playlists/library

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

### 2.1. Setup J.A.R.V.I.S for Windows

1. **Clone the repository:**
   ```bash
   git clone https://github.com/rahmonovme/J.A.R.V.I.S.git
   ```

2. **Enter the directory:**
   ```bash
   cd J.A.R.V.I.S
   ```

3. **Run the automated setup script:** *(This automatically downloads Python 3.12 via uv if needed, creates a venv, and installs dependencies)*
   ```bash
   python setup.py
   ```

4. **Activate the virtual environment (PowerShell):**
   ```bash
   .\venv\Scripts\Activate.ps1
   ```

5. **Run JARVIS:**
   ```bash
   python main.py
   ```

### 2.2. Setup J.A.R.V.I.S for Mac/Linux

1. **Clone the repository:**
   ```bash
   git clone https://github.com/rahmonovme/J.A.R.V.I.S.git
   ```

2. **Enter the directory:**
   ```bash
   cd J.A.R.V.I.S
   ```

3. **Run the automated setup script:** *(This automatically downloads Python 3.12 via uv if needed, creates a venv, and installs dependencies)*
   ```bash
   python3 setup.py
   ```

4. **Activate the virtual environment:**
   ```bash
   source venv/bin/activate
   ```

5. **Run JARVIS:**
   ```bash
   python3 main.py
   ```

On first launch, a setup wizard will prompt you for your Gemini API key.

---

## 📁 Project Structure

```text
J.A.R.V.I.S/
├── main.py                  # Entry point, audio streaming, Live API connection
├── ui_web.py                # Premium Web-based HUD interface (Flask backend)
├── build.py                 # PyInstaller executable compiler for distribution
├── setup.py                 # Automated cross-platform environment bootstrapper
├── static/                  # Web HUD frontend assets
│   ├── index.html           # HUD Layout and canvas boundaries
│   ├── app.js               # Frontend voice visualizer and WebSocket interface
│   └── style.css            # Premium animated aesthetics and transitions
├── config/
│   ├── api_keys.json        # API key storage (created on first run)
│   └── api_limits.json      # Intelligent daily quota limits tracker
├── core/
│   ├── gemini_client.py     # Gemini client with cascading bucket fallback mechanisms
│   └── prompt.txt           # System prompt for JARVIS personality
├── memory/
│   ├── memory_manager.py    # Session & persistent memory tracking
│   └── config_manager.py    # Application config management
├── agent/
│   ├── executor.py          # Multi-step task executor
│   ├── planner.py           # Gemini-powered task planner
│   ├── task_queue.py        # Background task queue
│   └── error_handler.py     # Error recovery with auto-replanning
└── actions/                 # Modular autonomous tools
    ├── computer_control.py  # High-precision Active-Window coordinate tracking
    ├── screen_processor.py  # Visual analysis engine
    ├── open_app.py          # Smart multi-strategy native launcher
    ├── web_search.py        # Web search integration
    └── ...                  # Other autonomous tools
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
