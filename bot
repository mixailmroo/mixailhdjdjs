import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

import database as db
import services as svc

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ─────────────────────────────────────────
#  FSM STATES
# ─────────────────────────────────────────

class PredictState(StatesGroup):
    choosing_event = State()
    choosing_fight = State()
    choosing_winner = State()


# ─────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥊 Сделать прогноз", callback_data="make_prediction")],
        [InlineKeyboardButton(text="📋 Мои прогнозы", callback_data="my_predictions")],
        [InlineKeyboardButton(text="🏆 Таблица лидеров", callback_data="leaderboard")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
    ])


def events_kb(grouped: dict[str, list]) -> InlineKeyboardMarkup:
    buttons = []
    for i, event_name in enumerate(grouped.keys()):
        short = event_name[:40]
        buttons.append([InlineKeyboardButton(
            text=f"🎯 {short}",
            callback_data=f"event_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def fights_kb(fights: list[dict], event_idx: int) -> InlineKeyboardMarkup:
    buttons = []
    for i, fight in enumerate(fights):
        f1 = fight["fighter1"].split()[-1]
        f2 = fight["fighter2"].split()[-1]
        buttons.append([InlineKeyboardButton(
            text=f"⚔️ {f1} vs {f2}",
            callback_data=f"fight_{event_idx}_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="make_prediction")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def winner_kb(fight: dict, event_idx: int, fight_idx: int) -> InlineKeyboardMarkup:
    f1 = fight["fighter1"]
    f2 = fight["fighter2"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔴 {f1}",
            callback_data=f"pick_{event_idx}_{fight_idx}_f1"
        )],
        [InlineKeyboardButton(
            text=f"🔵 {f2}",
            callback_data=f"pick_{event_idx}_{fight_idx}_f2"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"event_{event_idx}")],
    ])


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def format_datetime(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return iso


def format_stats_text(name: str, stats: dict) -> str:
    lines = [f"<b>{name}</b>"]
    nick = stats.get("nickname", "")
    if nick:
        lines.append(f'<i>"{nick}"</i>')

    record = svc.format_record(stats)
    if record != "?-?-?":
        lines.append(f"📊 Рекорд: <b>{record}</b>")

    for key, label in [
        ("height", "📏 Рост"), ("weight", "⚖️ Вес"),
        ("reach", "💪 Размах рук"), ("stance", "🥊 Стойка"),
        ("slpm", "⚡ Удары/мин"), ("str._acc.", "🎯 Точность"),
        ("td_avg.", "🤼 Тейкдауны/15мин"), ("sub._avg.", "🔒 Сабмишны/15мин"),
    ]:
        val = stats.get(key, "")
        if val:
            lines.append(f"{label}: {val}")

    return "\n".join(lines)


async def load_and_cache_events(state: FSMContext) -> dict:
    """Загружает ивенты из API и сохраняет в FSM."""
    data = await state.get_data()
    grouped = data.get("grouped_events")
    if not grouped:
        raw = await svc.get_ufc_events()
        grouped = svc.parse_fights_from_odds(raw)
        await state.update_data(grouped_events=grouped)
    return grouped


# ─────────────────────────────────────────
#  HANDLERS — START / MENU
# ─────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    db.register_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    await message.answer(
        "👊 <b>UFC Predictions Bot</b>\n\n"
        "Делай прогнозы на бои UFC, зарабатывай очки и соревнуйся с другими!\n\n"
        "За каждый правильный прогноз — <b>10 очков</b> 🏆",
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "👊 <b>UFC Predictions Bot</b>\n\nГлавное меню:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )


# ─────────────────────────────────────────
#  HANDLERS — ПРОГНОЗЫ
# ─────────────────────────────────────────

@router.callback_query(F.data == "make_prediction")
async def show_events(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("⏳ Загружаю предстоящие ивенты UFC...")

    try:
        grouped = await load_and_cache_events(state)
    except Exception as e:
        log.error(f"Error loading events: {e}")
        await call.message.edit_text(
            "❌ Не удалось загрузить ивенты. Проверь API ключ.\n\n"
            "Убедись что в .env файле указан верный ODDS_API_KEY.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
            ])
        )
        return

    if not grouped:
        await call.message.edit_text(
            "😔 Сейчас нет предстоящих ивентов UFC.\nПроверь позже!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
            ])
        )
        return

    await state.set_state(PredictState.choosing_event)
    event_list = "\n".join([f"• {name}" for name in list(grouped.keys())[:5]])
    await call.message.edit_text(
        f"🗓 <b>Предстоящие ивенты UFC:</b>\n\n{event_list}\n\nВыбери ивент:",
        reply_markup=events_kb(grouped),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("event_"))
async def show_fights(call: CallbackQuery, state: FSMContext):
    await call.answer()
    event_idx = int(call.data.split("_")[1])

    grouped = await load_and_cache_events(state)
    event_names = list(grouped.keys())

    if event_idx >= len(event_names):
        await call.answer("Ивент не найден", show_alert=True)
        return

    event_name = event_names[event_idx]
    fights = grouped[event_name]

    await state.update_data(current_event_idx=event_idx, current_event_name=event_name)
    await state.set_state(PredictState.choosing_fight)

    fights_text = "\n".join([
        f"⚔️ {f['fighter1']} vs {f['fighter2']}  |  {format_datetime(f['commence_time'])}"
        for f in fights
    ])

    await call.message.edit_text(
        f"🎯 <b>{event_name}</b>\n\n{fights_text}\n\nВыбери бой:",
        reply_markup=fights_kb(fights, event_idx),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("fight_"))
async def show_fight_detail(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split("_")
    event_idx = int(parts[1])
    fight_idx = int(parts[2])

    grouped = await load_and_cache_events(state)
    event_names = list(grouped.keys())
    event_name = event_names[event_idx]
    fights = grouped[event_name]
    fight = fights[fight_idx]

    f1 = fight["fighter1"]
    f2 = fight["fighter2"]

    await state.update_data(current_fight_idx=fight_idx)
    await state.set_state(PredictState.choosing_winner)

    # Показываем базовую инфо пока грузится детальная
    await call.message.edit_text(
        f"⏳ Загружаю данные о бойцах...\n\n⚔️ <b>{f1}</b> vs <b>{f2}</b>",
        parse_mode="HTML"
    )

    # Загружаем статистику и фото параллельно
    (stats1, stats2), (photo1, photo2) = await asyncio.gather(
        svc.get_both_fighters_data(f1, f2),
        svc.get_both_fighters_photos(f1, f2),
    )

    odds1 = svc.format_odds(fight.get("odds_f1"))
    odds2 = svc.format_odds(fight.get("odds_f2"))
    fight_time = format_datetime(fight.get("commence_time", ""))

    text = (
        f"⚔️ <b>{f1}</b> vs <b>{f2}</b>\n"
        f"📅 {fight_time}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 <b>{f1}</b> — коэф: <b>{odds1}</b>\n"
        f"{format_stats_text(f1, stats1)}\n\n"
        f"🔵 <b>{f2}</b> — коэф: <b>{odds2}</b>\n"
        f"{format_stats_text(f2, stats2)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Кто победит? 👇"
    )

    kb = winner_kb(fight, event_idx, fight_idx)

    # Пытаемся отправить с фото, если есть
    if photo1 or photo2:
        photo_url = photo1 or photo2
        try:
            await call.message.delete()
            await bot.send_photo(
                call.from_user.id,
                photo=photo_url,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            return
        except Exception:
            pass  # Если фото не грузится — показываем текст

    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("pick_"))
async def save_prediction(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split("_")
    event_idx = int(parts[1])
    fight_idx = int(parts[2])
    choice = parts[3]  # "f1" or "f2"

    grouped = await load_and_cache_events(state)
    event_names = list(grouped.keys())
    event_name = event_names[event_idx]
    fights = grouped[event_name]
    fight = fights[fight_idx]

    predicted_winner = fight["fighter1"] if choice == "f1" else fight["fighter2"]
    fight_id = fight["id"]
    f1 = fight["fighter1"]
    f2 = fight["fighter2"]

    updated = db.save_prediction(
        user_id=call.from_user.id,
        event_id=event_name,
        fight_id=fight_id,
        fighter1=f1,
        fighter2=f2,
        predicted_winner=predicted_winner,
    )

    action = "обновлён" if updated else "сохранён"
    emoji = "🔴" if choice == "f1" else "🔵"

    await call.message.edit_text(
        f"✅ Прогноз {action}!\n\n"
        f"⚔️ {f1} vs {f2}\n"
        f"{emoji} Твой выбор: <b>{predicted_winner}</b>\n\n"
        f"Удачи! 🍀",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Другой бой", callback_data=f"event_{event_idx}")],
            [InlineKeyboardButton(text="📋 Мои прогнозы", callback_data="my_predictions")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="back_main")],
        ]),
        parse_mode="HTML"
    )


