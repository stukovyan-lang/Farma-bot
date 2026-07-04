"""
srs.py — интервальное повторение по упрощённому алгоритму SM-2 (как в Anki).

Оценки из обоих режимов (карточки и вопросы ИИ) сводятся к одной шкале:
    "good"    (Знал / ответ верный)      -> quality 5
    "partial" (Частично / неполный)      -> quality 3
    "again"   (Не знал / ответ неверный) -> quality 1

Состояние карточки: ease (лёгкость), interval (дней до след. показа),
reps (успешных повторений подряд), lapses (сколько раз «провалил»).
"""
from dataclasses import dataclass
from datetime import date, timedelta

QUALITY = {"good": 5, "partial": 3, "again": 1}

MIN_EASE = 1.3
DEFAULT_EASE = 2.5


@dataclass
class CardState:
    ease: float = DEFAULT_EASE
    interval: int = 0
    reps: int = 0
    lapses: int = 0
    due_date: str = ""          # ISO YYYY-MM-DD
    last_rating: str = ""


def update(state: CardState, rating: str, today: date | None = None) -> CardState:
    """Пересчитать состояние карточки после ответа."""
    today = today or date.today()
    q = QUALITY.get(rating, 3)

    if q < 3:
        # провал — повторяем завтра, лёгкость чуть падает
        state.reps = 0
        state.lapses += 1
        state.interval = 1
    else:
        if state.reps == 0:
            state.interval = 1
        elif state.reps == 1:
            state.interval = 3
        else:
            state.interval = max(1, round(state.interval * state.ease))
        state.reps += 1
        if q == 3:
            # частично — интервал растёт медленнее
            state.interval = max(1, round(state.interval * 0.6))

    # корректировка лёгкости по формуле SM-2
    state.ease = max(
        MIN_EASE,
        state.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)),
    )
    state.due_date = (today + timedelta(days=state.interval)).isoformat()
    state.last_rating = rating
    return state


def strength(state: CardState) -> str:
    """Категория «силы» карточки для статистики."""
    if state.reps == 0 and not state.last_rating:
        return "new"
    if state.last_rating == "again" or state.lapses >= 2 and state.interval <= 2:
        return "weak"
    if state.interval >= 14 and state.last_rating == "good":
        return "strong"
    return "learning"
