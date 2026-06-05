"""
Yad2 Scraper – curl-cffi mimics Chrome TLS fingerprint to bypass ShieldSquare.
No headless browser needed.
"""

import json
import logging
import os
import re
from typing import Optional
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

YAD2_SEARCH_URL = "https://www.yad2.co.il/vehicles/cars"

MANUFACTURER_MAP = {
    "toyota": "טויוטה", "honda": "הונדה", "mazda": "מאזדה",
    "hyundai": "יונדאי", "kia": "קיה", "volkswagen": "פולקסווגן",
    "vw": "פולקסווגן", "ford": "פורד", "subaru": "סובארו",
    "nissan": "ניסאן", "suzuki": "סוזוקי", "seat": "סיאט",
    "skoda": "סקודה", "renault": "רנו", "peugeot": "פיג'ו",
    "citroen": "סיטרואן", "bmw": "ב.מ.וו", "mercedes": "מרצדס",
    "benz": "מרצדס", "audi": "אאודי", "opel": "אופל",
    "fiat": "פיאט", "volvo": "וולוו", "mitsubishi": "מיצובישי",
    "chevrolet": "שברולט", "mini": "מיני", "jeep": "ג'יפ",
    "lexus": "לקסוס", "land rover": "לנד רובר", "landrover": "לנד רובר",
    "tesla": "טסלה", "dacia": "דאצ'יה", "alfa romeo": "אלפא רומיאו",
    "alfa": "אלפא רומיאו", "porsche": "פורשה", "infiniti": "אינפיניטי",
}

YAD2_MANUFACTURER_IDS = {
    "אאודי": 1, "אופל": 2, "אינפיניטי": 3, "איסוזו": 4,
    "אלפא רומיאו": 5, "ב.מ.וו": 7, "ב מ וו": 7,
    "ג'יפ": 10, "דאצ'יה": 12, "דודג'": 13,
    "הונדה": 17, "וולוו": 18, "טויוטה": 19, "יגואר": 20,
    "יונדאי": 21, "לנד רובר": 24, "לקסוס": 26, "מאזדה": 27,
    "מיני": 29, "מיצובישי": 30, "מרצדס-בנץ": 31, "מרצדס": 31,
    "ניסאן": 32, "סובארו": 35, "סוזוקי": 36, "סיאט": 37,
    "סיטרואן": 38, "סקודה": 40, "פולקסווגן": 41, "פורד": 43,
    "פורשה": 44, "פיאט": 45, "פיג'ו": 46, "קאדילק": 47,
    "קיה": 48, "קרייזלר": 49, "רנו": 51, "שברולט": 52, "טסלה": 62,
}

MODEL_MAP = {
    "corolla": "קורולה", "camry": "קאמרי", "yaris": "יאריס",
    "auris": "אוריס", "civic": "סיוויק", "accord": "אקורד",
    "jazz": "ג'אז", "cr-v": "cr-v", "crv": "cr-v",
    "mazda3": "מאזדה 3", "mazda 3": "מאזדה 3", "mazda6": "מאזדה 6",
    "cx-5": "cx-5", "cx5": "cx-5", "golf": "גולף", "passat": "פאסאט",
    "polo": "פולו", "tiguan": "טיגואן", "jetta": "ג'טה",
    "focus": "פוקוס", "kuga": "קוגה", "fiesta": "פיאסטה",
    "i20": "i20", "i30": "i30", "tucson": "טוסון", "sonata": "סונטה",
    "elantra": "אלנטרה", "sportage": "ספורטז'", "rio": "ריו",
    "model 3": "מודל 3", "model s": "מודל S", "model y": "מודל Y",
    "a4": "a4", "a3": "a3", "q5": "q5", "q3": "q3",
}