# ─────────────────────────────────────────
#  HANDLERS — МОИ ПРОГНОЗЫ
# ─────────────────────────────────────────

@router.callback_query(F.data == "my_predictions")
async def show_my_predictions(call: CallbackQuery, state: FSMContext):
    await call.answer()

    grouped = await load_and_cache_events(state)

    if not grouped:
        await call.message.edit_text(
            "📋 Нет активных ивентов для отображения прогнозов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
            ])
        )
        return

    # Показываем прогнозы по последнему ивенту
    event_name = list(grouped.keys())[0]
    preds = db.get_user_predictions(call.from_user.id, event_name)

    if not preds:
        await call.message.edit_text(
            f"📋 У тебя ещё нет прогнозов на <b>{event_name}</b>\n\n"
            "Сделай первый прогноз! 🥊",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🥊 Сделать прогноз", callback_data="make_prediction")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
            ]),
            parse_mode="HTML"
        )
        return

    lines = [f"📋 <b>Твои прогнозы — {event_name}</b>\n"]
    for p in preds:
        if p["is_correct"] is None:
            status = "⏳"
        elif p["is_correct"]:
            status = "✅ +10 очков"
        else:
            status = "❌"

        lines.append(
            f"{status} {p['fighter1']} vs {p['fighter2']}\n"
            f"   👉 {p['predicted_winner']}"
        )

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🥊 Новый прогноз", callback_data="make_prediction")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
        ]),
        parse_mode="HTML"
    )


