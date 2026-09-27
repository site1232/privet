import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= НАСТРОЙКИ БОТА =================
BOT_TOKEN = "8701443421:AAE1Z0mwoIDUiqoGSZDx3pkZPqvX9DInSys"
USER_ID = 1448711405
# ==================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
scheduler = AsyncIOScheduler()

# Состояния для пошагового ввода: Предмет -> Задание -> Дедлайн
class HomeworkStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_task = State()
    waiting_for_deadline = State()

# Создание базы данных
def init_db():
    conn = sqlite3.connect("homework_v5.db")
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

# Кнопки главного меню
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Добавить ДЗ"), KeyboardButton(text="📋 Моё ДЗ")]
    ],
    resize_keyboard=True
)

@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id != USER_ID:
        await message.answer("Извини, этот бот приватный.")
        return
    await message.answer("Привет! Я помогу тебе вести учет домашних заданий в вузе.", reply_markup=main_kb)

# КНОПКА: Показать текущие домашние задания
@router.message(F.text == "📋 Моё ДЗ")
async def show_homework(message: Message):
    if message.from_user.id != USER_ID:
        return
    try:
        conn = sqlite3.connect("homework_v5.db")
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

# ШАГ 1: Начало добавления ДЗ
@router.message(F.text == "📚 Добавить ДЗ")
async def add_hw_start(message: Message, state: FSMContext):
    if message.from_user.id != USER_ID:
        return
    await message.answer("Введите название предмета (например, Матанализ):")
    await state.set_state(HomeworkStates.waiting_for_subject)

# ШАГ 2: Получаем предмет, запрашиваем описание задания
@router.message(HomeworkStates.waiting_for_subject)
async def add_hw_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text)
    await message.answer("Теперь напишите, что именно нужно сделать:")
    await state.set_state(HomeworkStates.waiting_for_task)

# ШАГ 3: Получаем задание, запрашиваем дату дедлайна
@router.message(HomeworkStates.waiting_for_task)
async def add_hw_task(message: Message, state: FSMContext):
    await state.update_data(task=message.text)
    await message.answer("Введите дату дедлайна в формате ДД.ММ.ГГГГ (например, 05.10.2026):")
    await state.set_state(HomeworkStates.waiting_for_deadline)

# ШАГ 4: Проверяем формат даты и сохраняем всё в БД
@router.message(HomeworkStates.waiting_for_deadline)
async def add_hw_deadline(message: Message, state: FSMContext):
    deadline_text = message.text.strip()
    
    # Проверка формата ДД.ММ.ГГГГ
    try:
        datetime.strptime(deadline_text, "%d.%m.%Y")
    except ValueError:
        await message.answer("❌ Неверный формат даты! Пожалуйста, введите дату строго как ДД.ММ.ГГГГ (например, 28.09.2026):")
        return

    user_data = await state.get_data()
    subject = user_data['subject']
    task = user_data['task']
    
    conn = sqlite3.connect("homework_v5.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO homework (subject, task, deadline) VALUES (?, ?, ?)", (subject, task, deadline_text))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Задание по предмету {subject} успешно добавлено!", reply_markup=main_kb)

# КОМАНДА: Выполнено (ИСПРАВЛЕННАЯ СТРОКА С ИНДЕКСОМ)
@router.message(F.text.startswith("/done_"))
async def delete_homework(message: Message):
    if message.from_user.id != USER_ID:
        return
    try:
        hw_id = int(message.text.split("_")[1])
        conn = sqlite3.connect("homework_v5.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
        conn.commit()
        conn.close()
        await message.answer("🗑️ Задание отмечено как выполненное и удалено из списка!")
    except Exception as e:
        await message.answer(f"Ошибка удаления: {e}")

# АВТОМАТИЗАЦИЯ: Напоминание по воскресеньям в 12:00
async def send_weekly_reminder():
    conn = sqlite3.connect("homework_v5.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subject, task, deadline FROM homework")
    rows = cursor.fetchall()
    conn.close()
    
    if rows:
        text = "⏰ Воскресное напоминание! Список всех задач на неделю:\n\n"
        for row in rows:
            subject, task, deadline = row
            text += f"▪️ {subject}: {task} (Сдать до: {deadline})\n"
        await bot.send_message(chat_id=USER_ID, text=text)

# АВТОМАТИЗАЦИЯ: Ежедневная проверка «дедлайн завтра» в 18:00
async def check_tomorrow_deadlines():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    
    conn = sqlite3.connect("homework_v5.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subject, task FROM homework WHERE deadline = ?", (tomorrow,))
    rows = cursor.fetchall()
    conn.close()
    
    if rows:
        text = "⚠️ Внимание! Завтра дедлайн по следующим предметам:\n\n"
        for row in rows:
            subject, task = row
            text += f"🚨 {subject}: {task}\n"
        await bot.send_message(chat_id=USER_ID, text=text)

async def main():
    init_db()
    dp.include_router(router)
    
    # 1. Запуск напоминания на воскресенье 12:00
    scheduler.add_job(send_weekly_reminder, "cron", day_of_week="sun", hour=12, minute=0)
    
    # 2. Запуск проверки дедлайнов каждый день в 18:00
    scheduler.add_job(check_tomorrow_deadlines, "cron", hour=18, minute=0)
    
    scheduler.start()
    
    print("Бот успешно запущен и ждет сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
