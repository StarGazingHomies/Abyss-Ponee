import discord
from discord import app_commands
from typing import Optional, Literal
import logging

from teto_commands import tetrioClient
from teto_commands import handle_tetra, handle_tetra_message
from teto_commands import handle_leagueflow
from teto_commands import handle_quickplay

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def log_command(interaction: discord.Interaction, command: str, **params):
    guild = interaction.guild.name if interaction.guild else 'DM'
    channel = getattr(interaction.channel, 'name', str(interaction.channel_id))
    user = f'{interaction.user} ({interaction.user.id})'
    param_str = ', '.join(f'{k}={v}' for k, v in params.items() if v is not None)
    logger.info(f'/{command} | {user} | {guild}#{channel} | {param_str}')

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
    game_number="Which recent game to display (1-100, default 1)",
)
async def tetra_command(interaction: discord.Interaction, username: Optional[str] = None, game_number: Optional[int] = None):
    log_command(interaction, 'tetra', username=username, game_number=game_number)
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
    name="qp",
    description="View past Quick Play games",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
    game_number="Which recent game to display (1-100, default 1)",
    expert="Expert mode",
    sort_by="Sort by recent games or highest altitude"
)
async def quickplay_command(interaction: discord.Interaction, username: Optional[str] = None, game_number: Optional[int] = None,
                            expert: bool=None, sort_by: Literal['recent', 'altitude'] = 'recent'):
    log_command(interaction, 'qp', username=username, game_number=game_number, expert=expert, sort_by=sort_by)
    await interaction.response.defer()
    try:
        await handle_quickplay(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
            round_num=game_number or 1,
            expert=expert or False,
            sort_by=sort_by,
        )
    except Exception as e:
        await interaction.followup.send(f'Error: {e.with_traceback(None)}')


@tree.command(
    name="leagueflow",
    description="Visualize your Tetra League progression",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
    render_arguments="Additional arguments for rendering: --no-points, --no-shading, --no-graph",
    after="Show games on or after this date (YYYY-MM-DD, UTC)",
    before="Show games before this date (YYYY-MM-DD, UTC)",
)
async def leagueflow_command(interaction: discord.Interaction, username: Optional[str] = None, render_arguments: Optional[str] = None, after: Optional[str] = None, before: Optional[str] = None):
    log_command(interaction, 'leagueflow', username=username, render_arguments=render_arguments, after=after, before=before)
    await interaction.response.defer()
    try:
        await handle_leagueflow(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
            render_arguments=render_arguments,
            after=after,
            before=before,
        )
    except Exception as e:
        await interaction.followup.send(f'Error: {e.with_traceback(None)}')

@client.event
async def on_ready():
    await tree.sync()
    tetrioClient.init(headers)
    logger.info(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('>stop'):
        if message.author.id != bot_owner:
            return
        logger.info(f'>stop | {message.author} ({message.author.id})')
        await message.channel.send('Shutting down...')
        await tetrioClient.shutdown()
        await client.close()

    if message.content.startswith('>tetra'):
        logger.info(f'>tetra | {message.author} ({message.author.id}) | {message.content}')
        try:
            await handle_tetra_message(message)
        except Exception as e:
            await message.reply(f'Error {e.with_traceback(None)}')

client.run(token)