# ─────────────────────────────────────────
#  HANDLERS — ТАБЛИЦА ЛИДЕРОВ
# ─────────────────────────────────────────

@router.callback_query(F.data == "leaderboard")
async def show_leaderboard(call: CallbackQuery):
    await call.answer()
    top = db.get_leaderboard(10)

    if not top:
        await call.message.edit_text(
            "🏆 Таблица пока пуста.\nСтань первым!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
            ])
        )
        return

    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 10
    lines = ["🏆 <b>Таблица лидеров</b>\n"]

    for i, user in enumerate(top):
        name = user.get("full_name") or user.get("username") or f"User {user['user_id']}"
        pts = user["points"]
        correct = user.get("correct_preds") or 0
        total = user.get("total_preds") or 0
        lines.append(f"{medals[i]} {name} — <b>{pts} очков</b> ({correct}/{total})")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ]),
        parse_mode="HTML"
    )


# ─────────────────────────────────────────
#  HANDLERS — МОЯ СТАТИСТИКА
# ─────────────────────────────────────────

@router.callback_query(F.data == "my_stats")
async def show_my_stats(call: CallbackQuery):
    await call.answer()
    stats = db.get_user_stats(call.from_user.id)

    total = stats.get("total") or 0
    correct = stats.get("correct") or 0
    points = stats.get("points") or 0
    accuracy = round((correct / total * 100), 1) if total > 0 else 0

    name = call.from_user.full_name or call.from_user.username or "Боец"

    await call.message.edit_text(
        f"📊 <b>Статистика — {name}</b>\n\n"
        f"🏆 Очки: <b>{points}</b>\n"
        f"📈 Всего прогнозов: <b>{total}</b>\n"
        f"✅ Угадано: <b>{correct}</b>\n"
        f"🎯 Точность: <b>{accuracy}%</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ]),
        parse_mode="HTML"
    )


# ─────────────────────────────────────────
#  ADMIN — ПРОСТАВИТЬ РЕЗУЛЬТАТЫ
# ─────────────────────────────────────────

@router.message(Command("set_result"))
async def cmd_set_result(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    # /set_result fight_id Winner Name
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ Формат: /set_result <fight_id> <победитель>\n"
            "Пример: /set_result abc123 Jon Jones"
        )
        return

    fight_id = args[1]
    winner = args[2]
    count = db.mark_prediction_result(fight_id, winner)
    await message.answer(
        f"✅ Результат проставлен!\n"
        f"Бой: {fight_id}\n"
        f"Победитель: {winner}\n"
        f"Обновлено прогнозов: {count}"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "👤 <b>Админ панель</b>\n\n"
        "/set_result <fight_id> <победитель> — проставить результат боя\n\n"
        "fight_id берётся из API (поле id в событии)",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

async def main():
    db.init_db()
    log.info("Database initialized")
    log.info("Starting UFC Predictions Bot...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
