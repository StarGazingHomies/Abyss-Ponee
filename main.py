import discord
from discord import app_commands
from typing import Optional, Literal
import logging

from teto_commands import tetrioClient
from teto_commands import handle_tetra, handle_tetra_message
from teto_commands import handle_tetra_recent
from teto_commands import handle_leagueflow
from teto_commands import handle_quickplay
from teto_commands import handle_changelog
from teto_commands import handle_tetoranks
from pony_commands import manebooruClient
from pony_commands import handle_image
from feature_requests import append_request, read_requests

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
    name="help",
    description="Show this help message",
)
@app_commands.describe(
    command="Optional specific command to get help for (tetra, qp, leagueflow, image)"
)
async def help_command(interaction: discord.Interaction,     command: Optional[Literal['tetra', 'tetra_recent', 'qp', 'leagueflow', 'image', 'changelog', 'tetoranks', 'request_feature']] = None):
    if command is None:
        description = "<:thinklight:905641655741329418>\n"
        description += "Miscellaneous teto bot by Pony (on Tetr.io)"
        await interaction.response.send_message(description)
    elif command == 'tetra':
        await interaction.response.send_message("/tetra [username] [game_number]\nView past Tetra League games.\nIf username is omitted, uses your linked account.\nGame number specifies which recent game to display (1 is most recent).")
    elif command == 'tetra_recent':
        await interaction.response.send_message("/tetra_recent [username] [page_size] [timezone]\nView a condensed list of recent Tetra League games.\nIf username is omitted, uses your linked account.\nPage_size specifies how many recent games to show per page (1-30, default 10).\nTimezone sets the game times: an IANA name (e.g. America/New_York) or a UTC offset (e.g. UTC-4). Defaults to UTC.")
    elif command == 'qp':
        await interaction.response.send_message("/qp [username] [game_number] [expert] [sort_by]\nView past Quick Play games. If username is omitted, uses your linked account.\nGame number specifies which recent game to display (1 is most recent or highest).\nExpert mode shows only expert games. Sort by can be 'recent' or 'altitude'.\nPersonal rank is capped at 100, country and global ranks at 500.")
    elif command == 'leagueflow':
        await interaction.response.send_message("/leagueflow [username] [render_arguments] [after] [before]\nVisualize your Tetra League progression.\nIf username is omitted, uses your linked account.\nRender arguments can include --no-points, --no-shading, --no-graph.\nAfter and before filter games by date (preferably YYYY-MM-DD, UTC, but stuff like '2 weeks ago' may be supported too).")
    elif command == 'image':
        await interaction.response.send_message("/image <tags> [sort] [direction] [result]\nSearch Manebooru for an image using the safe filter.\nTags are comma-separated (e.g. 'twilight sparkle, solo').\nSort can be score (top rated), first_seen_at (newest), or random.\nDirection is desc or asc. Result picks which match to show (1-50, default 1).")
    elif command == 'changelog':
        await interaction.response.send_message("/changelog\nView past changes to the bot, newest first, 5 versions per page.")
    elif command == 'tetoranks':
        await interaction.response.send_message("/tetoranks [verbose]\nShow TETRA LEAGUE rank TR thresholds, player counts, and average stats.\nVerbose also shows position, target TR and how deflated/inflated each rank is.")
    elif command == 'request_feature':
        await interaction.response.send_message("/request_feature [request]\nSuggest a feature for the bot (once per day).\nIf run by the bot owner with no request, shows all pending requests.")


@tree.command(
    name="changelog",
    description="View past changes to the bot",
)
async def changelog_command(interaction: discord.Interaction):
    log_command(interaction, 'changelog')
    await interaction.response.defer()
    try:
        await handle_changelog(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
        )
    except Exception as e:
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /changelog command: {e}', exc_info=True)


@tree.command(
    name="tetoranks",
    description="Show TETRA LEAGUE rank TR thresholds and stats",
)
@app_commands.describe(
    verbose="Also show position, target TR and rank deflation/inflation (default false)"
)
async def tetoranks_command(interaction: discord.Interaction, verbose: bool = False):
    log_command(interaction, 'tetoranks', verbose=verbose)
    await interaction.response.defer()
    try:
        await handle_tetoranks(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            verbose=verbose,
        )
    except Exception as e:
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /tetoranks command: {e}', exc_info=True)


@tree.command(
    name="tetra",
    description="View past Tetra League games",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
    game_number="Which recent game to display (1-100, default 1)",
    force_update="USE WITH CAUTION: Force update of cached data (default false)"
)
async def tetra_command(interaction: discord.Interaction, username: Optional[str] = None, game_number: Optional[int] = None, force_update: bool = False):
    log_command(interaction, 'tetra', username=username, game_number=game_number, force_update=force_update)
    await interaction.response.defer()
    try:
        await handle_tetra(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
            round_num=game_number or 1,
            force_update=force_update
        )
    except Exception as e:
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /tetra command: {e}', exc_info=True)


