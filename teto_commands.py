import itertools
import json
import logging
from datetime import datetime, timezone
import io
import math
import pathlib
import dateparser
from typing import Optional

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

from web import tetrio
from render import tetra as tetra_render
from render import tetra_recent as tetra_recent_render
from render import leagueflow as leagueflow_render
from render import quickplay as quickplay_render
from render import tetoranks as tetoranks_render
from render import leaderboard as leaderboard_render
from render import achievements as achievements_render

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

past_force_update_users = {}

async def handle_tetra(send_reply, send_message, author_id: int, username: Optional[str] = None, round_num: int = 1, force_update: bool = False):
    """Core logic for the tetra command. send_reply and send_message are callables."""

    if not username:
        username = await resolve_username(author_id)
        if not username:
            await send_message('No linked TETR.IO account found for your Discord ID. Please provide a username. Usage: `>tetra <username> [round]`')
            return

    # Check if the person is using force_update too often - if yes, then they can go fluff themselves and learn to downstack.
    if force_update:
        now = datetime.now(timezone.utc)
        last_used = past_force_update_users.get(author_id)
        if last_used and (now - last_used).total_seconds() < 60:
            await send_message('You are using force_update too frequently. Please only use it when absolutely necessary.\nIf you somehow finished a TL game so quickly, go learn how to downstack.')
            # Log this
            logger.warning(f'User {author_id} is using force_update too frequently.')
            return
        past_force_update_users[author_id] = now

    username = username.lower()

    # Force update doesn't actually do anything if I keep the same X-Session-ID lol
    # So like ima just not do it
    force_update = False
    result: dict = await tetrioClient.user_leaderboard(username, "league", "recent", force_update=force_update)

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


TETRA_RECENT_MAX = 100


def _build_recent_game(entry: dict, username: str) -> Optional[dict]:
    """Condense a single league 'recent' record into the fields the renderer needs,
    seen from *username*'s perspective. Returns None if it can't be interpreted."""
    leaderboard = entry["results"]["leaderboard"]
    if len(leaderboard) < 2:
        return None

    otherusers = entry.get("otherusers") or []
    other_ids = {u["id"] for u in otherusers}

    me = next((p for p in leaderboard if p["username"].lower() == username.lower()), None)
    if me is None:
        # Fall back to the player not listed among the "other" users.
        me = next((p for p in leaderboard if p["id"] not in other_ids), leaderboard[0])
    opp = next((p for p in leaderboard if p["id"] != me["id"]), None)
    if opp is None:
        return None

    opp_info = next((u for u in otherusers if u["id"] == opp["id"]), None)

    result = entry["extras"].get("result", "")
    if result == "dqvictory":
        outcome = "dqvictory"
    elif result == "dqdefeat":
        outcome = "dqdefeat"
    elif "victory" in result:
        outcome = "victory"
    elif "defeat" in result:
        outcome = "defeat"
    elif "nullified" in result:
        outcome = "nullified"
    else:
        outcome = "nocontest"

    tr_change = None
    new_rank = None
    league = entry["extras"].get("league", {}).get(me["id"])
    if league and len(league) >= 2:
        if league[0].get("tr") is not None and league[1].get("tr") is not None:
            tr_change = league[1]["tr"] - league[0]["tr"]
        if league[1].get("rank") and league[0].get("rank") != league[1].get("rank"):
            new_rank = league[1]["rank"]

    stats = me["stats"]
    return {
        "outcome": outcome,
        "my_wins": me["wins"],
        "opp_wins": opp["wins"],
        "opponent": opp["username"],
        "country": (opp_info or {}).get("country"),
        "supporter": (opp_info or {}).get("supporter", False),
        "apm": stats["apm"],
        "pps": stats["pps"],
        "vs": stats["vsscore"],
        "ts": entry["ts"],
        "tr_change": tr_change,
        "new_rank": new_rank,
    }


def _prisecter(entry: dict) -> str:
    """Pagination cursor for the entry after *entry*."""
    p = entry['p']
    return f"{p['pri']}:{p['sec']}:{p['ter']}"


