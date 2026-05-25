"""
Yad2 Scraper – fetches car listings from Yad2
Uses aiohttp with browser-like headers + BeautifulSoup HTML parsing as fallback
"""

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import urlencode, quote

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Yad2 search URL (browser-facing, returns Next.js page with embedded JSON)
YAD2_SEARCH_URL = "https://www.yad2.co.il/vehicles/cars"

# Yad2 internal API (works after session cookie)
YAD2_API_URL = "https://gw.yad2.co.il/feed-search-legacy/vehicles/cars"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9",
    "Referer": "https://www.yad2.co.il/vehicles/cars",
    "Origin": "https://www.yad2.co.il",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# Manufacturer name mapping Hebrew ↔ English
MANUFACTURER_MAP = {
    # English → Hebrew
    "toyota": "טויוטה",
    "honda": "הונדה",
    "mazda": "מאזדה",
    "hyundai": "יונדאי",
    "kia": "קיה",
    "volkswagen": "פולקסווגן",
    "vw": "פולקסווגן",
    "ford": "פורד",
    "subaru": "סובארו",
    "nissan": "ניסאן",
    "suzuki": "סוזוקי",
    "seat": "סיאט",
    "skoda": "סקודה",
    "renault": "רנו",
    "peugeot": "פיג'ו",
    "citroen": "סיטרואן",
    "bmw": "ב.מ.וו",
    "mercedes": "מרצדס",
    "benz": "מרצדס",
    "audi": "אאודי",
    "opel": "אופל",
    "fiat": "פיאט",
    "volvo": "וולוו",
    "mitsubishi": "מיצובישי",
    "chevrolet": "שברולט",
    "mini": "מיני",
    "jeep": "ג'יפ",
    "lexus": "לקסוס",
    "landrover": "לנד רובר",
    "land rover": "לנד רובר",
    "tesla": "טסלה",
    "dacia": "דאצ'יה",
    "alfa romeo": "אלפא רומיאו",
    "alfa": "אלפא רומיאו",
    "porsche": "פורשה",
    "infiniti": "אינפיניטי",
    "acura": "אקורה",
    "lincoln": "לינקולן",
    "cadillac": "קאדילק",
    "dodge": "דודג'",
    "chrysler": "קרייסלר",
    "buick": "ביואיק",
}

# Yad2 manufacturer IDs (numeric) – used in API params
YAD2_MANUFACTURER_IDS = {
    "טויוטה": 56,
    "הונדה": 19,
    "מאזדה": 35,
    "יונדאי": 20,
    "קיה": 28,
    "פולקסווגן": 59,
    "פורד": 13,
    "סובארו": 51,
    "ניסאן": 42,
    "סוזוקי": 52,
    "סיאט": 47,
    "סקודה": 48,
    "רנו": 45,
    "פיג'ו": 43,
    "סיטרואן": 9,
    "ב.מ.וו": 3,
    "מרצדס": 37,
    "אאודי": 1,
    "אופל": 43,
    "פיאט": 12,
    "וולוו": 60,
    "מיצובישי": 38,
    "שברולט": 8,
    "מיני": 39,
    "ג'יפ": 26,
    "לקסוס": 32,
    "לנד רובר": 31,
    "טסלה": 55,
    "דאצ'יה": 68,
    "פורשה": 44,
}


