import itertools
import json
import logging
from datetime import datetime, timezone
import io
import math
import dateparser
from typing import Optional

import discord

logger = logging.getLogger(__name__)

from web import tetrio
from render import tetra as tetra_render
from render import tetra_recent as tetra_recent_render
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
    league = entry["extras"].get("league", {}).get(me["id"])
    if league and len(league) >= 2 and league[0].get("tr") is not None and league[1].get("tr") is not None:
        tr_change = league[1]["tr"] - league[0]["tr"]

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
    }


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
        await interaction.response.edit_message(attachments=[p.render_page()], view=p)


class TetraRecentPaginator(discord.ui.View):
    def __init__(self, games, tz, page_size, username, cursor, has_more):
        super().__init__(timeout=600)      # must stay < 15 min: on_timeout edits via the original interaction token
        self.games = games
        self.tz = tz
        self.page = 0
        self.page_size = page_size
        self.num_pages = math.ceil(len(games) / self.page_size)
        self.message = None                # set after sending, used by on_timeout
        self.username = username
        self.cursor = cursor
        self.has_more = has_more
        self._cache = {}                   # page index -> PNG bytes
        self._sync_buttons()               # must run AFTER super().__init__()

    def render_page(self) -> discord.File:
        if self.page not in self._cache:
            start = self.page * self.page_size
            buf = io.BytesIO()
            tetra_recent_render.render(self.games[start:start + self.page_size],
                                       buf, tz=self.tz, summary=True)
            self._cache[self.page] = buf.getvalue()
        return discord.File(io.BytesIO(self._cache[self.page]), filename="tetra_recent.png")

    async def _flip(self, interaction: discord.Interaction, delta: int):
        target = self.page + delta
        if delta > 0 and target >= self.num_pages and self.has_more:
            first_unseen = len(self.games)
            await self._fetch_older()
            target = first_unseen // self.page_size  # land on the first page with unseen games
        self.page = max(0, min(target, self.num_pages - 1))
        self._sync_buttons()
        await interaction.response.edit_message(attachments=[self.render_page()], view=self)

    async def _fetch_older(self):
        result = await tetrioClient.user_leaderboard(self.username, "league", "recent", after=self.cursor)
        if not result.get('success') or not result["data"]["entries"]:
            self.has_more = False
            return
        entries = result["data"]["entries"]
        p = entries[-1]['p']
        self.cursor = f"{p['pri']}:{p['sec']}:{p['ter']}"
        self.has_more = len(entries) == 100
        new_games = [g for g in (_build_recent_game(e, self.username) for e in entries) if g]
        if new_games:
            self._cache.pop(self.num_pages - 1, None)  # old last page may have been partial — its PNG is stale
            self.games.extend(new_games)
            self.num_pages = math.ceil(len(self.games) / self.page_size)

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
    p = entries[-1]['p']
    cursor = f"{p['pri']}:{p['sec']}:{p['ter']}"
    paginator = TetraRecentPaginator(games, tzinfo, page_size=page_size,
                                     username=username, cursor=cursor,
                                     has_more=len(entries) == TETRA_RECENT_MAX)
    if paginator.num_pages > 1:
        paginator.message = await send_reply(file=paginator.render_page(), view=paginator)
    else:
        await send_reply(file=paginator.render_page())   # single page: footer, no buttons


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