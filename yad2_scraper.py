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
    "mg": "אם ג'י", "ssangyong": "סאנגיונג", "daihatsu": "דייהטסו",
    "cupra": "קופרה", "genesis": "ג'נסיס", "gmc": "ג'י.אם.סי",
    "ds": "די.אס", "smart": "סמארט", "buick": "ביואיק",
    "ram": "ראם", "maserati": "מזראטי", "abarth": "אבארט",
    "lamborghini": "למבורגיני", "isuzu": "איסוזו",
}

YAD2_MANUFACTURER_IDS = {
    "אאודי": 1, "אופל": 2, "אינפיניטי": 3, "איסוזו": 4,
    "אלפא רומיאו": 5, "אם ג'י": 6, "ב.מ.וו": 7, "ב מ וו": 7,
    "ביואיק": 8, "ג'י.אם.סי": 9, "ג'יפ": 10, "דאצ'יה": 12, "דודג'": 13,
    "די.אס": 14, "דייהטסו": 15, "הונדה": 17, "וולוו": 18,
    "טויוטה": 19, "יגואר": 20, "יונדאי": 21, "לנד רובר": 24,
    "לקסוס": 26, "מאזדה": 27, "מזראטי": 28, "מיני": 29,
    "מיצובישי": 30, "מרצדס-בנץ": 31, "מרצדס": 31,
    "ניסאן": 32, "סאנגיונג": 34, "סובארו": 35, "סוזוקי": 36,
    "סיאט": 37, "סיטרואן": 38, "סמארט": 39, "סקודה": 40,
    "פולקסווגן": 41, "פורד": 43, "פורשה": 44, "פיאט": 45,
    "פיג'ו": 46, "קאדילק": 47, "קיה": 48, "קרייזלר": 49,
    "ראם": 91, "רנו": 51, "שברולט": 52, "אבארט": 53,
    "טסלה": 62, "למבורגיני": 63, "קופרה": 92, "ג'נסיס": 93,
}

