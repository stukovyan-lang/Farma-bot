"""
parse_docx.py — превращает docx со «шпорами» в чистый JSON билетов.

Материал грязный: жирным выделены и заголовки билетов, и подпункты внутри,
номера местами сбиты. Ключевая эвристика — МОНОТОННОСТЬ номеров билетов:
настоящие билеты идут 1, 2, 3, ... и не сбрасываются, а подпункты внутри
билета сбрасываются (1, 2, 3 снова). Поэтому кандидат в заголовки
принимается, только если его номер идёт сразу за предыдущим принятым
(с небольшим допуском на пропущенные номера).

Использование:
    python parse_docx.py <файл.docx> <subject_code> <Название предмета> > data/<code>.json

Требует установленного pandoc.
"""
import json
import re
import subprocess
import sys


def docx_to_markdown(path: str) -> str:
    out = subprocess.run(
        ["pandoc", "-t", "markdown", path],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


# Кандидаты в заголовки билета:
#   **25. Заголовок**      -> bold
#   25. Заголовок          -> plain
#   **32**. Заголовок      -> число жирным, точка снаружи
HEADER_PATTERNS = [
    re.compile(r"^\*\*(\d+)\*\*\.?\s*(.*)$"),      # **32**. ...
    re.compile(r"^\*\*(\d+)[\.\)]\s*(.*?)\*?\*?$"),  # **25. ...
    re.compile(r"^(\d+)[\.\)]\s*(.*)$"),           # 25.  ...  или  12.Текст
]


def match_header(line: str):
    """Вернуть (номер, хвост заголовка) если строка похожа на заголовок билета."""
    s = line.strip()
    for pat in HEADER_PATTERNS:
        m = pat.match(s)
        if m:
            return int(m.group(1)), m.group(2).strip()
    return None


def clean_text(text: str) -> str:
    """Убрать pandoc-разметку, оставив читаемый текст."""
    t = text
    t = re.sub(r"\[([^\]]*)\]\{\.[a-z]+\}", r"\1", t)   # [x]{.underline} / [x]{.mark}
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", t)  # *курсив*
    t = re.sub(r"^\s*>\s?", "", t, flags=re.MULTILINE)   # цитатные >
    t = t.replace("\\", "")                               # экранирование pandoc
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def clean_title(title: str) -> str:
    t = clean_text(title)
    t = t.replace(" > ", " ").replace(">", " ")
    t = re.sub(r"\s+", " ", t)
    t = t.strip().strip('"').strip("'")
    t = t.rstrip(":. ").strip()
    return t


def find_sublist_lines(cands, max_gap: int = 8):
    """Определить строки, входящие в «плотные» нумерованные списки.

    Подпункты внутри билета (1. …, 2. …, 3. …) идут тесно — по несколько
    строк друг от друга. Настоящие билеты разнесены на десятки строк.
    Помечаем как список любой прогон из >=3 подряд идущих номеров, где
    соседи ближе max_gap строк, а нумерация растёт на 1–2 и стартует с <=2.
    """
    sub = set()
    i, n = 0, len(cands)
    while i < n:
        j = i
        while (j + 1 < n
               and cands[j + 1][0] - cands[j][0] <= max_gap
               and cands[j + 1][1] - cands[j][1] in (1, 2)):
            j += 1
        if (j - i + 1) >= 3 and cands[i][1] <= 2:
            for k in range(i, j + 1):
                sub.add(cands[k][0])
        i = j + 1
    return sub


def parse(markdown: str, max_jump: int = 40):
    """Разбить markdown на билеты.

    Правило: номер настоящего билета СТРОГО БОЛЬШЕ предыдущего принятого.
    Вложенные списки (реакции, шаги) отсекаются двумя способами: по строчной
    первой букве и по «плотности» (детектор find_sublist_lines).
    max_jump страхует от случайных больших чисел в тексте.
    """
    lines = markdown.splitlines()

    # предварительно собираем кандидаты. Для детектора плотных списков берём
    # только НЕ-жирные пункты: подпункты в шпорах идут обычным текстом, а
    # заголовки билетов — жирные, их нельзя случайно склеить в «список».
    raw_plain = []
    for i, line in enumerate(lines):
        s = line.strip()
        hit = match_header(line)
        if hit and not s.startswith("**"):
            raw_plain.append((i, hit[0]))
    sublist_lines = find_sublist_lines(raw_plain)

    # 1) находим индексы строк, принятых как заголовки билетов
    starts = []  # (line_index, number, tail)
    last_num = 0
    for i, line in enumerate(lines):
        if i in sublist_lines:
            continue
        hit = match_header(line)
        if not hit:
            continue
        num, tail = hit
        if num <= last_num or num > last_num + max_jump:
            continue
        # хвост должен быть содержательным (не пустой, начинается с буквы)
        if not tail or not re.search(r"[A-Za-zА-Яа-яЁё]", tail[:30]):
            # допускаем пустой хвост только если следующая строка — текст
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if not re.search(r"[A-Za-zА-Яа-яЁё]", nxt[:30]):
                continue
        # настоящий заголовок билета начинается с ЗАГЛАВНОЙ буквы;
        # подпункты-реакции идут со строчной ("с NaOH", "с винной кислотой")
        first_alpha = next((c for c in clean_text(tail) if c.isalpha()), "")
        if first_alpha and first_alpha.islower():
            continue
        starts.append((i, num, tail))
        last_num = num

    # 2) режем документ на блоки и делим каждый на заголовок + тело
    result = []
    for idx, (line_i, num, tail) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        block = lines[line_i + 1:end_i]

        # заголовок = хвост первой строки + продолжение до пустой строки (<=300 симв.)
        title_parts = [tail] if tail else []
        body_start = 0
        for j, bl in enumerate(block):
            if bl.strip() == "":
                body_start = j + 1
                break
            title_parts.append(bl)
            if sum(len(p) for p in title_parts) > 300:
                body_start = j + 1
                break
        else:
            body_start = len(block)

        title = clean_title(" ".join(title_parts))
        body = clean_text("\n".join(block[body_start:]))
        if not title:
            title = (body.split("\n", 1)[0][:120]).strip()
        result.append({"number": num, "title": title, "reference": body})
    return result


def main():
    if len(sys.argv) < 4:
        print("usage: python parse_docx.py <file.docx> <subject_code> <Subject name>",
              file=sys.stderr)
        sys.exit(1)
    path, code, name = sys.argv[1], sys.argv[2], " ".join(sys.argv[3:])
    md = docx_to_markdown(path)
    tickets = parse(md)
    payload = {"subject_code": code, "subject_name": name, "tickets": tickets}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # диагностика в stderr, чтобы не портить json
    nums = [t["number"] for t in tickets]
    print(f"[parsed] {len(tickets)} билетов, номера {min(nums)}..{max(nums)}",
          file=sys.stderr)
    missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
    if missing:
        print(f"[gaps] пропущены номера: {missing}", file=sys.stderr)
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    if dupes:
        print(f"[dupes] дублируются номера: {dupes}", file=sys.stderr)


if __name__ == "__main__":
    main()
