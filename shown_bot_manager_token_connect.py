#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Shown Bot Manager — manage a bot you own from Telegram.

Manager bot:
    BOT_TOKEN = token of THIS manager bot (environment variable)
    ADMIN_ID  = your numeric Telegram user ID (environment variable)

Usage in Telegram:
    /start       Open menu
    /connect     Connect a target bot you own (send its token when prompted)
    /disconnect  Forget the connected target bot from memory
    /cancel      Cancel the current operation

Security:
    - Target bot token is kept in RAM only; it is not written to disk or logs.
    - The token message is deleted on a best-effort basis after receipt.
    - Telegram may process/store messages before deletion. For stronger security,
      configure the target token through a private server environment variable
      instead of sending it in chat.
    - Only use tokens for bots you own or are authorized to administer.

Install:
    pip install requests

Run:
    export BOT_TOKEN="MANAGER_BOT_TOKEN"
    export ADMIN_ID="YOUR_NUMERIC_TELEGRAM_ID"
    python shown_bot_manager.py
"""

import os
import time
import logging
import tempfile
from pathlib import Path

import requests

MANAGER_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()

if not MANAGER_TOKEN:
    raise SystemExit("Set BOT_TOKEN (the manager bot token) in the environment.")
if not ADMIN_ID_RAW.isdigit():
    raise SystemExit("Set ADMIN_ID to your numeric Telegram user ID.")

ADMIN_ID = int(ADMIN_ID_RAW)
MANAGER_API = f"https://api.telegram.org/bot{MANAGER_TOKEN}"
MANAGER_FILE_API = f"https://api.telegram.org/file/bot{MANAGER_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("shown-bot-manager")

session = requests.Session()
user_states = {}
connected_target_tokens = {}  # RAM only; cleared when the process stops.


def api_for(token, method, data=None, files=None, timeout=60):
    """Call the Telegram Bot API for the supplied bot token."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        response = session.post(url, data=data, files=files, timeout=timeout)
        result = response.json()
        if not result.get("ok"):
            log.warning("Telegram API %s failed: %s", method, result.get("description"))
        return result
    except (requests.RequestException, ValueError) as exc:
        log.exception("Telegram API request failed")
        return {"ok": False, "description": str(exc)}


def manager_api(method, data=None, files=None, timeout=60):
    return api_for(MANAGER_TOKEN, method, data, files, timeout)


def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup)
    return manager_api("sendMessage", data=data)


def delete_message(chat_id, message_id):
    # Best effort only; do not assume deletion guarantees the token was never stored.
    return manager_api("deleteMessage", data={
        "chat_id": chat_id,
        "message_id": message_id
    })


def answer_callback(callback_id, text=""):
    return manager_api("answerCallbackQuery", data={
        "callback_query_id": callback_id,
        "text": text
    })


def main_menu():
    return {
        "inline_keyboard": [
            [
                {"text": "🔑 Connect Bot Token", "callback_data": "connect"},
                {"text": "🔌 Disconnect Bot", "callback_data": "disconnect"}
            ],
            [
                {"text": "✏️ Change Name", "callback_data": "change_name"},
                {"text": "🖼 Change Photo", "callback_data": "change_photo"}
            ],
            [
                {"text": "ℹ️ Bot Information", "callback_data": "bot_info"}
            ]
        ]
    }


def is_admin(user_id):
    return user_id == ADMIN_ID


def get_connected_token(user_id):
    return connected_target_tokens.get(user_id)


