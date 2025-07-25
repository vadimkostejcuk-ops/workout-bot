import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

# Состояния
CHOOSE_ACTION, EXERCISE_NAME, SETS, REPS, WEIGHT = range(5)

# Временное хранилище
user_data = {}

# Инициализация БД
def init_db():
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS workouts (
            user_id INTEGER,
            date TEXT,
            exercise TEXT,
            sets INTEGER,
            reps INTEGER,
            weight REAL
        )
    """)
    conn.commit()
    conn.close()

# Главное меню
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("Начать тренировку")],
        [KeyboardButton("Просмотреть историю тренировок")]
    ], resize_keyboard=True)

# Старт
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выбери действие:", reply_markup=main_menu_keyboard())
    return CHOOSE_ACTION

# Обработка кнопок главного меню
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Начать тренировку":
        user_data[update.effective_user.id] = {
            "exercises": [],
            "current_exercise": {}
        }
        await update.message.reply_text("Введите название первого упражнения:")
        return EXERCISE_NAME
    elif text == "Просмотреть историю тренировок":
        return await show_history_menu(update, context)

# Ввод названия
async def input_exercise_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]["current_exercise"] = {"name": update.message.text}
    await update.message.reply_text("Сколько подходов?")
    return SETS

# Ввод подходов
async def input_sets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]["current_exercise"]["sets"] = int(update.message.text)
    await update.message.reply_text("Сколько повторений?")
    return REPS

# Ввод повторений
async def input_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]["current_exercise"]["reps"] = int(update.message.text)
    await update.message.reply_text("Какой вес?")
    return WEIGHT

# Ввод веса
async def input_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]["current_exercise"]["weight"] = float(update.message.text)
    user_data[user_id]["exercises"].append(user_data[user_id]["current_exercise"])
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Добавить упражнение", callback_data="add_more")],
        [InlineKeyboardButton("Закончить тренировку", callback_data="finish")]
    ])
    await update.message.reply_text("Упражнение добавлено.", reply_markup=keyboard)
    return CHOOSE_ACTION

# Кнопки после добавления упражнения
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "add_more":
        await query.edit_message_text("Введите название следующего упражнения:")
        return EXERCISE_NAME
    elif query.data == "finish":
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        conn = sqlite3.connect("workouts.db")
        c = conn.cursor()
        for ex in user_data[user_id]["exercises"]:
            c.execute("INSERT INTO workouts (user_id, date, exercise, sets, reps, weight) VALUES (?, ?, ?, ?, ?, ?)",
                      (user_id, date_str, ex["name"], ex["sets"], ex["reps"], ex["weight"]))
        conn.commit()
        conn.close()
        del user_data[user_id]
        await query.edit_message_text("Тренировка завершена и сохранена!")
        await query.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return CHOOSE_ACTION

# Показ меню истории
async def show_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT date FROM workouts WHERE user_id = ? ORDER BY date DESC", (user_id,))
    dates = c.fetchall()
    conn.close()

    if not dates:
        await update.message.reply_text("История пуста.")
        return CHOOSE_ACTION

    keyboard = [
        [InlineKeyboardButton(f"{datetime.strptime(d[0], '%Y-%m-%d').strftime('%A %d.%m.%Y')}", callback_data=f"history_{d[0]}")]
        for d in dates
    ]
    await update.message.reply_text("Выбери дату:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSE_ACTION

# Показ конкретной тренировки
async def show_history_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    date = query.data.replace("history_", "")

    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("SELECT exercise, sets, reps, weight FROM workouts WHERE user_id = ? AND date = ?", (user_id, date))
    records = c.fetchall()
    conn.close()

    if not records:
        await query.edit_message_text("Нет записей.")
    else:
        text = f"Тренировка за {datetime.strptime(date, '%Y-%m-%d').strftime('%A %d.%m.%Y')}:\n\n"
        for idx, (name, sets, reps, weight) in enumerate(records, 1):
            text += f"{idx}. {name} — {sets}x{reps} {weight}кг\n"
        await query.edit_message_text(text)

    await query.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
    return CHOOSE_ACTION

# Запуск бота
def main():
    init_db()
    app = Application.builder().token("8436341684:AAHuw04R4ZK03tFpLrU98N4XxKI4lu45Hdg").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT, handle_main_menu)],
        states={
            CHOOSE_ACTION: [
                MessageHandler(filters.TEXT, handle_main_menu),
                CallbackQueryHandler(handle_callback, pattern="^(add_more|finish)$"),
                CallbackQueryHandler(show_history_entry, pattern="^history_.*$")
            ],
            EXERCISE_NAME: [MessageHandler(filters.TEXT, input_exercise_name)],
            SETS: [MessageHandler(filters.TEXT & filters.Regex(r"^\d+$"), input_sets)],
            REPS: [MessageHandler(filters.TEXT & filters.Regex(r"^\d+$"), input_reps)],
            WEIGHT: [MessageHandler(filters.TEXT & filters.Regex(r"^\d+(\.\d+)?$"), input_weight)]
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()


