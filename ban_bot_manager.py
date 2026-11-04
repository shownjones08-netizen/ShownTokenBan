#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHOWN BAN BOT MANAGER
---------------------
One manager bot connects to a Ban Bot token. The connected bot then runs its
own Telegram update loop and handles users directly.

Environment variables:
  BOT_TOKEN  = manager bot token
  ADMIN_ID   = your numeric Telegram user ID

Install:
  pip install -r requirements.txt

Run:
  python ban_bot_manager.py

Important:
- Add the connected Ban Bot to each group and make it an administrator with
  "Ban users" permission. Delete messages permission is needed for /purge.
- Tokens are held in RAM only and are lost when this process restarts.
- Send tokens only in a private chat. The manager attempts to delete the
  token message, but deletion is not a guarantee of secrecy.
- Use only bot tokens you own or are authorized to administer.
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

MANAGER_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()

if not MANAGER_TOKEN:
    raise SystemExit("Missing BOT_TOKEN environment variable.")
if not ADMIN_ID_RAW.isdigit():
    raise SystemExit("ADMIN_ID must be your numeric Telegram user ID.")

ADMIN_ID = int(ADMIN_ID_RAW)
API_ROOT = "https://api.telegram.org/bot{}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("shown-ban-manager")

HTTP = requests.Session()
manager_offset = None
manager_state = {}
connected = {}          # admin_id -> {"token": ..., "username": ..., "stop": Event, "thread": Thread}
warnings_store = {}     # (chat_id, user_id) -> list[str]
target_locks = threading.Lock()


# ----------------------------- Telegram API -----------------------------

def api(token, method, data=None, timeout=55):
    """Call Telegram Bot API without ever logging the supplied token."""
    try:
        response = requests.post(
            API_ROOT.format(token) + "/" + method,
            data=data or {},
            timeout=timeout
        )
        result = response.json()
        if not result.get("ok"):
            log.warning("Telegram API method %s failed: %s",
                        method, result.get("description", "Unknown error"))
        return result
    except (requests.RequestException, ValueError) as exc:
        log.warning("Telegram API request failed for %s: %s", method, exc)
        return {"ok": False, "description": str(exc)}


def send(token, chat_id, text, markup=None, reply_to=None):
    data = {"chat_id": chat_id, "text": text}
    if markup:
        import json
        data["reply_markup"] = json.dumps(markup)
    if reply_to:
        data["reply_to_message_id"] = reply_to
    return api(token, "sendMessage", data)


def answer_callback(token, callback_id, text=""):
    return api(token, "answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text
    })


def is_private(message):
    return message.get("chat", {}).get("type") == "private"


def is_group(message):
    return message.get("chat", {}).get("type") in ("group", "supergroup")


def get_target(admin_id=ADMIN_ID):
    with target_locks:
        return connected.get(admin_id)


def connected_status():
    target = get_target()
    return f"🟢 Connected: @{target['username']}" if target else "🔴 No Ban Bot connected"


# ------------------------------- Keyboards ------------------------------

def manager_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🟩 CONNECT BAN BOT", "callback_data": "mgr_connect"},
                {"text": "🟥 DISCONNECT", "callback_data": "mgr_disconnect"}
            ],
            [
                {"text": "🔎 BOT STATUS", "callback_data": "mgr_status"},
                {"text": "📖 COMMANDS", "callback_data": "mgr_help"}
            ]
        ]
    }


def banbot_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🟥 BAN", "callback_data": "menu_ban"},
                {"text": "🟩 UNBAN", "callback_data": "menu_unban"}
            ],
            [
                {"text": "🟧 MUTE", "callback_data": "menu_mute"},
                {"text": "🔊 UNMUTE", "callback_data": "menu_unmute"}
            ],
            [
                {"text": "⚠️ WARN", "callback_data": "menu_warn"},
                {"text": "🧹 PURGE", "callback_data": "menu_purge"}
            ],
            [
                {"text": "🆔 MY ID", "callback_data": "menu_id"},
                {"text": "📚 HELP", "callback_data": "menu_help"}
            ]
        ]
    }


def set_commands(token, commands):
    import json
    return api(token, "setMyCommands", {
        "commands": json.dumps(commands)
    })


MANAGER_COMMANDS = [
    {"command": "start", "description": "Open manager dashboard"},
    {"command": "connect", "description": "Connect your Ban Bot token"},
    {"command": "disconnect", "description": "Disconnect the Ban Bot"},
    {"command": "status", "description": "Show connection status"},
    {"command": "cancel", "description": "Cancel current action"},
]

