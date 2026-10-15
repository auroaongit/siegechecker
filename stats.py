"""Step 2: look up each username's ranked stats from Ubisoft's servers.

R6 Tracker gets its numbers from these same Ubisoft servers. There's no
official public API, so we use the `siegeapi` library, which logs in with
a Ubisoft account the same way the game does.
"""

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp
from siegeapi import Auth
from siegeapi.exceptions import FailedToConnect, InvalidRequest
from siegeapi.rank_profile import FullProfile

# Names used by R6 Tracker's profile URLs for each Ubisoft platform type.
TRACKER_PLATFORM = {"psn": "psn", "uplay": "ubi", "xbl": "xbl"}


@dataclass
class PlayerStats:
    searched_name: str
    found: bool = False
    error: str | None = None
    name: str | None = None
    platform: str | None = None
    rank: str | None = None
    rank_points: int | None = None
    max_rank: str | None = None
    kills: int = 0
    deaths: int = 0
    wins: int = 0
    losses: int = 0
    abandons: int = 0
    kd: float | None = None
    win_pct: float | None = None
    matches: int = 0
    avatar_url: str | None = None
    tracker_url: str | None = None


class StatsClient:
    """Keeps one logged-in Ubisoft session and uses it for every lookup."""

    def __init__(self) -> None:
        email = os.environ.get("UBISOFT_EMAIL")
        password = os.environ.get("UBISOFT_PASSWORD")
        if not email or not password:
            raise RuntimeError("Set UBISOFT_EMAIL and UBISOFT_PASSWORD in your .env file")

        # The login session is saved to creds/ so we don't log in on every restart
        # (Ubisoft temporarily blocks accounts that log in too often).
        self.auth = Auth(email, password, creds_path="creds/ubisoft_session.json")
        self.platform_family = os.environ.get("PLATFORM_FAMILY", "console")
        self.lookup_platforms = os.environ.get("LOOKUP_PLATFORMS", "psn,uplay,xbl").split(",")
        self._login_lock = asyncio.Lock()
        # Only ask Ubisoft about a few players at once, to avoid being rate limited.
        self._limit = asyncio.Semaphore(4)

    async def close(self) -> None:
        await self.auth.close()

    async def lookup_many(self, names: list[str]) -> list[PlayerStats]:
        # Log in once up front, otherwise every parallel lookup would try to log in.
        async with self._login_lock:
            try:
                await self.auth.connect()
            except FailedToConnect as e:
                error = f"Couldn't log in to Ubisoft ({e}). Check UBISOFT_EMAIL/PASSWORD in .env"
                return [PlayerStats(searched_name=n, error=error) for n in names]
            except aiohttp.ClientError:
                error = "Couldn't reach Ubisoft's servers. Check your internet connection"
                return [PlayerStats(searched_name=n, error=error) for n in names]
        # gather() runs all the lookups at the same time instead of one by one.
        return await asyncio.gather(*(self.lookup(name) for name in names))

    async def lookup(self, name: str) -> PlayerStats:
        name = name.strip()
        stats = PlayerStats(searched_name=name)
        async with self._limit:
            try:
                player = await self._find_player(name)
                if player is None:
                    stats.error = "Player not found"
                    return stats

                stats.found = True
                stats.name = player.name
                stats.platform = player._platform
                stats.avatar_url = player.profile_pic_url_146
                tracker_platform = TRACKER_PLATFORM[player._platform]
                stats.tracker_url = (
                    f"https://r6.tracker.network/r6siege/profile/"
                    f"{tracker_platform}/{quote(player.name)}/overview"
                )

                ranked = await self._load_ranked(player.uid)
                if ranked is not None:
                    _fill_ranked(stats, ranked)
            except (InvalidRequest, FailedToConnect) as e:
                stats.error = f"Ubisoft error: {e}"
            except aiohttp.ClientError:
                stats.error = "Couldn't reach Ubisoft's servers"
        return stats

    async def _find_player(self, name: str):
        """Try each platform in turn until one has an account with this name."""
        for platform in self.lookup_platforms:
            try:
                return await self.auth.get_player(name=name, platform=platform.strip())
            except InvalidRequest:
                continue  # no account with this name on this platform
        return None

    async def _load_ranked(self, uid: str) -> FullProfile | None:
        """Get this season's ranked stats for the chosen ranked pool (console or pc)."""
        space_id = self.auth.spaceids["xplay"]
        url = (
            f"https://public-ubiservices.ubi.com/v2/spaces/{space_id}/title/r6s/skill/full_profiles"
            f"?profile_ids={uid}&platform_families={self.platform_family}"
        )
        data = await self.auth.get(url, new=True)
        return parse_ranked(data)


def parse_ranked(data: dict) -> FullProfile | None:
    """Dig the ranked board out of Ubisoft's (very nested) JSON response."""
    families = data.get("platform_families_full_profiles") or []
    if not families:
        return None
    for board in families[0].get("board_ids_full_profiles", []):
        if board.get("board_id") == "ranked" and board.get("full_profiles"):
            return FullProfile(board["full_profiles"][0])
    return None


def _fill_ranked(stats: PlayerStats, ranked: FullProfile) -> None:
    stats.rank = ranked.rank
    stats.rank_points = ranked.rank_points
    stats.max_rank = ranked.max_rank
    stats.kills = ranked.kills
    stats.deaths = ranked.deaths
    stats.wins = ranked.wins
    stats.losses = ranked.losses
    stats.abandons = ranked.abandons
    stats.matches = ranked.wins + ranked.losses + ranked.abandons
    # Avoid dividing by zero for players who haven't played/died yet this season.
    stats.kd = round(ranked.kills / max(ranked.deaths, 1), 2) if ranked.kills or ranked.deaths else None
    stats.win_pct = round(100 * ranked.wins / stats.matches, 1) if stats.matches else None
