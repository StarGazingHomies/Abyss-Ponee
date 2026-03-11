import discord
from discord import app_commands
from typing import Optional

import tetrio
import render

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
bot_owner = 523717630972919809

tetrioClient = tetrio.TetraLeagueAPI()

with open('.config', 'r') as f:
    token = f.read().strip()
if not token:
    print('Token not found in token.txt')
    exit(1)

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

    render.render(render_data, "output.png")
    await send_reply(file=discord.File("output.png"))


@tree.command(
    name="tetra",
    description="View past Tetra League games",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
    game_number="Which recent game to display (1-10, default 1)",
)
async def tetra_command(interaction: discord.Interaction, username: Optional[str] = None, game_number: Optional[int] = 1):
    await interaction.response.defer()
    try:
        await handle_tetra(
            send_reply=lambda **kwargs: interaction.followup.send(**kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
            round_num=game_number or 1,
        )
    except Exception as e:
        await interaction.followup.send(f'Error: {e.with_traceback(None)}')


@client.event
async def on_ready():
    await tree.sync()
    tetrioClient.init()
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('>stop'):
        if message.author.id != bot_owner:
            return
        await message.channel.send('Shutting down...')
        tetrioClient.shutdown()
        await client.close()

    if message.content.startswith('>tetra'):
        try:
            round_num = 1
            username = None

            # If the message is a reply, look up the reply's author
            if message.reference is not None:
                replied_message = await message.channel.fetch_message(message.reference.message_id)
                snowflake = replied_message.author.id
                query_param = f"discord:id:{snowflake}"
                search_result = await tetrioClient.user_search(query_param)
                if search_result["data"]["users"]:
                    username = search_result["data"]["users"][0]["username"]
                    print(f'Found TETR.IO username {username} for Discord ID {snowflake}')
                else:
                    await message.channel.send('No linked TETR.IO account found for the replied user. Please provide a username. Usage: `>tetra <username> [round]`')
                    return
            else:
                parts = message.content.split(' ')
                if len(parts) >= 2:
                    username = parts[1]
                if len(parts) >= 3:
                    round_num = int(parts[2])

            await handle_tetra(
                send_reply=lambda **kwargs: message.reply(**kwargs),
                send_message=lambda msg: message.channel.send(msg),
                author_id=message.author.id,
                username=username,
                round_num=round_num,
            )

        except Exception as e:
            await message.reply(f'Error {e.with_traceback(None)}')

client.run(token)
