import json
import time

import aiohttp
from aiohttp import ClientResponse


class TetraLeagueAPI:
    def __init__(self):
        self.base_url = 'https://ch.tetr.io/api/'
        self.client = None
        self.cache = None
        self.initialized = False

    def init(self, headers):
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
        sanitized_cache = {"/".join(key): value for key, value in self.cache.items()}
        with open(filename, 'w') as f:
            json.dump(sanitized_cache, f)

    def load_cache(self, filename: str):
        try:
            with open(filename, 'r') as f:
                sanitized_cache = json.load(f)

            self.cache = {tuple(key.split('/')): value for key, value in sanitized_cache.items()}
        except FileNotFoundError:
            print(f'Cache file {filename} not found, starting with empty cache')
            self.cache = {}

    def prune_cache(self):
        # Delete expired items
        now = time.time()
        keys_to_delete = [key for key, value in self.cache.items() if value['expires'] <= now]
        for key in keys_to_delete:
            del self.cache[key]

    async def request(self, path: tuple[str, ...], cache_time: int = 60 * 5) -> dict:
        if not self.initialized:
            raise Exception('TetraLeagueAPI not initialized. Call init() first.')

        # Check cache
        if path in self.cache:
            if self.cache[path]['expires'] < time.time():
                print(f'Cache expired for {path}, fetching new data')
                del self.cache[path]
            else:
                print(f'Cache hit for {path}')
                return self.cache[path]['data']

        url = self.base_url + '/'.join(path)
        print(f'Fetching {url}')
        result = await self.client.get(url)
        result_json = await result.json()
        self.cache[path] = {
            'data': result_json,
            'expires': time.time() + cache_time
        }
        self.save_cache('cache.json')

        return result_json

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
        return await self.request(path, cache_time=60 * 10)

    async def user_search(self, query):
        path = ('users', 'search', query)
        return await self.request(path, cache_time=60 * 5)