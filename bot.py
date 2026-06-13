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
import card_generator as cg

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


def events_kb(grouped: dict) -> InlineKeyboardMarkup:
    buttons = []
    for i, event_name in enumerate(grouped.keys()):
        short = event_name[:40]
        buttons.append([InlineKeyboardButton(
            text=f"🎯 {short}",
            callback_data=f"event_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def fights_kb(fights: list, event_idx: int) -> InlineKeyboardMarkup:
    buttons = []
    for i, fight in enumerate(fights):
        f1 = fight["fighter1"].split()[-1]
        f2 = fight["fighter2"].split()[-1]
        o1 = svc.format_odds(fight.get("odds_f1"))
        o2 = svc.format_odds(fight.get("odds_f2"))
        buttons.append([InlineKeyboardButton(
            text=f"⚔️ {f1}({o1}) vs {f2}({o2})",
            callback_data=f"fight_{event_idx}_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="make_prediction")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def winner_kb(fight: dict, event_idx: int, fight_idx: int) -> InlineKeyboardMarkup:
    f1 = fight["fighter1"]
    f2 = fight["fighter2"]
    o1 = svc.format_odds(fight.get("odds_f1"))
    o2 = svc.format_odds(fight.get("odds_f2"))
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔴 {f1} ({o1})",
            callback_data=f"pick_{event_idx}_{fight_idx}_f1"
        )],
        [InlineKeyboardButton(
            text=f"🔵 {f2} ({o2})",
            callback_data=f"pick_{event_idx}_{fight_idx}_f2"
        )],
        [InlineKeyboardButton(text="🤝 Ничья", callback_data=f"pick_{event_idx}_{fight_idx}_draw")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"event_{event_idx}")],
    ])


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

async def load_and_cache_events(state: FSMContext) -> dict:
    data = await state.get_data()
    grouped = data.get("grouped_events")
    if not grouped:
        grouped = await svc.get_ufc_events_official()
        for event_name, fights in grouped.items():
            grouped[event_name] = await svc.enrich_fights_with_odds(fights)
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
        "✅ Правильный прогноз — <b>10 очков</b>\n"
        "🎯 Точный метод победы — <b>+5 очков</b> (скоро)",
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
    await call.message.edit_text("⏳ Загружаю официальные ивенты UFC...")

    try:
        grouped = await load_and_cache_events(state)
    except Exception as e:
        log.error(f"Error loading events: {e}")
        await call.message.edit_text(
            "❌ Не удалось загрузить ивенты. Попробуй позже.",
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

    await call.message.edit_text(
        f"🎯 <b>{event_name}</b>\n\nВыбери бой:",
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

    # Показываем загрузку
    loading_msg = await call.message.edit_text(
        f"⏳ Загружаю карточку боя...\n\n⚔️ <b>{f1}</b> vs <b>{f2}</b>",
        parse_mode="HTML"
    )

    # Параллельно грузим всё
    (stats1, stats2), (photo1, photo2) = await asyncio.gather(
        svc.get_both_fighters_data(f1, f2),
        svc.get_both_fighters_photos(f1, f2),
    )

    kb = winner_kb(fight, event_idx, fight_idx)
    wc = fight.get("weight_class", "")
    o1 = fight.get("odds_f1")
    o2 = fight.get("odds_f2")

    caption = (
        f"⚔️ <b>{f1}</b> vs <b>{f2}</b>\n"
        + (f"📌 {wc}\n" if wc else "")
        + f"\n🔴 {f1} — коэф: <b>{svc.format_odds(o1)}</b>\n"
        f"🔵 {f2} — коэф: <b>{svc.format_odds(o2)}</b>\n\n"
        f"Кто победит? 👇"
    )

    try:
        # Генерируем красивую карточку
        card_bytes = await cg.generate_fight_card(
            fighter1=f1, fighter2=f2,
            photo1_url=photo1, photo2_url=photo2,
            stats1=stats1, stats2=stats2,
            odds1=o1, odds2=o2,
            weight_class=wc,
        )

        await call.message.delete()
        await bot.send_photo(
            call.from_user.id,
            photo=BufferedInputFile(card_bytes, filename="fight_card.png"),
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Card generation error: {e}")
        # Fallback — просто текст
        await call.message.edit_text(caption, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("pick_"))
async def save_prediction(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split("_")
    event_idx = int(parts[1])
    fight_idx = int(parts[2])
    choice = parts[3]  # f1, f2, draw

    grouped = await load_and_cache_events(state)
    event_names = list(grouped.keys())
    event_name = event_names[event_idx]
    fights = grouped[event_name]
    fight = fights[fight_idx]

    f1 = fight["fighter1"]
    f2 = fight["fighter2"]

    if choice == "f1":
        predicted_winner = f1
        emoji = "🔴"
    elif choice == "f2":
        predicted_winner = f2
        emoji = "🔵"
    else:
        predicted_winner = "Draw"
        emoji = "🤝"

    fight_id = fight["id"]

    updated = db.save_prediction(
        user_id=call.from_user.id,
        event_id=event_name,
        fight_id=fight_id,
        fighter1=f1,
        fighter2=f2,
        predicted_winner=predicted_winner,
    )

    action = "обновлён" if updated else "сохранён"

    await call.message.edit_caption(
        caption=(
            f"✅ Прогноз {action}!\n\n"
            f"⚔️ <b>{f1}</b> vs <b>{f2}</b>\n"
            f"{emoji} Твой выбор: <b>{predicted_winner}</b>\n\n"
            f"Удачи! 🍀"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Следующий бой", callback_data=f"event_{event_idx}")],
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
            "📋 Нет активных ивентов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
            ])
        )
        return

    event_name = list(grouped.keys())[0]
    preds = db.get_user_predictions(call.from_user.id, event_name)

    if not preds:
        await call.message.edit_text(
            f"📋 У тебя ещё нет прогнозов на <b>{event_name}</b>\n\nСделай первый прогноз! 🥊",
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
        lines.append(f"{status} {p['fighter1']} vs {p['fighter2']}\n   👉 {p['predicted_winner']}")

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
            "🏆 Таблица пока пуста. Стань первым!",
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
#  ADMIN
# ─────────────────────────────────────────

@router.message(Command("set_result"))
async def cmd_set_result(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Формат: /set_result <fight_id> <победитель>")
        return
    fight_id = args[1]
    winner = args[2]
    count = db.mark_prediction_result(fight_id, winner)
    await message.answer(f"✅ Готово! Победитель: {winner}\nОбновлено прогнозов: {count}")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "👤 <b>Админ панель</b>\n\n"
        "/set_result <fight_id> <победитель> — проставить результат боя",
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
