import aiohttp
import asyncio
import time
from typing import Dict, Optional, Tuple

# Supported fiat currencies for display
FIAT_CURRENCIES = ["USD", "EUR", "RUB", "KZT", "GBP", "JPY", "CNY", "AED", "TRY"]

# Supported cryptos
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "TON": "the-open-network",
    "USDT": "tether",
    "XRP": "ripple",
}

# All supported currencies for selection
ALL_CURRENCIES = FIAT_CURRENCIES + list(CRYPTO_IDS.keys()) + ["XAU", "XAG"]


async def fetch_fiat_rates() -> Dict[str, float]:
    """Fetch fiat currency rates (base USD) using open.er-api."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://open.er-api.com/v6/latest/USD",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                if data.get("result") == "success":
                    rates = data.get("rates", {})
                    return {
                        cur: round(rates[cur], 4)
                        for cur in FIAT_CURRENCIES
                        if cur in rates
                    }
    except Exception:
        pass
    return {}


async def fetch_crypto_rates() -> Dict[str, float]:
    """Fetch crypto prices in USD from CoinGecko (free, no key needed)."""
    try:
        ids = ",".join(CRYPTO_IDS.values())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                result = {}
                for symbol, coin_id in CRYPTO_IDS.items():
                    if coin_id in data and "usd" in data[coin_id]:
                        result[symbol] = data[coin_id]["usd"]
                return result
    except Exception:
        pass
    return {}


async def fetch_metals_rates() -> Dict[str, float]:
    """Fetch gold and silver spot prices (USD per troy oz) from metals.live."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.metals.live/v1/spot",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                result = {}
                for item in data:
                    if "gold" in item:
                        result["XAU"] = round(item["gold"], 2)
                    if "silver" in item:
                        result["XAG"] = round(item["silver"], 4)
                return result
    except Exception:
        pass
    return {}


_rates_cache: Dict[str, object] = {"data": None, "fetched_at": 0.0}
_RATES_CACHE_TTL_SECONDS = 60


async def fetch_all_rates() -> Tuple[Dict, Dict, Dict]:
    """Fetch all rates concurrently, with a short-lived cache.

    A single web dashboard page load can trigger several independent calls
    to this (the page itself plus each embedded chart image, each a
    separate HTTP request with no shared state) — without a cache that's
    up to 9 external API calls for one page view. A failed fetch (all
    three dicts empty) is never cached, so a transient outage doesn't get
    "stuck" for the full TTL.
    """
    now = time.monotonic()
    cached = _rates_cache["data"]
    if cached is not None and (now - _rates_cache["fetched_at"]) < _RATES_CACHE_TTL_SECONDS:
        return cached

    fiat, crypto, metals = await asyncio.gather(
        fetch_fiat_rates(),
        fetch_crypto_rates(),
        fetch_metals_rates(),
    )
    if fiat or crypto or metals:
        _rates_cache["data"] = (fiat, crypto, metals)
        _rates_cache["fetched_at"] = now
    return fiat, crypto, metals


def get_usd_rate(currency: str,
                 fiat: Dict, crypto: Dict, metals: Dict) -> Optional[float]:
    """Get how many units of `currency` equal 1 USD."""
    if currency == "USD":
        return 1.0
    if currency in fiat:
        return fiat[currency]
    if currency in crypto:
        # crypto prices are USD per 1 coin → invert for "units per USD"
        price = crypto[currency]
        return (1.0 / price) if price else None
    if currency in metals:
        # metals prices are USD per troy oz → invert
        price = metals[currency]
        return (1.0 / price) if price else None
    return None


def convert_amount(amount: float, from_currency: str, to_currency: str,
                   fiat: Dict, crypto: Dict, metals: Dict) -> Optional[float]:
    """Convert amount from one currency to another."""
    if from_currency == to_currency:
        return amount

    # Get both rates relative to USD
    from_rate = get_usd_rate(from_currency, fiat, crypto, metals)
    to_rate = get_usd_rate(to_currency, fiat, crypto, metals)

    if from_rate is None or to_rate is None:
        return None

    # Convert: amount_from / from_rate = USD amount
    # For fiat, rate means "units per USD", so USD = amount / from_rate
    # For crypto/metals, rate means "units per USD" too (after inversion above)
    # Actually for fiat: from_rate = units per USD, so USD = amount_from / from_rate
    # Then to_currency = USD * to_rate

    if from_currency in fiat or from_currency == "USD":
        usd_amount = amount / from_rate
    elif from_currency in crypto:
        # from_rate was set to 1/price, so usd_amount = amount * price = amount / from_rate
        usd_amount = amount / from_rate
    elif from_currency in metals:
        usd_amount = amount / from_rate
    else:
        usd_amount = amount / from_rate

    if to_currency in fiat or to_currency == "USD":
        return usd_amount * to_rate
    elif to_currency in crypto:
        return usd_amount * to_rate
    elif to_currency in metals:
        return usd_amount * to_rate
    else:
        return usd_amount * to_rate


def format_rate(currency: str, value: float) -> str:
    if value >= 1000:
        return f"`{currency}`: ${value:,.2f}"
    elif value >= 1:
        return f"`{currency}`: ${value:.4f}"
    else:
        return f"`{currency}`: ${value:.8f}"
