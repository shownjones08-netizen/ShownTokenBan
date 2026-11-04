RESET = "033[0m"
RESET = "033[0m"
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║   💀 PYTHON SPIRIT — CHANGE NAME & PIC                  ║
║   Creator: SKHHACKER                                    ║
║   FINAL FIX • 100% WORKING                            ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import requests
import json
import base64
from pathlib import Path

# ============================================================
# COLORS
# ============================================================

R = '\033[91m'
G = '\033[92m'
Y = '\033[93m'
C = '\033[96m'
N = '\033[0m'
BOLD = '\033[1m'

def clear():
    os.system('clear' if os.name == 'posix' else 'cls')

def banner():
    clear()
    print(f"""
{R}╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   {BOLD}{R}💀 PYTHON SPIRIT — CHANGE NAME & PIC{R}                  ║
║   {BOLD}FINAL FIX • 100% WORKING{R}                                ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
{N}
""")

# ============================================================
# TELEGRAM API
# ============================================================

def call_api(token, method, data=None, files=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        if files:
            r = requests.post(url, files=files, timeout=30)
        elif data:
            r = requests.post(url, json=data, timeout=30)
        else:
            r = requests.get(url, timeout=30)
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def get_me(token):
    return call_api(token, "getMe")

def set_name(token, name):
    return call_api(token, "setMyName", {"name": name})

def get_name(token):
    r = call_api(token, "getMyName")
    return r.get("result", {}).get("name", None)

def set_photo(token, photo_path):
    """Set bot profile photo using Telegram Bot API."""
    try:
        if not os.path.exists(photo_path):
            return {"ok": False, "description": "File not found"}

        with open(photo_path, "rb") as f:
            files = {
                "photo": ("photo.jpg", f, "image/jpeg")
            }
            data = {
                "photo": '{"type":"static","photo":"attach://photo"}'
            }

            url = f"https://api.telegram.org/bot{token}/setMyProfilePhoto"
            r = requests.post(url, data=data, files=files, timeout=30)
            return r.json()

    except Exception as e:
        return {"ok": False, "description": str(e)}

# ============================================================
# CHANGE NAME
# ============================================================

def change_name():
    print(f"""
{C}╔═══════════════════════════════════════════════════════════╗
║   {BOLD}✏️  CHANGE BOT NAME{N}{C}                                    ║
╚═══════════════════════════════════════════════════════════╝
{N}
""")
    
    token = input(f"{Y}📤 Enter bot token: {N}").strip()
    if not token:
        print(f"{R}❌ No token!{N}")
        return
    
    print(f"{C}🔍 Checking bot...{N}")
    me = get_me(token)
    if not me.get("ok"):
        print(f"{R}❌ Invalid token!{N}")
        return
    
    bot_username = me["result"].get("username", "Unknown")
    current_name = get_name(token) or me["result"].get("first_name", "Unknown")
    
    print(f"{G}✅ Bot: @{bot_username}{N}")
    print(f"{C}📛 Current Name: {current_name}{N}")
    
    new_name = input(f"{Y}✏️ Enter new name: {N}").strip()
    if not new_name:
        print(f"{R}❌ No name!{N}")
        return
    
    print(f"{C}⏳ Changing name...{N}")
    r = set_name(token, new_name)
    
    if r.get("ok"):
        print(f"{G}✅ Name changed to: {new_name}{N}")
    else:
        print(f"{R}❌ Error: {r.get('description', 'Unknown')}{N}")

# ============================================================
# CHANGE PROFILE PICTURE
# ============================================================

def change_pic():
    print(f"""
{C}╔═══════════════════════════════════════════════════════════╗
║   {BOLD}🖼️  CHANGE PROFILE PICTURE{N}{C}                            ║
║                                                           ║
║   {Y}•{C} Enter bot token                                        ║
║   {Y}•{C} Enter photo file path                                 ║
║   {Y}•{C} 100% WORKING                                         ║
╚═══════════════════════════════════════════════════════════╝
{N}
""")
    
    token = input(f"{Y}📤 Enter bot token: {N}").strip()
    if not token:
        print(f"{R}❌ No token!{N}")
        return
    
    print(f"{C}🔍 Checking bot...{N}")
    me = get_me(token)
    if not me.get("ok"):
        print(f"{R}❌ Invalid token!{N}")
        return
    
    bot_username = me["result"].get("username", "Unknown")
    print(f"{G}✅ Bot: @{bot_username}{N}")
    
    photo_path = input(f"{Y}🖼️ Enter photo file path: {N}").strip()
    if not photo_path:
        print(f"{R}❌ No path!{N}")
        return
    
    if not os.path.exists(photo_path):
        print(f"{R}❌ File not found: {photo_path}{N}")
        return
    
    size = os.path.getsize(photo_path)
    print(f"{C}⏳ Uploading photo... ({size/1024:.1f} KB){N}")
    
    r = set_photo(token, photo_path)
    
    if r.get("ok"):
        print(f"{G}✅ Profile picture updated!{N}")
    else:
        error = r.get('description', 'Unknown')
        print(f"{R}❌ Error: {error}{N}")
        
        if "Not Found" in error or "Bad Request" in error:
            print(f"""
{Y}💡 FIXES:{N}
   1. Use a JPG image (convert PNG to JPG)
   2. Make image smaller (under 500KB)
   3. Use square image (1:1 ratio)
   4. Try this command to convert:
      ffmpeg -i input.png -q:v 2 -vf "scale=500:500" output.jpg
""")

# ============================================================
# MAIN
# ============================================================

def main():
    while True:
        banner()
        
        print(f"""
{BOLD}┌─────────────────────────────────────────────────────────────┐
│  {R}💀 PYTHON SPIRIT — CHANGE NAME & PIC{N}{BOLD}                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  {R}1.{N} {BOLD}CHANGE NAME{N}                                     │
│  {R}2.{N} {BOLD}CHANGE PROFILE PICTURE{N}                         │
│  {R}3.{N} {BOLD}EXIT{N}                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
""")
        
        choice = input(f"{Y}➜ Enter your choice [1-3]: {N}").strip()
        
        if choice == "3":
            print(f"\n{R}💀 Exiting Python Spirit...{N}")
            sys.exit(0)
        elif choice == "1":
            change_name()
        elif choice == "2":
            change_pic()
        else:
            print(f"{R}❌ Invalid choice!{N}")
        
        input(f"\n{C}Press Enter to continue...{N}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{R}💀 Interrupted!{N}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{R}❌ Error: {e}{N}")
        sys.exit(0)