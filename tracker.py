"""Step 2 (default): look up each username's ranked stats on R6 Tracker.

R6 Tracker has no official API for Siege. Its website loads player data from
a JSON address (api.tracker.gg/...), and we ask that same address for it.
This is unofficial: it can stop working whenever R6 Tracker changes its site,
and R6 Tracker may block requests (especially from cloud hosts like Render).
When that happens, each card still gets a link to the player's R6 Tracker page.
"""

import asyncio
import os
import time
from urllib.parse import quote

import aiohttp

from stats import PlayerStats

API_BASE = "https://api.tracker.gg/api/v2/r6siege/standard/profile"
PROFILE_BASE = "https://r6.tracker.network/r6siege/profile"
# Our setting uses Ubisoft's platform names; R6 Tracker calls Ubisoft "ubi".
TRACKER_PLATFORM = {"psn": "psn", "uplay": "ubi", "ubi": "ubi", "xbl": "xbl"}
HEADERS = {
    "Accept": "application/json",
    "Referer": "https://r6.tracker.network/",
    "Origin": "https://r6.tracker.network",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
}
CACHE_SECONDS = 120


class Blocked(Exception):
    """R6 Tracker refused to answer (bot protection or rate limit)."""


class TrackerClient:
    def __init__(self) -> None:
        platforms = os.environ.get("LOOKUP_PLATFORMS", "psn,uplay,xbl").split(",")
        self.platforms = [TRACKER_PLATFORM[p.strip()] for p in platforms]
        self.session = aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15))
        # Be polite: only 2 requests at a time, so R6 Tracker is less likely to block us.
        self._limit = asyncio.Semaphore(2)
        # Remember recent answers, so fixing one typo doesn't re-download everyone.
        self._cache: dict[str, tuple[float, PlayerStats]] = {}

    async def close(self) -> None:
        await self.session.close()

    async def lookup_many(self, names: list[str]) -> list[PlayerStats]:
        return await asyncio.gather(*(self.lookup(name) for name in names))

    async def lookup(self, name: str) -> PlayerStats:
        name = name.strip()
        cached = self._cache.get(name.lower())
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]

        # Link to the first platform we'd try, so there's always something to tap.
        stats = PlayerStats(searched_name=name, tracker_url=profile_url(self.platforms[0], name))
        async with self._limit:
            try:
                for platform in self.platforms:
                    data = await self._get_profile(platform, name)
                    if data is not None:
                        fill_from_profile(stats, data, platform)
                        break
                else:
                    stats.error = "Player not found"
            except Blocked:
                stats.error = "R6 Tracker blocked the lookup. Tap the link to view it there"
            except (aiohttp.ClientError, asyncio.TimeoutError):
                stats.error = "Couldn't reach R6 Tracker"
            except (KeyError, TypeError, ValueError):
                # The JSON wasn't shaped how we expected: R6 Tracker probably changed it.
                stats.error = "R6 Tracker's data changed and this app needs updating"

        if stats.found:
            self._cache[name.lower()] = (time.time(), stats)
        return stats

    async def _get_profile(self, platform: str, name: str) -> dict | None:
        """Return the player's profile JSON, or None if they don't exist on this platform."""
        url = f"{API_BASE}/{platform}/{quote(name, safe='')}"
        async with self.session.get(url) as resp:
            text = await resp.text()
            if is_blocked(resp.status, text):
                raise Blocked()
            if resp.status == 404:
                return None
            body = await resp.json(content_type=None)
        if body.get("errors"):
            code = str(body["errors"][0].get("code", "")).lower()
            if "notfound" in code or "not_found" in code:
                return None
            raise ValueError(f"R6 Tracker error: {code}")
        return body["data"]


def is_blocked(status: int, text: str) -> bool:
    """Spot Cloudflare's "are you a robot?" pages and rate limits."""
    if status in (401, 403, 429, 503):
        return True
    start = text[:16_000].lower()
    return any(m in start for m in ("just a moment", "you've been blocked", "cf-chl-", "verify you are human"))


def profile_url(platform: str, name: str) -> str:
    return f"{PROFILE_BASE}/{platform}/{quote(name, safe='')}/overview"


def value(stats: dict, key: str):
    """R6 Tracker stores each number as {"value": 1.23, "displayValue": "1.23", ...}."""
    return (stats.get(key) or {}).get("value")


def fill_from_profile(player: PlayerStats, data: dict, platform: str) -> None:
    info = data["platformInfo"]
    player.found = True
    player.name = info.get("platformUserHandle") or player.searched_name
    player.platform = platform
    player.avatar_url = info.get("avatarUrl")
    player.tracker_url = profile_url(platform, player.name)

    season = current_ranked_segment(data)
    if season is None:
        return  # hasn't played ranked this season

    s = season["stats"]
    player.rank = ((s.get("rankPoints") or {}).get("metadata") or {}).get("name")
    player.max_rank = ((s.get("maxRankPoints") or {}).get("metadata") or {}).get("name")
    player.rank_points = value(s, "rankPoints")
    player.kills = value(s, "kills") or 0
    player.deaths = value(s, "deaths") or 0
    player.wins = value(s, "matchesWon") or 0
    player.losses = value(s, "matchesLost") or 0
    player.abandons = value(s, "matchesAbandoned") or 0
    player.matches = value(s, "matchesPlayed") or (player.wins + player.losses + player.abandons)
    player.kd = value(s, "kdRatio")
    player.win_pct = value(s, "winPercentage")
    if player.rank_points is not None:
        player.rank_points = int(player.rank_points)
    if player.matches is not None:
        player.matches = int(player.matches)


def current_ranked_segment(data: dict) -> dict | None:
    """Find this season's ranked stats among all the profile's "segments"."""
    ranked = [
        seg for seg in data.get("segments", [])
        if seg.get("type") == "season" and (seg.get("attributes") or {}).get("gamemode") == "pvp_ranked"
    ]
    if not ranked:
        return None
    current = (data.get("metadata") or {}).get("currentSeason")
    for seg in ranked:
        if seg["attributes"].get("season") == current:
            return seg
    # Fall back to the newest season we have.
    newest = max(ranked, key=lambda seg: seg["attributes"].get("season") or 0)
    return newest if current is None else None
