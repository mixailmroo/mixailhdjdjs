import aiohttp
import asyncio
import re
import json
from bs4 import BeautifulSoup
from typing import Optional
from datetime import datetime
import os

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_BASE = "https://api.the-odds-api.com/v4"
UFC_STATS_BASE = "http://ufcstats.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────
#  UFC.COM — ОФИЦИАЛЬНЫЕ ИВЕНТЫ
# ─────────────────────────────────────────

async def get_ufc_events_official() -> dict[str, list[dict]]:
    """
    Парсит предстоящие ивенты UFC прямо с ufc.com/events.
    Возвращает { event_name: [ {fight}, ... ] }
    """
    url = "https://www.ufc.com/events"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return {}
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        grouped: dict[str, list[dict]] = {}

        # Карточки ивентов
        event_cards = soup.select(".c-card-event--result, .c-card-event")
        if not event_cards:
            # Запасной селектор
            event_cards = soup.select("[class*='event']")

        for card in event_cards[:5]:  # Берём ближайшие 5 ивентов
            # Название ивента
            name_el = card.select_one(".c-card-event--result__headline, h3, .headline")
            event_name = name_el.get_text(strip=True) if name_el else "UFC Event"

            # Ссылка на страницу ивента
            link_el = card.select_one("a[href*='/event/']")
            if not link_el:
                continue
            event_url = "https://www.ufc.com" + link_el["href"] if link_el["href"].startswith("/") else link_el["href"]

            # Дата
            date_el = card.select_one("time, .c-card-event--result__date")
            date_str = date_el.get_text(strip=True) if date_el else ""

            # Получаем бои с страницы ивента
            fights = await _get_fights_from_event_page(event_url, event_name)
            if fights:
                grouped[event_name] = fights

        return grouped

    except Exception as e:
        return {}


