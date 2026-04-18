import os
import subprocess
import sys
from pathlib import Path

# Safeguard against UnicodeEncodeError on older Windows terminals
_stdout_encoding = getattr(sys.stdout, 'encoding', None)
if _stdout_encoding and hasattr(sys.stdout, 'reconfigure') and _stdout_encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def print_step(msg):
    print(f"\n🚀 {msg}")

def main():
    print("🤖 Starting Setup for J.A.R.V.I.S...\n")

    # Install 'uv' in the current python environment to manage everything quickly
    print_step("Ensuring 'uv' package manager is installed...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-U", "uv", "--quiet"], 
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        try:
            # Fallback for PEP 668 externally-managed environments (macOS Homebrew, Ubuntu APT)
            subprocess.run([sys.executable, "-m", "pip", "install", "-U", "uv", "--break-system-packages", "--quiet"], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print("❌ Error: Failed to install 'uv'. Please ensure you have internet access and pip works.")
            sys.exit(1)

    venv_dir = Path("venv")
    
    # Bypass user-level cache permissions (os error 13) that occur if uv was previously run with sudo
    uv_env = os.environ.copy()
    uv_env["UV_NO_CACHE"] = "1"

    # Check available Python version
    if sys.version_info < (3, 11):
        print_step("Python version is older than 3.11. Creating venv with a new Python 3.12 via uv...")
        # 'uv' will automatically download and install Python 3.12 if it's not present on the system
        subprocess.run([sys.executable, "-m", "uv", "venv", "--python", "3.12", "venv"], check=True, env=uv_env)
    else:
        print_step(f"Python {sys.version_info.major}.{sys.version_info.minor} detected. Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "uv", "venv", "venv"], check=True, env=uv_env)

    # Determine the venv python executable path cross-platform
    if os.name == 'nt':
        venv_python = str(venv_dir / "Scripts" / "python.exe")
    else:
        venv_python = str(venv_dir / "bin" / "python")

    if not os.path.exists(venv_python):
        print(f"❌ Error: Could not find Python executable at {venv_python}")
        sys.exit(1)

    print_step("Installing dependencies from requirements.txt using uv...")
    subprocess.run([venv_python, "-m", "uv", "pip", "install", "-r", "requirements.txt"], check=True, env=uv_env)

    print_step("Installing Playwright browsers...")
    subprocess.run([venv_python, "-m", "playwright", "install"], check=True)

    print("\n" + "="*50)
    print("✅ Setup is completely finished!")
    print("="*50)
    print("To start J.A.R.V.I.S, you must first activate your virtual environment:")

    if os.name == 'nt':
        print("\n  1. Activate the environment (choose your terminal):")
        print("     PowerShell:    .\\venv\\Scripts\\Activate.ps1")
        print("     Command Prompt: .\\venv\\Scripts\\activate.bat")
        print("     Git Bash:       source venv/Scripts/activate")
        print("\n  2. Run the assistant:")
        print("     python main.py")
    else:
        print("\n  1. Activate the environment:")
        print("     source venv/bin/activate")
        print("\n  2. Run the assistant:")
        print("     python main.py")
    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()