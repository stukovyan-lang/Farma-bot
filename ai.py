"""
ai.py — обращения к OpenAI API, ЖЁСТКО привязанные к материалу билета.

Главное правило: любой ответ ИИ строится ТОЛЬКО на переданном эталонном
тексте билета (reference). Модели прямо запрещено добавлять факты из общих
знаний — если чего-то нет в материале, она это проговаривает, а не выдумывает.
Это критично для фармы/химии, где неточность в реакции или дозе недопустима.
"""
import json

from openai import AsyncOpenAI

import config

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

GROUNDING = (
    "Ты — помощник для подготовки к экзамену. Ты работаешь СТРОГО в рамках "
    "предоставленного учебного материала (эталонного текста билета). "
    "Категорически запрещено добавлять факты, формулы, реакции или цифры, "
    "которых нет в материале. Если в материале чего-то нет — прямо напиши "
    "«в материале билета это не раскрыто» и не додумывай. Отвечай по-русски, "
    "кратко и по делу."
)


async def _chat(system: str, user: str, max_tokens: int = 700,
                json_mode: bool = False, temperature: float = 0.3) -> str:
    kwargs = dict(
        model=config.AI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


async def explain(title: str, reference: str) -> str:
    """Развёрнутое объяснение билета для режима «Не знал»/«Частично»."""
    prompt = (
        f"Материал билета «{title}»:\n\n{reference}\n\n"
        "Объясни эту тему так, чтобы её было легко запомнить: выдели суть, "
        "ключевые термины и на чём чаще всего путаются. Только на основе "
        "материала выше. 4–8 предложений."
    )
    return await _chat(GROUNDING, prompt, max_tokens=700)


async def generate_questions(title: str, reference: str, n: int = 5,
                             avoid: list[str] | None = None) -> list[str]:
    """Сгенерировать n РАЗНЫХ проверочных вопросов по материалу билета."""
    avoid_block = ""
    if avoid:
        joined = "\n".join(f"- {q}" for q in avoid[:12])
        avoid_block = (
            "\n\nНЕ повторяй по смыслу эти уже заданные вопросы "
            f"(придумай про другое):\n{joined}"
        )
    prompt = (
        f"Материал билета «{title}»:\n\n{reference}\n\n"
        f"Составь {n} РАЗНЫХ проверочных вопроса по этому материалу. "
        "Вопросы должны затрагивать разные части материала и разные аспекты "
        "(определение, классификация, свойства, применение, условия, отличия) — "
        "не дублируй одну и ту же мысль разными словами. На каждый вопрос ответ "
        "ДОЛЖЕН однозначно содержаться в материале выше." + avoid_block +
        '\n\nВерни JSON вида {"questions": ["вопрос 1", "вопрос 2", ...]}.'
    )
    raw = await _chat(GROUNDING, prompt, max_tokens=700, json_mode=True,
                      temperature=0.8)
    try:
        data = json.loads(raw)
        qs = data.get("questions", []) if isinstance(data, dict) else data
        return [str(q).strip() for q in qs if str(q).strip()][:n]
    except (json.JSONDecodeError, TypeError, AttributeError):
        return [l.strip(" -*0123456789.") for l in raw.splitlines() if "?" in l][:n]


async def check_answer(title: str, reference: str, question: str, answer: str) -> dict:
    """
    Проверить ответ пользователя по материалу.
    Возвращает {"verdict": "correct|partial|incorrect", "feedback": "..."}.
    """
    prompt = (
        f"Материал билета «{title}»:\n\n{reference}\n\n"
        f"Вопрос: {question}\n"
        f"Ответ студента: {answer}\n\n"
        "Оцени ответ ТОЛЬКО по материалу выше. Если суть верна, но термин или "
        "формулировка неточны — это 'partial', прямо укажи неточность. "
        'Верни JSON: {"verdict":"correct|partial|incorrect","feedback":"краткое '
        "пояснение по-русски: что верно, что упущено или неверно; при ошибке — "
        'как правильно по материалу"}.'
    )
    raw = await _chat(GROUNDING, prompt, max_tokens=600, json_mode=True)
    try:
        data = json.loads(raw)
        verdict = data.get("verdict", "partial")
        if verdict not in ("correct", "partial", "incorrect"):
            verdict = "partial"
        return {"verdict": verdict, "feedback": str(data.get("feedback", "")).strip()}
    except (json.JSONDecodeError, TypeError, AttributeError):
        return {"verdict": "partial", "feedback": raw[:800]}