BAN_COMMANDS = [
    {"command": "start", "description": "Open Ban Bot welcome menu"},
    {"command": "help", "description": "Show moderation commands"},
    {"command": "ban", "description": "Ban a user (reply or user ID)"},
    {"command": "unban", "description": "Unban a user (user ID)"},
    {"command": "kick", "description": "Remove a user from the group"},
    {"command": "mute", "description": "Mute a user (e.g. /mute 30m)"},
    {"command": "unmute", "description": "Remove a user's mute"},
    {"command": "warn", "description": "Warn a user"},
    {"command": "warnings", "description": "Show a user's warnings"},
    {"command": "purge", "description": "Delete replied message and newer messages"},
    {"command": "id", "description": "Show chat and user IDs"},
]


# --------------------------- Manager bot logic ---------------------------

def manager_start(chat_id):
    text = (
        "✦ 𝗦𝗛𝗢𝗪𝗡 𝗕𝗔𝗡 𝗕𝗢𝗧 𝗠𝗔𝗡𝗔𝗚𝗘𝗥 ✦\n\n"
        "Connect the token of a Ban Bot you own. The connected bot will run "
        "separately and users will interact with that bot directly.\n\n"
        f"{connected_status()}\n\n"
        "Choose an action below."
    )
    send(MANAGER_TOKEN, chat_id, text, manager_keyboard())


def manager_connect(chat_id, user_id):
    manager_state[user_id] = "awaiting_token"
    send(
        MANAGER_TOKEN, chat_id,
        "🔐 𝗖𝗢𝗡𝗡𝗘𝗖𝗧 𝗬𝗢𝗨𝗥 𝗕𝗢𝗧\n\n"
        "Send the BotFather token in this private chat.\n"
        "I will validate it, try to delete the token message, and start the bot.\n\n"
        "⚠️ Never send a token in a group. Send /cancel to stop."
    )


def stop_connected(admin_id=ADMIN_ID):
    with target_locks:
        item = connected.pop(admin_id, None)
    if item:
        item["stop"].set()
        return True
    return False


def handle_manager_message(message):
    chat_id = message["chat"]["id"]
    user_id = message.get("from", {}).get("id")
    if user_id != ADMIN_ID or not is_private(message):
        send(MANAGER_TOKEN, chat_id, "⛔ Private admin access only.")
        return

    text = (message.get("text") or "").strip()
    state = manager_state.get(user_id)

    if text.startswith("/start"):
        manager_state.pop(user_id, None)
        manager_start(chat_id)
    elif text.startswith("/connect"):
        manager_connect(chat_id, user_id)
    elif text.startswith("/disconnect"):
        manager_state.pop(user_id, None)
        send(MANAGER_TOKEN, chat_id,
             "🔌 Ban Bot disconnected." if stop_connected() else "No bot was connected.",
             manager_keyboard())
    elif text.startswith("/status"):
        manager_start(chat_id)
    elif text.startswith("/cancel"):
        manager_state.pop(user_id, None)
        send(MANAGER_TOKEN, chat_id, "Operation cancelled.", manager_keyboard())
    elif state == "awaiting_token":
        token_message_id = message.get("message_id")
        if token_message_id:
            api(MANAGER_TOKEN, "deleteMessage", {
                "chat_id": chat_id, "message_id": token_message_id
            })
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", text):
            send(MANAGER_TOKEN, chat_id,
                 "❌ Token format does not look valid. Try again or /cancel.")
            return
        result = api(text, "getMe")
        if not result.get("ok"):
            send(MANAGER_TOKEN, chat_id,
                 "❌ Token validation failed. Check it and send again, or /cancel.")
            return
        bot = result["result"]
        stop_connected()
        stop_event = threading.Event()
        worker = threading.Thread(
            target=run_target_bot,
            args=(text, stop_event),
            daemon=True,
            name=f"banbot-{bot.get('id')}"
        )
        item = {
            "token": text,
            "username": bot.get("username", "unknown"),
            "stop": stop_event,
            "thread": worker
        }
        with target_locks:
            connected[user_id] = item
        manager_state.pop(user_id, None)
        set_commands(text, BAN_COMMANDS)
        worker.start()
        send(
            MANAGER_TOKEN, chat_id,
            "✅ 𝗕𝗢𝗧 𝗖𝗢𝗡𝗡𝗘𝗖𝗧𝗘𝗗 & 𝗦𝗧𝗔𝗥𝗧𝗘𝗗\n\n"
            f"Bot: @{bot.get('username', 'unknown')}\n"
            f"Name: {bot.get('first_name', 'Unknown')}\n\n"
            "Users can now open the connected bot and send /start.\n"
            "Add it to your group as an administrator and grant Ban users permission.",
            manager_keyboard()
        )
    else:
        send(MANAGER_TOKEN, chat_id, "Use /start to open the manager.", manager_keyboard())