class PageJumpModal(discord.ui.Modal, title="Jump to page"):
    page_number = discord.ui.TextInput(label="Page number", max_length=4)

    def __init__(self, paginator):
        super().__init__()
        self.paginator = paginator
        self.page_number.placeholder = f"1-{paginator.num_pages}"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target = int(self.page_number.value) - 1
        except ValueError:
            await interaction.response.send_message(
                f"`{self.page_number.value}` is not a page number.", ephemeral=True)
            return
        p = self.paginator
        p.page = max(0, min(target, p.num_pages - 1))
        p._sync_buttons()
        await interaction.response.edit_message(**p.page_kwargs(), view=p)


class ImagePaginator(discord.ui.View):
    """First/Previous/Page/Next buttons over a PNG rendered from a growing list
    of rows. Subclasses implement :meth:`_render_rows` and, if the source can
    be extended past what was initially fetched, :meth:`_fetch_more`."""
    filename = "page.png"

    def __init__(self, rows, page_size, has_more=False):
        super().__init__(timeout=600)      # must stay < 15 min: on_timeout edits via the original interaction token
        self.rows = rows
        self.page = 0
        self.page_size = page_size
        self.num_pages = math.ceil(len(rows) / self.page_size)
        self.message = None                # set after sending, used by on_timeout
        self.has_more = has_more
        self._cache = {}                   # page index -> PNG bytes
        self._sync_buttons()               # must run AFTER super().__init__()

    def _render_rows(self, rows) -> bytes:
        raise NotImplementedError

    async def _fetch_more(self) -> list:
        """Fetch the next batch of rows, update self.has_more, return the new rows."""
        return []

    def render_page(self) -> discord.File:
        if self.page not in self._cache:
            start = self.page * self.page_size
            self._cache[self.page] = self._render_rows(self.rows[start:start + self.page_size])
        return discord.File(io.BytesIO(self._cache[self.page]), filename=self.filename)

    def page_kwargs(self):
        """Edit-message kwargs for the current page (shared with PageJumpModal)."""
        return {"attachments": [self.render_page()]}

    async def _flip(self, interaction: discord.Interaction, delta: int):
        target = self.page + delta
        if delta > 0 and target >= self.num_pages and self.has_more:
            first_unseen = len(self.rows)
            await self._extend()
            target = first_unseen // self.page_size  # land on the first page with unseen rows
        self.page = max(0, min(target, self.num_pages - 1))
        self._sync_buttons()
        await interaction.response.edit_message(**self.page_kwargs(), view=self)

    async def _extend(self):
        new_rows = await self._fetch_more()
        if new_rows:
            self._cache.pop(self.num_pages - 1, None)  # old last page may have been partial: its PNG is stale
            self.rows.extend(new_rows)
            self.num_pages = math.ceil(len(self.rows) / self.page_size)

    def _sync_buttons(self):
        self.first_button.disabled = (self.page <= 0)
        self.prev_button.disabled = (self.page <= 0)
        self.next_button.disabled = (self.page >= self.num_pages - 1) and not self.has_more
        self.page_label.disabled = (self.num_pages <= 1 and not self.has_more)
        suffix = "+" if self.has_more else ""
        self.page_label.label = f"Page {self.page + 1}/{self.num_pages}{suffix}"

    @discord.ui.button(label="First", style=discord.ButtonStyle.secondary, disabled=True)
    async def first_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, -self.page)  # go to page 0

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, -1)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.gray)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PageJumpModal(self))

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, +1)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass  # message deleted or token expired


