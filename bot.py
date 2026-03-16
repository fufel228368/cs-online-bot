import os
import json
import logging
import html
import a2s
import telebot
from flask import Flask, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set in environment!")
else:
    logger.info("BOT_TOKEN loaded (first chars): %s***", BOT_TOKEN[:6])

CS_SERVER_ADDRESS = ("91.211.118.88", 27055)
SERVER_NAME_FALLBACK = "Харьковский  Фронт  18+ (+VIP)"
SHIFT_INFO = "Неизвестно"
FRAGS = 0

# Файл с привязками ник в игре → Telegram (ник храним в нижнем регистре)
NICK_LINKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nick_links.json")


def load_nick_links():
    """Загружает словарь: ник_в_нижнем_регистре -> {"user_id": int, "username": str или None}"""
    try:
        with open(NICK_LINKS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {k: {"user_id": v["user_id"], "username": v.get("username")} for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.exception("Error loading nick_links: %s", e)
        return {}


def save_nick_links(data):
    """Сохраняет словарь привязок ников."""
    try:
        with open(NICK_LINKS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error saving nick_links: %s", e)


def add_nick_link(nick: str, user_id: int, username: str or None):
    nick_key = nick.strip().lower()
    if not nick_key:
        return False
    links = load_nick_links()
    links[nick_key] = {"user_id": user_id, "username": username}
    save_nick_links(links)
    return True


def get_nick_link(nick: str):
    """Возвращает {"user_id": int, "username": ...} или None."""
    return load_nick_links().get(nick.strip().lower())


def remove_nick_link(nick: str):
    nick_key = nick.strip().lower()
    links = load_nick_links()
    if nick_key in links:
        del links[nick_key]
        save_nick_links(links)
        return True
    return False


def html_escape(s: str) -> str:
    """Экранирует HTML, чтобы ник с < или & не ломал разметку."""
    return html.escape(s) if s else ""


bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)
app = Flask(__name__)

# Выставляем webhook при старте приложения (для gunicorn)
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
if RENDER_EXTERNAL_URL:
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    try:
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        logger.info("Webhook set to: %s", webhook_url)
    except Exception as e:
        logger.exception("Failed to set webhook: %s", e)


def query_server_info():
    try:
        info = a2s.info(CS_SERVER_ADDRESS, timeout=2.5)
        players = a2s.players(CS_SERVER_ADDRESS, timeout=2.5)
        return True, info, players
    except Exception as e:
        logger.exception("Error while querying CS server: %s", e)
        return False, None, None


def build_online_message(is_online: bool, info, players):
    ip, port = CS_SERVER_ADDRESS

    if not is_online:
        return (
            "<b>Состояние сервера — 🔴 Офлайн</b>\n"
            f"<b>Сервер:</b> {SERVER_NAME_FALLBACK}\n"
            f"<b>IP:</b> {ip}:{port}\n"
        )

    server_name = getattr(info, "server_name", None) or SERVER_NAME_FALLBACK
    current_map = getattr(info, "map_name", None) or "Неизвестно"
    player_count = getattr(info, "player_count", 0)
    max_players = getattr(info, "max_players", 0)

    lines = [
        "<b>Состояние сервера — 🟢 Онлайн</b>",
        f"<b>Сервер:</b> {server_name}",
        f"<b>IP:</b> {ip}:{port}",
        f"<b>Карта:</b> {current_map}",
        f"<b>Онлайн:</b> {player_count}/{max_players}",
        "",
        "<b>Игроки:</b> (нажми на ник — откроется профиль в TG)",
    ]

    nick_links = load_nick_links()
    if players:
        for player in players:
            name = (player.name or "").strip() or "—"
            safe_name = html_escape(name)
            link = get_nick_link(name) if name else None
            if link:
                user_id = link["user_id"]
                # tg://user?id= открывает профиль в Telegram по клику
                lines.append(f'• <a href="tg://user?id={user_id}">{safe_name}</a>')
            else:
                lines.append(f"• {safe_name}")
    else:
        lines.append("Нет игроков")

    return "\n".join(lines)


# ===== ОБРАБОТЧИКИ =====

@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message):
    logger.info("Got /start from chat %s", message.chat.id)
    bot.reply_to(
        message,
        "Бот запущен.\n"
        "• /ONLINE — статистика сервера (игроки кликабельны, если привязали ник через /link)\n"
        "• /link Ник — привязать свой ник в игре к профилю в TG",
    )


@bot.message_handler(commands=["online", "ONLINE"])
def handle_online(message: telebot.types.Message):
    logger.info("Got /ONLINE from chat %s", message.chat.id)
    bot.reply_to(message, ".")
    is_online, info, players = query_server_info()
    msg = build_online_message(is_online, info, players)
    bot.send_message(message.chat.id, msg, disable_web_page_preview=True)


@bot.message_handler(commands=["link", "bind", "привязать"])
def handle_link(message: telebot.types.Message):
    """Привязать свой ник в игре к профилю в Telegram. Пример: /link МойНик"""
    text = (message.text or "").strip().split(maxsplit=1)
    if len(text) < 2:
        bot.reply_to(
            message,
            "Напиши ник, который используешь на сервере.\n"
            "Пример: <code>/link МойНик</code>\n"
            "После этого в статистике /ONLINE твой ник можно будет нажать — откроется твой профиль в TG.",
        )
        return
    nick = text[1].strip()
    if not nick:
        bot.reply_to(message, "Укажи ник, например: /link МойНик")
        return
    user_id = message.from_user.id
    username = message.from_user.username if message.from_user else None
    add_nick_link(nick, user_id, username)
    bot.reply_to(message, f"✅ Привязано: <b>{html_escape(nick)}</b> → твой профиль в TG. В /ONLINE ник будет кликабельным.")


@bot.message_handler(commands=["unlink", "unbind", "отвязать"])
def handle_unlink(message: telebot.types.Message):
    """Отвязать ник. Пример: /unlink МойНик"""
    text = (message.text or "").strip().split(maxsplit=1)
    if len(text) < 2:
        bot.reply_to(message, "Пример: <code>/unlink МойНик</code>")
        return
    nick = text[1].strip()
    if remove_nick_link(nick):
        bot.reply_to(message, f"✅ Ник <b>{html_escape(nick)}</b> отвязан.")
    else:
        bot.reply_to(message, f"Ник <b>{html_escape(nick)}</b> не был привязан.")


@bot.message_handler(content_types=["new_chat_members"])
def welcome_user(message: telebot.types.Message):
    for user in message.new_chat_members:
        name = user.first_name
        if user.last_name:
            name += " " + user.last_name
        welcome_text = (
            f"💙💛 Welcome HARKIV Front, <b>{name}</b>!\n\n"
            f"💙💛 Всі питання в розділах нашої групи ❤️💙💛"
        )
        bot.send_message(message.chat.id, welcome_text)


@bot.message_handler(func=lambda m: True)
def handle_any(message: telebot.types.Message):
    logger.info(
        "Got message: chat_id=%s, text=%r, from=%s",
        message.chat.id,
        message.text,
        message.from_user.username if message.from_user else None,
    )


# ===== FLASK =====

@app.route("/", methods=["GET"])
def index():
    """Корень — для проверки и для пингов (чтобы инстанс не засыпал)."""
    return "Bot is running", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    logger.info("Incoming webhook: %s", json_str[:200])
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200


if __name__ == "__main__":
    bot.remove_webhook()
    if RENDER_EXTERNAL_URL:
        bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook")
        logger.info("Webhook set to: %s", f"{RENDER_EXTERNAL_URL}/webhook")
    else:
        logger.warning("RENDER_EXTERNAL_URL not set; starting polling...")
        bot.infinity_polling(threaded=False)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