def handle_manager_callback(callback):
    user_id = callback.get("from", {}).get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    action = callback.get("data", "")
    if user_id != ADMIN_ID:
        answer_callback(MANAGER_TOKEN, callback["id"], "Not authorized")
        return
    answer_callback(MANAGER_TOKEN, callback["id"])
    if action == "mgr_connect":
        manager_connect(chat_id, user_id)
    elif action == "mgr_disconnect":
        stopped = stop_connected()
        send(MANAGER_TOKEN, chat_id,
             "🔌 Disconnected." if stopped else "No bot was connected.",
             manager_keyboard())
    elif action == "mgr_status":
        manager_start(chat_id)
    elif action == "mgr_help":
        send(
            MANAGER_TOKEN, chat_id,
            "𝗠𝗔𝗡𝗔𝗚𝗘𝗥 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦\n\n"
            "/connect — connect a Ban Bot token\n"
            "/status — show connection status\n"
            "/disconnect — stop the connected bot\n"
            "/cancel — cancel token entry\n\n"
            "The target bot token is kept in memory only. Reconnect after a restart.",
            manager_keyboard()
        )


# ----------------------------- Ban Bot logic -----------------------------

def parse_user_id(message, args):
    reply = message.get("reply_to_message")
    if reply and reply.get("from"):
        return int(reply["from"]["id"])
    if args:
        match = re.search(r"\d{5,}", args[0])
        if match:
            return int(match.group())
    return None


def actor_is_admin(token, chat_id, user_id):
    result = api(token, "getChatMember", {
        "chat_id": chat_id, "user_id": user_id
    })
    if not result.get("ok"):
        return False
    status = result["result"].get("status")
    return status in ("creator", "administrator")


def bot_can_restrict(token, chat_id):
    me = api(token, "getMe")
    if not me.get("ok"):
        return False
    member = api(token, "getChatMember", {
        "chat_id": chat_id, "user_id": me["result"]["id"]
    })
    if not member.get("ok"):
        return False
    info = member["result"]
    return info.get("status") == "administrator" and info.get("can_restrict_members", False)


def moderation_guard(token, message):
    if not is_group(message):
        send(token, message["chat"]["id"],
             "⚠️ Moderation commands work inside groups. Add me to your group as an admin.")
        return False
    chat_id = message["chat"]["id"]
    actor_id = message.get("from", {}).get("id")
    if not actor_is_admin(token, chat_id, actor_id):
        send(token, chat_id, "⛔ Only group administrators can use moderation commands.",
             reply_to=message.get("message_id"))
        return False
    if not bot_can_restrict(token, chat_id):
        send(token, chat_id,
             "⚠️ I need administrator status with the **Ban users** permission.",
             reply_to=message.get("message_id"))
        return False
    return True


