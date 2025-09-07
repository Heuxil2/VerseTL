# Standard library
import os
import json
import asyncio
import datetime as dt
from io import BytesIO
import datetime
import time
import random

# Discord
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.errors import HTTPException

# Env/hosting
from dotenv import load_dotenv
from keep_alive import keep_alive, register_vanilla_callback

# Google APIs (optionnels)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except Exception:
    service_account = None
    build = None

    class HttpError(Exception):
        pass

# ============ CONFIG & AUTHORIZATION ============

load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0")) if os.getenv("GUILD_ID") else None

# Bot owner (Heuxil) and server authorization persistence
OWNER_ID = 836452038548127764  # Heuxil
AUTHORIZED_FILE = "authorized_guilds.json"
authorized_guilds = set()
APP_CHECK_ADDED = False  # pour n'ajouter le check global qu'une seule fois

def _env_guild_ids():
    """
    Récupère les Guild IDs à scanner pour build_tiers.
    GUILD_ID_1 / GUILD_ID_2 (prioritaires), sinon GUILD_ID.
    """
    ids = []
    for key in ("GUILD_ID_1", "GUILD_ID_2"):
        v = os.getenv(key)
        if v:
            try:
                ids.append(int(v))
            except ValueError:
                pass
    if not ids and GUILD_ID:
        try:
            ids.append(int(GUILD_ID))
        except ValueError:
            pass
    return ids

# ====== Tiers builder (dedupe across 2 guilds; highest role wins) ======
def _split_ids(env_value: str | None):
    if not env_value:
        return []
    return [s.strip() for s in env_value.split(",") if s.strip()]

def _role_id_ranks_from_env():
    """
    role_id (str) -> (rank, display_tier, exact_label)
    """
    def get_ids(plural_key, singular_key):
        v = os.getenv(plural_key) or os.getenv(singular_key)
        return _split_ids(v)

    entries = [
        ("HT1_ROLE_IDS", "HT1_ROLE_ID", 1, 1),
        ("LT1_ROLE_IDS", "LT1_ROLE_ID", 2, 1),
        ("HT2_ROLE_IDS", "HT2_ROLE_ID", 3, 2),
        ("LT2_ROLE_IDS", "LT2_ROLE_ID", 4, 2),
        ("HT3_ROLE_IDS", "HT3_ROLE_ID", 5, 3),
        ("LT3_ROLE_IDS", "LT3_ROLE_ID", 6, 3),
        ("HT4_ROLE_IDS", "HT4_ROLE_ID", 7, 4),
        ("LT4_ROLE_IDS", "LT4_ROLE_ID", 8, 4),
        ("HT5_ROLE_IDS", "HT5_ROLE_ID", 9, 5),
        ("LT5_ROLE_IDS", "LT5_ROLE_ID", 10, 5),
    ]

    mapping = {}
    for plural, singular, rank, disp in entries:
        exact = plural.split("_", 1)[0]
        for rid in get_ids(plural, singular):
            mapping[str(rid)] = (rank, disp, exact)
    return mapping

ROLE_ID_RANKS = _role_id_ranks_from_env()

