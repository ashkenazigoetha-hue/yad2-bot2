"""Telegram listing card V2.

The renderer is deliberately a pure function with no Telegram/network imports so
it can be golden-snapshot tested. `bot.send_listing` calls `render_card` and only
handles transport.

Two rules drive the whole module:

1.  **Nothing is silently dropped.** Every field in `MANDATORY_FIELDS` appears in
    every card. When the source did not supply a value we print `לא פורסם` and
    record the field in `missing_fields`. The renderer never guesses, never
    infers and never lets a field vanish because it happened to be falsy.
2.  **Listing facts and search criteria never mix.** A search for 2024–2026 is
    not a fact about a 2024 car, so the search range only ever appears under
    "למה קיבלת אותה?".

Output is Telegram **HTML**, not Markdown. Scraped titles routinely contain `*`,
`_` and `[`, which silently corrupt legacy Markdown; HTML needs only `& < >`
escaped, which `esc()` does unconditionally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable, Optional

# Israel is UTC+3 (IDT) / UTC+2 (IST). Timestamps are stored UTC and displayed
# in Asia/Jerusalem per the spec. zoneinfo needs tzdata on some platforms, so
# fall back to a fixed offset rather than crash a delivery over a timezone.
try:  # pragma: no cover - platform dependent
    from zoneinfo import ZoneInfo

    _IL_TZ: Any = ZoneInfo("Asia/Jerusalem")
except Exception:  # pragma: no cover
    _IL_TZ = timezone(timedelta(hours=3))

NOT_PUBLISHED = "לא פורסם"

# The information contract. Every one of these renders in every card.
MANDATORY_FIELDS = (
    "vehicle_name",
    "variant_or_trim",
    "year",
    "price_current",
    "hand",
    "mileage_km",
    "ownership",
    "engine",
    "horsepower",
    "source_published_at",
)

EVENT_NEW = "new"
EVENT_PRICE_DROP = "price_drop"
EVENT_PRICE_RISE = "price_rise"
EVENT_RELISTED = "relisted"

_STATUS_LINE = {
    EVENT_NEW: "🚘 מודעה חדשה",
    EVENT_PRICE_DROP: "🔻 המחיר ירד",
    EVENT_PRICE_RISE: "🔺 המחיר עלה",
    EVENT_RELISTED: "🔁 פורסמה מחדש",
}


@dataclass
class Card:
    text: str
    missing_fields: list[str] = field(default_factory=list)
    event: str = EVENT_NEW


def esc(value: Any) -> str:
    """Escape for Telegram HTML. Applied to every interpolated value."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _present(value: Any) -> bool:
    """A value counts as supplied only if it carries real information.

    0 km and hand 0 are legitimate values, so this deliberately does not use
    plain truthiness — that bug is exactly how fields go missing today.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ("", "-", "N/A", "לא צוין")
    return True


def _fmt_int(value: Any) -> Optional[str]:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return None


def _to_il(dt: Any) -> Optional[datetime]:
    if isinstance(dt, datetime):
        aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return aware.astimezone(_IL_TZ)
    if isinstance(dt, str) and dt.strip():
        raw = dt.strip().replace("Z", "+00:00")
        for parse in (datetime.fromisoformat,):
            try:
                parsed = parse(raw)
            except ValueError:
                continue
            aware = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            return aware.astimezone(_IL_TZ)
    return None


def _fmt_dt(dt: Any, with_time: bool = True) -> Optional[str]:
    local = _to_il(dt)
    if local is None:
        return None
    return local.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def _engine_text(listing: dict) -> Optional[str]:
    """Displacement + fuel/powertrain, only from values the source supplied."""
    parts: list[str] = []
    cc = listing.get("engine_displacement", listing.get("engine_cc"))
    if _present(cc):
        try:
            parts.append(f"{round(int(cc) / 1000, 1)} ל׳")
        except (TypeError, ValueError):
            pass
    fuel = listing.get("fuel_or_powertrain", listing.get("engine_type"))
    if _present(fuel):
        parts.append(str(fuel).strip())
    if listing.get("turbo"):
        parts.append("טורבו")
    return " · ".join(parts) if parts else None


def price_delta(previous: Any, current: Any) -> Optional[tuple[int, float]]:
    """(absolute, percent) or None when either side is unusable.

    Guards the spec rule: never compute a delta from an invalid price.
    """
    try:
        prev, cur = int(previous), int(current)
    except (TypeError, ValueError):
        return None
    if prev <= 0 or cur <= 0 or prev == cur:
        return None
    return cur - prev, (cur - prev) / prev * 100.0


def render_card(
    listing: dict,
    *,
    search_name: Optional[str] = None,
    event: str = EVENT_NEW,
    match_reasons: Optional[Iterable[str]] = None,
    source: str = "יד2",
    detected_at: Any = None,
    last_checked_at: Any = None,
) -> Card:
    """Render one listing card. Returns the text plus the missing-field audit."""
    missing: list[str] = []
    lines: list[str] = []

    def note_missing(name: str) -> str:
        missing.append(name)
        return NOT_PUBLISHED

    # ── 1. status ────────────────────────────────────────────────────────────
    price_prev = listing.get("price_previous")
    price_now = listing.get("price_current", listing.get("price"))
    if event == EVENT_NEW and _present(price_prev):
        delta = price_delta(price_prev, price_now)
        if delta:
            event = EVENT_PRICE_DROP if delta[0] < 0 else EVENT_PRICE_RISE
    lines.append(f"<b>{esc(_STATUS_LINE.get(event, _STATUS_LINE[EVENT_NEW]))}</b>")

    # ── 2. vehicle identity ──────────────────────────────────────────────────
    name = listing.get("vehicle_name")
    if not _present(name):
        make, model = listing.get("make"), listing.get("model", listing.get("model_text"))
        name = " ".join(p for p in (make, model) if _present(p)) or listing.get("title")
    name = name if _present(name) else note_missing("vehicle_name")

    trim = listing.get("variant_or_trim", listing.get("trim"))
    trim = trim if _present(trim) else note_missing("variant_or_trim")

    headline = esc(name)
    if trim != NOT_PUBLISHED:
        headline += f" {esc(trim)}"
    lines.append(f"<b>{headline}</b>")
    if trim == NOT_PUBLISHED:
        lines.append(f"גרסה/רמת גימור: {NOT_PUBLISHED}")

    # ── 3. price ─────────────────────────────────────────────────────────────
    lines.append("")
    price_txt = _fmt_int(price_now)
    if price_txt is None:
        missing.append("price_current")
        lines.append("<b>מחיר לא פורסם</b>")
    elif event in (EVENT_PRICE_DROP, EVENT_PRICE_RISE):
        delta = price_delta(price_prev, price_now)
        lines.append(f"<b>₪{price_txt} מחיר חדש</b>")
        prev_txt = _fmt_int(price_prev)
        if delta and prev_txt:
            direction = "ירידה" if delta[0] < 0 else "עלייה"
            lines.append(
                f"<s>₪{prev_txt}</s> מחיר קודם · {direction} של "
                f"₪{abs(delta[0]):,} ({abs(delta[1]):.1f}%)"
            )
        elif prev_txt:
            lines.append(f"<s>₪{prev_txt}</s> מחיר קודם")
    else:
        lines.append(f"<b>₪{price_txt}</b>")

    # ── 4. key facts — every one printed, missing ones marked ────────────────
    year = listing.get("year")
    year_txt = str(year) if _present(year) else note_missing("year")

    km = listing.get("mileage_km", listing.get("km"))
    km_txt = f"{_fmt_int(km)} ק״מ" if _fmt_int(km) is not None else note_missing("mileage_km")

    hand = listing.get("hand_text") if _present(listing.get("hand_text")) else listing.get("hand")
    hand_txt = (
        f"יד {esc(hand)}" if _present(hand) and "יד" not in str(hand) else esc(hand)
    ) if _present(hand) else note_missing("hand")

    ownership = listing.get("ownership")
    ownership_txt = esc(ownership) if _present(ownership) else note_missing("ownership")

    lines.append("")
    lines.append(" · ".join([esc(year_txt), esc(km_txt), hand_txt, ownership_txt]))

    engine = _engine_text(listing)
    if engine is None:
        engine = note_missing("engine")
    hp = listing.get("horsepower")
    hp_txt = f'{esc(hp)} כ״ס' if _present(hp) else note_missing("horsepower")
    lines.append(f"מנוע: {esc(engine)} · {hp_txt}")

    area = listing.get("area", listing.get("city"))
    if _present(area):
        lines.append(f"אזור {esc(area)}")

    if _present(listing.get("test_date")):
        lines.append(f"טסט עד: {esc(listing['test_date'])}")

    # ── 5. why it was sent — search criteria live HERE, never above ──────────
    reasons = [r for r in (match_reasons or []) if _present(r)]
    if reasons:
        lines.append("")
        lines.append("<b>למה קיבלת אותה?</b>")
        lines.append(esc(" · ".join(reasons)))

    # ── 6. source & freshness ────────────────────────────────────────────────
    lines.append("")
    published = _fmt_dt(listing.get("source_published_at", listing.get("listing_date")))
    if published is None:
        missing.append("source_published_at")
        lines.append(f"פורסמה במקור: {NOT_PUBLISHED}")
    else:
        lines.append(f"פורסמה במקור: {published}")

    tail = [f"מקור: {esc(source)}"]
    detected = _fmt_dt(detected_at)
    if detected and detected != published:
        tail.append(f"זוהתה אצלנו {detected}")
    checked = _fmt_dt(last_checked_at)
    if checked and checked != published:
        tail.append(f"נבדקה לאחרונה {checked}")
    lines.append(" · ".join(tail))

    if _present(search_name):
        lines.append(f"חיפוש: {esc(search_name)}")

    # Free text last so a caption limit never truncates a mandatory fact.
    if _present(listing.get("features")):
        lines.append("")
        lines.append(f"תוספות: {esc(str(listing['features'])[:220])}")
    if _present(listing.get("description")):
        lines.append(f"הערות המוכר: {esc(str(listing['description'])[:240])}")

    return Card(text="\n".join(lines), missing_fields=missing, event=event)


# Telegram hard limits: 1024 for a photo caption, 4096 for a text message.
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def fit(text: str, limit: int = CAPTION_LIMIT) -> str:
    """Trim to a Telegram limit on a line boundary without splitting a tag."""
    if len(text) <= limit:
        return text
    kept: list[str] = []
    used = 0
    for line in text.split("\n"):
        if used + len(line) + 1 > limit - 1:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept) + "…"