@tree.command(
    name="tetra_recent",
    description="View a condensed list of recent Tetra League games",
)
@app_commands.describe(
    username="TETR.IO username (defaults to your linked account)",
    timezone="Timezone for game times: IANA name (e.g. America/New_York) or UTC offset (e.g. UTC-4). Default UTC",
    page_size="How large each page is (1-30, default 10)."
)
async def tetra_recent_command(interaction: discord.Interaction, username: Optional[str] = None, timezone: Optional[str] = None, page_size: Optional[int] = None):
    log_command(interaction, 'tetra_recent', username=username, page_size=page_size, timezone=timezone)
    await interaction.response.defer()
    try:
        await handle_tetra_recent(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            author_id=interaction.user.id,
            username=username,
            tz=timezone,
            page_size=page_size or 10
        )
    except Exception as e:
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /tetra_recent command: {e}', exc_info=True)


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
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /qp command: {e}', exc_info=True)


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
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /leagueflow command: {e}', exc_info=True)

@tree.command(
    name="image",
    description="Search Manebooru (safe filter) for an image",
)
@app_commands.describe(
    tags="Comma-separated search tags (e.g. 'twilight sparkle, solo')",
    sort="How to order results (default: top rated)",
    direction="Sort direction (default: descending)",
    result="Which result to show (1-50, default 1)",
)
async def image_command(interaction: discord.Interaction, tags: str,
                        sort: Literal['score', 'first_seen_at', 'random'] = 'score',
                        direction: Literal['desc', 'asc'] = 'desc',
                        result: Optional[int] = None):
    log_command(interaction, 'image', tags=tags, sort=sort, direction=direction, result=result)
    # Check if bot owner
    if interaction.user.id != bot_owner:
        await interaction.response.send_message('This command is restricted to the bot owner for now.', ephemeral=True)
        return
    await interaction.response.defer()
    try:
        await handle_image(
            send_reply=lambda *args, **kwargs: interaction.followup.send(*args, **kwargs),
            send_message=lambda msg: interaction.followup.send(msg),
            query=tags,
            sort_field=sort,
            sort_direction=direction,
            index=result or 1,
        )
    except Exception as e:
        await interaction.followup.send(f'Internal Error (details omitted). Please ping bot owner if this keeps happening.')
        logger.error(f'Error in /image command: {e}', exc_info=True)


def request_cooldown(interaction: discord.Interaction):
    if interaction.user.id == bot_owner:
        return None
    return app_commands.Cooldown(1, 86400)


@tree.command(
    name="request-feature",
    description="Request a feature for the bot",
)
@app_commands.describe(
    request="Describe the feature you want",
)
@app_commands.checks.dynamic_cooldown(request_cooldown)
async def request_feature_command(interaction: discord.Interaction, request: Optional[str] = None):
    log_command(interaction, 'request-feature', request=request)

    if interaction.user.id == bot_owner:
        await interaction.response.defer()
        content = read_requests().strip()
        if not content:
            await interaction.followup.send('No feature requests yet.')
            return
        for i in range(0, len(content), 2000):
            await interaction.followup.send(content[i:i + 2000])
        return

    if not request or not request.strip():
        await interaction.response.send_message(
            'Please describe the feature you would like. Usage: `/request-feature <your request>`',
            ephemeral=True,
        )
        return

    append_request(interaction.user.id, str(interaction.user), request.strip())
    await interaction.response.send_message('Thanks! Your request has been recorded.', ephemeral=True)


@request_feature_command.error
async def on_request_feature_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        retry = int(error.retry_after)
        hours, rem = divmod(retry, 3600)
        minutes, seconds = divmod(rem, 60)
        await interaction.response.send_message(
            f'You can request another feature in {hours}h {minutes}m {seconds}s.',
            ephemeral=True,
        )
    else:
        raise error


@client.event
async def on_ready():
    await tree.sync()
    logger.info(f'Command tree synced with Discord.')
    tetrioClient.init(headers)
    logger.info('Tetrio client initialized with headers from config.json.')
    manebooruClient.init(headers)
    logger.info('Manebooru client initialized.')
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
        await manebooruClient.shutdown()
        await client.close()

    if message.content.startswith('>tetra'):
        logger.info(f'>tetra | {message.author} ({message.author.id}) | {message.content}')
        try:
            await handle_tetra_message(message)
        except Exception as e:
            await message.reply(f'Error {e.with_traceback(None)}')

client.run(token)