def duration_seconds(value):
    match = re.fullmatch(r"(\d+)([mhd])", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * {"m": 60, "h": 3600, "d": 86400}[unit]
    if amount < 1 or seconds > 366 * 86400:
        return None
    return seconds


def banbot_start(token, message):
    chat_id = message["chat"]["id"]
    text = (
        "✦ 𝗦𝗛𝗢𝗪𝗡 𝗕𝗔𝗡 𝗕𝗢𝗧 ✦\n\n"
        "Welcome! I help group administrators keep their communities safe.\n\n"
        "🛡️ Ban • Unban • Kick • Mute\n"
        "⚠️ Warnings • 🧹 Purge • 🆔 IDs\n\n"
        "Add me to your group, promote me to admin, and grant the "
        "Ban users permission to enable moderation.\n\n"
        "Tap a button or use /help to see commands."
    )
    send(token, chat_id, text, banbot_keyboard())


def banbot_help(token, chat_id):
    send(
        token, chat_id,
        "📚 𝗠𝗢𝗗𝗘𝗥𝗔𝗧𝗜𝗢𝗡 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦\n\n"
        "Reply to a user's message or provide their numeric Telegram ID.\n\n"
        "🟥 /ban — ban user\n"
        "🟩 /unban USER_ID — unban user\n"
        "🚪 /kick — remove user (reply to them)\n"
        "🟧 /mute 30m — mute user (reply; use 10m, 2h, 1d)\n"
        "🔊 /unmute — unmute user (reply)\n"
        "⚠️ /warn — warn user (reply)\n"
        "📋 /warnings USER_ID — show warnings\n"
        "🧹 /purge — delete from replied message to command\n"
        "🆔 /id — show your ID and chat ID\n\n"
        "Admin-only commands. Bot needs group admin permissions."
    )


def do_moderation(token, message, command, args):
    chat_id = message["chat"]["id"]
    msg_id = message.get("message_id")
    if not moderation_guard(token, message):
        return

    target_id = parse_user_id(message, args)
    if command == "unban":
        if not target_id and args and args[0].isdigit():
            target_id = int(args[0])
        if not target_id:
            send(token, chat_id, "Usage: /unban USER_ID", reply_to=msg_id)
            return
        result = api(token, "unbanChatMember", {
            "chat_id": chat_id, "user_id": target_id, "only_if_banned": True
        })
        send(token, chat_id,
             "🟩 User unbanned." if result.get("ok") else
             f"❌ Unban failed: {result.get('description', 'Unknown error')}",
             reply_to=msg_id)
        return

    if not target_id:
        send(token, chat_id, "Reply to a user's message or provide their numeric user ID.",
             reply_to=msg_id)
        return

    if command == "ban":
        result = api(token, "banChatMember", {
            "chat_id": chat_id, "user_id": target_id
        })
        success = "🟥 User banned."
    elif command == "kick":
        result = api(token, "banChatMember", {
            "chat_id": chat_id, "user_id": target_id
        })
        if result.get("ok"):
            api(token, "unbanChatMember", {
                "chat_id": chat_id, "user_id": target_id, "only_if_banned": True
            })
        success = "🚪 User removed from the group."
    elif command == "mute":
        duration = duration_seconds(args[0]) if args else None
        if duration is None:
            send(token, chat_id, "Usage: reply to a user with /mute 30m (10m, 2h, 1d).",
                 reply_to=msg_id)
            return
        until = int(time.time()) + duration
        result = api(token, "restrictChatMember", {
            "chat_id": chat_id,
            "user_id": target_id,
            "permissions": '{"can_send_messages":false,"can_send_audios":false,'
                           '"can_send_documents":false,"can_send_photos":false,'
                           '"can_send_videos":false,"can_send_video_notes":false,'
                           '"can_send_voice_notes":false,"can_send_polls":false,'
                           '"can_send_other_messages":false,"can_add_web_page_previews":false}',
            "until_date": until
        })
        success = f"🟧 User muted for {args[0]}."
    elif command == "unmute":
        result = api(token, "restrictChatMember", {
            "chat_id": chat_id,
            "user_id": target_id,
            "permissions": '{"can_send_messages":true,"can_send_audios":true,'
                           '"can_send_documents":true,"can_send_photos":true,'
                           '"can_send_videos":true,"can_send_video_notes":true,'
                           '"can_send_voice_notes":true,"can_send_polls":true,'
                           '"can_send_other_messages":true,"can_add_web_page_previews":true}'
        })
        success = "🔊 User unmuted."
    elif command == "warn":
        key = (chat_id, target_id)
        warnings_store.setdefault(key, []).append(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        )
        count = len(warnings_store[key])
        result = {"ok": True}
        success = f"⚠️ Warning issued. Total warnings in this running session: {count}."
    else:
        return

    if result.get("ok"):
        send(token, chat_id, success, reply_to=msg_id)
    else:
        send(token, chat_id,
             f"❌ Action failed: {result.get('description', 'Unknown error')}",
             reply_to=msg_id)


def handle_banbot_callback(token, callback):
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    action = callback.get("data", "")
    answer_callback(token, callback["id"])
    if action == "menu_help":
        banbot_help(token, chat_id)
    elif action == "menu_id":
        user_id = callback.get("from", {}).get("id")
        send(token, chat_id, f"🆔 Your user ID: {user_id}\nChat ID: {chat_id}")
    elif action in ("menu_ban", "menu_unban", "menu_mute", "menu_unmute",
                    "menu_warn", "menu_purge"):
        hints = {
            "menu_ban": "Reply to a user's message with /ban.",
            "menu_unban": "Send /unban USER_ID.",
            "menu_mute": "Reply with /mute 30m.",
            "menu_unmute": "Reply with /unmute.",
            "menu_warn": "Reply with /warn.",
            "menu_purge": "Reply to the first message to delete, then send /purge."
        }
        send(token, chat_id, hints[action])


def handle_banbot_message(token, message):
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/start"):
        banbot_start(token, message)
        return
    if text.startswith("/help"):
        banbot_help(token, chat_id)
        return
    if text.startswith("/id"):
        send(token, chat_id,
             f"🆔 Your ID: {message.get('from', {}).get('id')}\nChat ID: {chat_id}")
        return

    parts = text.split()
    command = parts[0].split("@")[0].lower()
    args = parts[1:]

    if command in ("/ban", "/unban", "/kick", "/mute", "/unmute", "/warn"):
        do_moderation(token, message, command[1:], args)
    elif command == "/warnings":
        if not is_group(message):
            send(token, chat_id, "Use /warnings USER_ID inside the group.")
            return
        if not moderation_guard(token, message):
            return
        if not args or not args[0].isdigit():
            send(token, chat_id, "Usage: /warnings USER_ID")
            return
        key = (chat_id, int(args[0]))
        count = len(warnings_store.get(key, []))
        send(token, chat_id, f"⚠️ Warnings recorded this session: {count}")
    elif command == "/purge":
        if not moderation_guard(token, message):
            return
        reply = message.get("reply_to_message")
        if not reply:
            send(token, chat_id, "Reply to the first message to delete, then send /purge.")
            return
        first_id = reply["message_id"]
        last_id = message["message_id"]
        deleted = 0
        for mid in range(first_id, last_id + 1):
            result = api(token, "deleteMessage", {"chat_id": chat_id, "message_id": mid})
            if result.get("ok"):
                deleted += 1
            time.sleep(0.03)
        send(token, chat_id, f"🧹 Purge complete. Deleted {deleted} messages.")
    elif command == "/admin":
        if is_private(message):
            send(token, chat_id, "Add me to a group as an administrator to use moderation.")
        else:
            send(token, chat_id,
                 "🛡️ I am ready. Admins can use /help for moderation commands.")


def run_target_bot(token, stop_event):
    me = api(token, "getMe")
    if not me.get("ok"):
        log.error("Connected bot failed startup validation.")
        return
    bot_id = me["result"]["id"]
    username = me["result"].get("username", "unknown")
    log.info("Target Ban Bot started: @%s (id=%s)", username, bot_id)
    offset = None
    backoff = 2
    while not stop_event.is_set():
        try:
            params = {"timeout": 25, "allowed_updates": '["message","callback_query"]'}
            if offset is not None:
                params["offset"] = offset
            response = requests.get(
                API_ROOT.format(token) + "/getUpdates",
                params=params,
                timeout=35
            ).json()
            if not response.get("ok"):
                description = response.get("description", "")
                if "Conflict" in description:
                    log.error("Polling conflict for @%s. Another process may be polling this token.", username)
                    break
                log.warning("Target polling error for @%s: %s", username, description)
                stop_event.wait(backoff)
                backoff = min(backoff * 2, 20)
                continue
            backoff = 2
            for update in response.get("result", []):
                offset = update["update_id"] + 1
                if stop_event.is_set():
                    break
                if "callback_query" in update:
                    handle_banbot_callback(token, update["callback_query"])
                elif "message" in update:
                    handle_banbot_message(token, update["message"])
        except (requests.RequestException, ValueError) as exc:
            log.warning("Target bot network error: %s", exc)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, 20)
        except Exception:
            log.exception("Unexpected target bot error")
            stop_event.wait(2)
    log.info("Target Ban Bot stopped: @%s", username)


