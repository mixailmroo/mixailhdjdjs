"""
Генерирует карточку боя в стиле UFC — два бойца на тёмном фоне,
статистика по центру, кэфы и рекорды.
"""
import asyncio
import aiohttp
import io
from PIL import Image, ImageDraw, ImageFont, ImageOps
from typing import Optional

CARD_W, CARD_H = 900, 520

# Цвета
BG         = (15, 15, 20)
BG_STATS   = (22, 22, 30)
RED        = (220, 35, 35)
BLUE       = (35, 80, 210)
GOLD       = (212, 160, 30)
WHITE      = (255, 255, 255)
LIGHT_GRAY = (190, 190, 200)
MID_GRAY   = (120, 120, 135)
DARK_LINE  = (40, 40, 55)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    paths_reg = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in (paths_bold if bold else paths_reg):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


async def fetch_image(url: str) -> Optional[Image.Image]:
    if not url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers,
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return None
                return Image.open(io.BytesIO(await r.read())).convert("RGBA")
    except Exception:
        return None


def make_fighter_panel(img: Optional[Image.Image], color: tuple,
                        letter: str, w: int, h: int, flip: bool = False) -> Image.Image:
    """Создаёт панель с фото бойца или заглушкой."""
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if img:
        src = img.copy()
        if flip:
            src = src.transpose(Image.FLIP_LEFT_RIGHT)

        # Масштаб чтобы заполнить панель по высоте
        ratio = h / src.height
        nw = int(src.width * ratio)
        src = src.resize((nw, h), Image.LANCZOS)

        # Кроп по центру
        lft = max(0, (nw - w) // 2)
        src = src.crop((lft, 0, lft + w, h))

        # Градиентная маска — прозрачно по бокам и снизу
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        # Вертикальный градиент (снизу fade)
        for y in range(h):
            a = int(255 * min(1.0, (y / h) ** 0.6))
            md.line([(0, y), (w, y)], fill=a)
        # Горизонтальный fade с нужной стороны
        for x in range(w):
            ratio_x = x / w if not flip else (w - x) / w
            fade = int(255 * min(1.0, ratio_x * 2.5))
            for y in range(h):
                cur = mask.getpixel((x, y))
                mask.putpixel((x, y), min(cur, fade))

        if src.mode != "RGBA":
            src = src.convert("RGBA")
        src.putalpha(mask)
        panel.paste(src, (0, 0), src)
    else:
        # Заглушка
        d = ImageDraw.Draw(panel)
        d.rectangle([0, 0, w - 1, h - 1], fill=(*color[:3], 30))
        f = font(80, bold=True)
        d.text((w // 2, h // 2), letter.upper(), font=f,
               fill=(*color[:3], 80), anchor="mm")

    return panel


def centered_text(draw, cx, y, text, fnt, color, anchor="mm"):
    draw.text((cx, y), text, font=fnt, fill=color, anchor=anchor)


def stat_row(draw, y, label, v1, v2, cx, fnt_val, fnt_lbl):
    """Строка статы: v1  |  LABEL  |  v2"""
    pad = 90
    draw.text((cx - pad, y), str(v1), font=fnt_val, fill=WHITE, anchor="rm")
    draw.text((cx, y), label, font=fnt_lbl, fill=MID_GRAY, anchor="mm")
    draw.text((cx + pad, y), str(v2), font=fnt_val, fill=WHITE, anchor="lm")


async def generate_fight_card(
    fighter1: str, fighter2: str,
    photo1_url: Optional[str], photo2_url: Optional[str],
    stats1: dict, stats2: dict,
    odds1: Optional[float], odds2: Optional[float],
    weight_class: str = "",
) -> bytes:

    # Грузим фото параллельно
    img1, img2 = await asyncio.gather(
        fetch_image(photo1_url),
        fetch_image(photo2_url),
    )

    canvas = Image.new("RGB", (CARD_W, CARD_H), BG)

    # ── Фоновые панели бойцов ──
    panel_w = 340
    panel_h = CARD_H

    p1 = make_fighter_panel(img1, RED, fighter1[0], panel_w, panel_h, flip=False)
    p2 = make_fighter_panel(img2, BLUE, fighter2[0], panel_w, panel_h, flip=True)

    canvas.paste(p1.convert("RGB"), (0, 0), p1.split()[3])
    canvas.paste(p2.convert("RGB"), (CARD_W - panel_w, 0), p2.split()[3])

    draw = ImageDraw.Draw(canvas)

    # ── Боковые цветные полосы ──
    draw.rectangle([0, 0, 5, CARD_H], fill=RED)
    draw.rectangle([CARD_W - 5, 0, CARD_W, CARD_H], fill=BLUE)

    # ── Центральная колонка ──
    cx = CARD_W // 2
    stats_x1 = 310   # левый край центрального блока
    stats_x2 = CARD_W - 310

    # Тёмный фон центра
    draw.rectangle([stats_x1, 0, stats_x2, CARD_H], fill=BG_STATS)

    # ── VS + весовая ──
    f_vs   = font(26, bold=True)
    f_wc   = font(11)
    f_name = font(14, bold=True)
    f_rec  = font(12)
    f_odds = font(15, bold=True)
    f_val  = font(12, bold=True)
    f_lbl  = font(10)
    f_hdr  = font(9)

    draw.text((cx, 28), "VS", font=f_vs, fill=GOLD, anchor="mm")
    if weight_class:
        draw.text((cx, 54), weight_class.upper(), font=f_wc, fill=MID_GRAY, anchor="mm")

    # ── Имена ──
    name1 = fighter1.upper()
    name2 = fighter2.upper()
    # Разбиваем на строки если длинное
    def split_name(n):
        p = n.split()
        if len(p) >= 2:
            return p[0], " ".join(p[1:])
        return n, ""

    n1a, n1b = split_name(name1)
    n2a, n2b = split_name(name2)

    draw.text((cx, 78), n1a, font=f_name, fill=RED, anchor="mm")
    if n1b:
        draw.text((cx, 96), n1b, font=f_name, fill=WHITE, anchor="mm")

    # Разделитель
    draw.line([(stats_x1 + 10, 112), (stats_x2 - 10, 112)], fill=DARK_LINE, width=1)

    draw.text((cx, 128), n2a, font=f_name, fill=BLUE, anchor="mm")
    if n2b:
        draw.text((cx, 146), n2b, font=f_name, fill=WHITE, anchor="mm")

    # ── Рекорды ──
    rec1 = f"{stats1.get('wins','?')}-{stats1.get('losses','?')}-{stats1.get('draws','?')}"
    rec2 = f"{stats2.get('wins','?')}-{stats2.get('losses','?')}-{stats2.get('draws','?')}"

    draw.line([(stats_x1 + 10, 164), (stats_x2 - 10, 164)], fill=DARK_LINE, width=1)
    stat_row(draw, 178, "РЕКОРД", rec1, rec2, cx, f_rec, f_lbl)

    # ── Коэффициенты ──
    o1_str = f"{odds1:.2f}" if odds1 else "—"
    o2_str = f"{odds2:.2f}" if odds2 else "—"
    draw.line([(stats_x1 + 10, 196), (stats_x2 - 10, 196)], fill=DARK_LINE, width=1)
    stat_row(draw, 212, "КОЭФ", o1_str, o2_str, cx, f_odds, f_lbl)

    # ── Статистика ──
    draw.line([(stats_x1 + 10, 230), (stats_x2 - 10, 230)], fill=DARK_LINE, width=1)
    draw.text((cx, 244), "СТАТИСТИКА", font=f_hdr, fill=MID_GRAY, anchor="mm")

    rows = [
        ("ВОЗРАСТ",     stats1.get("age", "—"),      stats2.get("age", "—")),
        ("ВЕС",         stats1.get("weight", "—"),   stats2.get("weight", "—")),
        ("РОСТ",        stats1.get("height", "—"),   stats2.get("height", "—")),
        ("РАЗМАХ РУК",  stats1.get("reach", "—"),    stats2.get("reach", "—")),
        ("СТОЙКА",      stats1.get("stance", "—"),   stats2.get("stance", "—")),
        ("УД/МИН",      stats1.get("slpm", "—"),     stats2.get("slpm", "—")),
        ("ТОЧНОСТЬ %",  stats1.get("str._acc.", "—"), stats2.get("str._acc.", "—")),
        ("ТД/15МИН",    stats1.get("td_avg.", "—"),  stats2.get("td_avg.", "—")),
    ]

    y = 264
    for label, v1, v2 in rows:
        if str(v1) in ("—", "", "None") and str(v2) in ("—", "", "None"):
            continue
        # Чередующийся фон строк
        draw.rectangle([stats_x1 + 2, y - 10, stats_x2 - 2, y + 12],
                       fill=(28, 28, 38))
        stat_row(draw, y, label, v1, v2, cx, f_val, f_lbl)
        draw.line([(stats_x1 + 10, y + 13), (stats_x2 - 10, y + 13)],
                  fill=DARK_LINE, width=1)
        y += 28
        if y > CARD_H - 15:
            break

    # ── Нижняя полоса GOLD ──
    draw.rectangle([0, CARD_H - 4, CARD_W, CARD_H], fill=GOLD)

    # ── Имена бойцов поверх фото (левый и правый) ──
    f_photo_name = font(13, bold=True)
    draw.text((155, CARD_H - 40), fighter1.upper(),
              font=f_photo_name, fill=WHITE, anchor="mm")
    draw.text((CARD_W - 155, CARD_H - 40), fighter2.upper(),
              font=f_photo_name, fill=WHITE, anchor="mm")

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
