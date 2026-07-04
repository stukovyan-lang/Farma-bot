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


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")]
    ])
