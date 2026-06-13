import itertools
import json
import logging
from datetime import datetime, timezone
import dateparser
from typing import Optional

import discord

logger = logging.getLogger(__name__)

import tetrio
from render import tetra as tetra_render
from render import leagueflow as leagueflow_render
from render import quickplay as quickplay_render

tetrioClient = tetrio.TetraLeagueAPI()


async def resolve_username(author_id: int) -> Optional[str]:
    query_param = f"discord:id:{author_id}"
    search_result = await tetrioClient.user_search(query_param)
    if search_result["data"]["users"]:
        username = search_result["data"]["users"][0]["username"]
        logger.info(f'Resolved Discord ID {author_id} -> {username}')
        return username
    else:
        return None

async def handle_tetra(send_reply, send_message, author_id: int, username: Optional[str] = None, round_num: int = 1):
    """Core logic for the tetra command. send_reply and send_message are callables."""

    if not username:
        username = await resolve_username(author_id)
        if not username:
            await send_message('No linked TETR.IO account found for your Discord ID. Please provide a username. Usage: `>tetra <username> [round]`')
            return

    username = username.lower()

    result: dict = await tetrioClient.leaderboard(username, "league", "recent")

    if not result['success']:
        await send_reply(f"{result['error']['msg']}")
        return

    if round_num < 1 or round_num > len(result["data"]["entries"]):
        await send_reply(f"Invalid round number. Please choose a number between 1 and {len(result['data']['entries'])}.")
        return

    entry = result["data"]["entries"][round_num - 1]
    leaderboard = entry["results"]["leaderboard"]
    player0_data = leaderboard[0]
    player1_data = leaderboard[1]

    def parse_stats(stats):
        return stats["apm"], stats["pps"], stats["vsscore"]

    rounds = []
    for rnd in entry["results"]["rounds"]:
        p0 = next(p for p in rnd if p["id"] == player0_data["id"])
        p1 = next(p for p in rnd if p["id"] == player1_data["id"])
        winner = 0 if p0["alive"] else 1
        duration_ms = p0["lifetime"]
        duration_s = duration_ms / 1000
        rounds.append((winner, parse_stats(p0["stats"]), parse_stats(p1["stats"]), duration_s))

    render_data = {
        "player0": player0_data["username"],
        "player1": player1_data["username"],
        "stats": [parse_stats(player0_data["stats"]), parse_stats(player1_data["stats"])],
        "rounds": rounds,
    }

    tetra_render.render(render_data, "output.png")
    await send_reply(file=discord.File("output.png"))


async def handle_tetra_message(message: discord.Message):
    round_num = 1
    username = None

    if message.reference is not None:
        replied_message = await message.channel.fetch_message(message.reference.message_id)
        snowflake = replied_message.author.id
        query_param = f"discord:id:{snowflake}"
        search_result = await tetrioClient.user_search(query_param)
        if search_result["data"]["users"]:
            username = search_result["data"]["users"][0]["username"]
            logger.info(f'Resolved Discord ID {snowflake} -> {username}')
        else:
            await message.channel.send(
                'No linked TETR.IO account found for the replied user. Please provide a username. Usage: `>tetra <username> [round]`'
            )
            return
    else:
        parts = message.content.split()
        if len(parts) >= 2:
            username = parts[1]
        if len(parts) >= 3:
            try:
                round_num = int(parts[2])
            except ValueError:
                await message.channel.send('Invalid round number. Usage: `>tetra <username> [round]`')
                return

    await handle_tetra(
        send_reply=lambda *args, **kwargs: message.reply(*args, **kwargs),
        send_message=lambda msg: message.channel.send(msg),
        author_id=message.author.id,
        username=username,
        round_num=round_num,
    )


