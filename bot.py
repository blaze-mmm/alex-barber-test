import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
BARBER_ID = int(os.getenv("BARBER_ID", "0"))

WORK_HOURS = [
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
    "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
    "18:00", "18:30", "19:00", "19:30", "20:00"
]

SERVICES = {
    "haircut": ("Мужская стрижка", "1000 ₽"),
    "beard": ("Оформление бороды", "хуй знает"),
    "complex": ("Комплекс (Стрижка + Борода)", "хуй знает")
}

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            client_name TEXT,
            phone TEXT,
            service TEXT,
            date TEXT,
            time TEXT
        )
    """)
    try:
        cur.execute("ALTER TABLE bookings ADD COLUMN username TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def get_booked_times(date_str):
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("SELECT time FROM bookings WHERE date = ?", (date_str,))
    booked = [row for row in cur.fetchall()]
    conn.close()
    return booked

def add_booking(user_id, username, name, phone, service, date_str, time_str):
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (user_id, username, client_name, phone, service, date, time) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, name, phone, service, date_str, time_str)
    )
    conn.commit()
    conn.close()

# --- СОСТОЯНИЯ (ШАГИ ЗАПИСИ) ---
class BookingState(StatesGroup):
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    entering_name = State()
    entering_phone = State()

# --- КЛАВИАТУРЫ ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✂️ Записаться", callback_data="start_book")],
        [InlineKeyboardButton(text="💈 Прайс-лист", callback_data="price")],
        [InlineKeyboardButton(text="📍 Контакты", callback_data="contacts")]
    ])

# --- ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.first_name}! Это бот записи к **Alex Barber**.\nВыбери действие:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "price")
async def show_price(callback: types.CallbackQuery):
    text = "**Услуги Alex Barber:**\n\n" + "\n".join([f"• {name} — {price}" for name, price in SERVICES.values()])
    await callback.message.edit_text(text, reply_markup=main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "contacts")
async def show_contacts(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📍 **Адрес:** Оляга Сити, улица Сиси\n📞 **Телефон:** +79996666767",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

# Шаг 1: Выбор услуги
@dp.callback_query(F.data == "start_book")
async def book_service(callback: types.CallbackQuery, state: FSMContext):
    buttons = [[InlineKeyboardButton(text=f"{name} ({price})", callback_data=f"srv_{key}")] for key, (name, price) in SERVICES.items()]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    await callback.message.edit_text("Выбери услугу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BookingState.choosing_service)

@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())

# Шаг 2: Выбор даты (ближайшие 5 дней)
@dp.callback_query(BookingState.choosing_service, F.data.startswith("srv_"))
async def book_date(callback: types.CallbackQuery, state: FSMContext):
    srv_key = callback.data.split("_")[1]
    await state.update_data(service=SERVICES[srv_key][0])
    
    buttons = []
    today = datetime.now()
    for i in range(5):
        day = today + timedelta(days=i)
        date_str = day.strftime("%d.%m.%Y")
        buttons.append([InlineKeyboardButton(text=date_str, callback_data=f"date_{date_str}")])
    
    await callback.message.edit_text("Выбери удобную дату:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BookingState.choosing_date)

# Шаг 3: Выбор времени (сетка по 3 кнопки в ряд)
@dp.callback_query(BookingState.choosing_date, F.data.startswith("date_"))
async def book_time(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    await state.update_data(date=date_str)
    
    booked = [b[0] for b in get_booked_times(date_str)]
    free_times = [t for t in WORK_HOURS if t not in booked]
    
    if not free_times:
        await callback.answer("На эту дату свободных мест нет!", show_alert=True)
        return

    buttons = []
    row = []
    for t in free_times:
        row.append(InlineKeyboardButton(text=t, callback_data=f"time_{t}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await callback.message.edit_text(f"Свободное время на {date_str}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BookingState.choosing_time)

# Шаг 4: Ввод имени
@dp.callback_query(BookingState.choosing_time, F.data.startswith("time_"))
async def book_name(callback: types.CallbackQuery, state: FSMContext):
    time_str = callback.data.split("_")[1]
    await state.update_data(time=time_str)
    await callback.message.edit_text("Как тебя зовут? Напиши имя:")
    await state.set_state(BookingState.entering_name)

# Шаг 5: Ввод телефона
@dp.message(BookingState.entering_name)
async def book_phone(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Отправь свой номер телефона (нажми кнопку ниже или введи вручную):", reply_markup=kb)
    await state.set_state(BookingState.entering_phone)

# Финал: Сохранение и уведомление барбера
@dp.message(BookingState.entering_phone)
async def book_finish(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    username = f"@{message.from_user.username}" if message.from_user.username else "нет юзернейма"
    data = await state.get_data()
    
    add_booking(message.from_user.id, username, data['name'], phone, data['service'], data['date'], data['time'])
    
    await message.answer(
        f"✅ **Ты успешно записан!**\n\n"
        f"✂️ Услуга: {data['service']}\n"
        f"📅 Дата: {data['date']}\n"
        f"⏰ Время: {data['time']}\n\n"
        f"Ждем тебя в Alex Barber!",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    
    if BARBER_ID:
        await bot.send_message(
            BARBER_ID,
            f"🔔 **Новая запись!**\n\n"
            f"👤 Клиент: {data['name']} ({username})\n"
            f"📞 Телефон: {phone}\n"
            f"✂️ Услуга: {data['service']}\n"
            f"📅 Дата и время: {data['date']} в {data['time']}",
            parse_mode="Markdown"
        )
    await state.clear()

# Админ-команда для просмотра записей (/admin)
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != BARBER_ID:
        return
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("SELECT date, time, client_name, username, phone, service FROM bookings ORDER BY date, time")
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("Пока записей нет.")
        return
        
    text = "📋 **Список всех записей:**\n\n"
    for r in rows:
        uname = r[3] if r[3] else "нет юзернейма"
        text += f"• {r[0]} в {r[1]} — {r[2]} ({uname}, {r[4]}) | {r[5]}\n"
    await message.answer(text, parse_mode="Markdown")

async def main():
    init_db()
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
