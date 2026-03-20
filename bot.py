import os
import time
import uuid
import logging
import threading
import telebot
from telebot import types

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ['TOKEN']
CHANNEL_ID = os.environ['CHANNEL_ID']
ADMIN_ID = 8619511466
DELETE_TIMEOUT = 120

bot = telebot.TeleBot(TOKEN, threaded=True)
agreed_users = set()
user_mode = {}
pending_messages = {}
sent_to_channel = {}
lock = threading.Lock()


def cleanup_expired():
    now = time.time()
    with lock:
        expired = [k for k, v in sent_to_channel.items()
                   if now - v["timestamp"] > DELETE_TIMEOUT]
        for k in expired:
            del sent_to_channel[k]
    if expired:
        logger.info(f"Очистка: удалено {len(expired)} просроченных delete-записей")
    threading.Timer(60, cleanup_expired).start()


RULES_TEXT = (
    "🚀 Добро пожаловать в \"Ищу тебя Прикубанка\" 🔎\n\n"
    "Перед тем как искать кого-то или отправлять анкету, почитай правила:\n\n"
    "1️⃣ Соблюдай конфиденциальность других людей\n"
    "2️⃣ Пиши на Русском или Къарачаевском, без ненормативной лексики\n"
    "3️⃣ Владелец бота не имеет прямого доступа к сообщениям\n"
    "4️⃣ Адми��истратор может удалить любой пост без объяснений\n\n"
    "Продолжая пользоваться ботом, вы соглашаетесь с вышеуказанными правилами."
)

MAIN_MENU_TEXT = "📋 Главное меню\n\nВыберите, как хотите отправить сообщение:"
WAITING_TEXT = "✍️ Отправьте текст, фото или видео:"


def agree_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Согласен", callback_data="agree"))
    return kb


def main_menu_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔒 Анонимно", callback_data="anon"))
    kb.add(types.InlineKeyboardButton("👤 Не анонимно", callback_data="public"))
    return kb


def cancel_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def get_user_info(user):
    username = f"@{user.username}" if user.username else "нет юзернейма"
    name = (user.first_name or "") + (f" {user.last_name}" if user.last_name else "")
    return name.strip(), username


def make_caption(message, mode):
    footer = (
        '\n\n❇️ <a href="https://t.me/pr1kubankabot">БОТ</a> | '
        '🔗 <a href="https://t.me/pr1kubanka">КАНАЛ</a> | '
        '💬 <a href="https://t.me/pr1kub4nk4">ЧАТ</a>'
    )
    if mode == "anon":
        header = "✅ анонимно"
    else:
        u = message.from_user
        header = (f"✅ не анонимно от @{u.username}"
                  if u.username else f"✅ не анонимно от {u.first_name}")
    content = message.caption or message.text or ""
    return f"{header}\n\n{content}{footer}" if content else f"{header}{footer}"


def notify_admin_new(message, mode, content_type):
    name, username = get_user_info(message.from_user)
    mode_text = "🔒 Анонимно" if mode == "anon" else "👤 Не анонимно"
    msg_id = str(uuid.uuid4())[:8]

    content = {}
    if content_type == "text":
        content = {"type": "text", "text": message.text}
    elif content_type == "photo":
        content = {"type": "photo", "file_id": message.photo[-1].file_id,
                   "caption": message.caption or ""}
    elif content_type == "video":
        content = {"type": "video", "file_id": message.video.file_id,
                   "caption": message.caption or ""}

    with lock:
        pending_messages[msg_id] = {
            **content,
            "name": name,
            "username": username,
            "user_id": message.from_user.id,
            "time": time.strftime("%d.%m.%Y %H:%M:%S"),
        }

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Раскрыть сообщение", callback_data=f"reveal_{msg_id}"))

    admin_text = (
        f"📨 <b>Новое соо��щение в боте!</b>\n\n"
        f"👤 Имя: {name}\n"
        f"🔗 Юзернейм: {username}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"📌 Режим: {mode_text}\n"
        f"📁 Тип: {content_type}"
    )
    sent_admin = bot.send_message(ADMIN_ID, admin_text, reply_markup=kb, parse_mode='HTML')
    return sent_admin.message_id, admin_text