async def handle_leagueflow(send_reply, send_message, author_id: int, username: Optional[str] = None, render_arguments: Optional[str] = None, after: Optional[str] = None, before: Optional[str] = None):
    """Core logic for the leagueflow command. send_reply and send_message are callables."""

    if not username:
        username = await resolve_username(author_id)
        if not username:
            await send_message('No linked TETR.IO account found for your Discord ID. Please provide a username. Usage: `>leagueflow <username>`')
            return

    username = username.lower()

    result: dict = await tetrioClient.leagueflow(username)

    if not result['success']:
        await send_reply(f"{result['error']['msg']}")
        return

    # print(f"Fetched leagueflow data for {username}: {result['data']}")
    render_data = result['data']

    if not render_data['points']:
        await send_message('No tetra league history data available for this user.')
        return

    after_ms = None
    before_ms = None
    if after:
        try:
            after_ms = dateparser.parse(after, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}).timestamp() * 1000
        except AttributeError:
            await send_message(f'Invalid `after` date: {after}')
            return
    if before:
        try:
            before_ms = dateparser.parse(before, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}).timestamp() * 1000
        except AttributeError:
            await send_message(f'Invalid `before` date: {before}')
            return

    if after_ms is not None or before_ms is not None:
        start_time = render_data['startTime']
        filtered = [p for p in render_data['points']
                    if (after_ms is None or start_time + p[0] >= after_ms)
                    and (before_ms is None or start_time + p[0] < before_ms)]
        if not filtered:
            await send_message('No data found in the specified date range.')
            return
        render_data = {**render_data, 'points': filtered}

    no_points = False
    no_shading = False
    no_graph = False
    if render_arguments:
        args = render_arguments.split()
        for arg in args:
            if arg == "--no-points":
                no_points = True
            elif arg == "--no-shading":
                no_shading = True
            elif arg == "--no-graph":
                no_graph = True

    leagueflow_render.render_leagueflow(render_data, "leagueflow.png", no_points=no_points, no_shading=no_shading, no_graph=no_graph)
    await send_reply(file=discord.File("leagueflow.png"))


async def handle_quickplay(send_reply, send_message, author_id: int, username: Optional[str] = None, round_num: int = 1, expert: bool = False, sort_by: str = 'recent'):
    if not username:
        username = await resolve_username(author_id)
        if not username:
            await send_message('No linked TETR.IO account found for your Discord ID. Please provide a username. Usage: `>leagueflow <username>`')
            return

    username = username.lower()

    user_data = await tetrioClient.user(username)
    if not user_data['success']:
        await send_reply(f"{user_data['error']['msg']}")
        return

    user_country = user_data['data']['country']

    gamemode = "zenithex" if expert else "zenith"

    best_scores_result: dict = await tetrioClient.leaderboard(username, gamemode, "top")
    if not best_scores_result['success']:
        await send_reply(f"{best_scores_result['error']['msg']}")
        return

    if sort_by == 'recent':
        result: dict = await tetrioClient.leaderboard(username, gamemode, "recent")

        if not result['success']:
            await send_reply(f"{result['error']['msg']}")
            return
    else:
        result = best_scores_result

    entries = result["data"]["entries"]
    if round_num < 1 or round_num > len(entries):
        await send_reply(f"Invalid game number. Please choose between 1 and {len(entries)}.")
        return

    entry = entries[round_num - 1]

    # Find the true rank of the entry
    entry_id = entry["_id"]
    for i, e in enumerate(best_scores_result["data"]["entries"]):
        if e["_id"] == entry_id:
            entry["personal_rank"] = i + 1
            break
    else:
        entry["personal_rank"] = None

    if entry["personal_rank"] == 1:
        best_global_scores = await tetrioClient.records_leaderboard(f"{gamemode}_global", limit=500)
        best_country_scores = await tetrioClient.records_leaderboard(f"{gamemode}_country_{user_country}", limit=500)

        best_global_scores_id_nested = [[entry["_id"] for entry in s["data"]["entries"]] for s in best_global_scores]
        best_global_id_list = list(itertools.chain.from_iterable(best_global_scores_id_nested))

        if entry_id in best_global_id_list:
            entry["global_rank"] = best_global_id_list.index(entry_id) + 1
        else:
            entry["global_rank"] = None

        best_country_scores_id_nested = [[entry["_id"] for entry in s["data"]["entries"]] for s in best_country_scores]
        best_country_id_list = list(itertools.chain.from_iterable(best_country_scores_id_nested))

        if entry_id in best_country_id_list:
            entry["country_rank"] = best_country_id_list.index(entry_id) + 1
        else:
            entry["country_rank"] = None

        # with open("global.json", "w") as f:
        #     json.dump(best_global_scores, f, indent=2)
        #
        # with open("country.json", "w") as f:
        #     json.dump(best_country_scores, f, indent=2)
    else:
        entry["global_rank"] = None
        entry["country_rank"] = None

    quickplay_render.render_quickplay(entry, "qp_output.png")
    await send_reply(file=discord.File("qp_output.png"))