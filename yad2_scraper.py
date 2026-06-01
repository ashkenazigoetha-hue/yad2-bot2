"""
Yad2 Scraper – headless Playwright browser to bypass bot protection
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Browser
from playwright_stealth import stealth_async

logger = logging.getLogger(__name__)

YAD2_SEARCH_URL = "https://www.yad2.co.il/vehicles/cars"

MANUFACTURER_MAP = {
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
    "cadillac": "קאדילק",
    "dodge": "דודג'",
    "chrysler": "קרייסלר",
}

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

MODEL_MAP = {
    "corolla": "קורולה",
    "camry": "קאמרי",
    "yaris": "יאריס",
    "rav4": "rav4",
    "auris": "אוריס",
    "civic": "סיוויק",
    "accord": "אקורד",
    "jazz": "ג'אז",
    "cr-v": "cr-v",
    "crv": "cr-v",
    "hrv": "hr-v",
    "hr-v": "hr-v",
    "mazda3": "מאזדה 3",
    "mazda 3": "מאזדה 3",
    "mazda6": "מאזדה 6",
    "mazda 6": "מאזדה 6",
    "cx-5": "cx-5",
    "cx5": "cx-5",
    "cx-3": "cx-3",
    "golf": "גולף",
    "passat": "פאסאט",
    "polo": "פולו",
    "tiguan": "טיגואן",
    "jetta": "ג'טה",
    "focus": "פוקוס",
    "kuga": "קוגה",
    "fiesta": "פיאסטה",
    "i20": "i20",
    "i30": "i30",
    "i35": "i35",
    "tucson": "טוסון",
    "santa fe": "סנטה פה",
    "sonata": "סונטה",
    "elantra": "אלנטרה",
    "sportage": "ספורטז'",
    "rio": "ריו",
    "picanto": "פיקנטו",
    "ceed": "סיד",
    "stonic": "סטוניק",
    "3 series": "סדרה 3",
    "5 series": "סדרה 5",
    "x5": "x5",
    "x3": "x3",
    "c class": "קלאס C",
    "e class": "קלאס E",
    "a class": "קלאס A",
    "model 3": "מודל 3",
    "model s": "מודל S",
    "model y": "מודל Y",
    "a4": "a4",
    "a3": "a3",
    "a6": "a6",
    "q5": "q5",
    "q3": "q3",
}


class Yad2Scraper:
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()

    async def _get_browser(self) -> Browser:
        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--window-size=1280,800",
                    ],
                )
        return self._browser

    def _normalize_model(self, model: str) -> str:
        if not model:
            return model
        if re.search(r'[֐-׿]', model):
            return model
        return MODEL_MAP.get(model.lower().strip(), model)

    def _build_params(self, search: dict, ignore_date_filter: bool = False) -> dict:
        params = {}
        if not ignore_date_filter:
            week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            params['fromDate'] = week_ago

        manufacturer = search.get("manufacturer", "").lower().strip()
        if manufacturer:
            heb = MANUFACTURER_MAP.get(manufacturer, manufacturer)
            mid = YAD2_MANUFACTURER_IDS.get(heb)
            params["manufacturer"] = mid if mid else heb

        model = search.get("model", "").strip()
        if model:
            params["model"] = self._normalize_model(model)

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

    async def fetch_listings(self, search: dict, ignore_date_filter: bool = False) -> list[dict]:
        try:
            browser = await self._get_browser()
        except Exception as e:
            raise RuntimeError(f"Playwright browser launch failed: {e}") from e
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8"},
        )
        try:
            params = self._build_params(search, ignore_date_filter)
            url = f"{YAD2_SEARCH_URL}?{urlencode(params)}" if params else YAD2_SEARCH_URL
            page = await context.new_page()
            await stealth_async(page)

            captured_json = []

            async def on_response(resp):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct and resp.status == 200:
                        u = resp.url
                        if "vehicle" in u or "feed" in u or "/cars" in u:
                            data = await resp.json()
                            captured_json.append(data)
                except Exception:
                    pass

            page.on("response", on_response)

            logger.info(f"Playwright fetching: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(5000)

            try:
                raw = await page.evaluate(
                    "() => { const el = document.getElementById('__NEXT_DATA__'); return el ? el.textContent : null; }"
                )
                if raw:
                    nd = json.loads(raw)
                    listings = self._extract_listings(nd)
                    if listings:
                        logger.info(f"Got {len(listings)} listings from __NEXT_DATA__")
                        return listings
            except Exception as e:
                logger.debug(f"__NEXT_DATA__ error: {e}")

            for data in reversed(captured_json):
                listings = self._extract_listings(data)
                if listings:
                    logger.info(f"Got {len(listings)} listings from captured API response")
                    return listings

            logger.warning("No listings found on page")
            return []

        except Exception as e:
            logger.error(f"fetch_listings error: {e}")
            return []
        finally:
            await context.close()

    def _extract_listings(self, data) -> list[dict]:
        feed_items = self._deep_find(data, "feed_items") or []
        listings = []
        for item in feed_items:
            if isinstance(item, dict) and item.get("type") == "ad":
                parsed = self._parse_item(item)
                if parsed:
                    listings.append(parsed)
        return listings

    def _deep_find(self, obj, key: str, depth: int = 10):
        if depth == 0:
            return None
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = self._deep_find(v, key, depth - 1)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = self._deep_find(item, key, depth - 1)
                if r is not None:
                    return r
        return None

    def _parse_number(self, text) -> Optional[int]:
        digits = re.sub(r"[^\d]", "", str(text))
        return int(digits) if digits else None

    def _parse_item(self, item: dict) -> Optional[dict]:
        try:
            ad_id = str(item.get("id") or item.get("orderId") or "")
            if not ad_id:
                return None

            parts = []
            for key in ("manufacturer_he", "manufacturer", "ManufacturerHe"):
                if item.get(key):
                    parts.append(str(item[key]))
                    break
            for key in ("model", "Model"):
                if item.get(key):
                    parts.append(str(item[key]))
                    break
            for key in ("subModel", "sub_model"):
                if item.get(key):
                    parts.append(str(item[key]))
                    break

            title = " ".join(parts) or item.get("title", "רכב")

            price = None
            for key in ("price", "Price", "primaryPrice"):
                if item.get(key):
                    price = self._parse_number(item[key])
                    if price:
                        break

            year = item.get("year") or item.get("Year")

            km = None
            for key in ("km", "Km", "kilometers"):
                if item.get(key):
                    km = self._parse_number(item[key])
                    if km:
                        break

            city = item.get("city") or item.get("City") or item.get("cityText", "")
            order_id = item.get("orderId") or item.get("id", "")

            return {
                "id": ad_id,
                "title": title,
                "price": price,
                "year": year,
                "km": km,
                "city": city,
                "url": f"https://www.yad2.co.il/item/{order_id}",
            }
        except Exception as e:
            logger.debug(f"parse_item error: {e}")
            return None

    async def fetch_new_listings(
        self, search: dict, search_manager, user_id: str, search_id: str
    ) -> list[dict]:
        seen_ids = set(search_manager.get_seen_ids(user_id, search_id))
        is_first_run = len(seen_ids) == 0

        all_listings = await self.fetch_listings(search, ignore_date_filter=is_first_run)
        new_listings = [l for l in all_listings if l["id"] not in seen_ids]

        if is_first_run:
            search_manager.mark_seen(user_id, search_id, [l["id"] for l in all_listings])
            return new_listings[:15]

        if new_listings:
            search_manager.mark_seen(user_id, search_id, [l["id"] for l in new_listings])
        return new_listings

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