class TetraRecentPaginator(ImagePaginator):
    filename = "tetra_recent.png"

    def __init__(self, games, tz, page_size, username, cursor, has_more):
        self.tz = tz
        self.username = username
        self.cursor = cursor
        super().__init__(games, page_size, has_more)

    @property
    def games(self):
        return self.rows

    def _render_rows(self, rows) -> bytes:
        buf = io.BytesIO()
        tetra_recent_render.render(rows, buf, tz=self.tz, summary=True)
        return buf.getvalue()

    async def _fetch_more(self) -> list:
        result = await tetrioClient.user_leaderboard(self.username, "league", "recent", after=self.cursor)
        if not result.get('success') or not result["data"]["entries"]:
            self.has_more = False
            return []
        entries = result["data"]["entries"]
        self.cursor = _prisecter(entries[-1])
        self.has_more = len(entries) == 100
        return [g for g in (_build_recent_game(e, self.username) for e in entries) if g]


CHANGELOG_PATH = pathlib.Path(__file__).parent / 'changelog.json'
CHANGELOG_PAGE_SIZE = 5


class ChangelogPaginator(discord.ui.View):
    def __init__(self, entries):
        super().__init__(timeout=600)      # must stay < 15 min: on_timeout edits via the original interaction token
        self.entries = entries
        self.page = 0
        self.num_pages = math.ceil(len(entries) / CHANGELOG_PAGE_SIZE)
        self.message = None                # set after sending, used by on_timeout
        self._sync_buttons()               # must run AFTER super().__init__()

    def build_embed(self) -> discord.Embed:
        start = self.page * CHANGELOG_PAGE_SIZE
        embed = discord.Embed(title="Changelog", colour=discord.Colour.green())
        for entry in self.entries[start:start + CHANGELOG_PAGE_SIZE]:
            name = entry.get('version') or '?'
            if entry.get('date'):
                name += f" — {entry['date']}"
            value = '\n'.join(f'- {c}' for c in entry.get('changes') or []) or '(no details)'
            embed.add_field(name=name[:256], value=value[:1024], inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{self.num_pages}")
        return embed

    def page_kwargs(self):
        """Edit-message kwargs for the current page (shared with PageJumpModal)."""
        return {"embed": self.build_embed()}

    def _sync_buttons(self):
        self.first_button.disabled = (self.page <= 0)
        self.prev_button.disabled = (self.page <= 0)
        self.next_button.disabled = (self.page >= self.num_pages - 1)
        self.page_label.disabled = (self.num_pages <= 1)
        self.page_label.label = f"Page {self.page + 1}/{self.num_pages}"

    async def _flip(self, interaction: discord.Interaction, delta: int):
        self.page = max(0, min(self.page + delta, self.num_pages - 1))
        self._sync_buttons()
        await interaction.response.edit_message(**self.page_kwargs(), view=self)

    @discord.ui.button(label="First", style=discord.ButtonStyle.secondary, disabled=True)
    async def first_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, -self.page)  # go to page 0

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, -1)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.gray)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PageJumpModal(self))

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, +1)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass  # message deleted or token expired


async def handle_changelog(send_reply, send_message):
    """Core logic for the changelog command. send_reply and send_message are callables."""

    try:
        with open(CHANGELOG_PATH, 'r', encoding='utf-8') as f:
            entries = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f'Failed to load {CHANGELOG_PATH}: {e}')
        await send_message('Changelog is unavailable right now.')
        return

    if not entries:
        await send_message('No changelog entries yet.')
        return

    paginator = ChangelogPaginator(entries)
    if paginator.num_pages > 1:
        paginator.message = await send_reply(embed=paginator.build_embed(), view=paginator)
    else:
        await send_reply(embed=paginator.build_embed())   # single page: no buttons