def edit_admin_on_delete(entry, user):
    name, username = get_user_info(user)
    deleted_at = time.strftime("%d.%m.%Y %H:%M:%S")

    if entry.get("admin_msg_id"):
        updated_text = (
            entry["admin_text"] +
            f"\n\n🗑 <b>Удалено пользователем</b>\n"
            f"👤 {name} ({username})\n"
            f"🕐 {deleted_at}"
        )
        try:
            bot.edit_message_text(updated_text, ADMIN_ID, entry["admin_msg_id"], parse_mode='HTML')
        except Exception as e:
            logger.error(f"Не удалось обновить уведомление админа: {e}")

    content = entry.get("content", {})
    header = f"🗑 <b>Содержимое удалённого сообщения:</b>\n"
    if content.get("type") == "text":
        bot.send_message(ADMIN_ID, f"{header}\n{content['text']}", parse_mode='HTML')
    elif content.get("type") == "photo":
        cap = f"{header}\n{content['caption']}" if content.get("caption") else header.rstrip()
        bot.send_photo(ADMIN_ID, content["file_id"], caption=cap, parse_mode='HTML')
    elif content.get("type") == "video":
        cap = f"{header}\n{content['caption']}" if content.get("caption") else header.rstrip()
        bot.send_video(ADMIN_ID, content["file_id"], caption=cap, parse_mode='HTML')


def send_revealed(data):
    header = (
        f"👤 {data.get('name', '—')} ({data.get('username', '—')})\n"
        f"🆔 {data.get('user_id', '—')}\n"
        f"🕐 {data.get('time', '—')}\n"
        f"─────────────────\n"
    )
    if data["type"] == "text":
        bot.send_message(ADMIN_ID, f"{header}📝 {data['text']}", parse_mode='HTML')
    elif data["type"] == "photo":
        cap = f"{header}🖼 {data['caption']}" if data.get('caption') else header.rstrip()
        bot.send_photo(ADMIN_ID, data["file_id"], caption=cap, parse_mode='HTML')
    elif data["type"] == "video":
        cap = f"{header}🎥 {data['caption']}" if data.get('caption') else header.rstrip()
        bot.send_video(ADMIN_ID, data["file_id"], caption=cap, parse_mode='HTML')


@bot.message_handler(commands=['inbox'])
def inbox(message):
    if message.from_user.id != ADMIN_ID:
        return
    with lock:
        items = list(pending_messages.items())
    if not items:
        bot.send_message(ADMIN_ID, "📭 Нет нераскрытых сообщений.")
        return
    bot.send_message(ADMIN_ID, f"📬 <b>Нераскрытых сообщений: {len(items)}</b>", parse_mode='HTML')
    for msg_id, data in items:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 Раскрыть", callback_data=f"reveal_{msg_id}"))
        content_label = {"text": "📝 Текст", "photo": "🖼 Фото", "video": "🎥 Видео"}.get(data["type"], "📁 Файл")
        bot.send_message(
            ADMIN_ID,
            f"{content_label}\n"
            f"👤 {data.get('name', '—')} ({data.get('username', '—')})\n"
            f"🕐 {data.get('time', '—')}",
            reply_markup=kb,
            parse_mode='HTML'
        )


@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    if chat_id in agreed_users:
        bot.send_message(chat_id, MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())
    else:
        bot.send_message(chat_id, RULES_TEXT, reply_markup=agree_keyboard())


