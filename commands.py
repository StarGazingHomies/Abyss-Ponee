from typing import Optional

import discord

from main import tetrioClient
from render import tetra as tetra_render


async def handle_tetra(send_reply, send_message, author_id: int, username: Optional[str] = None, round_num: int = 1):
    """Core logic for the tetra command. send_reply and send_message are callables."""
    if round_num < 1 or round_num > 10:
        round_num = 1

    if not username:
        query_param = f"discord:id:{author_id}"
        search_result = await tetrioClient.user_search(query_param)
        if search_result["data"]["users"]:
            username = search_result["data"]["users"][0]["username"]
            print(f'Found TETR.IO username {username} for Discord ID {author_id}')
        else:
            await send_message('No linked TETR.IO account found for your Discord ID. Please provide a username.')
            return

    username = username.lower()

    result: dict = await tetrioClient.leaderboard(username, "league", "recent")

    if not result['success']:
        await send_reply(f"{result['error']['msg']}")
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
            print(f'Found TETR.IO username {username} for Discord ID {snowflake}')
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