def handle_start(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    if not is_admin(user_id):
        send_message(chat_id, "⛔ You are not authorized to use this manager.")
        return

    user_states.pop(user_id, None)
    target = get_connected_token(user_id)
    status = "Connected" if target else "Not connected"
    send_message(
        chat_id,
        "💀 SHOWN BOT MANAGER\n\n"
        f"Target bot: {status}\n\n"
        "Connect a bot you own, then use the profile controls below.\n"
        "The target token is held in memory only while this program is running.",
        main_menu()
    )


def begin_connect(chat_id, user_id):
    user_states[user_id] = "awaiting_target_token"
    send_message(
        chat_id,
        "🔑 Send the token of the Telegram bot you own.\n\n"
        "Security note: the manager will try to delete your token message "
        "after receiving it, but sending a token in chat still carries risk. "
        "Use a private chat and never share the token with anyone.\n\n"
        "Send /cancel to stop."
    )


def handle_callback(callback):
    query_id = callback["id"]
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = callback.get("from", {}).get("id")
    action = callback.get("data", "")

    if not is_admin(user_id):
        answer_callback(query_id, "Not authorized.")
        return

    answer_callback(query_id)

    if action == "connect":
        begin_connect(chat_id, user_id)

    elif action == "disconnect":
        connected_target_tokens.pop(user_id, None)
        user_states.pop(user_id, None)
        send_message(chat_id, "🔌 Target bot token forgotten from memory.", main_menu())

    elif action in ("change_name", "change_photo", "bot_info"):
        if not get_connected_token(user_id):
            send_message(chat_id, "First connect your bot using 🔑 Connect Bot Token.", main_menu())
            return

        if action == "change_name":
            user_states[user_id] = "awaiting_name"
            send_message(chat_id, "✏️ Send the new name for the connected bot. (1–64 characters)")
        elif action == "change_photo":
            user_states[user_id] = "awaiting_photo"
            send_message(chat_id, "🖼 Send the new profile photo as a Telegram image.")
        elif action == "bot_info":
            token = get_connected_token(user_id)
            result = api_for(token, "getMe")
            if result.get("ok"):
                bot = result["result"]
                send_message(
                    chat_id,
                    "ℹ️ CONNECTED BOT\n\n"
                    f"Name: {bot.get('first_name', 'Unknown')}\n"
                    f"Username: @{bot.get('username', 'Unknown')}\n"
                    f"Bot ID: {bot.get('id', 'Unknown')}",
                    main_menu()
                )
            else:
                send_message(chat_id, "Couldn't retrieve connected bot information.", main_menu())
    else:
        send_message(chat_id, "Unknown option. Use /start.", main_menu())


def handle_target_token(message, chat_id, user_id):
    token_message_id = message.get("message_id")
    supplied_token = (message.get("text") or "").strip()

    # Delete the message promptly on a best-effort basis.
    if token_message_id:
        delete_message(chat_id, token_message_id)

    if not supplied_token or len(supplied_token) > 200:
        send_message(chat_id, "That doesn't look like a valid bot token. Try again or /cancel.")
        return

    result = api_for(supplied_token, "getMe")
    if not result.get("ok"):
        user_states[user_id] = "awaiting_target_token"
        send_message(chat_id, "❌ Token validation failed. Check the token and try again, or /cancel.")
        return

    bot = result["result"]
    connected_target_tokens[user_id] = supplied_token
    user_states.pop(user_id, None)

    send_message(
        chat_id,
        "✅ Bot connected successfully.\n\n"
        f"Bot: @{bot.get('username', 'Unknown')}\n"
        f"Name: {bot.get('first_name', 'Unknown')}\n\n"
        "Choose a profile action:",
        main_menu()
    )


def update_name(chat_id, user_id, text):
    token = get_connected_token(user_id)
    if not token:
        user_states.pop(user_id, None)
        send_message(chat_id, "No bot is connected. Use /connect first.", main_menu())
        return

    name = text.strip()
    if not name or len(name) > 64:
        send_message(chat_id, "Please send a name between 1 and 64 characters.")
        return

    result = api_for(token, "setMyName", data={"name": name})
    user_states.pop(user_id, None)

    if result.get("ok"):
        send_message(chat_id, f"✅ Connected bot name updated to:\n{name}", main_menu())
    else:
        send_message(
            chat_id,
            "❌ Telegram couldn't update the name.\n"
            f"Reason: {result.get('description', 'Unknown error')}",
            main_menu()
        )


def download_target_file(token, file_id):
    info = api_for(token, "getFile", data={"file_id": file_id})
    if not info.get("ok"):
        raise RuntimeError(info.get("description", "Could not get file information"))

    file_path = info["result"]["file_path"]
    response = session.get(
        f"https://api.telegram.org/file/bot{token}/{file_path}",
        timeout=60
    )
    response.raise_for_status()

    suffix = Path(file_path).suffix or ".jpg"
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        temp.write(response.content)
        return temp.name
    finally:
        temp.close()


def update_photo(chat_id, user_id, message):
    token = get_connected_token(user_id)
    photos = message.get("photo")
    if not token:
        user_states.pop(user_id, None)
        send_message(chat_id, "No bot is connected. Use /connect first.", main_menu())
        return
    if not photos:
        send_message(chat_id, "Please send an image as a Telegram photo.")
        return

    # Download the image using the manager bot token because the image was sent to the manager.
    manager_file_id = photos[-1]["file_id"]
    manager_info = manager_api("getFile", data={"file_id": manager_file_id})
    local_path = None

    try:
        if not manager_info.get("ok"):
            raise RuntimeError(manager_info.get("description", "Could not retrieve uploaded image"))

        file_path = manager_info["result"]["file_path"]
        response = session.get(f"{MANAGER_FILE_API}/{file_path}", timeout=60)
        response.raise_for_status()

        suffix = Path(file_path).suffix or ".jpg"
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            temp.write(response.content)
            local_path = temp.name
        finally:
            temp.close()

        with open(local_path, "rb") as photo_file:
            result = api_for(
                token,
                "setMyProfilePhoto",
                data={"photo": '{"type":"static","photo":"attach://photo"}'},
                files={"photo": ("profile.jpg", photo_file, "application/octet-stream")},
                timeout=120
            )

        user_states.pop(user_id, None)
        if result.get("ok"):
            send_message(chat_id, "✅ Connected bot's profile photo has been updated.", main_menu())
        else:
            send_message(
                chat_id,
                "❌ Telegram couldn't update the profile photo.\n"
                f"Reason: {result.get('description', 'Unknown error')}",
                main_menu()
            )
    except Exception as exc:
        user_states.pop(user_id, None)
        send_message(chat_id, f"❌ Photo update failed: {exc}", main_menu())
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)


