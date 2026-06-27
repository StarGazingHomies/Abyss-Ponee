import logging

import discord

logger = logging.getLogger(__name__)

from web import manebooru

manebooruClient = manebooru.ManebooruAPI()

# Manebooru's "Default" safe filter. Hides everything not safe for work.
SAFE_FILTER_ID = 175


async def handle_image(send_reply, send_message, query: str,
                       sort_field: str = 'score', sort_direction: str = 'desc',
                       index: int = 1):
    """Core logic for the image command. send_reply and send_message are callables."""

    # Check if bot owner because this spams chat quite a bit tbh

    query = query.strip()
    if not query:
        await send_message('Please provide search tags. Usage: `/image <tags>`')
        return

    result = await manebooruClient.search_images(
        query=query,
        per_page=50,
        sort_field=sort_field,
        sort_direction=sort_direction,
        filter_id=SAFE_FILTER_ID,
    )

    if 'error' in result:
        await send_message(f"Search error: {result['error']}")
        return

    images = result.get('images', [])
    total = result.get('total', len(images))

    if not images:
        await send_message(f'No images found for `{query}`.')
        return

    if index < 1 or index > len(images):
        await send_message(f'Invalid result number. Please choose between 1 and {len(images)}.')
        return

    image = images[index - 1]
    image_id = image['id']
    post_url = f'https://manebooru.art/images/{image_id}'
    view_url = image['view_url']
    image_format = (image.get('format') or '').lower()

    # Discord can't render webm/mp4 inside an embed, so post the direct link
    # and let Discord build its own video player.
    if image_format in ('webm', 'mp4'):
        await send_reply(f'{post_url}\n{view_url}')
        return

    representations = image.get('representations') or {}
    display_url = representations.get('large') or representations.get('medium') or view_url

    score = image.get('score')
    embed = discord.Embed(
        title=f'#{image_id}',
        url=post_url,
        description=f'Result {index} of {total}' + (f' • score {score}' if score is not None else ''),
    )
    embed.set_image(url=display_url)
    await send_reply(embed=embed)
