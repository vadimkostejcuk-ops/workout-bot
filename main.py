import os
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    CallbackQueryHandler, MessageHandler, filters
)
import sqlite3
from datetime import datetime

load_dotenv()  # Загружаем переменные из .env

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения!")

# Состояния для ConversationHandler
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

# Подключение к базе
conn = sqlite3.connect('workouts.db', check_same_thread=False)
c = conn.cursor()

# Создаем таблицы, если их нет
c.execute('''
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    date TEXT,
    weekday TEXT
)
''')
c.execute('''
CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER,
    name TEXT,
    sets INTEGER,
    reps INTEGER,
    weight REAL,
    FOREIGN KEY(workout_id) REFERENCES workouts(id)
)
''')
conn.commit()

# Хранилище для данных сессии (упрощенно)
user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
        [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Выбери действие:", reply_markup=reply_markup)
    return MAIN_MENU

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'start_workout':
        user_id = query.from_user.id
        today_str = datetime.now().strftime('%Y-%m-%d')
        weekday_str = datetime.now().strftime('%A')
        # Создаем новую тренировку в БД
        c.execute("INSERT INTO workouts (user_id, date, weekday) VALUES (?, ?, ?)", (user_id, today_str, weekday_str))
        conn.commit()
        workout_id = c.lastrowid
        user_sessions[user_id] = {'workout_id': workout_id, 'exercises': []}

        await query.message.edit_text("Введите название первого упражнения:")
        return ADD_EXERCISE_NAME

    elif data == 'view_history':
        return await show_history_menu(update, context)

async def add_exercise_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("Сессия не найдена, начните тренировку заново.")
        return ConversationHandler.END

    # Сохраняем название упражнения
    session.setdefault('current_exercise', {})['name'] = text
    await update.message.reply_text("Сколько подходов?")
    return ADD_EXERCISE_SETS

async def add_exercise_sets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число для подходов.")
        return ADD_EXERCISE_SETS

    session = user_sessions.get(user_id)
    session['current_exercise']['sets'] = int(text)
    await update.message.reply_text("Сколько повторений в подходе?")
    return ADD_EXERCISE_REPS

async def add_exercise_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число для повторений.")
        return ADD_EXERCISE_REPS

    session = user_sessions.get(user_id)
    session['current_exercise']['reps'] = int(text)
    await update.message.reply_text("Какой рабочий вес (кг)? Введите число, можно с десятичной точкой.")
    return ADD_EXERCISE_WEIGHT

async def add_exercise_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    try:
        weight = float(text)
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число для веса.")
        return ADD_EXERCISE_WEIGHT

    session = user_sessions.get(user_id)
    exercise = session['current_exercise']
    exercise['weight'] = weight

    # Сохраняем упражнение в базу
    c.execute(
        "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES (?, ?, ?, ?, ?)",
        (session['workout_id'], exercise['name'], exercise['sets'], exercise['reps'], exercise['weight'])
    )
    conn.commit()
    session['exercises'].append(exercise)
    session.pop('current_exercise')

    keyboard = [
        [InlineKeyboardButton("Добавить ещё упражнение", callback_data='add_another')],
        [InlineKeyboardButton("Завершить тренировку", callback_data='finish_workout')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Упражнение добавлено. Что дальше?", reply_markup=reply_markup)
    return CONFIRM_ADD_ANOTHER

async def confirm_add_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == 'add_another':
        await query.message.edit_text("Введите название упражнения:")
        return ADD_EXERCISE_NAME
    elif query.data == 'finish_workout':
        # Очистим сессию
        user_sessions.pop(user_id, None)
        keyboard = [
            [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
            [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("Тренировка завершена!", reply_markup=reply_markup)
        return MAIN_MENU

async def show_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    c.execute("SELECT id, date, weekday FROM workouts WHERE user_id = ? ORDER BY date DESC", (user_id,))
    workouts = c.fetchall()
    if not workouts:
        await query.message.edit_text("История тренировок пуста.")
        return MAIN_MENU

    buttons = []
    for wid, date, weekday in workouts:
        btn_text = f"{weekday} {date}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"workout_{wid}")])

    buttons.append([InlineKeyboardButton("Назад", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text("Выберите тренировку для просмотра:", reply_markup=reply_markup)
    return VIEW_HISTORY

async def view_workout_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
            [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("Главное меню:", reply_markup=reply_markup)
        return MAIN_MENU

    if not data.startswith("workout_"):
        return MAIN_MENU

    workout_id = int(data.split("_")[1])
    c.execute("SELECT name, sets, reps, weight FROM exercises WHERE workout_id = ?", (workout_id,))
    exercises = c.fetchall()
    if not exercises:
        await query.message.edit_text("Упражнения не найдены для этой тренировки.")
        return VIEW_HISTORY

    text_lines = []
    for i, (name, sets, reps, weight) in enumerate(exercises, 1):
        text_lines.append(f"{i}. {name} — {sets} подходов по {reps} повторений, вес {weight} кг")

    text = "\n".join(text_lines)
    buttons = [[InlineKeyboardButton("Назад к истории", callback_data="view_history")]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(text, reply_markup=reply_markup)
    return VIEW_WORKOUT_DETAILS

async def back_to_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await show_history_menu(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отмена. Возвращаемся в главное меню.")
    keyboard = [
        [InlineKeyboardButton("Начать тренировку", callback_data='start_workout')],
        [InlineKeyboardButton("Просмотреть историю тренировок", callback_data='view_history')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Главное меню:", reply_markup=reply_markup)
    return MAIN_MENU

def main():
    app = Application.builder().token(TOKEN).build()

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