NAME_RANKS = {
    "HT1": (1,1), "LT1": (2,1),
    "HT2": (3,2), "LT2": (4,2),
    "HT3": (5,3), "LT3": (6,3),
    "HT4": (7,4), "LT4": (8,4),
    "HT5": (9,5), "LT5": (10,5),
}
EXACT_KEYS = ["HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]

def _normalize_role_name(n: str) -> str:
    return (n or "").strip().upper().replace("-", "").replace("_", "").replace(" ", "")

def _pick_display_name(m: discord.Member) -> str:
    return m.name

def _member_best_rank(member: discord.Member):
    best = None
    if ROLE_ID_RANKS:
        ids = {str(r.id) for r in member.roles}
        for rid in ids:
            if rid in ROLE_ID_RANKS:
                rnk = ROLE_ID_RANKS[rid]
                if (best is None) or (rnk[0] < best[0]):
                    best = rnk
    if best is None:
        for r in member.roles:
            key = _normalize_role_name(r.name)
            if key in NAME_RANKS:
                rank, disp = NAME_RANKS[key]
                rnk = (rank, disp, key)
                if (best is None) or (rnk[0] < best[0]):
                    best = rnk
    return best

async def build_tiers(bot: commands.Bot) -> dict:
    guild_ids = _env_guild_ids()
    if not guild_ids:
        raise RuntimeError("No GUILD_ID_1/GUILD_ID_2 (or GUILD_ID) configured")

    users = {}
    for gid in guild_ids:
        guild = bot.get_guild(gid) or await bot.fetch_guild(gid)
        async for m in guild.fetch_members(limit=None):
            best = _member_best_rank(m)
            if best is None:
                continue
            rank, disp, exact = best
            ign = None
            try:
                info = user_info.get(m.id)
                ign = (info or {}).get("ign")
            except Exception:
                ign = None
            cur = users.get(m.id)
            if (cur is None) or (rank < cur["rank"]):
                users[m.id] = {
                    "discord": _pick_display_name(m),
                    "ign": ign,
                    "rank": rank,
                    "display_tier": disp,
                    "exact": exact
                }

    tiers_discord = {f"tier{i}": [] for i in range(1, 6)}
    tiers_ign = {f"tier{i}": [] for i in range(1, 6)}
    tiers_detailed = {f"tier{i}": [] for i in range(1, 6)}
    exact_buckets_discord = {k: [] for k in EXACT_KEYS}
    exact_buckets_ign = {k: [] for k in EXACT_KEYS}

    for uid, data in users.items():
        tier_key = f"tier{data['display_tier']}"
        discord_name = data["discord"]
        ign_name = data["ign"] or discord_name

        tiers_discord[tier_key].append(discord_name)
        tiers_ign[tier_key].append(ign_name)
        tiers_detailed[tier_key].append({
            "user_id": uid,
            "discord": discord_name,
            "ign": data["ign"],
            "exact": data["exact"]
        })

        exact_buckets_discord[data["exact"]].append(discord_name)
        exact_buckets_ign[data["exact"]].append(ign_name)

    for arr in tiers_discord.values():
        arr.sort(key=lambda s: s.lower())
    for arr in tiers_ign.values():
        arr.sort(key=lambda s: s.lower())
    for arr in tiers_detailed.values():
        arr.sort(key=lambda d: (d["ign"] or d["discord"]).lower())
    for arr in exact_buckets_discord.values():
        arr.sort(key=lambda s: s.lower())
    for arr in exact_buckets_ign.values():
        arr.sort(key=lambda s: s.lower())

    return {
        "tiers": tiers_discord,
        "tiers_ign": tiers_ign,
        "tiers_detailed": tiers_detailed,
        "exact_tiers": exact_buckets_discord,
        "exact_tiers_ign": exact_buckets_ign,
    }

def load_authorized_guilds():
    global authorized_guilds
    try:
        if os.path.exists(AUTHORIZED_FILE):
            with open(AUTHORIZED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                authorized_guilds = set(data.get("guild_ids", []))
                print(f"DEBUG: Loaded {len(authorized_guilds)} authorized guild(s)")
        else:
            authorized_guilds = set()
            print("DEBUG: No authorized_guilds file found, starting empty")
    except Exception as e:
        print(f"DEBUG: Error loading authorized guilds: {e}")
        authorized_guilds = set()

def save_authorized_guilds():
    try:
        with open(AUTHORIZED_FILE, "w", encoding="utf-8") as f:
            json.dump({"guild_ids": list(authorized_guilds)}, f, indent=2)
        print(f"DEBUG: Saved {len(authorized_guilds)} authorized guild(s)")
    except Exception as e:
        print(f"DEBUG: Error saving authorized guilds: {e}")

def is_guild_authorized(guild_id):
    if guild_id is None:
        return False
    return guild_id in authorized_guilds

# ============ DISCORD SETUP ============

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Store server backups and logs
server_backups = {}
message_logs = {}

# Waitlist system variables
waitlists = {"na": [], "eu": [], "as": [], "au": []}
MAX_WAITLIST = 20
waitlist_message_ids = {}
waitlist_messages = {}
opened_queues = {}
active_testers = {}
user_info = {}
last_test_session = datetime.datetime.now()
last_region_activity = {}
tester_stats = {}
STATS_FILE = "tester_stats.json"
USER_INFO_FILE = "user_info.json"
user_test_cooldowns = {}
COOLDOWNS_FILE = "user_cooldowns.json"
LAST_ACTIVITY_FILE = "last_region_activity.json"

def _ensure_guild_queue_state(guild_id: int):
    if guild_id not in opened_queues:
        opened_queues[guild_id] = set()
    if guild_id not in active_testers:
        active_testers[guild_id] = {"na": [], "eu": [], "as": [], "au": []}

def _ensure_guild_activity_state(guild_id: int):
    if guild_id not in last_region_activity:
        last_region_activity[guild_id] = {"na": None, "eu": None, "as": None, "au": None}

# ====== Export web vanilla.json ======
VANILLA_CACHE = {
    "updated_at": None,
    "tiers": {f"tier{i}": [] for i in range(1, 6)},
    "tiers_ign": {f"tier{i}": [] for i in range(1, 6)},
    "tiers_detailed": {f"tier{i}": [] for i in range(1, 6)},
    "exact_tiers": {k: [] for k in EXACT_KEYS},
    "exact_tiers_ign": {k: [] for k in EXACT_KEYS},
}

async def rebuild_and_cache_vanilla():
    global VANILLA_CACHE
    built = await build_tiers(bot)
    VANILLA_CACHE = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **built,
    }
    total = sum(len(v) for v in built["tiers"].values())
    print(f"DEBUG: Rebuilt vanilla cache with {total} users")

@tasks.loop(minutes=10)
async def refresh_vanilla_export():
    try:
        await rebuild_and_cache_vanilla()
    except Exception as e:
        print(f"DEBUG: refresh_vanilla_export failed: {e}")

def _vanilla_payload():
    return VANILLA_CACHE

# Track active testing sessions
active_testing_sessions = {}
REGULAR_COOLDOWN_DAYS = 4
BOOSTER_COOLDOWN_DAYS = 2

SPREADSHEET_ID = "14JoOjPeQYJ1vq5WW2MGNrtNi79YUTrPw7fwUVVjH0CM"
TIER_COLUMNS = {
    "HT1": "B","LT1": "C","HT2": "D","LT2": "E","HT3": "F","LT3": "G","HT4": "H","LT4": "I","HT5": "J","LT5": "K"
}
HIGH_TIERS = ["HT1", "LT1", "HT2", "LT2", "HT3"]
VERSE_LOGO_URL = os.getenv("VERSE_LOGO_URL")

def get_brand_logo_url(guild: discord.Guild | None = None) -> str | None:
    url = VERSE_LOGO_URL
    if url and url.strip():
        return url.strip()
    try:
        return guild.icon.url if guild and guild.icon else None
    except Exception:
        return None

def get_brand_name(guild: discord.Guild | None = None) -> str:
    try:
        return guild.name if guild else "VerseTL"
    except Exception:
        return "VerseTL"

FIRST_IN_QUEUE_TRACKER = {}

def _ensure_first_tracker(guild_id: int):
    if guild_id not in FIRST_IN_QUEUE_TRACKER:
        FIRST_IN_QUEUE_TRACKER[guild_id] = {"na": None, "eu": None, "as": None, "au": None}

REQUEST_CHANNEL_ID = os.getenv("REQUEST_CHANNEL_ID")
REQUEST_CHANNEL_NAME = os.getenv("REQUEST_CHANNEL_NAME", "request-test")

def _normalize_channel_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())

def _get_request_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if REQUEST_CHANNEL_ID:
        try:
            ch = guild.get_channel(int(REQUEST_CHANNEL_ID))
            if isinstance(ch, discord.TextChannel): return ch
        except Exception:
            pass
    target = _normalize_channel_name(REQUEST_CHANNEL_NAME)
    for ch in guild.text_channels:
        if _normalize_channel_name(ch.name) == target or _normalize_channel_name(ch.name) in {"requesttest", "request"}:
            return ch
    return None

def _is_request_channel(channel: discord.abc.GuildChannel) -> bool:
    if REQUEST_CHANNEL_ID:
        try:
            return channel.id == int(REQUEST_CHANNEL_ID)
        except Exception:
            pass
    return _normalize_channel_name(channel.name) == _normalize_channel_name(REQUEST_CHANNEL_NAME)

def _get_logs_channel(guild: discord.Guild) -> discord.TextChannel | None:
    for ch in guild.text_channels:
        if _normalize_channel_name(ch.name) == "logs":
            return ch
    staff_category = discord.utils.get(guild.categories, name="Staff") or discord.utils.get(guild.categories, name="STAFF")
    if staff_category:
        for ch in staff_category.text_channels:
            if "logs" in ch.name.lower():
                return ch
    return None

def has_booster_role(member: discord.Member) -> bool:
    booster_role = discord.utils.get(member.roles, name="VT • Server Booster")
    return booster_role is not None

def get_cooldown_duration(member: discord.Member) -> int:
    return BOOSTER_COOLDOWN_DAYS if has_booster_role(member) else REGULAR_COOLDOWN_DAYS

def apply_cooldown(user_id: int, member: discord.Member):
    cooldown_days = get_cooldown_duration(member)
    cooldown_end = datetime.datetime.now() + datetime.timedelta(days=cooldown_days)
    user_test_cooldowns[user_id] = cooldown_end
    save_user_cooldowns()
    return cooldown_days

