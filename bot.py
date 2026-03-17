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


def get_nick_by_user_id(user_id: int):
    """По Telegram user_id возвращает привязанный ник (первый найденный) или None."""
    links = load_nick_links()
    for nick_key, data in links.items():
        if data["user_id"] == user_id:
            return nick_key
    return None


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


# ===== СТАТИСТИКА ИГРОКОВ (заглушки — подставь свой API) =====
# Переменная STATS_API_URL — базовый URL API твоего сервера (если есть).
# Пока не задана — бот отвечает "статистика не подключена".

STATS_API_URL = os.getenv("STATS_API_URL", "").rstrip("/")


def get_player_stats(nick: str):
    """
    Возвращает словарь с полями: kills, deaths, time, bonuses, place и т.д.
    или None, если статистика недоступна.
    Подставь сюда запрос к своему API по нику.
    """
    if not STATS_API_URL or not nick:
        return None
    try:
        import urllib.request
        url = f"{STATS_API_URL}/player?nick={urllib.request.quote(nick.strip())}"
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.debug("get_player_stats %s: %s", nick, e)
    return None


def get_top_anew(limit: int = 10):
    """Топ по бонусам. Возвращает список [{"nick": str, "value": int}, ...] или []."""
    if not STATS_API_URL:
        return []
    try:
        import urllib.request
        with urllib.request.urlopen(f"{STATS_API_URL}/top/anew?limit={limit}", timeout=5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.debug("get_top_anew: %s", e)
    return []


def get_top_kill(limit: int = 10):
    """Топ по убийствам."""
    if not STATS_API_URL:
        return []
    try:
        import urllib.request
        with urllib.request.urlopen(f"{STATS_API_URL}/top/kill?limit={limit}", timeout=5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.debug("get_top_kill: %s", e)
    return []


def get_top_time(limit: int = 10):
    """Топ по времени."""
    if not STATS_API_URL:
        return []
    try:
        import urllib.request
        with urllib.request.urlopen(f"{STATS_API_URL}/top/time?limit={limit}", timeout=5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.debug("get_top_time: %s", e)
    return []


def get_top10(limit: int = 10):
    """Общий топ игроков."""
    if not STATS_API_URL:
        return []
    try:
        import urllib.request
        with urllib.request.urlopen(f"{STATS_API_URL}/top?limit={limit}", timeout=5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.debug("get_top10: %s", e)
    return []


def format_player_stats(nick: str, stats: dict) -> str:
    """Форматирует ответ по статистике игрока."""
    parts = [f"<b>📊 {html_escape(nick)}</b>"]
    for key, val in (stats or {}).items():
        if key in ("nick", "name"):
            continue
        parts.append(f"  {key}: {val}")
    return "\n".join(parts) if len(parts) > 1 else f"<b>📊 {html_escape(nick)}</b>\nНет данных."


def format_top(title: str, rows: list, value_key: str = "value") -> str:
    """Форматирует топ-список."""
    if not rows:
        return f"<b>{title}</b>\nНет данных (или API не подключён: задай STATS_API_URL)."
    lines = [f"<b>{title}</b>"]
    for i, row in enumerate(rows[:15], 1):
        nick = row.get("nick", row.get("name", "—"))
        val = row.get(value_key, row.get("score", "—"))
        lines.append(f"{i}. {html_escape(str(nick))} — {val}")
    return "\n".join(lines)


bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)
app = Flask(__name__)

# В группах/супергруппах reply иногда падает (400: message to be replied not found).
# Поэтому делаем безопасный ответ: сначала reply, при ошибке — обычное сообщение в чат.
def safe_reply(message: telebot.types.Message, text: str, **kwargs):
    try:
        return bot.reply_to(message, text, **kwargs)
    except Exception as e:
        logger.warning("reply_to failed (chat_id=%s, message_id=%s): %s", getattr(message.chat, "id", None), getattr(message, "message_id", None), e)
        return bot.send_message(message.chat.id, text, **kwargs)


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
            f"🌐 <b>Сервер:</b> {html_escape(SERVER_NAME_FALLBACK)}\n"
            f"🧩 <b>IP:</b> {ip}:{port}\n"
        )

    server_name = getattr(info, "server_name", None) or SERVER_NAME_FALLBACK
    current_map = getattr(info, "map_name", None) or "Неизвестно"
    player_count = getattr(info, "player_count", 0)
    max_players = getattr(info, "max_players", 0)

    lines = [
        f"📂 <b>Состояние сервера —</b> 🟢 <b>Онлайн</b>",
        f"🌐 <b>Сервер:</b> {html_escape(server_name)}",
        f"🧩 <b>IP:</b> {ip}:{port}",
        f"🗺 <b>Карта:</b> {html_escape(current_map)}",
        f"⌛ <b>До смены:</b> {html_escape(SHIFT_INFO)}",
        f"👥 <b>Онлайн:</b> {player_count}/{max_players}",
    ]

    # Список игроков с фрагами (score). Топ-3 с медалями, остальные с иконкой.
    if players:
        players_sorted = sorted(players, key=lambda p: getattr(p, "score", 0), reverse=True)
        for idx, p in enumerate(players_sorted, start=1):
            name = (getattr(p, "name", "") or "").strip() or "—"
            score = int(getattr(p, "score", 0) or 0)

            safe_name = html_escape(name)
            link = get_nick_link(name) if name else None
            if link:
                user_id = link["user_id"]
                safe_name = f'<a href="tg://user?id={user_id}">{safe_name}</a>'

            icon = "👤"
            if idx == 1:
                icon = "🥇"
            elif idx == 2:
                icon = "🥈"
            elif idx == 3:
                icon = "🥉"

            lines.append(f"{icon} {safe_name} — {score} фр.")
    else:
        lines.append("👤 Нет игроков")

    return "\n".join(lines)


# ===== ОБРАБОТЧИКИ =====

@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message):
    logger.info("Got /start from chat %s", message.chat.id)
    safe_reply(
        message,
        "Бот запущен.\n\n"
        "• /ONLINE — кто на сервере (ники кликабельны)\n"
        "• /link Ник — привязать ник к профилю в TG\n\n"
        "<b>Статистика игроков:</b>\n"
        "• /me — твоя статистика\n"
        "• /yu — статистика игрока (ответь на его сообщение)\n"
        "• /play_Ник — информация по нику\n"
        "• /top_anew — топ по бонусам\n"
        "• /top_kill — топ по убийствам\n"
        "• /top_time — топ по времени\n"
        "• /top10 — общий топ",
    )


@bot.message_handler(commands=["online", "ONLINE"])
def handle_online(message: telebot.types.Message):
    logger.info("Got /ONLINE from chat %s", message.chat.id)
    # В группе reply может падать, поэтому используем safe_reply
    safe_reply(message, ".")
    is_online, info, players = query_server_info()
    msg = build_online_message(is_online, info, players)
    bot.send_message(message.chat.id, msg, disable_web_page_preview=True)


@bot.message_handler(commands=["link", "bind", "привязать"])
def handle_link(message: telebot.types.Message):
    """Привязать свой ник в игре к профилю в Telegram. Пример: /link МойНик"""
    text = (message.text or "").strip().split(maxsplit=1)
    if len(text) < 2:
        safe_reply(
            message,
            "Напиши ник, который используешь на сервере.\n"
            "Пример: <code>/link МойНик</code>\n"
            "После этого в статистике /ONLINE твой ник можно будет нажать — откроется твой профиль в TG.",
        )
        return
    nick = text[1].strip()
    if not nick:
        safe_reply(message, "Укажи ник, например: /link МойНик")
        return
    user_id = message.from_user.id
    username = message.from_user.username if message.from_user else None
    add_nick_link(nick, user_id, username)
    safe_reply(message, f"✅ Привязано: <b>{html_escape(nick)}</b> → твой профиль в TG. В /ONLINE ник будет кликабельным.")


@bot.message_handler(commands=["unlink", "unbind", "отвязать"])
def handle_unlink(message: telebot.types.Message):
    """Отвязать ник. Пример: /unlink МойНик"""
    text = (message.text or "").strip().split(maxsplit=1)
    if len(text) < 2:
        safe_reply(message, "Пример: <code>/unlink МойНик</code>")
        return
    nick = text[1].strip()
    if remove_nick_link(nick):
        safe_reply(message, f"✅ Ник <b>{html_escape(nick)}</b> отвязан.")
    else:
        safe_reply(message, f"Ник <b>{html_escape(nick)}</b> не был привязан.")


# ===== СТАТИСТИКА ИГРОКОВ =====

def reply_stats_unavailable(message: telebot.types.Message):
    safe_reply(message, "пока что данные недоступны")


@bot.message_handler(commands=["me"])
def handle_me(message: telebot.types.Message):
    """Ваша статистика — по привязанному нику."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        reply_stats_unavailable(message)
        return
    nick = get_nick_by_user_id(user_id)
    if not nick:
        reply_stats_unavailable(message)
        return
    stats = get_player_stats(nick)
    if stats is None:
        reply_stats_unavailable(message)
        return
    safe_reply(message, format_player_stats(nick, stats))


@bot.message_handler(commands=["yu"])
def handle_yu(message: telebot.types.Message):
    """Статистика другого игрока (в ответ на его сообщение)."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        reply_stats_unavailable(message)
        return
    user_id = message.reply_to_message.from_user.id
    nick = get_nick_by_user_id(user_id)
    if not nick:
        reply_stats_unavailable(message)
        return
    stats = get_player_stats(nick)
    if stats is None:
        reply_stats_unavailable(message)
        return
    safe_reply(message, format_player_stats(nick, stats))


@bot.message_handler(func=lambda m: m.text and m.text.strip().startswith("/play_"))
def handle_play_nick(message: telebot.types.Message):
    """Информация по нику: /play_Ник (без пробела)."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    text = (message.text or "").strip()
    # /play_Nick или /play_Ник
    if len(text) <= 6:
        reply_stats_unavailable(message)
        return
    nick = text[6:].strip()  # после "/play_"
    if not nick:
        reply_stats_unavailable(message)
        return
    stats = get_player_stats(nick)
    if stats is None:
        reply_stats_unavailable(message)
        return
    safe_reply(message, format_player_stats(nick, stats))


@bot.message_handler(commands=["top_anew"])
def handle_top_anew(message: telebot.types.Message):
    """Топ по бонусам."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    rows = get_top_anew(10)
    safe_reply(message, format_top("🏆 Топ по бонусам", rows))


@bot.message_handler(commands=["top_kill"])
def handle_top_kill(message: telebot.types.Message):
    """Топ по убийствам."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    rows = get_top_kill(10)
    safe_reply(message, format_top("🔫 Топ по убийствам", rows))


@bot.message_handler(commands=["top_time"])
def handle_top_time(message: telebot.types.Message):
    """Топ по времени."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    rows = get_top_time(10)
    safe_reply(message, format_top("⏱ Топ по времени", rows))


@bot.message_handler(commands=["top10"])
def handle_top10(message: telebot.types.Message):
    """Общий топ игроков."""
    if not STATS_API_URL:
        reply_stats_unavailable(message)
        return
    rows = get_top10(10)
    safe_reply(message, format_top("🏅 Общий топ игроков", rows))


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
