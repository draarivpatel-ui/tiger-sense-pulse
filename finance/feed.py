"""Parsing and pacing for the keyless CoinGecko price feed (standard library only, so it is unit-testable offline).

Feed: GET https://api.coingecko.com/api/v3/simple/price  (CoinGecko Keyless Public API: no key, no sign-up)
Data provided by CoinGecko: https://www.coingecko.com/en/api
"""
import json
from collections import namedtuple
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

BASE_URL = "https://api.coingecko.com/api/v3/simple/price"

# CoinGecko coin id -> symbol stored in crypto_ticks
COINS = {"bitcoin": "BTC-USD", "ethereum": "ETH-USD", "solana": "SOL-USD"}

# Pacing. The brief caps us at 1 request/second; CoinGecko's keyless pool is far
# tighter (~10-30 calls/min per IP), so the default is one request every 20 s
# (3 calls/min) for all coins at once.
MIN_INTERVAL_S = 1.0
DEFAULT_INTERVAL_S = 20.0
MAX_BACKOFF_S = 120.0


class RateLimited(Exception):
    """The feed answered 429 (or a body with error_code 429)."""


class FeedError(Exception):
    """The feed answered with an error body we cannot use."""


class Blocked(Exception):
    """The feed answered HTTP 403 (CoinGecko can bot-block scripted clients)."""


UNAVAILABLE = "live prices unavailable"

# One poll's outcome: ticks to show, whether they are live, the HTTP-ish status (200/403/429) and a note.
PollResult = namedtuple("PollResult", "ticks live status note")


def build_url(coin_ids):
    q = {
        "ids": ",".join(coin_ids),
        "vs_currencies": "usd",
        "include_24hr_vol": "true",
        "include_last_updated_at": "true",
        "precision": "full",
    }
    return BASE_URL + "?" + urllib.parse.urlencode(q, safe=",")


def clamp_interval(seconds):
    """Never poll faster than MIN_INTERVAL_S (<= 1 request/second)."""
    return max(MIN_INTERVAL_S, float(seconds))


def backoff_seconds(attempt, base=DEFAULT_INTERVAL_S):
    """Exponential backoff after the n-th consecutive 429 (attempt starts at 1), capped."""
    return min(MAX_BACKOFF_S, base * (2 ** max(0, attempt - 1)))


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def parse_simple_price(payload, coins=COINS):
    """Turn a /simple/price JSON body into ticks.

    Returns a list of dicts {time, symbol, price, volume_24h_usd} sorted by symbol.
    Coins that are missing, have no positive price, or no last_updated_at are skipped.
    Raises RateLimited / FeedError for error bodies.
    """
    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise FeedError("unexpected payload type %s" % type(payload).__name__)
    status = payload.get("status")
    if isinstance(status, dict) and "error_code" in status:
        if status.get("error_code") == 429:
            raise RateLimited(status.get("error_message", "rate limited"))
        raise FeedError("feed error %s: %s" % (status.get("error_code"), status.get("error_message")))
    ticks = []
    for coin_id, symbol in coins.items():
        row = payload.get(coin_id)
        if not isinstance(row, dict):
            continue
        price = _decimal(row.get("usd"))
        ts = row.get("last_updated_at")
        if price is None or price <= 0 or not isinstance(ts, (int, float)) or isinstance(ts, bool) or ts <= 0:
            continue
        vol = _decimal(row.get("usd_24h_vol"))
        ticks.append({
            "time": datetime.fromtimestamp(int(ts), tz=timezone.utc),
            "symbol": symbol,
            "price": price,
            "volume_24h_usd": vol if vol is not None and vol >= 0 else None,
        })
    return sorted(ticks, key=lambda t: t["symbol"])


def new_ticks(ticks, last_seen):
    """Keep only ticks newer than the last one seen for that symbol; updates last_seen in place."""
    fresh = []
    for t in ticks:
        prev = last_seen.get(t["symbol"])
        if prev is None or t["time"] > prev:
            fresh.append(t)
            last_seen[t["symbol"]] = t["time"]
    return fresh


def fetch(url, timeout=15):
    """One HTTP GET. Returns parsed JSON; raises RateLimited on HTTP 429."""
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "tiger-sense-pulse-finance/1.0 (student project)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited("HTTP 429")
        if e.code == 403:
            raise Blocked("HTTP 403")
        raise


def poll(url, last_good, fetcher=fetch):
    """One request with a fallback for HTTP 403 (blocked) and 429 (rate limited).

    last_good maps symbol -> the newest live tick seen; it is updated in place on success.
    On success: PollResult(fresh ticks, live=True, status=200, note=None).
    On 403/429 (HTTP status or a 429 error body): PollResult(last good ticks sorted by symbol, live=False,
    status, note) where note starts with "live prices unavailable" and says which prices are shown instead.
    Fallback ticks are copies of real earlier updates, never new data: callers must not store them again.
    Other errors propagate unchanged.
    """
    try:
        ticks = parse_simple_price(fetcher(url))
    except Blocked:
        status, why = 403, "HTTP 403, request blocked by CoinGecko"
    except RateLimited:
        status, why = 429, "HTTP 429, rate limited by CoinGecko"
    else:
        for t in ticks:
            prev = last_good.get(t["symbol"])
            if prev is None or t["time"] >= prev["time"]:
                last_good[t["symbol"]] = t
        return PollResult(ticks, True, 200, None)
    cached = sorted(last_good.values(), key=lambda t: t["symbol"])
    if cached:
        newest = max(t["time"] for t in cached).strftime("%H:%M:%S UTC")
        shown = "showing last good prices from %s" % newest
    else:
        shown = "no cached prices yet"
    return PollResult(cached, False, status, "%s (%s); %s" % (UNAVAILABLE, why, shown))
