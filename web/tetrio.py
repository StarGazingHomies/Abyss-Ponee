import logging
import uuid
from typing import Literal

from web._client import CachedAPIClient

logger = logging.getLogger(__name__)


class TetraLeagueAPI(CachedAPIClient):
    base_url = 'https://ch.tetr.io/api/'

    def __init__(self):
        super().__init__()
        self.session_id = str(uuid.uuid4())

    def init(self, headers=None):
        headers = dict(headers or {})
        headers['X-Session-ID'] = self.session_id
        super().init(headers)

    def _expiry(self, result_json, now, cache_time):
        # TETR.IO tells us exactly how long each response is fresh for.
        if not result_json.get('success', True):
            return None  # don't cache error responses
        cache_meta = result_json.get('cache') or {}
        cached_until = cache_meta.get('cached_until')
        if cached_until:
            return cached_until / 1000  # API timestamps are in milliseconds
        return now + cache_time

    async def request_paginate(self, path: tuple[str, ...], params=None,
                               page_using: Literal['after', 'before', 'limit'] = 'after',
                               page_times: int = 5,
                               cache_time: int = 60 * 10) -> list[dict]:
        if params is None:
            params = {}

        results = []
        last_id = None
        for _ in range(page_times):
            if last_id is not None:
                params[page_using] = last_id

            result_json = await self.request(path, params, cache_time)
            if 'data' not in result_json or not result_json['data']:
                break

            results.append(result_json)
            if len(result_json['data']['entries']) == 0:
                break
            last_id = result_json['data']['entries'][-1]['p']
            last_id = f"{last_id['pri']}:{last_id['sec']}:{last_id['ter']}"

        return results

    async def user(self, user: str):
        path = ('users', user)
        return await self.request(path)

    async def user_league(self, user: str):
        path = ('users', user, 'summaries', 'league')
        return await self.request(path)

    async def user_leaderboard(self, user, gamemode, leaderboard):
        if gamemode not in ('40l', 'blitz', 'zenith', 'zenithex', 'league'):
            raise ValueError('Invalid gamemode')

        if leaderboard not in ('top', 'recent', 'progression'):
            raise ValueError('Invalid leaderboard')

        path = ('users', user, 'records', gamemode, leaderboard)
        return await self.request(path, {"limit": "100"}, cache_time=60 * 10)

    async def leagueflow(self, user):
        path = ('labs', 'leagueflow', user)
        return await self.request(path, cache_time=60 * 10)

    async def user_search(self, query):
        path = ('users', 'search', query)
        return await self.request(path, cache_time=60 * 5)

    async def records_leaderboard(self, leaderboard: str, limit=500) -> list[dict]:
        path = ('records', leaderboard)
        single_max = 100
        if limit > single_max:
            return await self.request_paginate(path, {"limit": str(single_max)}, page_using='after', page_times=(limit + single_max - 1) // single_max, cache_time=60 * 10)
        return [await self.request(path, cache_time=60 * 10, params={"limit": str(limit)})]