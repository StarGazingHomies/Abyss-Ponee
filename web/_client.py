import logging
import time

import aiohttp
from cachetools import TLRUCache

logger = logging.getLogger(__name__)


def _ttu(_key, value, _now):
    # Each entry's expiry is precomputed when it is stored (see request()).
    return value['expires_at']


class CachedAPIClient:
    """Base class for the web API clients.

    Wraps an aiohttp session and an in-memory, size-bounded, TTL cache.
    Nothing is persisted to disk -- the cache is cold on startup and cleared
    on shutdown. Expired and least-recently-used entries are evicted
    automatically by the underlying TLRUCache.
    """

    base_url = ''

    def __init__(self, maxsize: int = 1024):
        self.client = None
        self.cache = TLRUCache(maxsize=maxsize, ttu=_ttu, timer=time.time)
        self.initialized = False

    def init(self, headers=None):
        self.client = aiohttp.ClientSession(
            headers=headers or {}
        )
        self.initialized = True

    async def shutdown(self):
        if self.client:
            await self.client.close()
        self.cache.clear()
        self.initialized = False

    def _expiry(self, result_json: dict, now: float, cache_time: int):
        """Absolute expiry time (epoch seconds) for a response.

        Return None to skip caching this response. The default is a fixed TTL
        measured from now; subclasses may override to honour a server-provided
        expiry.
        """
        return now + cache_time

    @staticmethod
    def _cache_key(method: str, path: tuple[str, ...], params: dict) -> str:
        return method + ' ' + '/'.join(path) + '?' + '&'.join(f'{k}={v}' for k, v in params.items())

    async def request(self, path: tuple[str, ...], params=None, method: str = 'GET',
                      cache_time: int = 60 * 5) -> dict:
        if params is None:
            params = {}
        if not self.initialized:
            raise Exception(f'{type(self).__name__} not initialized. Call init() first.')

        key = self._cache_key(method, path, params)
        try:
            cached = self.cache[key]
            logger.info(f'{self.base_url} at {key} CACHE HIT')
            return cached['data']
        except KeyError:
            logger.info(f'{self.base_url} at {key} CACHE MISS')

        url = self.base_url + '/'.join(path)
        result = await self.client.request(method, url, params=params)
        result_json = await result.json()
        logger.info(f'{method} {"/".join(path)} {result.status}')

        # Only cache successful responses so transient errors don't poison the cache.
        if result.status == 200:
            now = time.time()
            expires_at = self._expiry(result_json, now, cache_time)
            if expires_at is not None and expires_at > now:
                self.cache[key] = {'data': result_json, 'expires_at': expires_at}

        return result_json