async def handle_tetra_recent(send_reply, send_message, author_id: int, username: Optional[str] = None, page_size: Optional[int] = None, tz: Optional[str] = None):
    """Core logic for the tetra_recent command. send_reply and send_message are callables."""

    tzinfo = tetra_recent_render.parse_timezone(tz)
    if tzinfo is None:
        await send_message(f'Invalid timezone: `{tz}`. Use an IANA name (e.g. `America/New_York`) or a UTC offset (e.g. `UTC-4`).')
        return

    if not username:
        username = await resolve_username(author_id)
        if not username:
            await send_message('No linked TETR.IO account found for your Discord ID. Please provide a username. Usage: `/tetra_recent <username> [count]`')
            return

    username = username.lower()

    result: dict = await tetrioClient.user_leaderboard(username, "league", "recent")

    if not result['success']:
        await send_reply(f"{result['error']['msg']}")
        return

    entries = result["data"]["entries"]
    if not entries:
        await send_message('No recent Tetra League games found for this user.')
        return

    # count = max(1, min(count, TETRA_RECENT_MAX, len(entries)))
    count = min(TETRA_RECENT_MAX, len(entries))
    page_size = max(1, min(page_size, 30)) if page_size is not None else 10

    games = []
    for entry in entries[:count]:
        game = _build_recent_game(entry, username)
        if game is not None:
            games.append(game)

    if not games:
        await send_message('No recent Tetra League games found for this user.')
        return

    # tetra_recent_render.render(games, "recent_output.png", tz=tzinfo)
    cursor = _prisecter(entries[-1])
    paginator = TetraRecentPaginator(games, tzinfo, page_size=page_size,
                                     username=username, cursor=cursor,
                                     has_more=len(entries) == TETRA_RECENT_MAX)
    if paginator.num_pages > 1:
        paginator.message = await send_reply(file=paginator.render_page(), view=paginator)
    else:
        await send_reply(file=paginator.render_page())   # single page: footer, no buttons


async def handle_tetoranks(send_reply, send_message, verbose: bool = False):
    """Core logic for the tetoranks command. send_reply and send_message are callables."""

    result: dict = await tetrioClient.league_ranks()

    if not result['success']:
        await send_reply(f"{result['error']['msg']}")
        return

    total, ranks = tetoranks_render.parse(result['data']['data'])

    if not ranks:
        await send_message('No rank data available right now.')
        return

    tetoranks_render.render(ranks, "tetoranks.png", total=total, verbose=verbose)
    await send_reply(file=discord.File("tetoranks.png"))


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

    best_scores_result: dict = await tetrioClient.user_leaderboard(username, gamemode, "top")
    if not best_scores_result['success']:
        await send_reply(f"{best_scores_result['error']['msg']}")
        return

    if sort_by == 'recent':
        result: dict = await tetrioClient.user_leaderboard(username, gamemode, "recent")

        if not result['success']:
            await send_reply(f"{result['error']['msg']}")
            return

        with open("quickplay_output_2.json", "w") as f:
            json.dump(result, f, indent=4)
    else:
        result = best_scores_result

    entries = result["data"]["entries"]
    if round_num < 1 or round_num > len(entries):
        await send_reply(f"Invalid game number. Please choose between 1 and {len(entries)}.")
        return

    entry = entries[round_num - 1]

    # Find the true rank of the entry
    entry_id = entry["_id"]
    entry_altitude = entry["results"]["stats"]["zenith"]["altitude"]

    entry["global_rank"] = None
    entry["country_rank"] = None
    entry["personal_rank"] = None

    for i, e in enumerate(best_scores_result["data"]["entries"]):
        if e["_id"] == entry_id:
            entry["personal_rank"] = i + 1
            break

    best_global_scores = await tetrioClient.records_leaderboard(f"{gamemode}_global", limit=500)
    best_country_scores = await tetrioClient.records_leaderboard(f"{gamemode}_country_{user_country}", limit=500)

    best_global_scores_id_nested = [[entry["_id"] for entry in s["data"]["entries"]] for s in best_global_scores]
    best_global_id_list = list(itertools.chain.from_iterable(best_global_scores_id_nested))

    for global_score in best_global_scores:
        for e in global_score["data"]["entries"]:
            if e["_id"] == entry_id:
                entry["global_rank"] = best_global_id_list.index(entry_id) + 1
                break
            if e["results"]["stats"]["zenith"]["altitude"] < entry_altitude:
                entry["global_rank"] = best_global_id_list.index(e["_id"])
                break
        else:
            continue
        break

    entry["global_max_rank"] = len(best_global_id_list) + 1

    best_country_scores_nested = [[entry["_id"] for entry in s["data"]["entries"]] for s in best_country_scores]
    best_country_id_list = list(itertools.chain.from_iterable(best_country_scores_nested))

    for country_score in best_country_scores:
        for e in country_score["data"]["entries"]:
            if e["_id"] == entry_id:
                entry["country_rank"] = best_country_id_list.index(entry_id) + 1
                break
            if e["results"]["stats"]["zenith"]["altitude"] < entry_altitude:
                entry["country_rank"] = best_country_id_list.index(e["_id"])
                break
        else:
            continue
        break

    entry["country_max_rank"] = len(best_country_id_list) + 1

    quickplay_render.render_quickplay(entry, "qp_output.png")
    await send_reply(file=discord.File("qp_output.png"))


