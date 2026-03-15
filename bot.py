import os
import a2s
import telebot
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")

CS_SERVER_ADDRESS = ("91.211.118.88", 27055)
SERVER_SITE = "gamecs-ua.com"
SERVER_NAME_FALLBACK = "Харьковский  Фронт  18+ (+VIP)"
SHIFT_INFO = "Неизвестно"
FRAGS = 0

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)


def query_server_info():
    try:
        info = a2s.info(CS_SERVER_ADDRESS, timeout=2.5)
        players = a2s.players(CS_SERVER_ADDRESS, timeout=2.5)
        return True, info, players
    except Exception:
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


@bot.message_handler(commands=["ONLINE"])
def handle_online(message: telebot.types.Message):
    bot.reply_to(message, ".")
    is_online, info, players = query_server_info()
    msg = build_online_message(is_online, info, players)
    bot.send_message(message.chat.id, msg, disable_web_page_preview=True)


@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200


@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
