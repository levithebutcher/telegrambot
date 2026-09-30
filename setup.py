"""
One-time setup script: installs dependencies and creates .env file.
Run: python setup.py
"""

import subprocess
import sys
import os
import shutil


def run(cmd: list[str]) -> bool:
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def main():
    print("=" * 50)
    print("  Universal Downloader Bot — Setup")
    print("=" * 50)

    # 1. Install pip packages
    print("\n[1/3] Installing Python dependencies...")
    if not run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]):
        print("❌ Failed to install dependencies. Check your internet connection.")
        sys.exit(1)
    print("✅ Dependencies installed.")

    # 2. Check ffmpeg
    print("\n[2/3] Checking for ffmpeg...")
    if shutil.which("ffmpeg"):
        print("✅ ffmpeg found.")
    else:
        print("⚠️  ffmpeg NOT found.")
        print("   ffmpeg is required for merging video+audio (e.g. YouTube 1080p).")
        print("   Download from: https://ffmpeg.org/download.html")
        print("   For Windows: https://www.gyan.dev/ffmpeg/builds/")
        print("   Add ffmpeg to your PATH, then re-run this setup.")

    # 3. Create .env
    print("\n[3/3] Creating .env file...")
    if os.path.exists(".env"):
        print("⚠️  .env already exists — skipping.")
    else:
        shutil.copy(".env.example", ".env")
        print("✅ .env created from .env.example")

    # Prompt for token
    token = input("\n🔑 Enter your Telegram Bot Token (from @BotFather): ").strip()
    if token:
        with open(".env", "r") as f:
            content = f.read()
        content = content.replace("your_telegram_bot_token_here", token)
        with open(".env", "w") as f:
            f.write(content)
        print("✅ Token saved to .env")
    else:
        print("⚠️  No token entered. Edit .env manually before running the bot.")

    print("\n" + "=" * 50)
    print("  Setup complete!")
    print("  Start the bot with:  python bot.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