# ── /tetolb ────────────────────────────────────────────────────────────────────

LB_BOARDS = tetrio.USER_BOARDS + tetrio.RECORD_BOARDS
LB_PAGE_SIZE_DEFAULT = 10
LB_PAGE_SIZE_MAX = 25
LB_START_RANK_MAX = 1000       # seeding deeper than this means too many sequential API calls
LB_FETCH_SIZE = 100


def _xp_level(xp: float) -> int:
    """TETR.IO's XP -> level curve (verified against tetrio.team2xh.net/levels.txt)."""
    return math.floor((xp / 500) ** 0.6 + xp / (5000 + max(0, xp - 4e6) / 5000) + 1)


def _finesse(stats: dict):
    """(faults, accuracy %) for a singleplayer record, or None if unavailable."""
    fin = stats.get('finesse') or {}
    pieces = stats.get('piecesplaced')
    faults, perfect = fin.get('faults'), fin.get('perfectpieces')
    if faults is None or perfect is None or not pieces:
        return None
    return faults, perfect / pieces * 100


def _ratio(a, b):
    return a / b if a is not None and b else None


def _build_lb_row(board: str, entry: dict, rank: int) -> dict:
    """Flatten one leaderboard entry into the fields the renderer needs."""
    if board in tetrio.USER_BOARDS:
        league = entry.get('league') or {}
        row = {
            'rank': rank,
            'username': entry['username'],
            'country': entry.get('country'),
            'supporter': entry.get('supporter', False),
            'league_rank': league.get('rank'),
        }
        if board == 'league':
            row.update(tr=league.get('tr'), glicko=league.get('glicko'), rd=league.get('rd'),
                       apm=league.get('apm'), pps=league.get('pps'), vs=league.get('vs'),
                       games=league.get('gamesplayed'), wins=league.get('gameswon'))
        elif board == 'xp':
            xp = entry.get('xp') or 0
            games, gametime = entry.get('gamesplayed'), entry.get('gametime')
            row.update(xp=xp, level=_xp_level(xp),
                       games=games if games is not None and games >= 0 else None,
                       hours=(gametime / 3600) if gametime is not None and gametime >= 0 else None)
        else:  # ar
            counts = entry.get('ar_counts') or {}
            row['ar'] = entry.get('ar')
            for key in ('1', '2', '3', '4', '5', 't100', 't50', 't25', 't10', 't5', 't3'):
                row[f'ar_{key}'] = counts.get(key, 0)
        return row

    user = entry['user']
    results = entry['results']
    stats = results.get('stats') or {}
    agg = results.get('aggregatestats') or {}
    row = {
        'rank': rank,
        'username': user['username'],
        'country': user.get('country'),
        'supporter': user.get('supporter', False),
        'ts': entry.get('ts'),
    }
    if board == '40l':
        pieces, inputs, ms = stats.get('piecesplaced'), stats.get('inputs'), stats.get('finaltime')
        row.update(time=ms, pps=agg.get('pps'), pieces=pieces, finesse=_finesse(stats),
                   kpp=_ratio(inputs, pieces), kps=_ratio(inputs, ms / 1000 if ms else None))
    elif board == 'blitz':
        pieces, score = stats.get('piecesplaced'), stats.get('score')
        row.update(score=score, level=stats.get('level'), pps=agg.get('pps'), pieces=pieces,
                   finesse=_finesse(stats), spp=_ratio(score, pieces))
    else:  # zenith / zenithex
        z = stats.get('zenith') or {}
        row.update(altitude=z.get('altitude'), floor=z.get('floor'), time=stats.get('finaltime'),
                   apm=agg.get('apm'), pps=agg.get('pps'), vs=agg.get('vsscore'),
                   mods=((entry.get('extras') or {}).get('zenith') or {}).get('mods') or [])
    return row


