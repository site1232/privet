import asyncio
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web  # Библиотека для веб-заглушки

# ================= НАСТРОЙКИ БОТА =================
BOT_TOKEN = "8701443421:AAE1Z0mwoIDUiqoGSZDx3pkZPqvX9DInSys"

# СПИСОК ТЕХ, КОМУ МОЖНО ПОЛЬЗОВАТЬСЯ БОТОМ
# Просто добавь ID второго человека через запятую (узнать ID можно в @userinfobot)
ALLOWED_USERS = [1448711405, 1191749673]
# ==================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
scheduler = AsyncIOScheduler()

class HomeworkStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_task = State()
    waiting_for_deadline = State()

def init_db():
    conn = sqlite3.connect("homework_v6.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            task TEXT,
            deadline TEXT
        )
    ''')
    conn.commit()
    conn.close()

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Добавить ДЗ"), KeyboardButton(text="📋 Моё ДЗ")]
    ],
    resize_keyboard=True
)

@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("Извини, этот бот приватный.")
        return
    await message.answer("Привет! Я помогу тебе вести учет домашних заданий в вузе.", reply_markup=main_kb)

@router.message(F.text == "📋 Моё ДЗ")
async def show_homework(message: Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        conn = sqlite3.connect("homework_v6.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, subject, task, deadline FROM homework")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await message.answer("🎉 Отлично! Актуальных заданий нет.")
            return
            
        text = "📌 Список твоих актуальных задач:\n\n"
        for row in rows:
            hw_id, subject, task, deadline = row
            text += f"📘 Предмет: {subject}\n📝 Что сделать: {task}\n📅 Дедлайн: {deadline}\n👉 Выполнено: /done_{hw_id}\n\n"
            
        await message.answer(text)
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при чтении: {e}")

@router.message(F.text == "📚 Добавить ДЗ")
async def add_hw_start(message: Message, state: FSMContext):
    if message.from_user.id not in ALLOWED_USERS:
        return
    await message.answer("Введите название предмета (например, Матанализ):")
    await state.set_state(HomeworkStates.waiting_for_subject)

@router.message(HomeworkStates.waiting_for_subject)
async def add_hw_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text)
    await message.answer("Теперь напишите, что именно нужно сделать:")
    await state.set_state(HomeworkStates.waiting_for_task)

@router.message(HomeworkStates.waiting_for_task)
async def add_hw_task(message: Message, state: FSMContext):
    await state.update_data(task=message.text)
    await message.answer("Введите дату дедлайна в формате ДД.ММ.ГГГГ (например, 05.10.2026):")
    await state.set_state(HomeworkStates.waiting_for_deadline)

@router.message(HomeworkStates.waiting_for_deadline)
async def add_hw_deadline(message: Message, state: FSMContext):
    deadline_text = message.text.strip()
    try:
        datetime.strptime(deadline_text, "%d.%m.%Y")
    except ValueError:
        await message.answer("❌ Неверный формат даты! Пожалуйста, введите дату строго как ДД.ММ.ГГГГ (например, 28.09.2026):")
        return

    user_data = await state.get_data()
    subject = user_data['subject']
    task = user_data['task']
    
    conn = sqlite3.connect("homework_v6.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO homework (subject, task, deadline) VALUES (?, ?, ?)", (subject, task, deadline_text))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Задание по предмету {subject} успешно добавлено!", reply_markup=main_kb)

@router.message(F.text.startswith("/done_"))
async def delete_homework(message: Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        hw_id = int(message.text.split("_")[1])
        conn = sqlite3.connect("homework_v6.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
        conn.commit()
        conn.close()
        await message.answer("🗑️ Задание отмечено как выполненное и удалено из списка!")
    except Exception as e:
        await message.answer(f"Ошибка удаления: {e}")

async def send_weekly_reminder():
    conn = sqlite3.connect("homework_v6.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subject, task, deadline FROM homework")
    rows = cursor.fetchall()
    conn.close()
    
    if rows:
        text = "⏰ Воскресное напоминание! Список всех задач на неделю:\n\n"
        for row in rows:
            subject, task, deadline = row
            text += f"▪️ {subject}: {task} (Сдать до: {deadline})\n"
        
        # Напоминание придет ВСЕМ из белого списка
        for user_id in ALLOWED_USERS:
            try:
                await bot.send_message(chat_id=user_id, text=text)
            except Exception:
                pass

async def check_tomorrow_deadlines():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    conn = sqlite3.connect("homework_v6.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subject, task FROM homework WHERE deadline = ?", (tomorrow,))
    rows = cursor.fetchall()
    conn.close()
    
    if rows:
        text = "⚠️ Внимание! Завтра дедлайн по следующим предметам:\n\n"
        for row in rows:
            subject, task = row
            text += f"🚨 {subject}: {task}\n"
        
        for user_id in ALLOWED_USERS:
            try:
                await bot.send_message(chat_id=user_id, text=text)
            except Exception:
                pass

# --- ВЕБ-ЗАГЛУШКА ДЛЯ RENDER ---
async def handle_web_request(request):
    return web.Response(text="Бот запущен и порт открыт!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_web_request)
    runner = web.AppRunner(app)
    await runner.setup()
    # Читаем порт, который требует Render (по умолчанию 10000)
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-заглушка успешно поднята на порту {port}")

async def main():
    init_db()
    dp.include_router(router)
    
    scheduler.add_job(send_weekly_reminder, "cron", day_of_week="sun", hour=12, minute=0)
    scheduler.add_job(check_tomorrow_deadlines, "cron", hour=18, minute=0)
    scheduler.start()
    
    # Запускаем веб-заглушку параллельно с ботом
    await start_web_server()
    
    print("Бот успешно запущен и ждет сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
