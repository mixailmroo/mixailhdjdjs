import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from typing import Optional
import os

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_BASE = "https://api.the-odds-api.com/v4"
UFC_STATS_BASE = "http://ufcstats.com"


# ─────────────────────────────────────────
#  THE ODDS API
# ─────────────────────────────────────────

async def get_ufc_events() -> list[dict]:
    """Получает предстоящие бои UFC с коэффициентами."""
    url = f"{ODDS_BASE}/sports/mma_mixed_martial_arts/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,uk",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data if isinstance(data, list) else []


def parse_fights_from_odds(events: list[dict]) -> dict[str, list[dict]]:
    """
    Группирует бои по названию ивента.
    Возвращает: { "UFC Fight Night: Foo vs Bar": [ {fight}, ... ] }
    """
    grouped: dict[str, list[dict]] = {}

    for event in events:
        event_name = event.get("sport_title", "UFC Event")
        commence = event.get("commence_time", "")
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        fight_id = event.get("id", f"{home}_{away}")

        # Берём коэффициенты от первого букмекера
        odds_h2h = {"home": None, "away": None}
        bookmakers = event.get("bookmakers", [])
        if bookmakers:
            markets = bookmakers[0].get("markets", [])
            for market in markets:
                if market.get("key") == "h2h":
                    outcomes = market.get("outcomes", [])
                    for outcome in outcomes:
                        if outcome["name"] == home:
                            odds_h2h["home"] = outcome["price"]
                        elif outcome["name"] == away:
                            odds_h2h["away"] = outcome["price"]

        fight = {
            "id": fight_id,
            "fighter1": home,
            "fighter2": away,
            "commence_time": commence,
            "odds_f1": odds_h2h["home"],
            "odds_f2": odds_h2h["away"],
            "event_name": event_name,
        }

        if event_name not in grouped:
            grouped[event_name] = []
        grouped[event_name].append(fight)

    return grouped


# ─────────────────────────────────────────
#  UFC.COM — ФОТО БОЙЦА
# ─────────────────────────────────────────

def name_to_slug(name: str) -> str:
    """'Jon Jones' → 'jon-jones'"""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    return name


async def get_fighter_photo(name: str) -> Optional[str]:
    """Парсит фото бойца с UFC.com по имени."""
    slug = name_to_slug(name)
    url = f"https://www.ufc.com/athlete/{slug}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Ищем hero-фото бойца
                img = soup.select_one(".hero-profile__image img, .hero-profile img, img.hero-image")
                if img and img.get("src"):
                    return img["src"]

                # Fallback — ищем по cloudfront
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
    """Ищет статистику бойца на ufcstats.com."""
    search_url = f"{UFC_STATS_BASE}/statistics/fighters/search"
    parts = name.strip().split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""

    params = {"action": "search", "FirstName": first, "LastName": last}
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table.b-statistics__table tbody tr")

        if not rows:
            return None

        # Берём первый результат
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

        # Дополнительная статистика со страницы бойца
        if fighter_url:
            extra = await _get_fighter_detail_stats(fighter_url, headers)
            if extra:
                stats.update(extra)

        return stats

    except Exception:
        return None


async def _get_fighter_detail_stats(url: str, headers: dict) -> Optional[dict]:
    """Детальная стата с личной страницы бойца."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        stats = {}

        # Блок с числовой статой (SLpM, Str. Acc., etc.)
        boxes = soup.select(".b-list__info-box-left .b-list__box-list-item, "
                            ".b-list__info-box .b-list__box-list-item")
        for box in boxes:
            text = box.get_text(separator="|", strip=True)
            parts = text.split("|")
            if len(parts) == 2:
                key = parts[0].replace(":", "").strip().lower().replace(" ", "_")
                val = parts[1].strip()
                stats[key] = val

        # Career stats
        career_boxes = soup.select(".b-fight-details__text-item")
        for box in career_boxes:
            text = box.get_text(separator="|", strip=True)
            parts = text.split("|")
            if len(parts) >= 2:
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
    """Параллельно загружает статистику обоих бойцов."""
    stats1, stats2 = await asyncio.gather(
        get_fighter_stats(fighter1),
        get_fighter_stats(fighter2),
    )
    return stats1 or {}, stats2 or {}


async def get_both_fighters_photos(fighter1: str, fighter2: str) -> tuple[Optional[str], Optional[str]]:
    """Параллельно загружает фото обоих бойцов."""
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