# ------------------------------ Main polling -----------------------------

def main():
    me = api(MANAGER_TOKEN, "getMe")
    if not me.get("ok"):
        raise SystemExit("Manager BOT_TOKEN is invalid or Telegram is unreachable.")
    manager = me["result"]
    set_commands(MANAGER_TOKEN, MANAGER_COMMANDS)
    log.info("Manager running as @%s. Admin ID configured.", manager.get("username"))

    global manager_offset
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": '["message","callback_query"]'}
            if manager_offset is not None:
                params["offset"] = manager_offset
            updates = requests.get(
                API_ROOT.format(MANAGER_TOKEN) + "/getUpdates",
                params=params,
                timeout=35
            ).json()
            if not updates.get("ok"):
                log.warning("Manager polling failed: %s", updates.get("description"))
                time.sleep(3)
                continue
            for update in updates.get("result", []):
                manager_offset = update["update_id"] + 1
                if "callback_query" in update:
                    handle_manager_callback(update["callback_query"])
                elif "message" in update:
                    handle_manager_message(update["message"])
        except KeyboardInterrupt:
            log.info("Stopping manager and connected bot.")
            stop_connected()
            break
        except Exception:
            log.exception("Manager polling error")
            time.sleep(3)


if __name__ == "__main__":
    main()
