import sys
import time
from colorama import init, Fore, Style

# Initialize colorama for cross-platform support
init(autoreset=True)

class JarvisLogger:
    """Advanced color-coded console logging for JARVIS."""
    
    LEVEL_COLORS = {
        "SYS":  Fore.CYAN,
        "AUTH": Fore.MAGENTA,
        "LIVE": Fore.BLUE,
        "TOOL": Fore.YELLOW,
        "AI":   Fore.GREEN,
        "ERR":  Fore.RED,
        "WARN": Fore.YELLOW + Style.BRIGHT,
        "STATE": Fore.WHITE + Style.BRIGHT
    }
    
    LEVEL_ICONS = {
        "SYS":  "⚙️ ",
        "AUTH": "🔐",
        "LIVE": "🔊",
        "TOOL": "🛠️ ",
        "AI":   "🤖",
        "ERR":  "❌",
        "WARN": "⚠️ ",
        "STATE": "📊"
    }

    @staticmethod
    def log(tag: str, message: str, level: str = "SYS"):
        """
        Prints a structured, colored log message to the console.
        
        Args:
            tag (str): The specific component (e.g. 'REGISTRY', 'UI', 'CLIENT')
            message (str): The log message body
            level (str): The category (SYS, AUTH, LIVE, TOOL, AI, ERR, WARN, STATE)
        """
        color = JarvisLogger.LEVEL_COLORS.get(level.upper(), Fore.WHITE)
        icon  = JarvisLogger.LEVEL_ICONS.get(level.upper(), "📝")
        timestamp = time.strftime("%H:%M:%S")
        
        prefix = f"{Fore.BLACK + Style.BRIGHT}[{timestamp}]{Style.RESET_ALL} {color}{icon} {level.upper()} │ {tag}:"
        print(f"{prefix} {Style.RESET_ALL}{message}")

    @staticmethod
    def state(message: str, icon: str = "✅"):
        """Used for session/connection state transitions."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"{Fore.BLACK + Style.BRIGHT}[{timestamp}]{Style.RESET_ALL} {Fore.WHITE + Style.BRIGHT}{icon} {message}")

    @staticmethod
    def raw(message: str):
        """Standard print replacement."""
        print(message)

# Global instance for easy access
logger = JarvisLogger
