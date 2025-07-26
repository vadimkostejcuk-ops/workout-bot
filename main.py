import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, ConversationHandler,
    CallbackQueryHandler, MessageHandler, filters
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в .env!")

# Состояния
(
    MAIN_MENU,
    ADD_EXERCISE_NAME,
    ADD_EXERCISE_SETS,
    ADD_EXERCISE_REPS,
    ADD_EXERCISE_WEIGHT,
    CONFIRM_ADD_ANOTHER,
    VIEW_HISTORY,
    VIEW_WORKOUT_DETAILS,
) = range(8)

# БД
conn = sqlite3.connect('workouts.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    date TEXT,
    weekday TEXT
)''')
c.execute('''
CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER,
    name TEXT,
    sets INTEGER,
    reps INTEGER,
    weight REAL,
    FOREIGN KEY(workout_id) REFERENCES workouts(id)
)''')
conn.commit()

# Сессии
user_sessions = {}

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
        [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
    ]
    await update.message.reply_text("Привет! Выбери действие:", reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'start_workout':
        user_id = query.from_user.id
        now = datetime.now()
        c.execute("INSERT INTO workouts (user_id, date, weekday) VALUES (?, ?, ?)",
                  (user_id, now.strftime('%Y-%m-%d'), now.strftime('%A')))
        conn.commit()
        workout_id = c.lastrowid
        user_sessions[user_id] = {'workout_id': workout_id, 'exercises': []}
        await query.message.edit_text("Введите название первого упражнения:")
        return ADD_EXERCISE_NAME
    elif query.data == 'view_history':
        return await show_history_menu(update, context)

async def add_exercise_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("Сессия не найдена, начните заново.")
        return ConversationHandler.END
    session.setdefault('current_exercise', {})['name'] = text
    await update.message.reply_text("Сколько подходов?")
    return ADD_EXERCISE_SETS

async def add_exercise_sets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not update.message.text.strip().isdigit():
        await update.message.reply_text("Введите число.")
        return ADD_EXERCISE_SETS
    user_sessions[user_id]['current_exercise']['sets'] = int(update.message.text.strip())
    await update.message.reply_text("Сколько повторений?")
    return ADD_EXERCISE_REPS

async def add_exercise_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not update.message.text.strip().isdigit():
        await update.message.reply_text("Введите число.")
        return ADD_EXERCISE_REPS
    user_sessions[user_id]['current_exercise']['reps'] = int(update.message.text.strip())
    await update.message.reply_text("Какой вес (кг)?")
    return ADD_EXERCISE_WEIGHT

async def add_exercise_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        weight = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введите число.")
        return ADD_EXERCISE_WEIGHT
    exercise = user_sessions[user_id]['current_exercise']
    exercise['weight'] = weight
    c.execute("INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES (?, ?, ?, ?, ?)",
              (user_sessions[user_id]['workout_id'], exercise['name'], exercise['sets'], exercise['reps'], exercise['weight']))
    conn.commit()
    user_sessions[user_id]['exercises'].append(exercise)
    user_sessions[user_id].pop('current_exercise')

    keyboard = [
        [InlineKeyboardButton("Добавить ещё упражнение", callback_data='add_another')],
        [InlineKeyboardButton("Завершить тренировку", callback_data='finish_workout')]
    ]
    await update.message.reply_text("Упражнение добавлено. Что дальше?", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_ADD_ANOTHER

async def confirm_add_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'add_another':
        await query.message.edit_text("Введите название упражнения:")
        return ADD_EXERCISE_NAME
    else:
        user_sessions.pop(query.from_user.id, None)
        keyboard = [
            [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
            [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
        ]
        await query.message.edit_text("Тренировка завершена!", reply_markup=InlineKeyboardMarkup(keyboard))
        return MAIN_MENU

async def show_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    c.execute("SELECT id, date, weekday FROM workouts WHERE user_id = ? ORDER BY date DESC", (user_id,))
    workouts = c.fetchall()
    if not workouts:
        await query.message.edit_text("История пуста.")
        return MAIN_MENU

    buttons = [[InlineKeyboardButton(f"{weekday} {date}", callback_data=f"workout_{wid}")]
               for wid, date, weekday in workouts]
    buttons.append([InlineKeyboardButton("Назад", callback_data="back_to_main")])
    await query.message.edit_text("Выберите тренировку:", reply_markup=InlineKeyboardMarkup(buttons))
    return VIEW_HISTORY

async def view_workout_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
            [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
        ]
        await query.message.edit_text("Главное меню:", reply_markup=InlineKeyboardMarkup(keyboard))
        return MAIN_MENU

    workout_id = int(query.data.split("_")[1])
    c.execute("SELECT name, sets, reps, weight FROM exercises WHERE workout_id = ?", (workout_id,))
    exercises = c.fetchall()
    if not exercises:
        await query.message.edit_text("Упражнений не найдено.")
        return VIEW_HISTORY

    text = "\n".join(
        f"{i+1}. {name} — {sets} x {reps}, {weight} кг"
        for i, (name, sets, reps, weight) in enumerate(exercises)
    )
    buttons = [[InlineKeyboardButton("Назад к истории", callback_data="view_history")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return VIEW_WORKOUT_DETAILS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отмена. Главное меню.")
    keyboard = [
        [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
        [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
    ]
    await update.message.reply_text("Главное меню:", reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(main_menu_handler)],
            ADD_EXERCISE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exercise_name)],
            ADD_EXERCISE_SETS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exercise_sets)],
            ADD_EXERCISE_REPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exercise_reps)],
            ADD_EXERCISE_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exercise_weight)],
            CONFIRM_ADD_ANOTHER: [CallbackQueryHandler(confirm_add_another)],
            VIEW_HISTORY: [CallbackQueryHandler(show_history_menu)],
            VIEW_WORKOUT_DETAILS: [CallbackQueryHandler(view_workout_details)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == '__main__':
    main()