# (manufacturer_hebrew, MODEL_NAME_UPPER) -> yad2 numeric model id
YAD2_MODEL_IDS: dict = {
    ("אאודי", "A1"): 10003, ("אאודי", "A3"): 10004, ("אאודי", "A4"): 10005, ("אאודי", "A5"): 10006,
    ("אאודי", "E-TRON"): 10010, ("אאודי", "Q2"): 10011, ("אאודי", "Q3"): 10012,
    ("אאודי", "Q4 E-TRON"): 10883, ("אאודי", "Q5"): 10013, ("אאודי", "Q7"): 10014,
    ("אאודי", "Q8 E-TRON"): 13069, ("אאודי", "RS 3"): 10017, ("אאודי", "RS Q8"): 10022,
    ("אאודי", "S3"): 10024, ("אאודי", "TT"): 10033,
    ("אופל", "אדם"): 10034, ("אופל", "אסטרה"): 10035, ("אופל", "גרנדלנד"): 10041,
    ("אופל", "זאפירה"): 10051, ("אופל", "מוקה"): 10045, ("אופל", "מריבה"): 10044,
    ("אופל", "קומבו"): 10037, ("אופל", "קורסה"): 10038, ("אופל", "קרוסלנד"): 10899,
    ("אינפיניטי", "EX37"): 10914, ("אינפיניטי", "FX37"): 13124, ("אינפיניטי", "G37"): 10053,
    ("אינפיניטי", "Q30"): 10055, ("אינפיניטי", "Q50"): 10056, ("אינפיניטי", "QX50"): 10060,
    ("אינפיניטי", "QX60"): 10062, ("אינפיניטי", "QX70"): 10063,
    ("אלפא רומיאו", "ג'וליה"): 10080, ("אלפא רומיאו", "ג'ולייטה"): 10081,
    ("אלפא רומיאו", "סטלביו"): 10086, ("אלפא רומיאו", "מיטו"): 10084,
    ("ב.מ.וו", "IX3"): 10965, ("ב.מ.וו", "IX1"): 13135, ("ב.מ.וו", "iX"): 10964,
    ("ב.מ.וו", "i4"): 10963, ("ב.מ.וו", "i7"): 13013, ("ב.מ.וו", "i8"): 10104,
    ("ב.מ.וו", "I5"): 13309, ("ב.מ.וו", "XM"): 13121,
    ("ב.מ.וו", "M2"): 10105, ("ב.מ.וו", "M3"): 10106, ("ב.מ.וו", "M4"): 10107,
    ("ב.מ.וו", "M5"): 10108, ("ב.מ.וו", "M8"): 10110,
    ("ב.מ.וו", "X1"): 10111, ("ב.מ.וו", "X2"): 10112, ("ב.מ.וו", "X3"): 10113,
    ("ב.מ.וו", "X4"): 10114, ("ב.מ.וו", "X5"): 10116,
    ("ב.מ.וו", "X6"): 10118, ("ב.מ.וו", "X6 M"): 10119,
    ("ב.מ.וו", "X7"): 10120, ("ב.מ.וו", "Z4"): 10122,
    ("ב.מ.וו", "סדרה 1"): 10095, ("ב.מ.וו", "סדרה 2"): 10096,
    ("ב.מ.וו", "סדרה 3"): 10097, ("ב.מ.וו", "סדרה 4"): 10098,
    ("ב.מ.וו", "סדרה 5"): 10099, ("ב.מ.וו", "סדרה 6"): 10100,
    ("ב.מ.וו", "סדרה 7"): 10101, ("ב.מ.וו", "סדרה 8"): 10102,
    ("ג'יפ", "גלדיאטור"): 10143, ("ג'יפ", "גרנד צ'ירוקי"): 10144,
    ("ג'יפ", "קומפאס"): 10142, ("ג'יפ", "רנגלר"): 10147,
    ("דאצ'יה", "דאסטר"): 10154, ("דאצ'יה", "דוקר"): 10153, ("דאצ'יה", "לודג'י"): 10155,
    ("דודג'", "דורנגו"): 10163, ("דודג'", "צ'ארג'ר"): 10162, ("דודג'", "צ'לנג'ר"): 10161,
    ("הונדה", "CR-V"): 10183, ("הונדה", "אקורד"): 10181, ("הונדה", "ג'אז"): 10188,
    ("הונדה", "סיוויק"): 10182, ("הונדה", "סיטי"): 11069,
    ("וולוו", "C40"): 11127, ("וולוו", "S60"): 10203, ("וולוו", "V60"): 10209,
    ("וולוו", "XC40"): 10212, ("וולוו", "XC60"): 10213, ("וולוו", "XC90"): 10215,
    ("טויוטה", "C-HR"): 10225, ("טויוטה", "RAV4"): 10238, ("טויוטה", "bZ4X"): 12894,
    ("טויוטה", "FJ קרוזר"): 10228, ("טויוטה", "אוולון"): 10219,
    ("טויוטה", "אוונסיס"): 10220, ("טויוטה", "אוריס"): 10218,
    ("טויוטה", "אייגו"): 10221, ("טויוטה", "אייגו X"): 12897,
    ("טויוטה", "היילנדר"): 10230, ("טויוטה", "היילקס"): 10231,
    ("טויוטה", "יאריס"): 10247, ("טויוטה", "יאריס קרוס"): 11228,
    ("טויוטה", "לנד קרוזר"): 10233, ("טויוטה", "סיינה"): 10240,
    ("טויוטה", "סקויה"): 10239, ("טויוטה", "פרואייס"): 13093,
    ("טויוטה", "פרואייס סיטי"): 10237, ("טויוטה", "פריוס"): 10236,
    ("טויוטה", "פריוס פלוס"): 13238, ("טויוטה", "קאמרי"): 10222,
    ("טויוטה", "קורולה"): 10226, ("טויוטה", "קורולה קרוס"): 11150,
    ("יגואר", "E-PACE"): 10248, ("יגואר", "F-PACE"): 10249, ("יגואר", "XE"): 10254,
    ("יגואר", "XF"): 10255,
    ("יונדאי", "I10"): 10272, ("יונדאי", "I20"): 10273, ("יונדאי", "I30"): 10276,
    ("יונדאי", "I35"): 13276, ("יונדאי", "ix35"): 10281,
    ("יונדאי", "איוניק"): 10279, ("יונדאי", "איוניק 5"): 11239, ("יונדאי", "איוניק 6"): 13099,
    ("יונדאי", "אלנטרה"): 10263, ("יונדאי", "אקסנט i25"): 10259,
    ("יונדאי", "באיון"): 11234, ("יונדאי", "וניו"): 10293,
    ("יונדאי", "טוסון"): 10291, ("יונדאי", "H-1 / I800"): 10268,
    ("יונדאי", "קונה"): 10283, ("יונדאי", "סנטה פה"): 10287, ("יונדאי", "סונטה"): 10288,
    ("לנד רובר", "דיסקברי"): 10304, ("לנד רובר", "דיפנדר"): 10303,
    ("לנד רובר", "ריינג' רובר"): 10307, ("לנד רובר", "ריינג' רובר ספורט"): 10309,
    ("לקסוס", "ES"): 10318, ("לקסוס", "IS"): 10321, ("לקסוס", "NX"): 10325,
    ("לקסוס", "RX"): 10327, ("לקסוס", "UX"): 10329,
    ("מאזדה", "2"): 10331, ("מאזדה", "3"): 10332, ("מאזדה", "6"): 10335,
    ("מאזדה", "CX-5"): 10342, ("מאזדה", "CX-30"): 10341,
    ("מיני", "קופר"): 10360, ("מיני", "קאנטרימן"): 10361,
    ("מיצובישי", "ASX"): 10366, ("מיצובישי", "אאוטלנדר"): 10381,
    ("מיצובישי", "לנסר"): 10379,
    ("מרצדס", "C-CLASS"): 10394, ("מרצדס", "CLA"): 10397, ("מרצדס", "E-CLASS"): 10401,
    ("מרצדס", "EQA"): 11412, ("מרצדס", "EQC"): 10402, ("מרצדס", "GLA"): 10405,
    ("מרצדס", "GLC"): 10407, ("מרצדס", "GLE"): 10408, ("מרצדס", "S-CLASS"): 10414,
    ("ניסאן", "אקס טרייל"): 10457, ("ניסאן", "ג'וק"): 10433, ("ניסאן", "קשקאי"): 10449,
    ("ניסאן", "סנטרה"): 10451,
    ("סובארו", "פורסטר"): 10476, ("סובארו", "XV"): 10485,
    ("סוזוקי", "ג'ימני"): 10493, ("סוזוקי", "ויטרה"): 10499, ("סוזוקי", "סוויפט"): 10497,
    ("סיאט", "לאון"): 10509, ("סיאט", "איביזה"): 10507, ("סיאט", "ארונה"): 10504,
    ("סיטרואן", "C3"): 10517, ("סיטרואן", "C4"): 10518, ("סיטרואן", "C5 איירקרוס"): 11551,
    ("סקודה", "אוקטביה"): 10547, ("סקודה", "קודיאק"): 10546, ("סקודה", "קארוק"): 10545,
    ("סקודה", "סופרב"): 10551,
    ("פולקסווגן", "גולף"): 10562, ("פולקסווגן", "טיגואן"): 10574,
    ("פולקסווגן", "פולו"): 10571, ("פולקסווגן", "פאסאט"): 10568,
    ("פולקסווגן", "ID.4"): 11579, ("פולקסווגן", "T-קרוס"): 10573,
    ("פורד", "פוקוס"): 10598, ("פורד", "קוגה"): 10601, ("פורד", "מוסטנג"): 10604,
    ("פורשה", "קאיין"): 10619, ("פורשה", "מקאן"): 10621, ("פורשה", "911"): 10616,
    ("פיאט", "500"): 10627, ("פיאט", "500X"): 10628, ("פיאט", "פנדה"): 10642,
    ("פיג'ו", "208"): 10659, ("פיג'ו", "2008"): 10655, ("פיג'ו", "308"): 10665,
    ("פיג'ו", "3008"): 10661, ("פיג'ו", "5008"): 10669,
    ("קיה", "אופטימה"): 10710, ("קיה", "סיד"): 10698, ("קיה", "סטוניק"): 10722,
    ("קיה", "ספורטז'"): 10720, ("קיה", "ספורטאז'"): 10720,
    ("קיה", "פורטה"): 10701, ("קיה", "פיקנטו"): 10711, ("קיה", "קרניבל"): 10697,
    ("קיה", "ריו"): 10714, ("קיה", "נירו"): 10708, ("קיה", "נירו פלוס"): 13158,
    ("קיה", "סורנטו"): 10718, ("קיה", "סלטוס"): 10715,
    ("רנו", "קליאו"): 10751, ("רנו", "מגאן"): 10762, ("רנו", "קדגא'ר"): 10755,
    ("רנו", "קפצ'ור"): 10750,
    ("שברולט", "אקווינוקס"): 10784, ("שברולט", "בלייזר"): 10774,
    ("טסלה", "מודל 3"): 10846, ("טסלה", "מודל X"): 10848, ("טסלה", "מודל Y"): 11942,
    # אם ג'י (MG)
    ("אם ג'י", "350"): 10087, ("אם ג'י", "EHS PHEV"): 13059,
    ("אם ג'י", "MG3"): 10089, ("אם ג'י", "MG4"): 13065, ("אם ג'י", "MG5"): 10952,
    ("אם ג'י", "S6"): 13833, ("אם ג'י", "S9"): 13844, ("אם ג'י", "ZS"): 10093,
    ("אם ג'י", "מארוול R"): 12880, ("אם ג'י", "סייברסטר"): 13413,
    # דייהטסו
    ("דייהטסו", "טריוס"): 10177, ("דייהטסו", "מאטריה"): 10175, ("דייהטסו", "סיריון"): 10176,
    # סאנגיונג
    ("סאנגיונג", "אקטיון"): 10462, ("סאנגיונג", "טיבולי"): 10469,
    ("סאנגיונג", "מוסו"): 10466, ("סאנגיונג", "קורנדו"): 10464,
    ("סאנגיונג", "רודיוס"): 10468, ("סאנגיונג", "רקסטון"): 10467,
    # קופרה
    ("קופרה", "אטקה"): 12132, ("קופרה", "בורן"): 12133, ("קופרה", "טווסקאן"): 13133,
    ("קופרה", "לאון"): 12135, ("קופרה", "פורמנטור"): 12134,
    # English aliases — website stores these names, bot needs to resolve them to IDs
    ("יונדאי", "IONIQ"): 10279, ("יונדאי", "IONIQ 5"): 11239, ("יונדאי", "IONIQ 6"): 13099,
    ("יונדאי", "BAYON"): 11234, ("יונדאי", "VENUE"): 10293,
    ("יונדאי", "SANTA FE"): 10287, ("יונדאי", "KONA"): 10283,
    ("קיה", "CEED"): 10698, ("קיה", "PROCEED"): 10698, ("קיה", "CARNIVAL"): 10697,
    ("קיה", "NIRO"): 10708, ("קיה", "SPORTAGE"): 10720,
    ("לנד רובר", "DEFENDER"): 10303, ("לנד רובר", "DISCOVERY"): 10304,
    ("לנד רובר", "RANGE ROVER"): 10307, ("לנד רובר", "RANGE ROVER SPORT"): 10309,
    ("סובארו", "FORESTER"): 10476,
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
    # English model names used by the website that map to Hebrew yad2 names
    "ioniq": "איוניק", "ioniq 5": "איוניק 5", "ioniq 6": "איוניק 6",
    "bayon": "באיון", "venue": "וניו",
    "ceed": "סיד", "proceed": "סיד", "carnival": "קרניבל", "niro": "נירו",
    "santa fe": "סנטה פה", "kona": "קונה",
    "range rover": "ריינג' רובר", "defender": "דיפנדר", "discovery": "דיסקברי",
    "forester": "פורסטר",
}


