import discord
from discord import app_commands
from typing import Optional

from teto_commands import tetrioClient
from teto_commands import handle_tetra, handle_tetra_message
from teto_commands import handle_leagueflow

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

with open('config.json', 'r') as f:
    import json
    config = json.load(f)
    token = config.get('token')
    bot_owner = int(config.get('bot_owner'))
    headers = config.get('headers', {})
if not token or not bot_owner or not headers:
    print('Token not found in token.txt')
    exit(1)


@tree.command(
    name="tetra",
    description="View past Tetra League games",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
    game_number="Which recent game to display (1-10, default 1)",
)
async def tetra_command(interaction: discord.Interaction, username: Optional[str] = None, game_number: Optional[int] = None):
    await interaction.response.defer()
    try:
        await handle_tetra(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
            round_num=game_number or 1,
        )
    except Exception as e:
        await interaction.followup.send(f'Error: {e.with_traceback(None)}')


@tree.command(
    name="leagueflow",
    description="Visualize your Tetra League progression",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
)
async def leagueflow_command(interaction: discord.Interaction, username: Optional[str] = None):
    await interaction.response.defer()
    try:
        await handle_leagueflow(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
        )
    except Exception as e:
        await interaction.followup.send(f'Error: {e.with_traceback(None)}')

@client.event
async def on_ready():
    await tree.sync()
    tetrioClient.init(headers)
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('>stop'):
        if message.author.id != bot_owner:
            return
        await message.channel.send('Shutting down...')
        await tetrioClient.shutdown()
        await client.close()

    if message.content.startswith('>tetra'):
        try:
            await handle_tetra_message(message)
        except Exception as e:
            await message.reply(f'Error {e.with_traceback(None)}')

client.run(token)
