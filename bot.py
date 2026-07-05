"""
bot.py — Telegram-бот для подготовки к экзаменам (ФТ / Аналитическая химия).

Возможности:
  • выбор предмета (у каждого своя колода, статистика и расписание повторений);
  • карточки с самооценкой Знал / Частично / Не знал; на «частично/не знал»
    ИИ объясняет тему глубже — строго по материалу билета;
  • режим «Вопрос от ИИ»: модель задаёт вопрос по материалу, студентка
    отвечает текстом, ИИ проверяет и объясняет ошибку — строго по материалу;
  • интервальное повторение (SM-2): бот сам решает, что показать сегодня;
  • статистика: готовность, слабые/сильные билеты, streak, дни до экзамена;
  • ежедневные напоминания в выбранный час.

Все кнопки встроены в сообщения (inline-клавиатуры).
"""
import asyncio
import logging
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import ai
import config
import db
import keyboards as kb
from srs import update as srs_update

logging.basicConfig(level=logging.INFO)
router = Router()
conn = db.connect(config.DB_PATH)

VERDICT_TO_RATING = {"correct": "good", "partial": "partial", "incorrect": "again"}
VERDICT_EMOJI = {"correct": "✅ Верно", "partial": "🟡 Частично", "incorrect": "❌ Неверно"}
TG_LIMIT = 3800


class Flow(StatesGroup):
    answering = State()          # ждём текстовый ответ в режиме «Вопрос от ИИ»
    set_reminder = State()       # ждём час напоминания
    set_exam = State()           # ждём дату экзамена


async def send_long(msg: Message, text: str, reply_markup=None):
    """Отправить длинный текст частями (лимит Telegram ~4096)."""
    parts = [text[i:i + TG_LIMIT] for i in range(0, len(text), TG_LIMIT)] or [""]
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        await msg.answer(part, reply_markup=reply_markup if last else None)


def active_subject(tg_id: int):
    u = db.get_user(conn, tg_id)
    return u["active_subject"] if u else None


# ---------- старт и навигация ----------

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db.ensure_user(conn, message.from_user.id, message.from_user.full_name)
    await message.answer(
        "Привет! Это бот для подготовки к экзаменам. Выбери предмет:",
        reply_markup=kb.subjects_kb(db.list_subjects(conn)),
    )