# Words we use in sub_model labels → how they appear in Yad2 trim text
SUBMODEL_SYNONYMS: dict[str, list[str]] = {
    "sportback": ["האצ'בק", "sportback", "5 דל"],
    "sedan":     ["סדאן", "sedan", "4 דל"],
    "avant":     ["אוואנט", "avant"],
    "allroad":   ["אולרוד", "allroad"],
    "cabriolet": ["קבריולט", "cabriolet", "cabrio"],
    "coupe":     ["קופה", "coupe"],
    "phev":      ["phev", "plug-in", "פלאג"],
    "hybrid":    ["היברידי", "hybrid"],
    "electric":  ["חשמלי", "electric", "ev"],
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

        manufacturer = str(search.get("manufacturer") or "").strip()
        if manufacturer:
            if manufacturer.isdigit():
                params["manufacturer"] = int(manufacturer)
            else:
                heb = MANUFACTURER_MAP.get(manufacturer.lower(), manufacturer)
                mid = YAD2_MANUFACTURER_IDS.get(heb)
                if mid:
                    params["manufacturer"] = mid
                elif heb:
                    params["manufacturer"] = heb

        # yad2 only accepts numeric model IDs — look up from table or use directly if numeric
        model = str(search.get("model") or "").strip()
        if model:
            if model.isdigit():
                params["model"] = int(model)
            else:
                # Resolve Hebrew manufacturer name for model table lookup
                if manufacturer.isdigit():
                    heb_mfr = next(
                        (k for k, v in YAD2_MANUFACTURER_IDS.items() if v == int(manufacturer)),
                        manufacturer,
                    )
                else:
                    heb_mfr = MANUFACTURER_MAP.get(manufacturer.lower(), manufacturer)
                # Strip manufacturer prefix if model was saved with it (e.g. "מאזדה 3" → "3")
                model_stripped = model
                if heb_mfr and model.startswith(heb_mfr):
                    model_stripped = model[len(heb_mfr):].strip()
                model_id = (
                    YAD2_MODEL_IDS.get((heb_mfr, model_stripped.upper()))
                    or YAD2_MODEL_IDS.get((heb_mfr, model.upper()))
                )
                if model_id:
                    params["model"] = model_id
                    logger.info(f"Resolved model '{model}' → ID {model_id}")

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
        """Client-side full filter: model, sub_model, price, year. km is checked separately after enrichment."""
        wanted_model = str(search.get("model") or "").strip()
        wanted_sub = str(search.get("sub_model") or "").strip()

        if wanted_model and not wanted_model.isdigit():
            normalized = self._normalize_model(wanted_model)
            listing_model = str(listing.get("model_text") or "").strip()
            wl = wanted_model.lower()
            nl = normalized.lower()
            ll = listing_model.lower()

            def _word_match(pattern: str, text: str) -> bool:
                return bool(re.search(r'(?<!\w)' + re.escape(pattern) + r'(?!\w)', text, re.IGNORECASE))

            if not (_word_match(wl, ll) or _word_match(ll, wl) or _word_match(nl, ll) or _word_match(ll, nl)):
                return False

        if wanted_sub and not wanted_sub.isdigit():
            listing_trim = str(listing.get("trim") or "").strip().lower()
            for token in wanted_sub.lower().split():
                synonyms = SUBMODEL_SYNONYMS.get(token, [token])
                if not any(syn in listing_trim for syn in synonyms):
                    return False

        # Price range
        price = listing.get("price")
        if price is not None:
            try:
                p = int(price)
                if search.get("price_min") and p < int(search["price_min"]):
                    return False
                if search.get("price_max") and p > int(search["price_max"]):
                    return False
            except (ValueError, TypeError):
                pass

        # Year range
        year = listing.get("year")
        if year is not None:
            try:
                y = int(year)
                if search.get("year_min") and y < int(search["year_min"]):
                    return False
                if search.get("year_max") and y > int(search["year_max"]):
                    return False
            except (ValueError, TypeError):
                pass

        return True

    async def _fetch_item_km(self, token: str) -> Optional[int]:
        """Fetch km for a single listing by loading its detail page."""
        try:
            session = await self._get_session()
            r = await session.get(
                f"https://www.yad2.co.il/item/{token}",
                impersonate="chrome124",
                headers={"Accept-Language": "he-IL,he;q=0.9"},
                timeout=12,
            )
            if r.status_code != 200:
                return None
            nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if not nd:
                return None
            data = json.loads(nd.group(1))
            queries = (data.get("props", {}).get("pageProps", {})
                       .get("dehydratedState", {}).get("queries", []))
            for q in queries:
                if q.get("queryKey", [None])[0] == "vehicles":
                    return q["state"]["data"].get("km")
        except Exception as e:
            logger.debug(f"_fetch_item_km {token}: {e}")
        return None

    async def enrich_with_km(self, listings: list[dict]) -> list[dict]:
        """Fetch km for each listing, max 3 concurrent to avoid rate-limiting."""
        import asyncio as _asyncio
        if not listings:
            return listings
        sem = _asyncio.Semaphore(3)

        async def _limited(token: str):
            async with sem:
                return await self._fetch_item_km(token)

        km_values = await _asyncio.gather(
            *[_limited(l["id"]) for l in listings],
            return_exceptions=True,
        )
        for listing, km in zip(listings, km_values):
            if isinstance(km, int):
                listing["km"] = km
        return listings

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
            if "shieldsquare" in html.lower() or "captcha" in html.lower():
                logger.warning(f"ShieldSquare/CAPTCHA detected on {url[:80]} — bot is being blocked")
            else:
                logger.warning(f"No __NEXT_DATA__ (status={response.status_code}) on {url[:80]} — wrong page or blocked")
            return []
        return self._parse_page(html)

    async def fetch_listings(self, search: dict, seen_ids: set = None) -> list[dict]:
        try:
            params = self._build_params(search)
            # Sort by newest first so fresh listings appear on page 1
            params["order"] = "date"
            wanted_model = str(search.get("model") or "").strip()
            wanted_sub = str(search.get("sub_model") or "").strip()

            all_results: list[dict] = []
            # Promoted/boost listings dominate pages 1-2; new organic listings land on page 3+.
            # Fetch up to 5 pages, but stop early once a full page contains only already-seen IDs.
            max_pages = 5
            for page in range(1, max_pages + 1):
                p = dict(params)
                if page > 1:
                    p["page"] = page
                url = f"{YAD2_SEARCH_URL}?{urlencode(p)}" if p else YAD2_SEARCH_URL
                page_results = await self._fetch_url(url)
                if not page_results:
                    break
                all_results.extend(page_results)

                # Smart early stop: once past page 1, if every listing on this page was
                # already seen, there's no point going deeper — new listings would have
                # appeared earlier in the date-sorted feed.
                if seen_ids is not None and page >= 2 and page_results:
                    new_on_page = [r for r in page_results if r["id"] not in seen_ids]
                    if not new_on_page:
                        logger.info(f"Page {page}: all {len(page_results)} listings already seen — stopping pagination")
                        break

                if len(all_results) > 300:
                    break

            # Deduplicate by id
            seen: set[str] = set()
            unique = []
            for r in all_results:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    unique.append(r)

            # Client-side filter by model / sub_model
            if wanted_model or wanted_sub:
                before = len(unique)
                unique = [r for r in unique if self._matches_search(r, search)]
                logger.info(
                    f"Model filter '{wanted_model}' / sub '{wanted_sub}': "
                    f"{before} → {len(unique)} listings (across {max_pages} pages)"
                )

            return unique
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
            # Fallback: top-level images array (format used in some yad2 responses)
            if not photo_url:
                top_imgs = item.get("images", [])
                if top_imgs and isinstance(top_imgs, list):
                    first = top_imgs[0]
                    if isinstance(first, dict):
                        photo_url = first.get("src") or first.get("url") or first.get("uri") or first.get("thumbnail")
                    elif isinstance(first, str):
                        photo_url = first
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
            ownership = "סוכנות" if ad_type == "commercial" else "פרטית" if ad_type == "private" else ""

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
        # Unix timestamp (int or numeric string)
        try:
            ts = int(date_str)
            if ts > 1_000_000_000:  # sanity check — must be after year 2001
                return datetime.utcfromtimestamp(ts)  # yad2 timestamps are UTC
        except (ValueError, TypeError, OSError):
            pass
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
        return (datetime.utcnow() - dt).days < self.MAX_LISTING_AGE_DAYS

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
