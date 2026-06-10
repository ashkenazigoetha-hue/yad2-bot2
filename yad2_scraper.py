"""
Yad2 Scraper – curl-cffi mimics Chrome TLS fingerprint to bypass ShieldSquare.
No headless browser needed.
"""

import json
import logging
import os
import re
from datetime import datetime
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

    async def download_photo(self, url: str) -> Optional[bytes]:
        """Download photo using the same Chrome-impersonating session that bypasses yad2 CDN."""
        try:
            session = await self._get_session()
            response = await session.get(
                url,
                impersonate="chrome124",
                headers={
                    "Referer": "https://www.yad2.co.il/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "he-IL,he;q=0.9",
                },
                timeout=10,
            )
            if response.status_code == 200:
                return response.content
            logger.debug(f"Photo HTTP {response.status_code}: {url[:60]}")
        except Exception as e:
            logger.debug(f"Photo download error: {e}")
        return None

    def _normalize_model(self, model: str) -> str:
        if not model:
            return model
        if re.search(r'[֐-׿]', model):
            return model
        return MODEL_MAP.get(model.lower().strip(), model)

    def _build_params(self, search: dict) -> dict:
        params = {}

        manufacturer = (search.get("manufacturer") or "").strip()
        if manufacturer:
            # manufacturer may already be Hebrew (from website) or English (legacy)
            heb = MANUFACTURER_MAP.get(manufacturer.lower(), manufacturer)
            mid = YAD2_MANUFACTURER_IDS.get(heb)
            if mid:
                params["manufacturer"] = mid
            elif heb:
                params["manufacturer"] = heb

        # We don't pass model/subModel to the URL because Yad2 needs internal
        # numeric IDs we don't have. Instead we filter client-side after fetch.

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

    def _matches_search(self, listing: dict, search: dict) -> bool:
        """Client-side exact match for model and sub_model."""
        wanted_model = (search.get("model") or "").strip()
        wanted_sub = (search.get("sub_model") or "").strip()

        if wanted_model:
            listing_model = (listing.get("model_text") or "").strip()
            if listing_model.lower() != wanted_model.lower():
                return False

        if wanted_sub:
            listing_trim = (listing.get("trim") or "").strip()
            # sub_model must appear as a substring of the trim description
            if wanted_sub.lower() not in listing_trim.lower():
                return False

        return True

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

            # Client-side filter: exact model + sub_model match
            wanted_model = (search.get("model") or "").strip()
            wanted_sub = (search.get("sub_model") or "").strip()
            if wanted_model or wanted_sub:
                before = len(results)
                results = [r for r in results if self._matches_search(r, search)]
                logger.info(
                    f"Model filter '{wanted_model}' / sub '{wanted_sub}': "
                    f"{before} → {len(results)} listings"
                )

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
            ad_id = str(token or order_id).strip()
            if not ad_id or ad_id in ("None", "0", ""):
                return None

            def _t(obj):
                if isinstance(obj, dict):
                    return obj.get("text") or obj.get("value") or obj.get("name", "")
                return obj if isinstance(obj, str) else ""

            manufacturer_text = _t(item.get("manufacturer", {}))
            model_text        = _t(item.get("model", {}))
            submodel_text     = _t(item.get("subModel", {}))
            title_base = " ".join(p for p in [manufacturer_text, model_text] if p) or "רכב"

            price = item.get("price")
            if isinstance(price, dict):
                price = price.get("value") or price.get("price")
            try:
                price = int(price) if price else None
            except (ValueError, TypeError):
                price = None

            vehicle_dates = item.get("vehicleDates") or {}
            year     = vehicle_dates.get("yearOfProduction") or item.get("year")
            test_date = vehicle_dates.get("testDate") or item.get("testDate")

            # km not available in yad2 feed — only on full listing page
            km = item.get("km") or item.get("kilometers") or item.get("mileage")
            try:
                km = int(km) if km else None
            except (ValueError, TypeError):
                km = None

            addr = item.get("address") or {}
            city = (
                _t(addr.get("city") or {})
                or _t(addr.get("area") or {})
                or addr.get("cityText", "")
                or (addr if isinstance(addr, str) else "")
                or item.get("city", "")
            )

            # Photo is inside metaData (confirmed from live yad2 JSON)
            meta = item.get("metaData") or {}
            photo_url = meta.get("coverImage")
            if not photo_url:
                imgs = meta.get("images", [])
                if imgs and isinstance(imgs, list):
                    photo_url = imgs[0] if isinstance(imgs[0], str) else None
            # Also check legacy top-level fields
            if not photo_url:
                photo_url = item.get("mainImage") or item.get("coverImage")
            if photo_url:
                if photo_url.startswith("//"):
                    photo_url = "https:" + photo_url
                elif not photo_url.startswith("http"):
                    photo_url = "https://img.yad2.co.il" + photo_url

            # hand.id = number (1,2,3…), hand.text = "יד ראשונה"
            hand_obj  = item.get("hand") or {}
            hand_num  = hand_obj.get("id") if isinstance(hand_obj, dict) else hand_obj
            hand_text = hand_obj.get("text", "") if isinstance(hand_obj, dict) else ""

            # adType: "private" = פרטי, "commercial" = עוסק/דילר
            ad_type   = item.get("adType", "")
            ownership = "עוסק" if ad_type == "commercial" else "פרטי" if ad_type == "private" else ""

            # Engine: engineVolume (cc), engineType.text ("בנזין"/"דיזל"/"חשמלי"…)
            engine_cc = item.get("engineVolume")
            try:
                engine_cc = int(engine_cc) if engine_cc else None
            except (ValueError, TypeError):
                engine_cc = None
            engine_type = _t(item.get("engineType") or {})

            # Horsepower is embedded in subModel text: "... (177 כ״ס)"
            horsepower = None
            if submodel_text:
                hp_m = re.search(r'\((\d+)\s*כ[״\'"ּ]ס\)', submodel_text)
                if hp_m:
                    try:
                        horsepower = int(hp_m.group(1))
                    except ValueError:
                        pass

            turbo = "טורבו" in submodel_text or "טורבו" in engine_type

            # Tags = equipment features (גלגלי מגנזיום, בקרת שיוט, ...)
            tags = item.get("tags") or []
            features = ", ".join(
                t["name"] for t in tags[:6]
                if isinstance(t, dict) and t.get("name")
            )

            # Listing date — createdAt is the real publish time
            listing_date = (
                item.get("createdAt")
                or item.get("date")
                or item.get("feedDate")
                or item.get("updatedAt")
            )

            link_id = token or order_id
            return {
                "id":           ad_id,
                "title":        title_base,
                "model_text":   model_text,
                "trim":         submodel_text,
                "price":        price,
                "year":         year,
                "km":           km,
                "city":         city,
                "url":          f"https://www.yad2.co.il/item/{link_id}",
                "photo_url":    photo_url,
                "hand":         hand_num,
                "hand_text":    hand_text,
                "ownership":    ownership,
                "engine_cc":    engine_cc,
                "engine_type":  engine_type,
                "horsepower":   horsepower,
                "turbo":        turbo,
                "test_date":    test_date,
                "description":  features,
                "contact_name": "",
                "contact_phone": "",
                "listing_date": listing_date,
            }
        except Exception as e:
            logger.debug(f"parse_item error: {e}", exc_info=True)
            return None

    MAX_LISTING_AGE_DAYS = 7

    def _parse_listing_date(self, date_str) -> Optional[datetime]:
        if not date_str:
            return None
        s = str(date_str).strip()
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y",
        ]:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            pass
        return None

    def _is_recent(self, listing_date) -> bool:
        dt = self._parse_listing_date(listing_date)
        if dt is None:
            return True  # no date info → don't filter out
        return (datetime.now() - dt).days <= self.MAX_LISTING_AGE_DAYS

    async def fetch_new_listings(
        self, search: dict, search_manager, user_id: str, search_id: str
    ) -> list[dict]:
        seen_ids = set(search_manager.get_seen_ids(user_id, search_id))
        is_first_run = len(seen_ids) == 0

        all_listings = await self.fetch_listings(search)

        # Drop listings older than MAX_LISTING_AGE_DAYS (when date is available)
        fresh = [l for l in all_listings if self._is_recent(l.get("listing_date"))]

        if is_first_run:
            # Mark everything as seen; send the 10 most recent as welcome batch
            search_manager.mark_seen(user_id, search_id, [l["id"] for l in all_listings])
            logger.info(
                f"First run {user_id}/{search_id}: marked {len(all_listings)} seen, "
                f"sending top {min(10, len(fresh))} fresh"
            )
            return fresh[:10]

        new_listings = [l for l in fresh if l["id"] not in seen_ids]
        if new_listings:
            search_manager.mark_seen(user_id, search_id, [l["id"] for l in new_listings])
        logger.info(f"Poll {user_id}/{search_id}: {len(fresh)} fresh, {len(new_listings)} new")
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

            sample_photo = None
            sample_date = None
            if listings:
                first = listings[0]
                sample_photo = first.get("photo_url")
                sample_date = first.get("listing_date")

            return {
                "status": response.status_code,
                "url": str(response.url),
                "html_length": len(html),
                "has_next_data": nd_present,
                "is_captcha": "shieldsquare" in html.lower() and not nd_present,
                "listings_found": len(listings),
                "title": title.group(1) if title else "N/A",
                "sample_photo_url": sample_photo,
                "sample_listing_date": sample_date,
                "html_preview": html[:300],
            }
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        if self._session:
            await self._session.close()