async def _get_fights_from_event_page(event_url: str, event_name: str) -> list[dict]:
    """Парсит бои с официальной страницы UFC ивента."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(event_url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        fights = []

        # Ищем карточки боёв
        fight_rows = soup.select(".c-listing-fight, .fight-card-fight, [class*='fight-row']")

        for i, row in enumerate(fight_rows):
            # Имена бойцов
            fighters = row.select(".c-listing-fight__corner-name, .fighter-name, [class*='corner-name']")
            if len(fighters) < 2:
                # Запасной способ
                red = row.select_one("[class*='red'] [class*='name'], [class*='corner--red'] .c-listing-fight__corner-given-name")
                blue = row.select_one("[class*='blue'] [class*='name'], [class*='corner--blue'] .c-listing-fight__corner-given-name")
                if not red or not blue:
                    continue
                f1 = red.get_text(strip=True)
                f2 = blue.get_text(strip=True)
            else:
                f1 = fighters[0].get_text(strip=True)
                f2 = fighters[1].get_text(strip=True)

            if not f1 or not f2 or f1 == f2:
                continue

            # Весовая категория
            weight_el = row.select_one(".c-listing-fight__class-text, [class*='weight-class']")
            weight = weight_el.get_text(strip=True) if weight_el else ""

            fights.append({
                "id": f"{event_name}_{i}_{f1}_{f2}".replace(" ", "_"),
                "fighter1": f1,
                "fighter2": f2,
                "weight_class": weight,
                "commence_time": "",
                "odds_f1": None,
                "odds_f2": None,
                "event_name": event_name,
            })

        return fights

    except Exception:
        return []


# ─────────────────────────────────────────
#  THE ODDS API — только коэффициенты
# ─────────────────────────────────────────

async def get_odds_for_fighters(fighter1: str, fighter2: str) -> tuple[Optional[float], Optional[float]]:
    """Ищет коэффициенты для конкретной пары бойцов в Odds API."""
    url = f"{ODDS_BASE}/sports/mma_mixed_martial_arts/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,uk,us",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None, None
                events = await resp.json()

        f1_lower = fighter1.lower()
        f2_lower = fighter2.lower()

        for event in events:
            home = event.get("home_team", "").lower()
            away = event.get("away_team", "").lower()

            # Проверяем совпадение по фамилии
            f1_last = f1_lower.split()[-1] if f1_lower.split() else f1_lower
            f2_last = f2_lower.split()[-1] if f2_lower.split() else f2_lower

            match = (f1_last in home or f1_last in away) and \
                    (f2_last in home or f2_last in away)

            if match:
                odds1, odds2 = None, None
                for bm in event.get("bookmakers", []):
                    for market in bm.get("markets", []):
                        if market.get("key") == "h2h":
                            for outcome in market.get("outcomes", []):
                                name_lower = outcome["name"].lower()
                                price = outcome["price"]
                                if f1_last in name_lower:
                                    if odds1 is None or price > odds1:
                                        odds1 = price
                                elif f2_last in name_lower:
                                    if odds2 is None or price > odds2:
                                        odds2 = price
                return odds1, odds2

        return None, None

    except Exception:
        return None, None


async def enrich_fights_with_odds(fights: list[dict]) -> list[dict]:
    """Добавляет коэффициенты к списку боёв."""
    # Загружаем все odds один раз
    url = f"{ODDS_BASE}/sports/mma_mixed_martial_arts/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,uk,us",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    all_odds = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    all_odds = await resp.json()
    except Exception:
        pass

    # Матчим бои с коэффициентами по фамилиям
    for fight in fights:
        f1_last = fight["fighter1"].split()[-1].lower()
        f2_last = fight["fighter2"].split()[-1].lower()

        for event in all_odds:
            home = event.get("home_team", "").lower()
            away = event.get("away_team", "").lower()

            if (f1_last in home or f1_last in away) and \
               (f2_last in home or f2_last in away):
                for bm in event.get("bookmakers", []):
                    for market in bm.get("markets", []):
                        if market.get("key") == "h2h":
                            for outcome in market.get("outcomes", []):
                                n = outcome["name"].lower()
                                p = outcome["price"]
                                if f1_last in n:
                                    if fight["odds_f1"] is None or p > fight["odds_f1"]:
                                        fight["odds_f1"] = p
                                elif f2_last in n:
                                    if fight["odds_f2"] is None or p > fight["odds_f2"]:
                                        fight["odds_f2"] = p
                break

    return fights


# ─────────────────────────────────────────
#  UFC.COM — ФОТО БОЙЦА
# ─────────────────────────────────────────

def name_to_slug(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    return name


async def get_fighter_photo(name: str) -> Optional[str]:
    slug = name_to_slug(name)
    url = f"https://www.ufc.com/athlete/{slug}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")

        img = soup.select_one(".hero-profile__image img, .hero-profile img")
        if img and img.get("src"):
            return img["src"]

        for tag in soup.find_all("img"):
            src = tag.get("src", "")
            if "cloudfront" in src and "athlete" in src:
                return src

        return None
    except Exception:
        return None


# ─────────────────────────────────────────
#  UFCSTATS.COM — СТАТИСТИКА БОЙЦА
# ─────────────────────────────────────────

async def get_fighter_stats(name: str) -> Optional[dict]:
    search_url = f"{UFC_STATS_BASE}/statistics/fighters/search"
    parts = name.strip().split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""

    params = {"action": "search", "FirstName": first, "LastName": last}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table.b-statistics__table tbody tr")

        if not rows:
            return None

        row = rows[0]
        cols = row.select("td")
        if len(cols) < 10:
            return None

        fighter_link = row.select_one("a")
        fighter_url = fighter_link["href"] if fighter_link else None

        stats = {
            "name": f"{cols[0].get_text(strip=True)} {cols[1].get_text(strip=True)}",
            "nickname": cols[2].get_text(strip=True),
            "height": cols[3].get_text(strip=True),
            "weight": cols[4].get_text(strip=True),
            "reach": cols[5].get_text(strip=True),
            "stance": cols[6].get_text(strip=True),
            "wins": cols[7].get_text(strip=True),
            "losses": cols[8].get_text(strip=True),
            "draws": cols[9].get_text(strip=True),
            "url": fighter_url,
        }

        if fighter_url:
            extra = await _get_fighter_detail_stats(fighter_url)
            if extra:
                stats.update(extra)

        return stats

    except Exception:
        return None


async def _get_fighter_detail_stats(url: str) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        stats = {}

        boxes = soup.select(".b-list__info-box-left .b-list__box-list-item, "
                            ".b-list__info-box .b-list__box-list-item")
        for box in boxes:
            text = box.get_text(separator="|", strip=True)
            parts = text.split("|")
            if len(parts) == 2:
                key = parts[0].replace(":", "").strip().lower().replace(" ", "_")
                val = parts[1].strip()
                stats[key] = val

        return stats if stats else None

    except Exception:
        return None


# ─────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ
# ─────────────────────────────────────────

async def get_both_fighters_data(fighter1: str, fighter2: str) -> tuple[dict, dict]:
    stats1, stats2 = await asyncio.gather(
        get_fighter_stats(fighter1),
        get_fighter_stats(fighter2),
    )
    return stats1 or {}, stats2 or {}


async def get_both_fighters_photos(fighter1: str, fighter2: str) -> tuple[Optional[str], Optional[str]]:
    photo1, photo2 = await asyncio.gather(
        get_fighter_photo(fighter1),
        get_fighter_photo(fighter2),
    )
    return photo1, photo2


def format_odds(odds: Optional[float]) -> str:
    if odds is None:
        return "N/A"
    return f"{odds:.2f}"


def format_record(stats: dict) -> str:
    w = stats.get("wins", "?")
    l = stats.get("losses", "?")
    d = stats.get("draws", "?")
    return f"{w}-{l}-{d}"
EOF
echo "Done"