class Yad2Scraper:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cookies_initialized = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False, limit=5)
            jar = aiohttp.CookieJar()
            self._session = aiohttp.ClientSession(
                connector=connector,
                cookie_jar=jar,
            )
            self._cookies_initialized = False
        return self._session

    async def _init_cookies(self):
        """Visit Yad2 homepage to get session cookies (bypasses Cloudflare basic check)."""
        if self._cookies_initialized:
            return
        session = await self._get_session()
        try:
            async with session.get(
                "https://www.yad2.co.il/vehicles/cars",
                headers=BROWSER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as resp:
                logger.info(f"Cookie init: {resp.status}")
                self._cookies_initialized = resp.status < 500
        except Exception as e:
            logger.warning(f"Cookie init failed: {e}")

    def _build_api_params(self, search: dict) -> dict:
        params = {}

        manufacturer = search.get("manufacturer", "").lower().strip()
        if manufacturer:
            heb_name = MANUFACTURER_MAP.get(manufacturer, manufacturer)
            man_id = YAD2_MANUFACTURER_IDS.get(heb_name)
            if man_id:
                params["manufacturer"] = man_id
            else:
                params["manufacturer"] = heb_name

        model = search.get("model", "").strip()
        if model:
            params["model"] = model

        if search.get("price_min"):
            params["price"] = search["price_min"]
        if search.get("price_max"):
            params["priceMax"] = search["price_max"]
        if search.get("year_min"):
            params["year"] = search["year_min"]
        if search.get("year_max"):
            params["yearMax"] = search["year_max"]
        if search.get("km_max"):
            params["km"] = search["km_max"]

        return params

    def _build_search_url(self, search: dict) -> str:
        """Build a Yad2 browser search URL for the listing link."""
        params = self._build_api_params(search)
        if params:
            return f"{YAD2_SEARCH_URL}?{urlencode(params)}"
        return YAD2_SEARCH_URL

    async def fetch_listings(self, search: dict) -> list[dict]:
        """Fetch listings – tries API, falls back to HTML parsing."""
        await self._init_cookies()
        
        # Try method 1: Direct API
        listings = await self._fetch_via_api(search)
        if listings:
            return listings

        # Fallback method 2: HTML parsing
        logger.info("API failed, trying HTML parsing...")
        listings = await self._fetch_via_html(search)
        return listings

    async def _fetch_via_api(self, search: dict) -> list[dict]:
        session = await self._get_session()
        params = self._build_api_params(search)

        try:
            async with session.get(
                YAD2_API_URL,
                params=params,
                headers=API_HEADERS,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"API returned {resp.status}")
                    return []
                data = await resp.json(content_type=None)
                return self._parse_api_response(data)
        except Exception as e:
            logger.warning(f"API fetch error: {e}")
            return []

    async def _fetch_via_html(self, search: dict) -> list[dict]:
        """Parse the Yad2 search page HTML to extract listings from embedded JSON."""
        session = await self._get_session()
        params = self._build_api_params(search)
        url = YAD2_SEARCH_URL

        try:
            async with session.get(
                url,
                params=params,
                headers=BROWSER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"HTML fetch returned {resp.status}")
                    return []
                html = await resp.text()
                return self._parse_html(html)
        except Exception as e:
            logger.error(f"HTML fetch error: {e}")
            return []

    def _parse_html(self, html: str) -> list[dict]:
        """Extract listings from Next.js __NEXT_DATA__ or window.__data__ JSON embedded in HTML."""
        listings = []

        # Try __NEXT_DATA__ (Next.js)
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                # Navigate the Next.js page props
                feed = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                )
                # Try to find feed_items anywhere in the nested structure
                feed_items = self._deep_find(data, "feed_items")
                if feed_items:
                    for item in feed_items:
                        if isinstance(item, dict) and item.get("type") == "ad":
                            parsed = self._parse_item(item)
                            if parsed:
                                listings.append(parsed)
                    logger.info(f"HTML parse: found {len(listings)} from __NEXT_DATA__")
                    return listings
            except Exception as e:
                logger.debug(f"__NEXT_DATA__ parse error: {e}")

        # Try window.__data__ pattern
        match2 = re.search(r'window\.__data__\s*=\s*({.*?});\s*</script>', html, re.DOTALL)
        if match2:
            try:
                data = json.loads(match2.group(1))
                feed_items = self._deep_find(data, "feed_items")
                if feed_items:
                    for item in feed_items:
                        if isinstance(item, dict) and item.get("type") == "ad":
                            parsed = self._parse_item(item)
                            if parsed:
                                listings.append(parsed)
                    return listings
            except Exception as e:
                logger.debug(f"window.__data__ parse error: {e}")

        # Fallback: BeautifulSoup to find listing cards
        soup = BeautifulSoup(html, "lxml")
        cards = soup.find_all("div", attrs={"data-item-id": True})
        for card in cards:
            item_id = card.get("data-item-id", "")
            title = card.find(class_=re.compile(r"title|heading", re.I))
            price_el = card.find(class_=re.compile(r"price", re.I))
            if item_id:
                listings.append({
                    "id": item_id,
                    "title": title.get_text(strip=True) if title else "רכב",
                    "price": self._parse_number(price_el.get_text() if price_el else ""),
                    "year": None,
                    "km": None,
                    "city": "",
                    "url": f"https://www.yad2.co.il/item/{item_id}",
                })

        logger.info(f"HTML BS4 parse: found {len(listings)} listings")
        return listings

    def _deep_find(self, obj, key: str, max_depth: int = 10):
        """Recursively search for a key in nested dicts/lists."""
        if max_depth == 0:
            return None
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                result = self._deep_find(v, key, max_depth - 1)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._deep_find(item, key, max_depth - 1)
                if result is not None:
                    return result
        return None

    def _parse_api_response(self, data: dict) -> list[dict]:
        listings = []
        feed_items = (
            data.get("data", {})
            .get("feed", {})
            .get("feed_items", [])
        )
        for item in feed_items:
            if item.get("type") == "ad":
                parsed = self._parse_item(item)
                if parsed:
                    listings.append(parsed)
        logger.info(f"API parse: found {len(listings)} listings")
        return listings

    def _parse_number(self, text: str) -> Optional[int]:
        if not text:
            return None
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None

    def _parse_item(self, item: dict) -> Optional[dict]:
        try:
            ad_id = str(item.get("id") or item.get("orderId") or "")
            if not ad_id:
                return None

            # Build title
            parts = []
            for key in ("manufacturer_he", "manufacturer", "ManufacturerHe"):
                if item.get(key):
                    parts.append(item[key])
                    break
            for key in ("model", "Model"):
                if item.get(key):
                    parts.append(item[key])
                    break
            for key in ("subModel", "sub_model"):
                if item.get(key):
                    parts.append(item[key])
                    break

            title = " ".join(parts) if parts else item.get("title", "רכב")

            # Price
            price = None
            for key in ("price", "Price", "primaryPrice"):
                raw = item.get(key)
                if raw:
                    price = self._parse_number(str(raw))
                    if price:
                        break

            # Year
            year = item.get("year") or item.get("Year")

            # KM
            km = None
            for key in ("km", "Km", "kilometers"):
                raw = item.get(key)
                if raw:
                    km = self._parse_number(str(raw))
                    if km:
                        break

            city = item.get("city") or item.get("City") or item.get("cityText", "")
            order_id = item.get("orderId") or item.get("id", "")
            url = f"https://www.yad2.co.il/item/{order_id}"

            return {
                "id": ad_id,
                "title": title,
                "price": price,
                "year": year,
                "km": km,
                "city": city,
                "url": url,
            }
        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    async def fetch_new_listings(
        self, search: dict, search_manager, user_id: str, search_id: str
    ) -> list[dict]:
        """Return only listings not yet seen for this search."""
        all_listings = await self.fetch_listings(search)
        seen_ids = set(search_manager.get_seen_ids(user_id, search_id))

        new_listings = [l for l in all_listings if l["id"] not in seen_ids]

        if new_listings:
            new_ids = [l["id"] for l in new_listings]
            search_manager.mark_seen(user_id, search_id, new_ids)

        return new_listings

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
