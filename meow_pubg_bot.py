import os
import logging
import json
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

cap_chat_url = None
registration_data = {}
reserved_teams = []
used_users = set()
max_free_events = 2
connected_events = {}
TEMPLATE_IMAGE_PATH = "template.png"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 28

def buy_access_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Купить доступ", url="https://t.me/your_username")]
    ])

@dp.message(F.text.startswith("/setcapchat"))
async def set_capchat(message: Message):
    global cap_chat_url
    if message.from_user.id == ADMIN_ID:
        parts = message.text.split()
        if len(parts) == 2:
            cap_chat_url = parts[1]
            await message.answer("✅ Кэп-чат установлен")

@dp.message(F.text.startswith("/регистрация"))
async def register_team(message: Message):
    if message.from_user.id in used_users:
        await message.answer("❌ Вы уже использовали бесплатную регистрацию.", reply_markup=buy_access_keyboard())
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer("Формат: /регистрация TEAM_NAME @cap")
        return
    team_name, cap_username = parts[1], parts[2]
    slot = 5
    while str(slot) in registration_data:
        slot += 1
    registration_data[str(slot)] = {
        "team": team_name,
        "cap": cap_username,
        "cap_id": message.from_user.id,
        "status": "⏳"
    }
    used_users.add(message.from_user.id)
    await message.answer(f"✅ {team_name} зарегистрирована в слот {slot}")
    if cap_chat_url:
        await bot.send_message(chat_id=cap_chat_url, text=f"Новая регистрация: <b>{team_name}</b> — {cap_username}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{slot}"),
                 InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{slot}")]
            ]))

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_slot(callback: CallbackQuery):
    slot = callback.data.split("_")[1]
    data = registration_data.get(slot)
    if not data or callback.from_user.id != data["cap_id"]:
        return await callback.answer("Вы не капитан этой команды.", show_alert=True)
    registration_data[slot]["status"] = "✅"
    await callback.message.edit_text(f"✅ {data['team']} подтвердила слот {slot}")

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_slot(callback: CallbackQuery):
    slot = callback.data.split("_")[1]
    data = registration_data.get(slot)
    if not data or callback.from_user.id != data["cap_id"]:
        return await callback.answer("Вы не капитан этой команды.", show_alert=True)
    registration_data.pop(slot)
    await callback.message.edit_text(f"❌ {data['team']} отказалась от слота {slot}.")
    if reserved_teams:
        reserve = reserved_teams.pop(0)
        registration_data[slot] = reserve
        await bot.send_message(chat_id=cap_chat_url, text=f"Резерв подключён: {reserve['team']} — {reserve['cap']}")

@dp.message(F.text == "/тимлист")
async def team_list(message: Message):
    text = "\n".join([f"Слот {k}: {v['team']} — {v['status']}" for k, v in registration_data.items()])
    await message.answer(text or "Пока никто не зарегистрирован")

@dp.message(F.text.startswith("/резерв"))
async def add_reserve(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.answer("Формат: /резерв TEAM_NAME @cap")
    reserved_teams.append({"team": parts[1], "cap": parts[2]})
    await message.answer("✅ Добавлено в резерв")

@dp.message(F.text == "/лист_резерв")
async def list_reserve(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = "\n".join([f"{i+1}. {t['team']} — {t['cap']}" for i, t in enumerate(reserved_teams)])
    await message.answer(text or "Резерв пуст")

@dp.message(F.text == "/лист_рег")
async def list_reg(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = json.dumps(registration_data, indent=2, ensure_ascii=False)
    await message.answer(f"<pre>{text}</pre>", parse_mode="HTML")
from aiogram.types import InputMediaPhoto
from urllib.parse import urlparse

@dp.message(F.photo)
async def handle_photo_template(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ Только админ может отправлять шаблон.")
    file = await bot.get_file(message.photo[-1].file_id)
    downloaded = await bot.download_file(file.file_path)
    with open("template.png", "wb") as f:
        f.write(downloaded.read())
    await message.answer("✅ Шаблон принят. Теперь отправь ссылку на Google Таблицу.")

@dp.message(F.text.contains("docs.google.com"))
async def fill_image_from_sheet(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        spreadsheet_id = message.text.split("/d/")[1].split("/")[0]
        creds = Credentials.from_service_account_file("credentials.json", scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        sheet = build("sheets", "v4", credentials=creds).spreadsheets()
        values = sheet.values().get(spreadsheetId=spreadsheet_id, range="A2:D19").execute().get("values", [])
        img = Image.open("template.png")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        for i, row in enumerate(values):
            name, pos, kills, total = row + [""] * (4 - len(row))
            y = 220 + (i % 9) * 65
            x = 100 if i < 9 else 700
            draw.text((x, y), f"{name}  {pos}  {kills}  {total}", font=font, fill=(255,255,255))
        title = values[0][0] if values else "meow"
        out_path = f"{title}_meow.png"
        img.save(out_path)
        await message.answer_photo(InputFile(out_path), caption=f"✅ Таблица: {title}_meow.png")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# === Проверка пруфов ===
@dp.message(F.text.startswith("/autocheck"))
async def activate_autocheck(message: Message):
    if message.chat.type != "supergroup":
        return await message.answer("Эту команду можно использовать только в группе.")
    connected_events[message.chat.id] = 0
    await message.answer("✅ Автопроверка включена. Отправляйте пруфы.")

@dp.message(F.text.contains("http"))
async def check_pruf_links(message: Message):
    if message.chat.id not in connected_events:
        return
    links = [x for x in message.text.split() if x.startswith("http")]
    if len(links) < 4:
        return
    failed = []
    for link in links:
        domain = urlparse(link).netloc
        if "t.me" in domain and not "sponsor" in link:
            failed.append("Telegram")
        if "youtube.com" in domain and not "@" in link:
            failed.append("YouTube")
        if "instagram.com" in domain:
            pass  # можно добавить логику
    if failed:
        await message.reply(f"❌ Нет подписки на: {', '.join(set(failed))}")
    else:
        await message.reply("✅ Пруфы пройдены")

# === Ограничения на подключение событий ===
@dp.message(F.text.startswith("/approvechat"))
async def approve_chat(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    chat_id = int(message.text.split()[1])
    connected_events[chat_id] = 0
    await message.answer(f"✅ Подключён: {chat_id}")

@dp.message(F.text.startswith("/broadcast"))
async def broadcast_to_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/broadcast", "").strip()
    for uid in used_users:
        try:
            await bot.send_message(uid, f"📢 Объявление:\n{text}")
        except: pass
    await message.answer("✅ Рассылка завершена")

@dp.message(F.text == "/resetlimit")
async def reset_limits(message: Message):
    if message.from_user.id == ADMIN_ID:
        used_users.clear()
        await message.answer("Лимиты сброшены.")

# === Старт бота ===
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
