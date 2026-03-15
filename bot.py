import os
import logging

import a2s
import telebot
from flask import Flask, request

# Логи будем видеть в Render → Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота берём из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set in environment!")
else:
    logger.info("BOT_TOKEN loaded (first chars): %s***", BOT_TOKEN[:6])

CS_SERVER_ADDRESS = ("91.211.118.88", 27055)
SERVER_SITE = "gamecs-ua.com"
SERVER_NAME_FALLBACK = "Харьковский  Фронт  18+ (+VIP)"
SHIFT_INFO = "Неизвестно"
FRAGS = 0

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)

app = Flask(__name__)

# Ця функція спрацює один раз ПЕРЕД тим, як сервер почне приймати запити
@app.before_request
def setup_webhook():
    # Робимо це лише один раз
    app.before_request_funcs[None].remove(setup_webhook)
    
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    else:
        logger.error("RENDER_EXTERNAL_URL is not set!")



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
            f"<b>Site:</b> {SERVER_SITE}\n"
        )

    server_name = getattr(info, "server_name", None) or SERVER_NAME_FALLBACK
    current_map = getattr(info, "map_name", None) or "Неизвестно"
    player_count = getattr(info, "player_count", 0)
    max_players = getattr(info, "max_players", 0)

    players_list = []

    if players:
        for player in players:
            name = player.name if player.name else "Без ника"
            name = html.escape(name)
            players_list.append(f"• {name}")

        players_text = "\n".join(players_list)

    else:
        players_text = "Нет игроков"
        
    lines = [
        "<b>Состояние сервера — 🟢 Онлайн</b>",
        f"<b>Сервер:</b> {server_name}",
        f"<b>IP:</b> {ip}:{port}",
        f"<b>Карта:</b> {current_map}",
        f"<b>До смены:</b> {SHIFT_INFO}",
        f"<b>Онлайн:</b> {player_count}/{max_players}",
        f"<b>Site:</b> {SERVER_SITE} — {FRAGS} фр.",
    ]
    return "\n".join(lines)


# ===== ОБРАБОТЧИКИ =====

@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message):
    logger.info("Got /start from chat %s", message.chat.id)
    bot.reply_to(message, "Бот запущен, пиши /ONLINE")


@bot.message_handler(commands=["online", "ONLINE"])
def handle_online(message: telebot.types.Message):
    logger.info("Got /ONLINE from chat %s", message.chat.id)
    bot.reply_to(message, ".")
    is_online, info, players = query_server_info()
    msg = build_online_message(is_online, info, players)
    bot.send_message(message.chat.id, msg, disable_web_page_preview=True)

@bot.message_handler(content_types=["new_chat_members"])
def welcome_user(message: telebot.types.Message):

    for user in message.new_chat_members:

        name = user.first_name
        if user.last_name:
            name += " " + user.last_name

        welcome_text = (
            f"💙💛Welcome HARKIV Front, <b>{name}</b>!\n\n 💙💛 "
            f"Всі питання в розділах нашої групи ❤️💙💛"
        )
        
@bot.message_handler(func=lambda m: True)
def handle_any(message: telebot.types.Message):
    # Для отладки: логируем любое входящее сообщение
    logger.info(
        "Got message: chat_id=%s, text=%r, from=%s",
        message.chat.id,
        message.text,
        message.from_user.username if message.from_user else None,
    )


# ===== FLASK WEBHOOK =====

@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    logger.info("Incoming webhook: %s", json_str)
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

if __name__ == "__main__":
    # 1. Обов'язково видаляємо старий вебхук/поллінг перед встановленням нового
    bot.remove_webhook()
    
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        # 2. Встановлюємо вебхук
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    else:
        logger.warning("RENDER_EXTERNAL_URL not found! Starting polling (not recommended for Web Service)...")
        # Якщо URL немає, запускаємо звичайний поллінг як запасний варіант
        bot.infinity_polling(threaded=False)

    # 3. Запускаємо сервер Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200
