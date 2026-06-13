"""
Генерирует красивую карточку боя с фото двух бойцов.
"""
import asyncio
import aiohttp
import io
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Optional

CARD_W, CARD_H = 800, 500
BG_COLOR = (10, 10, 15)
RED_COLOR = (200, 30, 30)
BLUE_COLOR = (30, 80, 200)
ACCENT = (220, 170, 30)
WHITE = (255, 255, 255)
GRAY = (160, 160, 160)
DARK_GRAY = (40, 40, 50)


def get_font(size: int, bold: bool = False):
    """Возвращает шрифт, fallback на дефолтный если нет кастомного."""
    try:
        if bold:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


async def download_image(url: str) -> Optional[Image.Image]:
    """Скачивает изображение по URL."""
    if not url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def draw_fighter_placeholder(draw: ImageDraw, x: int, y: int, w: int, h: int,
                              color: tuple, letter: str):
    """Рисует заглушку если нет фото."""
    draw.rectangle([x, y, x + w, y + h], fill=(*color[:3], 40))
    font = get_font(60, bold=True)
    draw.text((x + w // 2, y + h // 2), letter, font=font, fill=(*color[:3], 120),
              anchor="mm")


def paste_fighter_image(canvas: Image.Image, fighter_img: Image.Image,
                         x: int, y: int, w: int, h: int, flip: bool = False):
    """Вставляет фото бойца с обрезкой по размеру."""
    # Ресайз с сохранением пропорций
    img = fighter_img.copy()
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)

    # Масштабируем чтобы заполнить область
    ratio = max(w / img.width, h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Кропим по центру
    left = (new_w - w) // 2
    top = max(0, new_h - h)  # Снизу (ноги)
    img = img.crop((left, top, left + w, top + h))

    # Делаем градиентную маску (снизу прозрачно)
    mask = Image.new("L", (w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    for i in range(h):
        alpha = int(255 * (i / h) ** 0.5)
        mask_draw.line([(0, i), (w, i)], fill=alpha)

    if img.mode != "RGBA":
        img = img.convert("RGBA")
    img.putalpha(mask)
    canvas.paste(img, (x, y), img)


def draw_stat_row(draw: ImageDraw, label: str, val1: str, val2: str,
                  y: int, x_left: int, x_right: int, x_center: int,
                  font, font_bold, accent_color=(220, 170, 30)):
    """Рисует строку статистики: val1 | label | val2"""
    draw.text((x_left, y), val1, font=font_bold, fill=WHITE, anchor="rm")
    draw.text((x_center, y), label, font=font, fill=GRAY, anchor="mm")
    draw.text((x_right, y), val2, font=font_bold, fill=WHITE, anchor="lm")


async def generate_fight_card(
    fighter1: str, fighter2: str,
    photo1_url: Optional[str], photo2_url: Optional[str],
    stats1: dict, stats2: dict,
    odds1: Optional[float], odds2: Optional[float],
    weight_class: str = "",
) -> bytes:
    """Генерирует карточку боя, возвращает bytes (PNG)."""

    # Скачиваем фото параллельно
    img1, img2 = await asyncio.gather(
        download_image(photo1_url) if photo1_url else asyncio.sleep(0, result=None),
        download_image(photo2_url) if photo2_url else asyncio.sleep(0, result=None),
    )

    # Создаём канвас
    canvas = Image.new("RGBA", (CARD_W, CARD_H), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Фоновый градиент
    for i in range(CARD_H):
        alpha = int(20 * (1 - i / CARD_H))
        draw.line([(0, i), (CARD_W, i)], fill=(20, 20, 30, alpha))

    # Разделительная линия посередине
    mid = CARD_W // 2
    draw.line([(mid, 20), (mid, CARD_H - 20)], fill=(60, 60, 70), width=1)

    # Красная полоса слева
    draw.rectangle([0, 0, 4, CARD_H], fill=RED_COLOR)
    # Синяя полоса справа
    draw.rectangle([CARD_W - 4, 0, CARD_W, CARD_H], fill=BLUE_COLOR)

    # Фото бойцов
    photo_w = 220
    photo_h = 300
    photo_y = 20

    if img1:
        paste_fighter_image(canvas, img1, 30, photo_y, photo_w, photo_h)
    else:
        draw_placeholder = ImageDraw.Draw(canvas)
        draw_fighter_placeholder(draw_placeholder, 30, photo_y, photo_w, photo_h,
                                  RED_COLOR, fighter1[0].upper())

    if img2:
        paste_fighter_image(canvas, img2, CARD_W - 30 - photo_w, photo_y, photo_w, photo_h, flip=True)
    else:
        draw_placeholder = ImageDraw.Draw(canvas)
        draw_fighter_placeholder(draw_placeholder, CARD_W - 30 - photo_w, photo_y,
                                  photo_w, photo_h, BLUE_COLOR, fighter2[0].upper())

    draw = ImageDraw.Draw(canvas)

    # Шрифты
    f_big = get_font(22, bold=True)
    f_med = get_font(16, bold=True)
    f_small = get_font(13)
    f_tiny = get_font(11)
    f_vs = get_font(28, bold=True)

    # VS по центру
    draw.text((mid, 60), "VS", font=f_vs, fill=ACCENT, anchor="mm")

    # Весовая категория
    if weight_class:
        draw.text((mid, 95), weight_class, font=f_tiny, fill=GRAY, anchor="mm")

    # Имена бойцов
    name1_parts = fighter1.split()
    name2_parts = fighter2.split()

    # Имя 1 (красный угол)
    draw.text((260, 140), name1_parts[0] if name1_parts else fighter1,
              font=f_med, fill=RED_COLOR, anchor="mm")
    if len(name1_parts) > 1:
        draw.text((260, 160), " ".join(name1_parts[1:]),
                  font=f_big, fill=WHITE, anchor="mm")

    # Имя 2 (синий угол)
    draw.text((CARD_W - 260, 140), name2_parts[0] if name2_parts else fighter2,
              font=f_med, fill=BLUE_COLOR, anchor="mm")
    if len(name2_parts) > 1:
        draw.text((CARD_W - 260, 160), " ".join(name2_parts[1:]),
                  font=f_big, fill=WHITE, anchor="mm")

    # Рекорд
    rec1 = f"{stats1.get('wins','?')}-{stats1.get('losses','?')}-{stats1.get('draws','?')}"
    rec2 = f"{stats2.get('wins','?')}-{stats2.get('losses','?')}-{stats2.get('draws','?')}"
    draw.text((260, 182), rec1, font=f_small, fill=GRAY, anchor="mm")
    draw.text((CARD_W - 260, 182), rec2, font=f_small, fill=GRAY, anchor="mm")

    # Коэффициенты
    if odds1:
        draw.text((260, 205), f"Коэф: {odds1:.2f}", font=f_med, fill=ACCENT, anchor="mm")
    if odds2:
        draw.text((CARD_W - 260, 205), f"Коэф: {odds2:.2f}", font=f_med, fill=ACCENT, anchor="mm")

    # Разделитель статистики
    stats_y_start = 235
    draw.rectangle([40, stats_y_start - 5, CARD_W - 40, stats_y_start - 4],
                   fill=(50, 50, 60))

    # Заголовок статы
    draw.text((mid, stats_y_start + 8), "СТАТИСТИКА", font=f_tiny, fill=GRAY, anchor="mm")

    # Строки статистики
    x_left = mid - 20
    x_right = mid + 20
    rows = [
        ("ВОЗРАСТ", stats1.get("age", "—"), stats2.get("age", "—")),
        ("ВЕС", stats1.get("weight", "—"), stats2.get("weight", "—")),
        ("РОСТ", stats1.get("height", "—"), stats2.get("height", "—")),
        ("РАЗМАХ РУК", stats1.get("reach", "—"), stats2.get("reach", "—")),
        ("СТОЙКА", stats1.get("stance", "—"), stats2.get("stance", "—")),
        ("УД/МИН", stats1.get("slpm", "—"), stats2.get("slpm", "—")),
        ("ТОЧНОСТЬ", stats1.get("str._acc.", "—"), stats2.get("str._acc.", "—")),
    ]

    y = stats_y_start + 30
    for label, v1, v2 in rows:
        if v1 == "—" and v2 == "—":
            continue
        # Фон строки
        draw.rectangle([42, y - 10, CARD_W - 42, y + 12], fill=(20, 20, 28))
        draw_stat_row(draw, label, str(v1), str(v2), y,
                      x_left, x_right, mid, f_tiny, f_tiny)
        y += 26
        if y > CARD_H - 20:
            break

    # Нижняя полоса
    draw.rectangle([0, CARD_H - 3, CARD_W, CARD_H], fill=ACCENT)

    # Конвертируем в RGB и отдаём bytes
    final = canvas.convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf.read()