def has_tester_role(member: discord.Member) -> bool:
    tester_role_names = ["Tester", "Verified Tester", "Staff Tester", "tester", "verified tester", "staff tester"]
    for role in member.roles:
        if role.name in tester_role_names:
            return True
    return False

def has_high_tier(member: discord.Member) -> bool:
    try:
        for tier_name in HIGH_TIERS:
            role = discord.utils.get(member.roles, name=tier_name)
            if role is not None:
                return True
    except Exception:
        pass
    return False

def is_tier_role_obj(role: discord.Role) -> bool:
    if str(role.id) in ROLE_ID_RANKS:
        return True
    return _normalize_role_name(role.name) in NAME_RANKS

def save_tester_stats():
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump(tester_stats, f, indent=2)
    except Exception as e:
        print(f"DEBUG: Error saving tester stats: {e}")

def load_tester_stats():
    global tester_stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                loaded_stats = json.load(f)
                tester_stats = {int(user_id): count for user_id, count in loaded_stats.items()}
        else:
            tester_stats = {}
    except Exception as e:
        print(f"DEBUG: Error loading tester stats: {e}")
        tester_stats = {}

def save_user_cooldowns():
    try:
        cooldowns_data = {str(uid): ts.isoformat() for uid, ts in user_test_cooldowns.items()}
        with open(COOLDOWNS_FILE, 'w') as f:
            json.dump(cooldowns_data, f, indent=2)
    except Exception as e:
        print(f"DEBUG: Error saving user cooldowns: {e}")

def load_user_cooldowns():
    global user_test_cooldowns
    try:
        if os.path.exists(COOLDOWNS_FILE):
            with open(COOLDOWNS_FILE, 'r') as f:
                loaded_cooldowns = json.load(f)
            user_test_cooldowns = {}
            now = datetime.datetime.now()
            for user_id_str, cooldown_str in loaded_cooldowns.items():
                try:
                    uid = int(user_id_str)
                    when = datetime.datetime.fromisoformat(cooldown_str)
                    if when > now:
                        user_test_cooldowns[uid] = when
                except Exception:
                    pass
        else:
            user_test_cooldowns = {}
    except Exception as e:
        print(f"DEBUG: Error loading user cooldowns: {e}")
        user_test_cooldowns = {}

def save_last_region_activity():
    try:
        data = {str(gid): {r: (t.isoformat() if t else None) for r, t in regions.items()} for gid, regions in last_region_activity.items()}
        with open(LAST_ACTIVITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"DEBUG: Error saving last region activities: {e}")