@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    chat_id = call.message.chat.id

    if call.data == "agree":
        agreed_users.add(chat_id)
        user_mode.pop(chat_id, None)
        bot.edit_message_text(MAIN_MENU_TEXT, chat_id, call.message.message_id,
                              reply_markup=main_menu_keyboard())
        bot.answer_callback_query(call.id)

    elif call.data in ("anon", "public"):
        user_mode[chat_id] = call.data
        bot.edit_message_text(WAITING_TEXT, chat_id, call.message.message_id,
                              reply_markup=cancel_keyboard())
        bot.answer_callback_query(call.id)

    elif call.data == "back":
        user_mode.pop(chat_id, None)
        bot.edit_message_text(MAIN_MENU_TEXT, chat_id, call.message.message_id,
                              reply_markup=main_menu_keyboard())
        bot.answer_callback_query(call.id)

    elif call.data.startswith("delete_"):
        del_id = call.data.split("_", 1)[1]
        with lock:
            entry = sent_to_channel.pop(del_id, None)
        if not entry:
            bot.answer_callback_query(call.id, "⚠️ Сообщение уже удалено или недоступно")
            return
        if time.time() - entry["timestamp"] > DELETE_TIMEOUT:
            bot.edit_message_text("⏰ Время на удаление истекло (2 минуты).",
                                  chat_id, call.message.message_id)
            bot.answer_callback_query(call.id, "⏰ Время вышло")
        else:
            try:
                bot.delete_message(CHANNEL_ID, entry["message_id"])
                edit_admin_on_delete(entry, call.from_user)
                bot.edit_message_text("🗑 Сообщение удалено из канала.",
                                      chat_id, call.message.message_id)
                bot.answer_callback_query(call.id, "✅ Удалено")
            except Exception as e:
                logger.error(f"Ошибка удаления из канала: {e}")
                with lock:
                    sent_to_channel[del_id] = entry
                bot.answer_callback_query(call.id, "⚠️ Не удалось удалить.")

    elif call.data.startswith("reveal_"):
        msg_id = call.data.split("_", 1)[1]
        with lock:
            data = pending_messages.pop(msg_id, None)
        if data:
            send_revealed(data)
            bot.answer_callback_query(call.id, "✅ Сообщение раскрыто")
        else:
            bot.answer_callback_query(call.id, "⚠️ Уже было раскрыто")


def send_to_channel(message, content_type):
    chat_id = message.chat.id
    mode = user_mode.get(chat_id)
    if not mode:
        if chat_id in agreed_users:
            bot.send_message(chat_id, MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())
        else:
            bot.send_message(chat_id, RULES_TEXT, reply_markup=agree_keyboard())
        return

    caption = make_caption(message, mode)

    try:
        if content_type == "text":
            sent = bot.send_message(CHANNEL_ID, caption, parse_mode='HTML')
            content = {"type": "text", "text": message.text}
        elif content_type == "photo":
            file_id = message.photo[-1].file_id
            sent = bot.send_photo(CHANNEL_ID, file_id, caption=caption, parse_mode='HTML')
            content = {"type": "photo", "file_id": file_id, "caption": message.caption or ""}
        elif content_type == "video":
            file_id = message.video.file_id
            sent = bot.send_video(CHANNEL_ID, file_id, caption=caption, parse_mode='HTML')
            content = {"type": "video", "file_id": file_id, "caption": message.caption or ""}
        else:
            bot.send_message(chat_id, "⚠️ Неподдерживаемый тип сообщения.")
            return
    except Exception as e:
        logger.error(f"Ошибка отправки в канал: {e}")
        bot.send_message(chat_id, "❌ Не удалось отправить. Попробуйте позже.")
        return

    try:
        admin_msg_id, admin_text = notify_admin_new(message, mode, content_type)
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора: {e}")
        admin_msg_id, admin_text = None, ""

    del_id = str(uuid.uuid4())[:8]
    with lock:
        sent_to_channel[del_id] = {
            "message_id": sent.message_id,
            "admin_msg_id": admin_msg_id,
            "admin_text": admin_text,
            "timestamp": time.time(),
            "content": content,
        }
    user_mode.pop(chat_id, None)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🗑 Удалить из канала (2 мин)", callback_data=f"delete_{del_id}"))
    bot.send_message(chat_id, "✅ Отправлено! У вас есть 2 минуты на удаление:", reply_markup=kb)
    bot.send_message(chat_id, MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())


@bot.message_handler(content_types=['text'])
def handle_text(message):
    send_to_channel(message, "text")


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_to_channel(message, "photo")


@bot.message_handler(content_types=['video'])
def handle_video(message):
    send_to_channel(message, "video")


if __name__ == "__main__":
    cleanup_expired()
    logger.info("Бот запу��ен")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)