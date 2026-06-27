from web._client import CachedAPIClient


class ManebooruAPI(CachedAPIClient):
    base_url = 'https://manebooru.art/api/v1/json/'

    async def search_images(self, query: str, page: int = 1, per_page: int = 25,
                            sort_field: str = None, sort_direction: str = None,
                            filter_id: int = None) -> dict:
        params = {
            'q': query,
            'page': page,
            'per_page': min(per_page, 50),  # API caps per_page at 50
        }
        if sort_field is not None:
            params['sf'] = sort_field
        if sort_direction is not None:
            params['sd'] = sort_direction
        if filter_id is not None:
            params['filter_id'] = filter_id
        return await self.request(('search', 'images'), params, cache_time=60 * 5)

    async def image(self, image_id: int | str) -> dict:
        path = ('images', str(image_id))
        return await self.request(path, cache_time=60 * 10)

    async def reverse_search(self, url: str, distance: float = None) -> dict:
        params = {'url': url}
        if distance is not None:
            params['distance'] = distance
        return await self.request(('search', 'reverse'), params, method='POST', cache_time=60 * 5)
