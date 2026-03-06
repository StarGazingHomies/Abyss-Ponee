import discord
from aiohttp import ClientResponse

import tetrio
import render

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
bot_owner = 523717630972919809

tetrioClient = tetrio.TetraLeagueAPI()

with open('.config', 'r') as f:
    token = f.read().strip()
if not token:
    print('Token not found in token.txt')
    exit(1)

@client.event
async def on_ready():
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

            if not username:
                if len(message.content.split(' ')) < 2:
                    # await message.channel.send('Please provide a username. Usage: `>tetra <username> [round]`')
                    # Try to find the username using query
                    snowflake = message.author.id
                    query_param = f"discord:id:{snowflake}"
                    search_result = await tetrioClient.user_search(query_param)
                    if search_result["data"]["users"]:
                        username = search_result["data"]["users"][0]["username"]
                        print(f'Found TETR.IO username {username} for Discord ID {snowflake}')
                    else:
                        await message.channel.send('No linked TETR.IO account found for your Discord ID. Please provide a username. Usage: `>tetra <username> [round]`')
                        return
                else:
                    username = message.content.split(' ')[1]
                    if len(message.content.split(' ')) >= 3:
                        round_num = int(message.content.split(' ')[2])
                        if round_num < 1 or round_num > 10:
                            round_num = 1

            # await message.channel.send(f'Fetching data for {username}...')

            result: ClientResponse = await tetrioClient.leaderboard(username, "league", "recent")

            # print(result["data"]["entries"][0].keys())
            # print(result["data"]["entries"][0]['results'])
            # print(result["data"]["entries"][0]['results']['rounds'][0][0]['stats'])
            # print(result["data"]["entries"][0]['results']['rounds'][0][1])

            entry = result["data"]["entries"][round_num - 1]
            leaderboard = entry["results"]["leaderboard"]
            player0_data = leaderboard[0]
            player1_data = leaderboard[1]

            def parse_stats(stats):
                return (stats["apm"], stats["pps"], stats["vsscore"])

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

            await message.channel.send(file=discord.File("output.png"))

        except Exception as e:
            await message.channel.send(f'Error: {str(e)}')

client.run(token)

