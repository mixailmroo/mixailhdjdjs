import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from typing import Optional
import os

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_BASE = "https://api.the-odds-api.com/v4"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


# ─────────────────────────────────────────
#  ESPN API — ОФИЦИАЛЬНЫЕ ИВЕНТЫ UFC
# ─────────────────────────────────────────

async def get_ufc_events_official() -> dict[str, list[dict]]:
    """Берёт предстоящие UFC ивенты через ESPN API."""
    url = f"{ESPN_BASE}/scoreboard"
    params = {"limit": 10}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, params=params,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

        grouped: dict[str, list[dict]] = {}
        events = data.get("events", [])

        for event in events:
            event_name = event.get("name", "UFC Event")
            event_id = event.get("id", "")
            competitions = event.get("competitions", [])

            fights = []
            for i, comp in enumerate(competitions):
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                # ESPN даёт home/away
                comp_a = competitors[0]
                comp_b = competitors[1]

                athlete_a = comp_a.get("athlete", {})
                athlete_b = comp_b.get("athlete", {})

                name_a = athlete_a.get("displayName", comp_a.get("displayName", "Fighter 1"))
                name_b = athlete_b.get("displayName", comp_b.get("displayName", "Fighter 2"))

                # Фото
                photo_a = athlete_a.get("headshot", {}).get("href") or \
                          athlete_a.get("flag", {}).get("href")
                photo_b = athlete_b.get("headshot", {}).get("href") or \
                          athlete_b.get("flag", {}).get("href")

                # Весовая категория
                weight_class = comp.get("type", {}).get("text", "") or \
                               comp.get("status", {}).get("type", {}).get("detail", "")

                # ID атлетов для детальной статы
                athlete_id_a = athlete_a.get("id", "")
                athlete_id_b = athlete_b.get("id", "")

                fights.append({
                    "id": f"{event_id}_{comp.get('id', i)}",
                    "fighter1": name_a,
                    "fighter2": name_b,
                    "photo1": photo_a,
                    "photo2": photo_b,
                    "athlete_id1": athlete_id_a,
                    "athlete_id2": athlete_id_b,
                    "weight_class": weight_class,
                    "commence_time": comp.get("date", ""),
                    "odds_f1": None,
                    "odds_f2": None,
                    "event_name": event_name,
                })

            if fights:
                grouped[event_name] = fights

        return grouped

    except Exception as e:
        return {}


async def get_fighter_espn_stats(athlete_id: str) -> dict:
    """Получает статистику бойца через ESPN по ID."""
    if not athlete_id:
        return {}
    url = f"{ESPN_CORE}/athletes/{athlete_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

        stats = {}
        # Основная инфа
        stats["nickname"] = data.get("nickname", "")
        stats["age"] = str(data.get("age", ""))

        # Физические данные
        height_raw = data.get("displayHeight", "")
        weight_raw = data.get("displayWeight", "")
        stats["height"] = height_raw
        stats["weight"] = weight_raw

        # Рекорд
        record = data.get("record", {})
        if record:
            stats["wins"] = str(record.get("wins", "?"))
            stats["losses"] = str(record.get("losses", "?"))
            stats["draws"] = str(record.get("draws", "?"))

        # Флаг страны
        flag = data.get("flag", {})
        stats["country"] = flag.get("alt", "")

        return stats

    except Exception:
        return {}


async def get_both_fighters_data(fighter1: str, fighter2: str,
                                  id1: str = "", id2: str = "") -> tuple[dict, dict]:
    """Параллельно получает статистику обоих бойцов."""
    if id1 or id2:
        stats1, stats2 = await asyncio.gather(
            get_fighter_espn_stats(id1),
            get_fighter_espn_stats(id2),
        )
    else:
        # Фолбэк на ufcstats если нет id
        stats1, stats2 = await asyncio.gather(
            get_fighter_stats_ufcstats(fighter1),
            get_fighter_stats_ufcstats(fighter2),
        )
    return stats1 or {}, stats2 or {}


# ─────────────────────────────────────────
#  UFCSTATS.COM — ФОЛБЭК СТАТИСТИКА
# ─────────────────────────────────────────

async def get_fighter_stats_ufcstats(name: str) -> Optional[dict]:
    search_url = "http://ufcstats.com/statistics/fighters/search"
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

        cols = rows[0].select("td")
        if len(cols) < 10:
            return None

        return {
            "nickname": cols[2].get_text(strip=True),
            "height": cols[3].get_text(strip=True),
            "weight": cols[4].get_text(strip=True),
            "reach": cols[5].get_text(strip=True),
            "stance": cols[6].get_text(strip=True),
            "wins": cols[7].get_text(strip=True),
            "losses": cols[8].get_text(strip=True),
            "draws": cols[9].get_text(strip=True),
        }
    except Exception:
        return None


# ─────────────────────────────────────────
#  UFC.COM — ФОТО (ФОЛБЭК)
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


async def get_both_fighters_photos(fighter1: str, fighter2: str,
                                    photo1: str = "", photo2: str = "") -> tuple[Optional[str], Optional[str]]:
    """Возвращает фото — сначала из ESPN, потом с ufc.com."""
    if photo1 and photo2:
        return photo1, photo2

    p1, p2 = await asyncio.gather(
        get_fighter_photo(fighter1) if not photo1 else asyncio.sleep(0, result=photo1),
        get_fighter_photo(fighter2) if not photo2 else asyncio.sleep(0, result=photo2),
    )
    return p1, p2


# ─────────────────────────────────────────
#  THE ODDS API — КОЭФФИЦИЕНТЫ
# ─────────────────────────────────────────

async def enrich_fights_with_odds(fights: list[dict]) -> list[dict]:
    """Добавляет коэффициенты к списку боёв по фамилиям бойцов."""
    if not ODDS_API_KEY:
        return fights

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
        return fights

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
#  ВСПОМОГАТЕЛЬНЫЕ
# ─────────────────────────────────────────

def format_odds(odds: Optional[float]) -> str:
    if odds is None:
        return "N/A"
    return f"{odds:.2f}"


def format_record(stats: dict) -> str:
    w = stats.get("wins", "?")
    l = stats.get("losses", "?")
    d = stats.get("draws", "?")
    return f"{w}-{l}-{d}"