class Yad2Scraper:
    def __init__(self):
        self._session: Optional[AsyncSession] = None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            proxy = os.getenv("PROXY_URL", "")
            self._session = AsyncSession(proxies={"https": proxy, "http": proxy} if proxy else None)
            if proxy:
                logger.info(f"Using proxy: {proxy.split('@')[-1]}")
        return self._session

    def _normalize_model(self, model: str) -> str:
        if not model:
            return model
        if re.search(r'[֐-׿]', model):
            return model
        return MODEL_MAP.get(model.lower().strip(), model)

    def _build_params(self, search: dict) -> dict:
        params = {}

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
            params["priceEnd"] = search["price_max"]
        if search.get("year_min"):
            params["year"] = search["year_min"]
        if search.get("year_max"):
            params["yearEnd"] = search["year_max"]
        if search.get("km_max"):
            params["kmEnd"] = search["km_max"]

        return params

    async def _fetch_url(self, url: str) -> list[dict]:
        session = await self._get_session()
        response = await session.get(
            url,
            impersonate="chrome124",
            headers={"Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8"},
            timeout=30,
        )
        html = response.text
        logger.info(f"yad2 fetch: url={url} status={response.status_code} len={len(html)}")
        if response.status_code != 200:
            logger.warning(f"Bad status: {response.status_code}")
            return []
        if "__NEXT_DATA__" not in html:
            logger.warning("No __NEXT_DATA__ — likely blocked or CAPTCHA page")
            return []
        return self._parse_page(html)

    async def fetch_listings(self, search: dict) -> list[dict]:
        try:
            params = self._build_params(search)
            url = f"{YAD2_SEARCH_URL}?{urlencode(params)}" if params else YAD2_SEARCH_URL
            results = await self._fetch_url(url)

            if not results and params.get("model"):
                logger.info("No results with model filter — retrying without model")
                params_no_model = {k: v for k, v in params.items() if k != "model"}
                url2 = f"{YAD2_SEARCH_URL}?{urlencode(params_no_model)}" if params_no_model else YAD2_SEARCH_URL
                results = await self._fetch_url(url2)

            return results
        except Exception as e:
            logger.error(f"fetch_listings error: {e}", exc_info=True)
            raise

    def _parse_page(self, html: str) -> list[dict]:
        try:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                return []

            nd = json.loads(m.group(1))
            pp = nd['props']['pageProps']
            logger.info(f"totalFeedItems={pp.get('totalFeedItems')} hasFeed={pp.get('hasFeedResults')}")
            queries = pp.get('dehydratedState', {}).get('queries', [])
            logger.info(f"queries in dehydrated state: {len(queries)}")
            feed_q = next((q for q in queries if q.get('queryKey', [None])[0] == 'feed'), None)
            if not feed_q:
                logger.warning(f"No feed query. Keys: {[q.get('queryKey') for q in queries]}")
                return []

            data = feed_q['state']['data']
            cat_counts = {c: len(data.get(c, [])) for c in ['private','commercial','boost','platinum','solo']}
            logger.info(f"Categories: {cat_counts}")
            listings = []
            for cat in ['private', 'commercial', 'boost', 'platinum', 'solo']:
                for item in data.get(cat, []):
                    parsed = self._parse_item(item)
                    if parsed:
                        listings.append(parsed)

            logger.info(f"Parsed {len(listings)} listings")
            return listings

        except Exception as e:
            logger.error(f"_parse_page error: {e}", exc_info=True)
            return []

    def _parse_item(self, item: dict) -> Optional[dict]:
        try:
            token = item.get("token", "")
            order_id = item.get("orderId") or item.get("id") or item.get("adId")
            ad_id = str(order_id or token).strip()
            if not ad_id or ad_id in ("None", "0", ""):
                return None

            parts = []
            for field in ["manufacturer", "model", "subModel"]:
                obj = item.get(field, {})
                if isinstance(obj, dict):
                    text = obj.get("text") or obj.get("value") or obj.get("name", "")
                    if text:
                        parts.append(text)
                elif isinstance(obj, str) and obj:
                    parts.append(obj)
            title = " ".join(parts) if parts else item.get("title", "רכב")

            price = item.get("price")
            if isinstance(price, dict):
                price = price.get("value") or price.get("price")

            year = (
                item.get("vehicleDates", {}).get("yearOfProduction")
                or item.get("year")
                or item.get("yearOfProduction")
            )

            km = (
                item.get("km")
                or item.get("kilometers")
                or item.get("mileage")
            )

            addr = item.get("address", {})
            city = (
                addr.get("city", {}).get("text", "")
                or addr.get("area", {}).get("text", "")
                or addr.get("cityText", "")
                or (addr if isinstance(addr, str) else "")
                or item.get("city", "")
            )

            images = item.get("images", [])
            photo_url = None
            if images and isinstance(images, list):
                first = images[0]
                if isinstance(first, dict):
                    photo_url = (
                        first.get("src") or first.get("url")
                        or first.get("uri") or first.get("thumbnail")
                    )
                elif isinstance(first, str):
                    photo_url = first

            hand = item.get("hand") or item.get("ownerID") or item.get("handNum")

            ownership_obj = item.get("ownerType") or item.get("ownership") or {}
            if isinstance(ownership_obj, dict):
                ownership = ownership_obj.get("text") or ownership_obj.get("value") or ""
            elif isinstance(ownership_obj, str):
                ownership = ownership_obj
            else:
                ownership = ""

            link_id = token or order_id
            return {
                "id": ad_id,
                "title": title,
                "price": price,
                "year": year,
                "km": km,
                "city": city,
                "url": f"https://www.yad2.co.il/item/{link_id}",
                "photo_url": photo_url,
                "hand": hand,
                "ownership": ownership,
            }
        except Exception as e:
            logger.debug(f"parse_item error: {e}")
            return None

    async def fetch_new_listings(
        self, search: dict, search_manager, user_id: str, search_id: str
    ) -> list[dict]:
        seen_ids = set(search_manager.get_seen_ids(user_id, search_id))
        is_first_run = len(seen_ids) == 0

        all_listings = await self.fetch_listings(search)
        new_listings = [l for l in all_listings if l["id"] not in seen_ids]

        if is_first_run:
            # Mark everything as seen so future runs only send truly new listings
            search_manager.mark_seen(user_id, search_id, [l["id"] for l in all_listings])
            logger.info(f"First run: marked {len(all_listings)} listings as seen, sending nothing")
            return []

        if new_listings:
            search_manager.mark_seen(user_id, search_id, [l["id"] for l in new_listings])
        return new_listings[:15]

    async def debug_page(self) -> dict:
        try:
            session = await self._get_session()
            response = await session.get(
                "https://www.yad2.co.il/vehicles/cars?manufacturer=56",
                impersonate="chrome124",
                headers={"Accept-Language": "he-IL,he;q=0.9"},
                timeout=30,
            )
            html = response.text
            nd_present = "__NEXT_DATA__" in html
            listings = self._parse_page(html) if nd_present else []
            title = re.search(r'<title>(.*?)</title>', html)
            return {
                "status": response.status_code,
                "url": str(response.url),
                "html_length": len(html),
                "has_next_data": nd_present,
                "is_captcha": "shieldsquare" in html.lower() and not nd_present,
                "listings_found": len(listings),
                "title": title.group(1) if title else "N/A",
                "html_preview": html[:300],
            }
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        if self._session:
            await self._session.close()
