"""keyboards.py — все встроенные кнопки (inline-клавиатуры)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def subjects_kb(subjects) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in subjects:
        kb.button(text=f"📕 {s['name']}", callback_data=f"subj:{s['code']}")
    kb.adjust(1)
    return kb.as_markup()


def main_menu_kb(subject_name: str, due: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"📚 Учить карточки ({due} на сегодня)", callback_data="mode:study")
    kb.button(text="✍️ Вопрос от ИИ", callback_data="mode:quiz")
    kb.button(text="🔀 Только слабые", callback_data="mode:weak")
    kb.button(text="🔎 Выбрать билет", callback_data="pick:0")
    kb.button(text="📊 Статистика", callback_data="menu:stats")
    kb.button(text="🔄 Сменить предмет", callback_data="menu:subjects")
    kb.button(text="⚙️ Напоминание и дата экзамена", callback_data="menu:settings")
    kb.adjust(1)
    return kb.as_markup()


def show_answer_kb(card_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👀 Показать ответ", callback_data=f"show:{card_id}")
    kb.button(text="⬅️ В меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def rating_kb(card_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Знал", callback_data=f"rate:{card_id}:good")
    kb.button(text="🟡 Частично", callback_data=f"rate:{card_id}:partial")
    kb.button(text="❌ Не знал", callback_data=f"rate:{card_id}:again")
    kb.adjust(3)
    return kb.as_markup()


def next_kb(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    label = "➡️ Следующий вопрос" if mode == "quiz" else "➡️ Следующий билет"
    kb.button(text=label, callback_data=f"next:{mode}")
    kb.button(text="⬅️ В меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def quiz_after_kb(card_id: int) -> InlineKeyboardMarkup:
    """Кнопки после ответа в режиме «Вопрос от ИИ»."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Ещё вопрос по этому билету", callback_data=f"quizcard:{card_id}")
    kb.button(text="➡️ Перейти к следующему билету", callback_data=f"quiznext:{card_id}")
    kb.button(text="⬅️ В меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def tickets_list_kb(cards, page: int, total: int, per_page: int) -> InlineKeyboardMarkup:
    """Экран выбора билета с листанием."""
    kb = InlineKeyboardBuilder()
    for c in cards:
        title = c["title"][:32] + ("…" if len(c["title"]) > 32 else "")
        kb.button(text=f"№{c['number']} · {title}", callback_data=f"pickcard:{c['id']}")
    kb.adjust(1)
    # ряд навигации
    nav = []
    last_page = max(0, (total - 1) // per_page)
    if page > 0:
        nav.append(InlineKeyboardButton(text="‹ Назад", callback_data=f"pick:{page-1}"))
    nav.append(InlineKeyboardButton(
        text=f"{page+1}/{last_page+1}", callback_data="noop"))
    if page < last_page:
        nav.append(InlineKeyboardButton(text="Далее ›", callback_data=f"pick:{page+1}"))
    kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main"))
    return kb.as_markup()


def ticket_actions_kb(card_id: int) -> InlineKeyboardMarkup:
    """Что сделать с выбранным билетом."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Показать карточку", callback_data=f"cardshow:{card_id}")
    kb.button(text="✍️ Вопрос по этому билету", callback_data=f"quizcard:{card_id}")
    kb.button(text="🔎 К списку билетов", callback_data="pick:0")
    kb.button(text="⬅️ В меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")]
    ])
