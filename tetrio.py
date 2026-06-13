import json
import logging
import time
import uuid
from typing import Literal

import aiohttp
from aiohttp import ClientResponse

logger = logging.getLogger(__name__)


class TetraLeagueAPI:
    def __init__(self):
        self.base_url = 'https://ch.tetr.io/api/'
        self.client = None
        self.cache = None
        self.initialized = False
        self.session_id = str(uuid.uuid4())

    def init(self, headers):
        headers['X-Session-ID'] = self.session_id
        self.client = aiohttp.ClientSession(
            headers=headers
        )
        self.load_cache('cache.json')
        self.initialized = True

    async def shutdown(self, save_cache: bool = True):
        if self.client:
            await self.client.close()
        if save_cache:
            self.save_cache('cache.json')
        self.initialized = False

    def save_cache(self, filename: str):
        # TODO: This is stupid. Don't do this.
        # Like, seriously, this is speedran not actual prod code.
        self.prune_cache()
        # sanitized_cache = {key: value for key, value in self.cache.items()}
        with open(filename, 'w') as f:
            json.dump(self.cache, f)

    def load_cache(self, filename: str):
        try:
            with open(filename, 'r') as f:
                self.cache  = json.load(f)

        except FileNotFoundError:
            logger.warning(f'Cache file {filename} not found, starting with empty cache')
            self.cache = {}

    def prune_cache(self):
        # Delete expired items
        now = time.time()
        keys_to_delete = [key for key, value in self.cache.items() if value['expires'] <= now]
        for key in keys_to_delete:
            del self.cache[key]

    async def request(self, path: tuple[str, ...], params=None, cache_time: int = 60 * 5) -> dict:
        if params is None:
            params = {}
        if not self.initialized:
            raise Exception('TetraLeagueAPI not initialized. Call init() first.')

        cache_path = '/'.join(path) + '?' + '&'.join(f'{k}={v}' for k, v in params.items())

        # Check cache
        if cache_path in self.cache:
            if self.cache[cache_path]['expires'] < time.time():
                logger.info(f'GET {cache_path} EXPIRED')
                del self.cache[cache_path]
            else:
                logger.info(f'GET {cache_path} CACHE HIT')
                return self.cache[cache_path]['data']
        else:
            logger.info(f'GET {cache_path} CACHE MISS')

        url = self.base_url + cache_path
        result = await self.client.get(url)
        result_json = await result.json()

        logger.info(f'GET {"/".join(path)} {result.status}')
        self.cache[cache_path] = {
            'data': result_json,
            'expires': time.time() + cache_time
        }
        self.save_cache('cache.json')

        return result_json

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

    async def leaderboard(self, user, gamemode, leaderboard):
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