def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message.get("from", {}).get("id")

    if not is_admin(user_id):
        send_message(chat_id, "⛔ You are not authorized to use this manager.")
        return

    text = message.get("text", "")
    state = user_states.get(user_id)

    if text.startswith("/start"):
        handle_start(message)
    elif text.startswith("/connect"):
        begin_connect(chat_id, user_id)
    elif text.startswith("/disconnect"):
        connected_target_tokens.pop(user_id, None)
        user_states.pop(user_id, None)
        send_message(chat_id, "🔌 Target bot token forgotten from memory.", main_menu())
    elif text.startswith("/cancel"):
        user_states.pop(user_id, None)
        send_message(chat_id, "Cancelled.", main_menu())
    elif state == "awaiting_target_token":
        handle_target_token(message, chat_id, user_id)
    elif state == "awaiting_name" and text:
        update_name(chat_id, user_id, text)
    elif state == "awaiting_photo" and message.get("photo"):
        update_photo(chat_id, user_id, message)
    elif state == "awaiting_photo":
        send_message(chat_id, "Please upload a photo, or send /cancel.")
    else:
        send_message(chat_id, "Use /start to open the manager menu.")


def run():
    result = manager_api("getMe")
    if not result.get("ok"):
        raise SystemExit(f"Manager bot token check failed: {result.get('description', 'Unknown error')}")

    bot = result["result"]
    log.info("Manager running as @%s (ID: %s)", bot.get("username"), bot.get("id"))
    log.info("Authorized Telegram user ID: %s", ADMIN_ID)

    offset = None
    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset

            updates = session.get(
                f"{MANAGER_API}/getUpdates",
                params=params,
                timeout=60
            ).json()

            if not updates.get("ok"):
                log.warning("getUpdates failed: %s", updates.get("description"))
                time.sleep(3)
                continue

            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    handle_message(update["message"])

        except KeyboardInterrupt:
            log.info("Manager stopped.")
            break
        except Exception:
            log.exception("Polling error")
            time.sleep(3)


if __name__ == "__main__":
    run()