def load_last_region_activity():
    global last_region_activity
    try:
        last_region_activity = {}
        if os.path.exists(LAST_ACTIVITY_FILE):
            with open(LAST_ACTIVITY_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            for gid_str, regions in loaded.items():
                try:
                    gid = int(gid_str)
                except Exception:
                    continue
                last_region_activity[gid] = {"na": None, "eu": None, "as": None, "au": None}
                for r in ["na","eu","as","au"]:
                    v = regions.get(r)
                    if v:
                        try:
                            last_region_activity[gid][r] = datetime.datetime.fromisoformat(v)
                        except Exception:
                            last_region_activity[gid][r] = None
    except Exception as e:
        print(f"DEBUG: Error loading last region activities: {e}")
        last_region_activity = {}

def get_sheets_service():
    try:
        if not service_account or not build:
            return None
        creds_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_CREDENTIALS')
        if creds_json:
            creds_info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(
                creds_info, scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            return build('sheets', 'v4', credentials=credentials)
    except Exception as e:
        print(f"DEBUG: Error setting up Google Sheets service: {e}")
    return None

def save_user_info():
    try:
        serializable = {str(uid): data for uid, data in user_info.items()}
        with open(USER_INFO_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"DEBUG: Error saving user_info: {e}")

def load_user_info():
    global user_info
    try:
        if os.path.exists(USER_INFO_FILE):
            with open(USER_INFO_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            user_info = {int(uid): data for uid, data in raw.items()}
        else:
            user_info = {}
    except Exception as e:
        print(f"DEBUG: Error loading user_info: {e}")
        user_info = {}

async def add_ign_to_sheet(ign: str, tier: str):
    try:
        service = get_sheets_service()
        if not service:
            return False
        column = TIER_COLUMNS.get(tier.upper())
        if not column:
            return False
        range_name = f"'VerseTL Crystal'!{column}:{column}"
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=range_name).execute()
        values = result.get('values', [])
        next_row = len(values) + 1
        range_name = f"'VerseTL Crystal'!{column}{next_row}"
        body = {'values': [[ign]]}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=range_name, valueInputOption='RAW', body=body
        ).execute()
        return True
    except HttpError as e:
        print(f"DEBUG: Google Sheets API error: {e}")
        return False
    except Exception as e:
        print(f"DEBUG: Error adding IGN to sheet: {e}")
        return False

async def update_user_count_channel(guild):
    prefix = "👥┃Users:"
    existing = discord.utils.find(lambda c: c.name.startswith(prefix), guild.voice_channels)
    member_count = len([m for m in guild.members if not m.bot])
    new_name = f"{prefix} {member_count}"
    if existing:
        if existing.name != new_name:
            await existing.edit(name=new_name)
    else:
        category = discord.utils.get(guild.categories, name="Voice")
        await guild.create_voice_channel(new_name, category=category)

def run_with_backoff():
    base = 600
    while True:
        try:
            bot.run(TOKEN, reconnect=True)
            break
        except HTTPException as e:
            if getattr(e, "status", None) == 429:
                delay = base + random.randint(30, 120)
                print(f"[WARN] Rate limited (429/1015). Sleeping {delay}s before retry.")
                time.sleep(delay)
                base = min(int(base * 1.5), 3600)
                continue
            raise

# ============ HELPERS (FEATURES) ============

def _slug_username(name: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "user"

async def post_tier_results(interaction: discord.Interaction, user: discord.Member, ign: str,
                            region: str, gamemode: str, current_rank: str, earned_rank: str,
                            tester: discord.Member):
    guild = interaction.guild
    results_channel = discord.utils.get(guild.text_channels, name="🏆┃results") or \
                      discord.utils.get(guild.text_channels, name="results")
    if not results_channel:
        return

    # Identique pour tous les tiers
    embed = discord.Embed(title=f"{ign}'s Test Results", color=0xff0000)
    embed.description = (
        f"**Tester:**\n{tester.mention}\n"
        f"**Region:**\n{region}\n"
        f"**Minecraft IGN:**\n{ign}\n"
        f"**Previous Tier:**\n{current_rank}\n"
        f"**Tier Earned:**\n{earned_rank}"
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/head/{ign}/100")

    sent = await results_channel.send(content=user.mention, embed=embed)
    try:
        for e in ["👑", "🤯", "👀", "😱", "🔥"]:
            await sent.add_reaction(e)
    except Exception:
        pass

    tester_id = tester.id
    if tester_id not in tester_stats:
        tester_stats[tester_id] = 0
    tester_stats[tester_id] += 1
    save_tester_stats()

    try:
        await add_ign_to_sheet(ign, earned_rank)
    except Exception:
        pass

    try:
        await update_leaderboard(guild)
    except Exception:
        pass

    try:
        earned_role = discord.utils.get(guild.roles, name=earned_rank)
        if earned_role and earned_role < guild.me.top_role:
            all_tier_roles = ["HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]
            to_remove = []
            for rn in all_tier_roles:
                r = discord.utils.get(guild.roles, name=rn)
                if r and r in user.roles:
                    to_remove.append(r)
            if to_remove:
                await user.remove_roles(*to_remove, reason=f"Remove previous tier roles before giving {earned_rank}")
            await user.add_roles(earned_role, reason=f"Earned {earned_rank} from tier test")
    except Exception:
        pass

    try:
        reg = (region or "").lower()
        if reg in ("na","eu","as","au"):
            _ensure_guild_activity_state(guild.id)
            last_region_activity[guild.id][reg] = datetime.datetime.now()
            save_last_region_activity()
    except Exception as e:
        print(f"DEBUG: last test at update failed: {e}")

    try:
        await rebuild_and_cache_vanilla()
    except Exception:
        pass

    try:
        if user.id in active_testing_sessions:
            del active_testing_sessions[user.id]
    except Exception:
        pass

# No-op: ne ping plus les testeurs dans waitlist-<region>
async def ping_testers_in_waitlist_channel(guild: discord.Guild, region: str, user: discord.Member):
    return

async def maybe_notify_queue_top_change(guild: discord.Guild, region: str):
    if not is_guild_authorized(getattr(guild, "id", None)):
        return
    _ensure_first_tracker(guild.id)
    top_list = waitlists.get(region, [])
    current_top_id = top_list[0] if top_list else None
    if FIRST_IN_QUEUE_TRACKER[guild.id].get(region) == current_top_id:
        return
    FIRST_IN_QUEUE_TRACKER[guild.id][region] = current_top_id
    if current_top_id is None:
        return
    member = guild.get_member(current_top_id)
    if not member:
        return
    try:
        embed = discord.Embed(
            title="Queue Position Updated",
            description="Your position in the queue has changed.\nYou are now #1 in the queue.",
            color=discord.Color.blurple()
        )
        embed.set_author(name=get_brand_name(guild), icon_url=get_brand_logo_url(guild))
        await member.send(embed=embed)
    except Exception as e:
        print(f"DEBUG: queue top DM failed: {e}")

async def send_eval_welcome_message(channel: discord.TextChannel, region: str, player: discord.Member | None, tester: discord.Member | None):
    try:
        user_data = user_info.get(player.id, {}) if player else {}
        ign = user_data.get('ign', 'N/A')
        server = user_data.get('server', 'N/A')
        player_mention = player.mention if player else "Player"
        tester_mention = tester.mention if tester else "a tester"
        info_embed = discord.Embed(
            title="Welcome to your Evaluation Session",
            description=(f"Hello {player_mention}! You have been selected for testing in the {region.upper()} region.\n\n"
                         f"Your tester {tester_mention} will guide you through the process.\n\n"
                         f"**IGN:** {ign}\n**Preferred Server:** {server}"),
            color=0x00ff7f
        )
        await channel.send(embed=info_embed)
    except Exception as e:
        print(f"DEBUG: send_eval_welcome_message failed: {e}")

async def create_initial_waitlist_message(guild: discord.Guild, region: str):
    if not is_guild_authorized(getattr(guild, "id", None)):
        return
    channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
    if not channel:
        return
    region_last_active = last_region_activity.get(guild.id, {}).get(region)
    if region_last_active:
        timestamp_unix = int(region_last_active.timestamp())
        timestamp = f"<t:{timestamp_unix}:R>"
    else:
        timestamp = "Never"
    embed = discord.Embed(
        title="No Testers Online",
        description=(f"No testers for your region are available at this time.\n"
                     f"You will be pinged when a tester is available.\n"
                     f"Check back later!\n\n"
                     f"Last Test At: {timestamp}"),
        color=discord.Color(15880807)
    )
    embed.set_author(name=get_brand_name(guild), icon_url=get_brand_logo_url(guild))
    try:
        initial_message = await channel.send(embed=embed)
        if guild.id not in waitlist_messages:
            waitlist_messages[guild.id] = {}
        if guild.id not in waitlist_message_ids:
            waitlist_message_ids[guild.id] = {}
        waitlist_messages[guild.id][region] = initial_message
        waitlist_message_ids[guild.id][region] = initial_message.id
    except Exception as e:
        print(f"DEBUG: create_initial_waitlist_message error: {e}")

def _display_name_or_ign(user_id: int, guild: discord.Guild) -> str:
    try:
        info = user_info.get(user_id)
        if info and info.get("ign"):
            return info["ign"]
    except Exception:
        pass
    member = guild.get_member(user_id)
    return member.display_name if member else f"User {user_id}"

async def update_leaderboard(guild: discord.Guild):
    try:
        if not tester_stats:
            return
        channel = (discord.utils.get(guild.text_channels, name="🏆┃leaderboard")
                   or discord.utils.get(guild.text_channels, name="leaderboard"))
        if not channel:
            return
        top = sorted(tester_stats.items(), key=lambda kv: kv[1], reverse=True)[:10]
        lines = []
        for idx, (uid, count) in enumerate(top, 1):
            display = _display_name_or_ign(uid, guild)
            lines.append(f"{idx}. {display} — {count} test(s)")
        embed = discord.Embed(title="Tester Leaderboard", description="\n".join(lines) or "*No data*", color=discord.Color.gold())
        async for msg in channel.history(limit=20):
            if msg.author == guild.me and msg.embeds and (msg.embeds[0].title or "") == "Tester Leaderboard":
                await msg.edit(embed=embed)
                break
        else:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"DEBUG: update_leaderboard error: {e}")

# === EVENTS & INTERACTIONS ===

async def global_app_check(interaction: discord.Interaction) -> bool:
    if interaction.command and interaction.command.name == "authorize" and interaction.user.id == OWNER_ID:
        return True
    if interaction.guild is None:
        return True
    if not is_guild_authorized(interaction.guild.id):
        try:
            embed = discord.Embed(
                title="Unauthorized Server",
                description=("This server is not authorized to use this bot.\n"
                             "The owner <@836452038548127764> must run /authorize here."),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.InteractionResponded:
            pass
        return False
    return True

@bot.event
async def on_ready():
    print(f"{bot.user.name} is online and ready!")
    load_authorized_guilds()
    for guild in bot.guilds:
        if guild.id not in message_logs:
            message_logs[guild.id] = []
    load_tester_stats()
    load_user_cooldowns()
    load_user_info()
    load_last_region_activity()

    for g in bot.guilds:
        _ensure_guild_activity_state(g.id)
        _ensure_first_tracker(g.id)

    global opened_queues, active_testers, waitlists, waitlist_message_ids, waitlist_messages, active_testing_sessions
    opened_queues.clear()
    active_testers.clear()
    for region in waitlists:
        waitlists[region].clear()
    waitlist_message_ids.clear()
    waitlist_messages.clear()
    active_testing_sessions.clear()

    global APP_CHECK_ADDED
    if not APP_CHECK_ADDED:
        try:
            bot.tree.add_check(global_app_check)
            APP_CHECK_ADDED = True
        except Exception as e:
            print(f"DEBUG: add_check failed: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced_guild = await bot.tree.sync(guild=guild)
            print(f"DEBUG: Synced {len(synced_guild)} slash command(s) for guild {GUILD_ID}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    newly_added = 0
    for g in bot.guilds:
        if g.id not in authorized_guilds:
            authorized_guilds.add(g.id)
            newly_added += 1
    if newly_added > 0:
        save_authorized_guilds()

    for guild in bot.guilds:
        if not is_guild_authorized(guild.id):
            continue
        request_channel = _get_request_channel(guild)
        if not request_channel:
            try:
                request_channel = await guild.create_text_channel(REQUEST_CHANNEL_NAME)
            except discord.Forbidden:
                request_channel = None

        if request_channel:
            embed = discord.Embed(
                title="📋 Evaluation Testing Waitlist",
                description=("Upon applying, you will be added to a waitlist channel.\n"
                             "Here you will be pinged when a tester of your region is available.\n"
                             "If you are HT3 or higher, a high ticket will be created.\n\n"
                             "• Region should be the region of the server you wish to test on\n"
                             "• Username should be the name of the account you will be testing on\n\n"
                             "🛑 Failure to provide authentic information will result in a denied test.\n"),
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Enter Waitlist", style=discord.ButtonStyle.success, custom_id="open_form"))
            try:
                await request_channel.purge(limit=100)
            except Exception:
                pass
            await request_channel.send(embed=embed, view=view)

        for region in waitlists:
            channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
            if channel:
                try:
                    await channel.purge(limit=100)
                except Exception:
                    pass
                _ensure_guild_queue_state(guild.id)
                opened_queues[guild.id].discard(region)
                await create_initial_waitlist_message(guild, region)

    if not refresh_messages.is_running():
        refresh_messages.start()
    if not cleanup_expired_cooldowns.is_running():
        cleanup_expired_cooldowns.start()
    if not periodic_save_activities.is_running():
        periodic_save_activities.start()

    try:
        await rebuild_and_cache_vanilla()
    except Exception as e:
        print(f"DEBUG: initial vanilla rebuild failed: {e}")

    if not refresh_vanilla_export.is_running():
        refresh_vanilla_export.start()
    try:
        register_vanilla_callback(_vanilla_payload)
    except Exception as e:
        print(f"DEBUG: register_vanilla_callback failed: {e}")

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if not is_guild_authorized(getattr(after.guild, "id", None)):
        return
    if before.roles == after.roles:
        return
    before_ids = {r.id for r in before.roles}
    after_ids  = {r.id for r in after.roles}
    added   = [r for r in after.roles  if r.id not in before_ids]
    removed = [r for r in before.roles if r.id not in after_ids]
    if any(is_tier_role_obj(r) for r in (added + removed)):
        try:
            await rebuild_and_cache_vanilla()
        except Exception as e:
            print(f"DEBUG: on_member_update rebuild failed: {e}")

@bot.event
async def on_guild_join(guild):
    message_logs[guild.id] = []
    embed = discord.Embed(
        title="Thanks for adding me!",
        description=("This bot is disabled by default on new servers.\n"
                     "The owner <@836452038548127764> must run /authorize in this server to enable it."),
        color=discord.Color.blurple()
    )
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass
            break

@bot.event
async def on_command_error(ctx, error):
    try:
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(embed=discord.Embed(title="Unknown Command", description="This command is not available.", color=discord.Color.red()))
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=discord.Embed(title="Missing Permissions", description="You don't have permission to use this command.", color=discord.Color.red()))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(title="Missing Arguments", description="Missing required arguments.", color=discord.Color.red()))
        else:
            await ctx.send(embed=discord.Embed(title="Error", description=str(error), color=discord.Color.red()))
    except Exception:
        pass

@bot.event
async def on_member_join(member):
    if member.bot:
        return
    if not is_guild_authorized(member.guild.id):
        return
    role = discord.utils.get(member.guild.roles, name="Member")
    if role:
        try:
            await member.add_roles(role)
        except Exception:
            pass
    await update_user_count_channel(member.guild)
    log_entry = {"type": "member_join", "user": str(member), "user_id": member.id, "timestamp": datetime.datetime.now().isoformat()}
    if member.guild.id not in message_logs:
        message_logs[member.guild.id] = []
    message_logs[member.guild.id].append(log_entry)

@bot.event
async def on_member_remove(member):
    if not is_guild_authorized(member.guild.id):
        return
    await update_user_count_channel(member.guild)
    log_entry = {"type": "member_leave", "user": str(member), "user_id": member.id, "timestamp": datetime.datetime.now().isoformat()}
    if member.guild.id not in message_logs:
        message_logs[member.guild.id] = []
    message_logs[member.guild.id].append(log_entry)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if not is_guild_authorized(getattr(message.guild, "id", None)):
        return

    if message.channel.name == "💬┃general":
        content_lower = message.content.lower()
        discord_patterns = ["discord.gg/","discord.com/invite/","discordapp.com/invite/"]
        youtube_patterns = ["youtube.com/","youtu.be/","m.youtube.com/"]
        contains_discord_link = any(pattern in content_lower for pattern in discord_patterns)
        contains_youtube_link = any(pattern in content_lower for pattern in youtube_patterns)
        if contains_discord_link or contains_youtube_link:
            try:
                await message.delete()
                warning_message = f"⚠️ Your message in **{message.guild.name}** was deleted because it contained a prohibited link."
                try:
                    await message.author.send(warning_message)
                except discord.Forbidden:
                    warn_embed = discord.Embed(title="⚠️ Link Removed", description=f"{message.author.mention}, please avoid sharing links in this channel.", color=discord.Color.orange())
                    warning_in_channel = await message.channel.send(embed=warn_embed)
                    await asyncio.sleep(10)
                    try:
                        await warning_in_channel.delete()
                    except discord.NotFound:
                        pass
                log_entry = {
                    "type": "auto_moderation",
                    "user": str(message.author),
                    "user_id": message.author.id,
                    "channel": str(message.channel),
                    "reason": "Prohibited link",
                    "content": message.content[:100] + "..." if len(message.content) > 100 else message.content,
                    "timestamp": datetime.datetime.now().isoformat()
                }
                if message.guild.id not in message_logs:
                    message_logs[message.guild.id] = []
                message_logs[message.guild.id].append(log_entry)
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"Error in auto-moderation: {e}")

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    if not is_guild_authorized(getattr(message.guild, "id", None)):
        return
    log_entry = {
        "type": "message_delete",
        "user": str(message.author),
        "user_id": message.author.id,
        "channel": str(message.channel),
        "content": message.content[:100] + "..." if len(message.content) > 100 else message.content,
        "timestamp": datetime.datetime.now().isoformat()
    }
    if message.guild.id not in message_logs:
        message_logs[message.guild.id] = []
    message_logs[message.guild.id].append(log_entry)

@bot.event
async def on_guild_channel_delete(channel):
    if channel.name.startswith("eval-") or channel.name.startswith("high-eval-"):
        channel_id = channel.id
        user_to_remove = None
        for user_id, active_channel_id in active_testing_sessions.items():
            if active_channel_id == channel_id:
                user_to_remove = user_id
                break
        if user_to_remove:
            del active_testing_sessions[user_to_remove]
            print(f"DEBUG: Cleaned up active testing session for user {user_to_remove} (channel deleted)")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if (interaction.type == discord.InteractionType.application_command
        and interaction.command and interaction.command.name == "authorize"
        and interaction.user.id == OWNER_ID):
        pass
    else:
        if interaction.guild and not is_guild_authorized(interaction.guild.id):
            if interaction.type == discord.InteractionType.component:
                return

    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]
        if custom_id == "open_form":
            if _is_request_channel(interaction.channel):
                if discord.utils.get(interaction.user.roles, name="Tierlist Restricted"):
                    embed = discord.Embed(title="⛔ Access Denied", description="You are currently restricted from entering the queue.", color=discord.Color.red())
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                modal = WaitlistModal(get_brand_name(interaction.guild))
                await interaction.response.send_modal(modal)
                return

            for region in waitlists:
                if interaction.channel.name.lower() == f"waitlist-{region}":
                    if discord.utils.get(interaction.user.roles, name="Tierlist Restricted"):
                        embed = discord.Embed(title="⛔ Access Denied", description="You are currently restricted from joining the queue.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    user_id = interaction.user.id
                    if user_id not in user_info:
                        embed = discord.Embed(title="❌ Form Required", description="You must submit the form in <#📨┃request-test> before joining the queue.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    user_region = user_info[user_id]["region"].lower()
                    if user_region != region:
                        embed = discord.Embed(title="❌ Wrong Region", description=f"Your form was submitted for {user_region.upper()} region, but you're trying to join the {region.upper()} queue.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    if user_id in active_testing_sessions:
                        existing_channel_id = active_testing_sessions[user_id]
                        existing_channel = interaction.guild.get_channel(existing_channel_id)
                        if existing_channel:
                            embed = discord.Embed(title="⚠️ Active Session Exists", description=f"You already have an active testing session in {existing_channel.mention}. Please complete that test first.", color=discord.Color.red())
                            await interaction.response.send_message(embed=embed, ephemeral=True)
                            return
                        else:
                            del active_testing_sessions[user_id]

                    if interaction.user.id in waitlists[region]:
                        embed = discord.Embed(title="ℹ️ Already in Queue", description="You're already in the queue.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    if len(waitlists[region]) >= MAX_WAITLIST:
                        embed = discord.Embed(title="⛔ Queue Full", description="Queue is full.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    waitlists[region].append(interaction.user.id)

                    role = discord.utils.get(interaction.guild.roles, name=f"Waitlist-{region.upper()}")
                    if role and role not in interaction.user.roles and role < interaction.guild.me.top_role:
                        try:
                            await interaction.user.add_roles(role)
                        except discord.Forbidden:
                            pass

                    await interaction.response.send_message(
                        f"✅ Successfully joined the {region.upper()} queue! You are position #{len(waitlists[region])} in line.",
                        ephemeral=True
                    )

                    await log_queue_join(interaction.guild, interaction.user, region, len(waitlists[region]))
                    await update_waitlist_message(interaction.guild, region)
                    # No-op ping to keep flow consistent (does nothing)
                    try:
                        await ping_testers_in_waitlist_channel(interaction.guild, region, interaction.user)
                    except Exception:
                        pass
                    return

            embed = discord.Embed(title="❌ Invalid Region", description="Invalid waitlist region.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

# === AUTHORIZATION COMMAND ===

@bot.tree.command(name="authorize", description="Authorize the bot to operate in this server (Owner only)")
async def authorize(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        embed = discord.Embed(title="Not Allowed", description="Only the owner can authorize a server.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.guild is None:
        embed = discord.Embed(title="Server Only", description="This command must be used in a server.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.guild.id in authorized_guilds:
        embed = discord.Embed(title="Already Authorized", description="This server is already authorized.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    authorized_guilds.add(interaction.guild.id)
    save_authorized_guilds()
    await interaction.response.send_message(
        embed=discord.Embed(title="Server Authorized", description=f"Server **{interaction.guild.name}** (`{interaction.guild.id}`) is now authorized.", color=discord.Color.green()),
        ephemeral=True
    )
    try:
        await interaction.channel.send(embed=discord.Embed(title="Server Authorized", description="This server has been authorized. Commands are now active.", color=discord.Color.green()))
    except Exception:
        pass

# === WAITLIST / EVAL COMMANDS ===

@bot.tree.command(name="leave", description="Leave all waitlists you're currently in")
async def leave(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    left_regions = []
    for region, queue in waitlists.items():
        if interaction.user.id in queue:
            queue.remove(interaction.user.id)
            left_regions.append(region)
            role = discord.utils.get(interaction.guild.roles, name=f"Waitlist-{region.upper()}")
            if role and role < interaction.guild.me.top_role:
                try:
                    await interaction.user.remove_roles(role)
                except discord.Forbidden:
                    pass
            await update_waitlist_message(interaction.guild, region)
    if left_regions:
        regions_list = ", ".join(region.upper() for region in left_regions)
        await interaction.response.send_message(f"You left the following waitlists: {regions_list}", ephemeral=True)
    else:
        await interaction.response.send_message(embed=discord.Embed(title="ℹ️ Not in Queue", description="You are not in any waitlist.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="removecooldown", description="Remove a user's cooldown before testing")
@app_commands.describe(member="Member to clear cooldown for")
async def removecooldown(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not (has_tester_role(interaction.user) or interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator):
        embed = discord.Embed(title="Permission Required", description="You must be a Tester or have the Manage Roles permission to use this command.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    had = member.id in user_test_cooldowns
    if had:
        try:
            del user_test_cooldowns[member.id]
            save_user_cooldowns()
        except Exception:
            pass
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✅ Cooldown Removed" if had else "ℹ️ No Active Cooldown",
            description=(f"The testing cooldown for {member.mention} has been cleared." if had else f"{member.mention} currently has no active cooldown."),
            color=discord.Color.green() if had else discord.Color.orange()
        ),
        ephemeral=True
    )

def get_region_from_channel(channel_name: str) -> str:
    print(f"DEBUG: get_region_from_channel called with: {channel_name}")
    channel_lower = channel_name.lower()
    for region in ["na", "eu", "as", "au"]:
        if f"waitlist-{region}" in channel_lower:
            print(f"DEBUG: Found region {region} in channel {channel_name}")
            return region
    print(f"DEBUG: No region found for channel: {channel_name}")
    return None

@bot.tree.command(name="startqueue", description="Start the queue for testing (Tester role required)")
@app_commands.describe(channel="The waitlist channel to start the queue for")
async def startqueue(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if channel is None:
        channel = interaction.channel
    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    region = get_region_from_channel(channel.name)
    if not region:
        embed = discord.Embed(title="❌ Invalid Channel", description=f"This is not a valid waitlist channel. Channel name: {channel.name}\n\nValid channels are: waitlist-na, waitlist-eu, waitlist-as, waitlist-au", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    to_purge = [uid for uid in waitlists[region] if interaction.guild.get_member(uid)]
    cleared_count = len(to_purge)
    if cleared_count > 0:
        for user_id in to_purge:
            member = interaction.guild.get_member(user_id)
            if member:
                roles_to_remove = []
                for role_name in [f"Waitlist-{region.upper()}", f"{region.upper()} Waitlist", f"{region.upper()} Matchmaking", f"waitlist-{region.upper()}", f"waitlist-{region.lower()}", f"{region.lower()} waitlist", f"{region.lower()} matchmaking"]:
                    role = discord.utils.get(interaction.guild.roles, name=role_name)
                    if role and role in member.roles and role < interaction.guild.me.top_role:
                        roles_to_remove.append(role)
                for role in roles_to_remove:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        pass
        for uid in to_purge:
            try:
                waitlists[region].remove(uid)
            except ValueError:
                pass

    _ensure_guild_queue_state(interaction.guild.id)
    opened_queues[interaction.guild.id].add(region)
    _ensure_guild_activity_state(interaction.guild.id)
    last_region_activity[interaction.guild.id][region] = datetime.datetime.now()
    save_last_region_activity()

    if interaction.user.id not in active_testers[interaction.guild.id][region]:
        active_testers[interaction.guild.id][region].append(interaction.user.id)

    waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{region}")
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✅ Queue Started",
            description=f"{region.upper()} waitlist is now active in {waitlist_channel.mention if waitlist_channel else f'#waitlist-{region}'}. You are now an active tester." + (f"\n🧹 Cleared {cleared_count} users from the previous queue." if cleared_count > 0 else ""),
            color=discord.Color.green()
        ),
        ephemeral=True
    )

    await maybe_notify_queue_top_change(interaction.guild, region)
    await update_waitlist_message(interaction.guild, region)

@bot.tree.command(name="stopqueue", description="Remove yourself from active testers (Tester role required)")
@app_commands.describe(channel="The waitlist channel to leave as tester")
async def stopqueue(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if channel is None:
        channel = interaction.channel
    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    region = get_region_from_channel(channel.name)
    if not region:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid Channel", description=f"This is not a valid waitlist channel. Channel name: {channel.name}", color=discord.Color.red()), ephemeral=True)
        return

    _ensure_guild_queue_state(interaction.guild.id)
    if interaction.user.id in active_testers[interaction.guild.id][region]:
        active_testers[interaction.guild.id][region].remove(interaction.user.id)
        if not active_testers[interaction.guild.id][region]:
            opened_queues[interaction.guild.id].discard(region)
        await interaction.response.send_message(embed=discord.Embed(title="👋 Left Active Testers", description=f"You have been removed from active testers for {region.upper()} in {channel.mention}.", color=discord.Color.blurple()), ephemeral=True)
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Not Active", description=f"You are not an active tester for {region.upper()}.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="nextuser", description="Create a private channel for the next person in waitlist (Tester role required)")
@app_commands.describe(channel="The waitlist channel to get the next person from")
async def nextuser(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if channel is None:
        channel = interaction.channel
    if not has_tester_role(interaction.user):
        await interaction.response.send_message(embed=discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.", color=discord.Color.red()), ephemeral=True)
        return
    region = get_region_from_channel(channel.name)
    if not region:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid Channel", description="This is not a valid waitlist channel.", color=discord.Color.red()), ephemeral=True)
        return
    if not waitlists[region]:
        await interaction.response.send_message(embed=discord.Embed(title="Empty Queue", description=f"No one is in the {region.upper()} waitlist.", color=discord.Color.red()), ephemeral=True)
        return

    next_user_id = waitlists[region].pop(0)
    next_user = interaction.guild.get_member(next_user_id)
    if not next_user:
        await interaction.response.send_message(embed=discord.Embed(title="User Not Found", description="Could not find the next user in the waitlist.", color=discord.Color.red()), ephemeral=True)
        return
    if next_user_id in active_testing_sessions:
        existing_channel = interaction.guild.get_channel(active_testing_sessions[next_user_id])
        if existing_channel:
            await interaction.response.send_message(embed=discord.Embed(title="Active Session Exists", description=f"{next_user.mention} already has an active testing session in {existing_channel.mention}.", color=discord.Color.red()), ephemeral=True)
            return
        else:
            del active_testing_sessions[next_user_id]

    target_high = has_high_tier(next_user)
    primary_category_name = f"High Eval {region.upper()}" if target_high else f"Eval {region.upper()}"
    category = discord.utils.get(interaction.guild.categories, name=primary_category_name)
    if not category and target_high:
        category = discord.utils.get(interaction.guild.categories, name=f"Eval {region.upper()}")
    if not category:
        await interaction.response.send_message(embed=discord.Embed(title="Category Missing", description=f"Could not find category {primary_category_name}.", color=discord.Color.red()), ephemeral=True)
        return

    username = next_user.display_name
    channel_name = f"High-Eval-{username}" if target_high else f"Eval {username}"

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        next_user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    for rn in ["Tester","Verified Tester","Staff Tester","tester","verified tester","staff tester"]:
        tr = discord.utils.get(interaction.guild.roles, name=rn)
        if tr:
            overwrites[tr] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        new_channel = await interaction.guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        active_testing_sessions[next_user_id] = new_channel.id

        # Remove waitlist roles
        to_remove = []
        for rn in [f"Waitlist-{region.upper()}", f"{region.upper()} Waitlist", f"{region.upper()} Matchmaking", f"waitlist-{region.upper()}", f"waitlist-{region.lower()}", f"{region.lower()} waitlist", f"{region.lower()} matchmaking"]:
            r = discord.utils.get(interaction.guild.roles, name=rn)
            if r and r in next_user.roles and r < interaction.guild.me.top_role:
                to_remove.append(r)
        for r in to_remove:
            try:
                await next_user.remove_roles(r)
            except Exception:
                pass

        await update_waitlist_message(interaction.guild, region)

        await interaction.response.send_message(embed=discord.Embed(title="Private Channel Created", description=f"Created {new_channel.mention} for {next_user.mention}.", color=discord.Color.green()), ephemeral=True)

        cooldown_days = apply_cooldown(next_user_id, next_user)
        await send_eval_welcome_message(new_channel, region, next_user, interaction.user)

    except discord.Forbidden:
        await interaction.response.send_message(embed=discord.Embed(title="Missing Permission", description="I don't have permission to create channels in that category.", color=discord.Color.red()), ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(embed=discord.Embed(title="Error", description=f"An error occurred while creating the channel: {str(e)}", color=discord.Color.red()), ephemeral=True)

# CLOSE + RESULTS

@bot.tree.command(name="close", description="Close an eval channel and optionally post results (Tester role required)")
@app_commands.describe(previous_tier="Previous tier before the test (optional)", earned_tier="Tier earned from the test (optional)")
@app_commands.choices(
    previous_tier=[app_commands.Choice(name=v, value=v) for v in ["N/A","HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]],
    earned_tier=[app_commands.Choice(name=v, value=v) for v in ["HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]],
)
async def close(interaction: discord.Interaction, previous_tier: str | None = None, earned_tier: str | None = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        await interaction.response.send_message(embed=discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.", color=discord.Color.red()), ephemeral=True)
        return
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel) or "eval" not in ch.name.lower():
        await interaction.response.send_message(embed=discord.Embed(title="❌ Wrong Channel", description="This command can only be used in eval channels.", color=discord.Color.red()), ephemeral=True)
        return

    # Find tested player
    player = None
    for uid, cid in active_testing_sessions.items():
        if cid == ch.id:
            player = ch.guild.get_member(uid)
            break
    if not player:
        await interaction.response.send_message(embed=discord.Embed(title="No Active Player", description="Could not determine the tested player for this channel.", color=discord.Color.red()), ephemeral=True)
        return

    # Region from category
    region = "NA"
    if ch.category:
        cname = ch.category.name.lower()
        for r in ["na","eu","as","au"]:
            if r in cname:
                region = r.upper()
                break

    data = user_info.get(player.id, {}) if isinstance(user_info, dict) else {}
    ign = data.get("ign", player.display_name)

    # No params -> just close in 5s
    if not earned_tier:
        await interaction.response.send_message(embed=discord.Embed(title="Channel Closing", description="This channel will be deleted in 5 seconds…", color=discord.Color.orange()), ephemeral=True)
        try:
            if player.id in active_testing_sessions:
                del active_testing_sessions[player.id]
        except Exception:
            pass
        await asyncio.sleep(5)
        try:
            await ch.delete(reason=f"Eval closed without results by {interaction.user.name}")
        except Exception:
            pass
        return

    # With params: post results then close in 5s
    try:
        await post_tier_results(
            interaction=interaction,
            user=player,
            ign=ign,
            region=region,
            gamemode="Crystal",
            current_rank=(previous_tier or "N/A"),
            earned_rank=earned_tier,
            tester=interaction.user
        )
    except Exception as e:
        print(f"DEBUG: /close post_tier_results error: {e}")

    await interaction.response.send_message(embed=discord.Embed(title="Channel Closing", description=f"Results posted for {earned_tier}. This channel will be deleted in 5 seconds…", color=discord.Color.green()), ephemeral=True)

    try:
        if player.id in active_testing_sessions:
            del active_testing_sessions[player.id]
    except Exception:
        pass

    await asyncio.sleep(5)
    try:
        await ch.delete(reason=f"Eval closed with tier {earned_tier} by {interaction.user.name}")
    except Exception:
        pass

@bot.tree.command(name="results", description="Post tier test results")
@app_commands.describe(user="The user who took the test", ign="Minecraft IGN of the player", region="Region where the test was taken", gamemode="Game mode tested", current_rank="Current rank before the test", earned_rank="Rank earned from the test")
@app_commands.choices(
    region=[app_commands.Choice(name=v, value=v) for v in ["NA","EU","AS","AU"]],
    gamemode=[app_commands.Choice(name="Crystal", value="Crystal")],
    current_rank=[app_commands.Choice(name=v, value=v) for v in ["N/A","HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]],
    earned_rank=[app_commands.Choice(name=v, value=v) for v in ["HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]],
)
async def results(interaction: discord.Interaction, user: discord.Member, ign: str, region: str, gamemode: str, current_rank: str, earned_rank: str):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        await interaction.response.send_message(embed=discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.", color=discord.Color.red()), ephemeral=True)
        return
    if not (interaction.channel.name.startswith("Eval ") or interaction.channel.name.startswith("High-Eval-")):
        await interaction.response.send_message(embed=discord.Embed(title="Wrong Channel", description="This command can only be used in eval channels to prevent duplicate results.", color=discord.Color.red()), ephemeral=True)
        return

    await post_tier_results(interaction=interaction, user=user, ign=ign, region=region, gamemode=gamemode, current_rank=current_rank, earned_rank=earned_rank, tester=interaction.user)

    await interaction.response.send_message(embed=discord.Embed(title="Results Posted", description=f"✅ Results posted for {user.mention}\n✅ Testing session completed", color=discord.Color.green()), ephemeral=True)

# === PERIODIC TASKS ===

@tasks.loop(minutes=1)
async def refresh_messages():
    global last_test_session
    last_test_session = datetime.datetime.now()
    for guild in bot.guilds:
        if not is_guild_authorized(getattr(guild, "id", None)):
            continue
        for region in waitlists.keys():
            try:
                await update_waitlist_message(guild, region)
            except Exception as e:
                print(f"DEBUG: refresh waitlist {region} failed: {e}")

@tasks.loop(hours=1)
async def cleanup_expired_cooldowns():
    now = datetime.datetime.now()
    expired = [uid for uid, ts in user_test_cooldowns.items() if ts <= now]
    for uid in expired:
        del user_test_cooldowns[uid]
    if expired:
        save_user_cooldowns()

@tasks.loop(minutes=30)
async def periodic_save_activities():
    save_last_region_activity()

# === RUN BOT ===

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN manquant: définis la variable d'environnement TOKEN.")
    try:
        keep_alive()
    except Exception:
        pass
    run_with_backoff()