@router.callback_query(F.data == "menu:subjects")
async def cb_subjects(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer(
        "Выбери предмет:", reply_markup=kb.subjects_kb(db.list_subjects(conn))
    )
    await cq.answer()


@router.callback_query(F.data.startswith("subj:"))
async def cb_pick_subject(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    code = cq.data.split(":", 1)[1]
    db.set_active_subject(conn, cq.from_user.id, code)
    await show_menu(cq.message, cq.from_user.id)
    await cq.answer()


@router.callback_query(F.data == "menu:main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_menu(cq.message, cq.from_user.id)
    await cq.answer()


async def show_menu(message: Message, tg_id: int):
    code = active_subject(tg_id)
    if not code:
        await message.answer(
            "Сначала выбери предмет:", reply_markup=kb.subjects_kb(db.list_subjects(conn))
        )
        return
    subj = conn.execute("SELECT name FROM subjects WHERE code=?", (code,)).fetchone()
    due = db.due_count(conn, tg_id, code)
    await message.answer(
        f"📕 <b>{subj['name']}</b>\nЧто делаем?",
        reply_markup=kb.main_menu_kb(subj["name"], due),
    )


# ---------- режим карточек ----------

async def send_card(message: Message, tg_id: int, mode: str):
    code = active_subject(tg_id)
    pick_mode = "weak" if mode == "weak" else "smart"
    card = db.pick_next_card(conn, tg_id, code, pick_mode)
    if not card:
        await message.answer(
            "На сегодня всё повторено 🎉", reply_markup=kb.back_kb()
        )
        return
    await message.answer(
        f"🃏 <b>Билет №{card['number']}</b>\n\n{card['title']}\n\n"
        "Вспомни ответ и открой проверку.",
        reply_markup=kb.show_answer_kb(card["id"]),
    )


@router.callback_query(F.data.in_({"mode:study", "mode:weak"}))
async def cb_mode_card(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    mode = "weak" if cq.data == "mode:weak" else "study"
    await send_card(cq.message, cq.from_user.id, mode)
    await cq.answer()


@router.callback_query(F.data.startswith("show:"))
async def cb_show(cq: CallbackQuery):
    card_id = int(cq.data.split(":")[1])
    card = db.get_card(conn, card_id)
    if not card:
        await cq.answer("Билет не найден", show_alert=True)
        return
    ref = card["reference"] or "⚠️ В материале билета нет текста (вероятно, схема-картинка). Добавь его вручную."
    await send_long(cq.message, f"📖 <b>Ответ (билет №{card['number']}):</b>\n\n{ref}")
    await cq.message.answer(
        "Как ты знала этот билет?", reply_markup=kb.rating_kb(card_id)
    )
    await cq.answer()


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(cq: CallbackQuery):
    _, card_id_s, rating = cq.data.split(":")
    card_id = int(card_id_s)
    tg_id = cq.from_user.id

    st = db.get_state(conn, tg_id, card_id)
    st = srs_update(st, rating)
    db.save_state(conn, tg_id, card_id, st)
    db.log_review(conn, tg_id, card_id, "card", rating)

    # на «частично» и «не знал» — объяснение от ИИ, строго по материалу
    if rating in ("again", "partial"):
        card = db.get_card(conn, card_id)
        if card["reference"]:
            await cq.answer("Разбираю тему…")
            explanation = db.get_explanation(conn, card_id)
            if not explanation:
                try:
                    explanation = await ai.explain(card["title"], card["reference"])
                    db.save_explanation(conn, card_id, explanation)
                except Exception as e:
                    logging.exception("AI explain failed")
                    explanation = f"(Не удалось получить объяснение: {e})"
            await send_long(cq.message, f"💡 <b>Разбор:</b>\n\n{explanation}")
    else:
        await cq.answer("Отлично!")

    nxt = "weak" if st.last_rating == "again" else "study"
    await cq.message.answer(
        f"⏭ Следующее повторение через {st.interval} дн.",
        reply_markup=kb.next_kb(nxt),
    )


@router.callback_query(F.data.startswith("next:"))
async def cb_next(cq: CallbackQuery, state: FSMContext):
    mode = cq.data.split(":")[1]
    if mode == "quiz":
        await send_quiz(cq.message, cq.from_user.id, state)
    else:
        await send_card(cq.message, cq.from_user.id, mode)
    await cq.answer()


# ---------- режим «Вопрос от ИИ» ----------

async def send_quiz(message: Message, tg_id: int, state: FSMContext,
                    target_card_id: int | None = None,
                    exclude_card_id: int | None = None):
    code = active_subject(tg_id)
    if target_card_id:
        card = db.get_card(conn, target_card_id)
    elif exclude_card_id:
        # «следующий билет» — берём другой билет с текстом
        card = db.random_card(conn, code, exclude_id=exclude_card_id)
    else:
        card = db.pick_next_card(conn, tg_id, code, "smart")
        if not card or not card["reference"]:
            card = db.random_card(conn, code)
    if not card or not card["reference"]:
        await message.answer("Нет доступного материала для вопроса.",
                             reply_markup=kb.back_kb())
        return

    import random
    data = await state.get_data()
    asked_map = data.get("asked_map", {})
    key = str(card["id"])
    asked = asked_map.get(key, [])

    cached = [r["question"] for r in db.get_cached_questions(conn, card["id"])]
    pool = [q for q in cached if q not in asked]

    # если незаданных вопросов не осталось — догенерируем новые (не повторяя)
    if not pool:
        await message.answer("Готовлю новый вопрос…")
        try:
            new_qs = await ai.generate_questions(
                card["title"], card["reference"], n=5, avoid=asked or cached
            )
        except Exception as e:
            logging.exception("AI question gen failed")
            await message.answer(f"Не удалось сгенерировать вопрос: {e}",
                                reply_markup=kb.back_kb())
            return
        for q in new_qs:
            if q not in cached:
                db.save_question(conn, card["id"], q)
        cached = [r["question"] for r in db.get_cached_questions(conn, card["id"])]
        pool = [q for q in cached if q not in asked]

    # крайний случай: все варианты исчерпаны — начинаем круг заново
    if not pool:
        asked = []
        pool = cached
    if not pool:
        await message.answer("Не удалось составить вопрос по этому билету.",
                            reply_markup=kb.back_kb())
        return

    question = random.choice(pool)
    asked.append(question)
    asked_map[key] = asked

    await state.set_state(Flow.answering)
    await state.update_data(card_id=card["id"], question=question,
                            asked_map=asked_map)
    await message.answer(
        f"✍️ <b>Билет №{card['number']}. Вопрос:</b>\n\n{question}\n\n"
        "Напиши ответ текстом.",
    )


@router.callback_query(F.data == "mode:quiz")
async def cb_mode_quiz(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_quiz(cq.message, cq.from_user.id, state)
    await cq.answer()


@router.message(Flow.answering)
async def on_answer(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Ответь, пожалуйста, текстом.")
        return
    data = await state.get_data()
    card_id = data.get("card_id")
    question = data.get("question")
    card = db.get_card(conn, card_id)
    if not card:
        await state.clear()
        await message.answer("Что-то пошло не так, вернись в меню.",
                            reply_markup=kb.back_kb())
        return

    await message.answer("Проверяю ответ…")
    try:
        result = await ai.check_answer(
            card["title"], card["reference"], question, message.text
        )
    except Exception as e:
        logging.exception("AI check failed")
        await message.answer(f"Не удалось проверить ответ: {e}",
                            reply_markup=kb.back_kb())
        return

    verdict = result["verdict"]
    rating = VERDICT_TO_RATING.get(verdict, "partial")
    st = db.get_state(conn, message.from_user.id, card_id)
    st = srs_update(st, rating)
    db.save_state(conn, message.from_user.id, card_id, st)
    db.log_review(conn, message.from_user.id, card_id, "quiz", rating)

    head = VERDICT_EMOJI.get(verdict, "🟡 Частично")
    await state.set_state(None)  # выходим из режима ответа, но помним asked_map
    await send_long(
        message,
        f"{head}\n\n{result['feedback']}\n\n"
        f"⏭ Следующее повторение через {st.interval} дн.",
        reply_markup=kb.quiz_after_kb(card_id),
    )


@router.callback_query(F.data.startswith("quizcard:"))
async def cb_quizcard(cq: CallbackQuery, state: FSMContext):
    """Ещё один вопрос по этому же билету."""
    await state.set_state(None)  # сохраняем историю заданных вопросов
    card_id = int(cq.data.split(":")[1])
    await send_quiz(cq.message, cq.from_user.id, state, target_card_id=card_id)
    await cq.answer()


@router.callback_query(F.data.startswith("quiznext:"))
async def cb_quiznext(cq: CallbackQuery, state: FSMContext):
    """Перейти к вопросу по другому билету."""
    await state.set_state(None)
    card_id = int(cq.data.split(":")[1])
    await send_quiz(cq.message, cq.from_user.id, state, exclude_card_id=card_id)
    await cq.answer()


# ---------- выбор конкретного билета ----------

PER_PAGE = 8


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(cq.data.split(":")[1])
    code = active_subject(cq.from_user.id)
    if not code:
        await cq.answer()
        return
    total = db.count_cards(conn, code)
    cards = db.list_cards(conn, code, PER_PAGE, page * PER_PAGE)
    await cq.message.answer(
        "🔎 Выбери билет:",
        reply_markup=kb.tickets_list_kb(cards, page, total, PER_PAGE),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("pickcard:"))
async def cb_pickcard(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    card_id = int(cq.data.split(":")[1])
    card = db.get_card(conn, card_id)
    if not card:
        await cq.answer("Билет не найден", show_alert=True)
        return
    await cq.message.answer(
        f"🎫 <b>Билет №{card['number']}</b>\n\n{card['title']}\n\nЧто сделать?",
        reply_markup=kb.ticket_actions_kb(card_id),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("cardshow:"))
async def cb_cardshow(cq: CallbackQuery, state: FSMContext):
    """Показать выбранный билет как карточку (с самооценкой)."""
    await state.clear()
    card_id = int(cq.data.split(":")[1])
    card = db.get_card(conn, card_id)
    if not card:
        await cq.answer("Билет не найден", show_alert=True)
        return
    await cq.message.answer(
        f"🃏 <b>Билет №{card['number']}</b>\n\n{card['title']}\n\n"
        "Вспомни ответ и открой проверку.",
        reply_markup=kb.show_answer_kb(card_id),
    )
    await cq.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cq: CallbackQuery):
    await cq.answer()


# ---------- статистика ----------

@router.callback_query(F.data == "menu:stats")
async def cb_stats(cq: CallbackQuery):
    tg_id = cq.from_user.id
    code = active_subject(tg_id)
    if not code:
        await cq.answer()
        return
    s = db.stats(conn, tg_id, code)
    st_streak = db.streak(conn, tg_id)
    u = db.get_user(conn, tg_id)

    lines = [
        f"📊 <b>Статистика</b>",
        f"Готовность: <b>{s['readiness']}%</b>  ({s['strong']} из {s['total']} освоено)",
        "",
        f"🟢 Уверенно знает: {s['strong']}",
        f"🟡 В процессе: {s['learning']}",
        f"🔴 Слабые: {s['weak']}",
        f"⚪️ Не начаты: {s['new']}",
        f"🔥 Дней подряд: {st_streak}",
    ]
    if u and u["exam_date"]:
        try:
            d = (date.fromisoformat(u["exam_date"]) - date.today()).days
            lines.append(f"📅 До экзамена: {d} дн.")
        except ValueError:
            pass
    if s["weak_list"]:
        lines.append("\n<b>Повторить в первую очередь:</b>")
        for num, title in s["weak_list"]:
            lines.append(f"• №{num} — {title[:60]}")

    await cq.message.answer("\n".join(lines), reply_markup=kb.back_kb())
    await cq.answer()


# ---------- настройки: напоминание и дата экзамена ----------

@router.callback_query(F.data == "menu:settings")
async def cb_settings(cq: CallbackQuery, state: FSMContext):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⏰ Час напоминания", callback_data="set:reminder")
    b.button(text="📅 Дата экзамена", callback_data="set:exam")
    b.button(text="⬅️ В меню", callback_data="menu:main")
    b.adjust(1)
    await cq.message.answer("Настройки:", reply_markup=b.as_markup())
    await cq.answer()


@router.callback_query(F.data == "set:reminder")
async def cb_set_reminder(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.set_reminder)
    await cq.message.answer("Во сколько напоминать? Напиши час 0–23 (например, 19).")
    await cq.answer()


@router.message(Flow.set_reminder)
async def on_set_reminder(message: Message, state: FSMContext):
    try:
        hour = int(message.text.strip())
        assert 0 <= hour <= 23
    except (ValueError, AssertionError):
        await message.answer("Нужно число от 0 до 23. Попробуй ещё раз.")
        return
    db.set_reminder_hour(conn, message.from_user.id, hour)
    await state.clear()
    await message.answer(f"Готово, буду напоминать в {hour}:00.",
                        reply_markup=kb.back_kb())


@router.callback_query(F.data == "set:exam")
async def cb_set_exam(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.set_exam)
    await cq.message.answer("Дата экзамена в формате ГГГГ-ММ-ДД (например, 2026-06-15).")
    await cq.answer()


@router.message(Flow.set_exam)
async def on_set_exam(message: Message, state: FSMContext):
    try:
        d = date.fromisoformat(message.text.strip())
    except ValueError:
        await message.answer("Формат ГГГГ-ММ-ДД. Попробуй ещё раз.")
        return
    db.set_exam_date(conn, message.from_user.id, d.isoformat())
    await state.clear()
    await message.answer(f"Дата экзамена сохранена: {d.isoformat()}.",
                        reply_markup=kb.back_kb())


# ---------- фоновые напоминания ----------

async def reminder_loop(bot: Bot):
    """Раз в 30 минут проверяет, кому пора напомнить в текущий час."""
    sent_today = {}  # tg_id -> дата последнего напоминания
    while True:
        now = datetime.now()
        rows = conn.execute(
            "SELECT tg_id, active_subject, reminder_hour FROM users "
            "WHERE reminder_hour IS NOT NULL"
        ).fetchall()
        for r in rows:
            if r["reminder_hour"] != now.hour or not r["active_subject"]:
                continue
            if sent_today.get(r["tg_id"]) == now.date():
                continue
            due = db.due_count(conn, r["tg_id"], r["active_subject"])
            if due > 0:
                try:
                    await bot.send_message(
                        r["tg_id"],
                        f"⏰ Пора повторить: на сегодня {due} билетов. /start",
                    )
                    sent_today[r["tg_id"]] = now.date()
                except Exception:
                    logging.exception("reminder send failed")
        await asyncio.sleep(1800)


async def main():
    db.load_all_data(conn, config.DATA_DIR)
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(reminder_loop(bot))
    logging.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