class LeaderboardPaginator(ImagePaginator):
    filename = "tetolb.png"

    def __init__(self, rows, board, country, page_size, cursor, has_more):
        self.board = board
        self.country = country
        self.cursor = cursor
        super().__init__(rows, page_size, has_more)

    def _render_rows(self, rows) -> bytes:
        buf = io.BytesIO()
        leaderboard_render.render(rows, buf, board=self.board, country=self.country)
        return buf.getvalue()

    async def _fetch_more(self) -> list:
        result = await tetrioClient.leaderboard_page(self.board, self.country, after=self.cursor,
                                                     limit=LB_FETCH_SIZE)
        entries = (result.get('data') or {}).get('entries') if result.get('success') else None
        if not entries:
            self.has_more = False
            return []
        self.cursor = _prisecter(entries[-1])
        self.has_more = len(entries) == LB_FETCH_SIZE
        base = len(self.rows)
        return [_build_lb_row(self.board, e, base + i + 1) for i, e in enumerate(entries)]


async def handle_tetolb(send_reply, send_message, board: str = 'league', country: Optional[str] = None,
                        page_size: Optional[int] = None, start_rank: Optional[int] = None):
    """Core logic for the tetolb command. send_reply and send_message are callables."""
    board = (board or 'league').lower()
    if board not in LB_BOARDS:
        await send_message(f'Unknown leaderboard `{board}`. Choose one of: {", ".join(LB_BOARDS)}.')
        return

    if country:
        country = country.strip().upper()
        if len(country) != 2 or not country.isalpha():
            await send_message(f'Invalid country `{country}`. Use a two-letter ISO code (e.g. `US`).')
            return

    page_size = max(1, min(page_size or LB_PAGE_SIZE_DEFAULT, LB_PAGE_SIZE_MAX))
    start_rank = max(1, min(start_rank or 1, LB_START_RANK_MAX))

    # Seed enough pages to reach start_rank (there is no rank -> cursor lookup).
    rows, cursor, has_more = [], None, True
    while has_more and len(rows) < start_rank:
        result = await tetrioClient.leaderboard_page(board, country, after=cursor, limit=LB_FETCH_SIZE)
        if not result.get('success'):
            await send_reply(f"{result.get('error', {}).get('msg', 'Unknown error')}")
            return
        entries = result['data']['entries']
        if not entries:
            has_more = False
            break
        base = len(rows)
        rows.extend(_build_lb_row(board, e, base + i + 1) for i, e in enumerate(entries))
        cursor = _prisecter(entries[-1])
        has_more = len(entries) == LB_FETCH_SIZE

    if not rows:
        await send_message('No entries found on this leaderboard.')
        return

    paginator = LeaderboardPaginator(rows, board, country, page_size, cursor, has_more)
    paginator.page = min((start_rank - 1) // page_size, paginator.num_pages - 1)
    paginator._sync_buttons()
    if paginator.num_pages > 1 or paginator.has_more:
        paginator.message = await send_reply(file=paginator.render_page(), view=paginator)
    else:
        await send_reply(file=paginator.render_page())   # single page: no buttons


# ── /teto_achievements ─────────────────────────────────────────────────────────

ACHIEVEMENTS_PATH = pathlib.Path(__file__).parent / 'achievements.json'
ACH_PAGE_SIZE_DEFAULT = 10
ACH_PAGE_SIZE_MAX = 25
ACH_START_RANK_MAX = 1000      # seeding deeper than this means too many sequential API calls
ACH_FETCH_SIZE = 100

_achievements_cache = None


def _load_achievements() -> list:
    """The bundled achievement table, used only to power autocomplete and to
    resolve a typed name to an ID. Rendering always uses the live API response,
    so a stale file can never produce a wrong board -- at worst a new achievement
    is missing from the suggestions and has to be given by ID."""
    global _achievements_cache
    if _achievements_cache is None:
        try:
            with open(ACHIEVEMENTS_PATH, encoding='utf-8') as f:
                _achievements_cache = json.load(f)
        except (OSError, ValueError):
            logger.warning(f'Could not read {ACHIEVEMENTS_PATH.name}; autocomplete disabled')
            _achievements_cache = []
    return _achievements_cache


def _resolve_achievement(text: str) -> Optional[int]:
    """An autocomplete value, a raw ID or an achievement name -> achievement ID."""
    text = (text or '').strip()
    if not text:
        return None
    if text.lstrip('#').isdigit():
        return int(text.lstrip('#'))
    lowered = text.lower()
    achievements = _load_achievements()
    for a in achievements:
        if a['name'].lower() == lowered:
            return a['k']
    for a in achievements:
        if lowered in a['name'].lower():
            return a['k']
    return None


async def achievement_autocomplete(interaction: discord.Interaction, current: str):
    """Discord caps choices at 25 and there are 66 achievements, so the picker
    has to filter rather than list."""
    query = (current or '').strip().lower()
    matches = [a for a in _load_achievements()
               if not query
               or query in a['name'].lower()
               or query in (a.get('category') or '').lower()
               or query in (a.get('object') or '').lower()
               or query == str(a['k'])]
    return [app_commands.Choice(name=f"#{a['k']} - {a['name']} ({a['category']})"[:100],
                                value=str(a['k']))
            for a in matches[:25]]


def _build_ach_row(entry: dict, pos: int) -> dict:
    """Flatten one achievement entry into the fields the renderer needs."""
    user = entry.get('u') or {}
    ally = (entry.get('x') or {}).get('ally')
    return {
        'pos': pos,
        'username': user.get('username'),
        'country': user.get('country'),
        'supporter': user.get('supporter', False),
        'ally': {'username': ally.get('username'), 'country': ally.get('country'),
                 'supporter': ally.get('supporter', False)} if ally else None,
        'v': entry.get('v'),
        'a': entry.get('a'),
        'ts': entry.get('t'),
    }


def _untiebreak(pri: float) -> float:
    """TETR.IO nudges each prisecter by a tiny unique amount to keep the sort
    stable; strip it so genuinely equal scores compare equal."""
    return round(pri * 1e4) / 1e4


def _ach_rows(entries: list, ach: dict, state: Optional[dict] = None):
    """Number *entries* into rows, returning (rows, state).

    Mirrors the doublecount handling in ch.tetr.io/res/js/leaderboard-base.js:
    entries with the same score share a position and the next distinct score
    skips past all of them. Pair achievements (Duo) return both halves of every
    pair, so an entry is dropped once either of its two players has been seen.
    *state* carries the counters between pages -- pass back the value returned by
    the previous call."""
    if state is None:
        state = {'position': 0, 'pending': 0, 'last_pri': None, 'seen': set()}
    pair = bool(ach.get('pair'))
    rows = []

    for entry in entries:
        pri = (entry.get('p') or {}).get('pri')
        if pair:
            user_id = (entry.get('u') or {}).get('_id')
            ally_id = ((entry.get('x') or {}).get('ally') or {}).get('_id')
            if user_id in state['seen'] or (ally_id and ally_id in state['seen']):
                state['last_pri'] = pri
                continue
            state['seen'].add(user_id)
            if ally_id:
                state['seen'].add(ally_id)

        tied = (state['last_pri'] is not None and pri is not None
                and abs(_untiebreak(state['last_pri']) - _untiebreak(pri)) <= 0.001)
        if tied:
            state['pending'] += 1
        else:
            state['position'] += state['pending'] + 1
            state['pending'] = 0
        state['last_pri'] = pri
        rows.append(_build_ach_row(entry, state['position']))

    return rows, state


def _ach_top_values(entries: list) -> dict:
    """The value held at each competitive placement, for the header's TOP N cards.
    Read from the untouched first page, exactly as achievement.js does."""
    return {key: entries[pos - 1]['v']
            for key, pos, _ar in achievements_render.COMPETITIVE_AR if len(entries) >= pos}


class AchievementPaginator(ImagePaginator):
    filename = "teto_achievements.png"

    def __init__(self, rows, k, achievement, cutoffs, top_values, page_size, cursor,
                 has_more, state):
        self.k = k
        self.achievement = achievement
        self.cutoffs = cutoffs
        self.top_values = top_values
        self.cursor = cursor
        self.state = state            # position/tie/seen counters, continued by _fetch_more
        super().__init__(rows, page_size, has_more)

    def _render_rows(self, rows) -> bytes:
        buf = io.BytesIO()
        achievements_render.render(rows, buf, achievement=self.achievement,
                                   cutoffs=self.cutoffs, top_values=self.top_values)
        return buf.getvalue()

    async def _fetch_more(self) -> list:
        result = await tetrioClient.achievement_entries(self.k, after=self.cursor,
                                                        limit=ACH_FETCH_SIZE)
        entries = (result.get('data') or {}).get('entries') if result.get('success') else None
        if not entries:
            self.has_more = False
            return []
        self.cursor = _prisecter(entries[-1])
        self.has_more = len(entries) == ACH_FETCH_SIZE
        rows, self.state = _ach_rows(entries, self.achievement, self.state)
        return rows


async def handle_teto_achievements(send_reply, send_message, achievement: str,
                                   page_size: Optional[int] = None,
                                   start_rank: Optional[int] = None):
    """Core logic for the teto_achievements command. send_reply and send_message
    are callables."""
    k = _resolve_achievement(achievement)
    if k is None:
        await send_message(f'Unknown achievement "{achievement}". Pick one from the '
                           f'autocomplete list, or give an ID between 1 and 67.')
        return

    page_size = max(1, min(page_size or ACH_PAGE_SIZE_DEFAULT, ACH_PAGE_SIZE_MAX))
    start_rank = max(1, min(start_rank or 1, ACH_START_RANK_MAX))

    # Page one also carries the achievement info and cutoffs the header needs.
    result = await tetrioClient.achievement(k)
    if not result.get('success'):
        await send_reply(f"{result.get('error', {}).get('msg', 'Unknown error')}")
        return
    data = result['data']
    ach, cutoffs = data['achievement'], data.get('cutoffs') or {}
    entries = data.get('leaderboard') or []
    top_values = _ach_top_values(entries)

    rows, state = _ach_rows(entries, ach)
    cursor = _prisecter(entries[-1]) if entries else None
    has_more = len(entries) == ACH_FETCH_SIZE

    # Seed enough pages to reach start_rank (there is no rank -> cursor lookup).
    while has_more and len(rows) < start_rank:
        page = await tetrioClient.achievement_entries(k, after=cursor, limit=ACH_FETCH_SIZE)
        if not page.get('success'):
            await send_reply(f"{page.get('error', {}).get('msg', 'Unknown error')}")
            return
        page_entries = page['data']['entries']
        if not page_entries:
            has_more = False
            break
        new_rows, state = _ach_rows(page_entries, ach, state)
        rows.extend(new_rows)
        cursor = _prisecter(page_entries[-1])
        has_more = len(page_entries) == ACH_FETCH_SIZE

    if not rows:
        await send_message(f"No one has earned {ach.get('name', k)} yet.")
        return

    paginator = AchievementPaginator(rows, k, ach, cutoffs, top_values, page_size, cursor,
                                     has_more, state)
    paginator.page = min((start_rank - 1) // page_size, paginator.num_pages - 1)
    paginator._sync_buttons()
    if paginator.num_pages > 1 or paginator.has_more:
        paginator.message = await send_reply(file=paginator.render_page(), view=paginator)
    else:
        await send_reply(file=paginator.render_page())   # single page: no buttons
