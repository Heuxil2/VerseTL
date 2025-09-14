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

# ====== Tiers builder ======

def _split_ids(env_value: str | None):
    if not env_value:
        return []
    return [s.strip() for s in env_value.split(",") if s.strip()]

def _role_id_ranks_from_env():
    """
    role_id (str) -> (rank, display_tier, exact_label)
    Priorité (rank croissant = plus haut): HT1(1) > LT1(2) > HT2(3) > LT2(4) > HT3(5) > LT3(6) > HT4(7) > LT4(8) > HT5(9) > LT5(10)
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
        exact = plural.split("_", 1)[0]  # "HT3_ROLE_IDS" -> "HT3"
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
    best = None  # (rank, display_tier, exact_label)
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
waitlist_message_ids = {}  # {guild_id: {region: message_id}}
waitlist_messages = {}     # {guild_id: {region: message_obj}}
# Per-guild queue state
opened_queues = {}  # {guild_id: set(region)}
active_testers = {}  # {guild_id: {"na": [], "eu": [], "as": [], "au": []}}
user_info = {}  # {user_id: {"ign": str, "server": str, "region": str}}
last_test_session = datetime.datetime.now()
# Last Test At par serveur
last_region_activity = {}  # {guild_id: {"na": datetime|None, "eu": ..., "as": ..., "au": ...}}
tester_stats = {}  # {user_id: test_count}
STATS_FILE = "tester_stats.json"
USER_INFO_FILE = "user_info.json"
user_test_cooldowns = {}  # {user_id: datetime}
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

# Track active testing sessions to prevent duplicates
active_testing_sessions = {}  # {user_id: channel_id}

# Cooldown durations
REGULAR_COOLDOWN_DAYS = 4
BOOSTER_COOLDOWN_DAYS = 2

# Google Sheets configuration
SPREADSHEET_ID = "14JoOjPeQYJ1vq5WW2MGNrtNi79YUTrPw7fwUVVjH0CM"
TIER_COLUMNS = {
    "HT1": "B",
    "LT1": "C",
    "HT2": "D",
    "LT2": "E",
    "HT3": "F",
    "LT3": "G",
    "HT4": "H",
    "LT4": "I",
    "HT5": "J",
    "LT5": "K"
}

# High tier definitions
HIGH_TIERS = ["HT1", "LT1", "HT2", "LT2", "HT3"]

# Branding for embeds
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

# Track the current #1 per guild and region
FIRST_IN_QUEUE_TRACKER = {}  # {guild_id: {"na": None, "eu": None, "as": None, "au": None}}

def _ensure_first_tracker(guild_id: int):
    if guild_id not in FIRST_IN_QUEUE_TRACKER:
        FIRST_IN_QUEUE_TRACKER[guild_id] = {"na": None, "eu": None, "as": None, "au": None}

# Request channel configuration
REQUEST_CHANNEL_ID = os.getenv("REQUEST_CHANNEL_ID")
REQUEST_CHANNEL_NAME = os.getenv("REQUEST_CHANNEL_NAME", "request-test")

def _normalize_channel_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())

def _get_request_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if REQUEST_CHANNEL_ID:
        try:
            ch = guild.get_channel(int(REQUEST_CHANNEL_ID))
            if isinstance(ch, discord.TextChannel):
                return ch
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
    role_type = "VT • Server Booster" if has_booster_role(member) else "Regular"
    print(f"DEBUG: Applied {cooldown_days}-day cooldown for {role_type} user {member.name} (ID: {user_id}) until {cooldown_end}")
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
        print(f"DEBUG: Saved tester stats to {STATS_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving tester stats: {e}")

def load_tester_stats():
    global tester_stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                loaded_stats = json.load(f)
                tester_stats = {int(user_id): count for user_id, count in loaded_stats.items()}
            print(f"DEBUG: Loaded {len(tester_stats)} tester stats from {STATS_FILE}")
        else:
            print(f"DEBUG: No existing stats file found, starting fresh")
            tester_stats = {}
    except Exception as e:
        print(f"DEBUG: Error loading tester stats: {e}")
        tester_stats = {}

def save_user_cooldowns():
    try:
        cooldowns_data = {}
        for user_id, cooldown_time in user_test_cooldowns.items():
            cooldowns_data[str(user_id)] = cooldown_time.isoformat()
        with open(COOLDOWNS_FILE, 'w') as f:
            json.dump(cooldowns_data, f, indent=2)
        print(f"DEBUG: Saved {len(cooldowns_data)} user cooldowns to {COOLDOWNS_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving user cooldowns: {e}")

def load_user_cooldowns():
    global user_test_cooldowns
    try:
        if os.path.exists(COOLDOWNS_FILE):
            with open(COOLDOWNS_FILE, 'r') as f:
                loaded_cooldowns = json.load(f)
            user_test_cooldowns = {}
            current_time = datetime.datetime.now()
            for user_id_str, cooldown_str in loaded_cooldowns.items():
                try:
                    user_id = int(user_id_str)
                    cooldown_time = datetime.datetime.fromisoformat(cooldown_str)
                    if cooldown_time > current_time:
                        user_test_cooldowns[user_id] = cooldown_time
                        time_remaining = cooldown_time - current_time
                        days = time_remaining.days
                        hours = time_remaining.seconds // 3600
                        print(f"DEBUG: Loaded active cooldown for user {user_id}: {days}d {hours}h remaining")
                    else:
                        print(f"DEBUG: Skipped expired cooldown for user {user_id}")
                except (ValueError, TypeError) as e:
                    print(f"DEBUG: Error parsing cooldown for user {user_id_str}: {e}")
            print(f"DEBUG: Loaded {len(user_test_cooldowns)} active cooldowns from {COOLDOWNS_FILE}")
        else:
            print(f"DEBUG: No existing cooldowns file found, starting fresh")
            user_test_cooldowns = {}
    except Exception as e:
        print(f"DEBUG: Error loading user cooldowns: {e}")
        user_test_cooldowns = {}

def save_last_region_activity():
    try:
        data = {}
        for gid, regions in last_region_activity.items():
            data[str(gid)] = {}
            for region, last_time in regions.items():
                data[str(gid)][region] = last_time.isoformat() if last_time is not None else None
        with open(LAST_ACTIVITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"DEBUG: Saved last region activities (per guild) to {LAST_ACTIVITY_FILE}")
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
                for region in ["na", "eu", "as", "au"]:
                    val = regions.get(region)
                    if val:
                        try:
                            last_region_activity[gid][region] = datetime.datetime.fromisoformat(val)
                            time_ago = datetime.datetime.now() - last_region_activity[gid][region]
                            print(f"DEBUG: Loaded last activity for guild {gid} {region.upper()}: {time_ago.days} days ago")
                        except (ValueError, TypeError) as e:
                            print(f"DEBUG: Error parsing last activity for guild {gid} {region}: {e}")
                            last_region_activity[gid][region] = None
        else:
            print(f"DEBUG: No existing last activity file found, starting fresh")
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
                creds_info,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
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
        print(f"DEBUG: Saved {len(user_info)} user_info entries to {USER_INFO_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving user_info: {e}")

def load_user_info():
    global user_info
    try:
        if os.path.exists(USER_INFO_FILE):
            with open(USER_INFO_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            user_info = {int(uid): data for uid, data in raw.items()}
            print(f"DEBUG: Loaded {len(user_info)} user_info entries from {USER_INFO_FILE}")
        else:
            print("DEBUG: No user_info file found, starting fresh")
            user_info = {}
    except Exception as e:
        print(f"DEBUG: Error loading user_info: {e}")
        user_info = {}

async def add_ign_to_sheet(ign: str, tier: str):
    """Add IGN to the appropriate tier column in the Google Sheet"""
    try:
        service = get_sheets_service()
        if not service:
            print("DEBUG: Google Sheets service not available")
            return False

        column = TIER_COLUMNS.get(tier.upper())
        if not column:
            print(f"DEBUG: Unknown tier: {tier}")
            return False

        range_name = f"'VerseTL Crystal'!{column}:{column}"
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()

        values = result.get('values', [])
        next_row = len(values) + 1

        range_name = f"'VerseTL Crystal'!{column}{next_row}"
        body = {'values': [[ign]]}

        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()

        print(f"DEBUG: Successfully added {ign} to {tier} column at row {next_row}")
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

# ============ HELPERS ============

def _slug_username(name: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "user"

async def post_tier_results(interaction: discord.Interaction, user: discord.Member, ign: str,
                            region: str, gamemode: str, current_rank: str, earned_rank: str,
                            tester: discord.Member):
    guild = interaction.guild

    is_high_result = earned_rank in HIGH_TIERS
    results_channel = discord.utils.get(guild.text_channels, name="🏆┃results") or \
                      discord.utils.get(guild.text_channels, name="results")
    if not results_channel:
        return

    embed_color=discord.Color(15880807)
    # Add user's profile image as author icon to display it as a circle
    user_avatar_url = user.avatar.url if user.avatar else user.default_avatar.url
    embed = discord.Embed(color=embed_color)
    embed.set_author(name=f"**{ign}'s Test Results 🏆**", icon_url=user_avatar_url)
    embed.description = (
        f"**Tester:**\n{tester.mention}\n"
        f"**Region:**\n{region}\n"
        f"**Minecraft IGN:**\n{ign}\n"
        f"**Previous Tier:**\n{current_rank}\n"
        f"**Tier Earned:**\n{earned_rank}"
    )
    # MODIFICATION: Utilise l'image du corps entier avec les skins 3D au lieu de juste la tête
    embed.set_image(url=f"https://mc-heads.net/body/{ign}/100")

    sent = await results_channel.send(content=user.mention, embed=embed)

    try:
        for e in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
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
        if reg in ("na", "eu", "as", "au") and guild:
            _ensure_guild_activity_state(guild.id)
            last_region_activity[guild.id][reg] = datetime.datetime.now()
            save_last_region_activity()
            print(f"DEBUG: Updated last test at for guild {guild.id} region {reg.upper()}")
    except Exception as e:
        print(f"DEBUG: Failed updating last test at: {e}")

    try:
        await rebuild_and_cache_vanilla()
    except Exception:
        pass

    try:
        if user.id in active_testing_sessions:
            del active_testing_sessions[user.id]
    except Exception:
        pass

# ============ DROPDOWN VIEW FOR /CLOSE ============

class TierSelectView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, tester: discord.Member, previous_tier: str = "N/A"):
        super().__init__(timeout=60)
        self.channel = channel
        self.tester = tester
        self.player = None
        self.previous_tier_value = previous_tier or "N/A"
        for uid, cid in active_testing_sessions.items():
            if cid == channel.id:
                self.player = channel.guild.get_member(uid)
                break

    @discord.ui.select(
        placeholder="Select PREVIOUS tier (optional)",
        options=[discord.SelectOption(label=l, value=l) for l in ["N/A","HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]],
        min_values=1, max_values=1, row=0
    )
    async def previous_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.previous_tier_value = select.values[0]
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

    @discord.ui.select(
        placeholder="Select EARNED tier or 'Only Close'",
        options=[discord.SelectOption(label=l, value=l) for l in ["HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]] + [discord.SelectOption(label="Only Close", value="only_close", description="Close channel without posting results")],
        min_values=1, max_values=1, row=1
    )
    async def earned_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        earned = select.values[0]

        if earned == "only_close":
            embed = discord.Embed(
                title="Channel Closing",
                description="This channel will be closed in 5 seconds…",
                color=discord.Color(15880807)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            try:
                if self.player and self.player.id in active_testing_sessions:
                    del active_testing_sessions[self.player.id]
            except Exception:
                pass
            await asyncio.sleep(5)
            try:
                await self.channel.delete(reason=f"Eval closed without results by {self.tester.name}")
            except Exception:
                pass
            self.stop()
            return

        if self.player:
            data = user_info.get(self.player.id, {}) if isinstance(user_info, dict) else {}
            ign = data.get("ign", self.player.display_name)
            region = "NA"
            if self.channel.category:
                cname = self.channel.category.name.lower()
                for r in ["na","eu","as","au"]:
                    if r in cname:
                        region = r.upper()
                        break
            try:
                await post_tier_results(
                    interaction=interaction,
                    user=self.player,
                    ign=ign,
                    region=region,
                    gamemode="Crystal",
                    current_rank=self.previous_tier_value or "N/A",
                    earned_rank=earned,
                    tester=self.tester
                )
            except Exception as e:
                print(f"DEBUG: post_tier_results error: {e}")

        embed = discord.Embed(
            title="Channel Closing",
            description=f"Results posted for {earned}.\nThis channel will be deleted in 5 seconds…",
            color=discord.Color(15880807)
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.InteractionResponded:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass

        try:
            if self.player and self.player.id in active_testing_sessions:
                del active_testing_sessions[self.player.id]
        except Exception:
            pass

        await asyncio.sleep(5)
        try:
            await self.channel.delete(reason=f"Eval closed with tier {earned} by {self.tester.name}")
        except Exception:
            pass
        self.stop()

# ============ GLOBAL CHECK ============

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
                color=discord.Color(15880807)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.InteractionResponded:
            pass
        return False
    return True

# ============ EVENTS ============

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

    # MODIFICATION: Fermer toutes les queues au restart et remettre à zéro le "last test at"
    global opened_queues, active_testers, waitlists, waitlist_message_ids, waitlist_messages, active_testing_sessions
    opened_queues.clear()
    active_testers.clear()
    for region in waitlists:
        waitlists[region].clear()
    waitlist_message_ids.clear()
    waitlist_messages.clear()
    active_testing_sessions.clear()
    
    # Forcer la fermeture de toutes les queues et remettre à zéro le "last test at" pour chaque serveur
    for guild in bot.guilds:
        if is_guild_authorized(guild.id):
            _ensure_guild_queue_state(guild.id)
            _ensure_guild_activity_state(guild.id)
            for region in ["na", "eu", "as", "au"]:
                # Forcer la fermeture des queues
                opened_queues[guild.id].discard(region)
                if region in active_testers[guild.id]:
                    active_testers[guild.id][region].clear()
                # Remettre à zéro le "last test at" pour chaque région
                last_region_activity[guild.id][region] = None
            print(f"DEBUG: Reset last test at for all regions in guild {guild.id}")
    
    # Sauvegarder l'état réinitialisé
    save_last_region_activity()
    print("DEBUG: Cleared queue/tester/waitlist state on startup and reset last test at")

    global APP_CHECK_ADDED
    if not APP_CHECK_ADDED:
        try:
            bot.tree.add_check(global_app_check)
            APP_CHECK_ADDED = True
            print("DEBUG: Registered global app command check")
        except Exception as e:
            print(f"DEBUG: Failed to add global app check: {e}")

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
        print(f"DEBUG: Auto-authorized {newly_added} guild(s) on startup")

    for guild in bot.guilds:
        if not is_guild_authorized(guild.id):
            print(f"DEBUG: Skipping setup for unauthorized guild {guild.id}")
            continue

        request_channel = _get_request_channel(guild)
        if not request_channel:
            try:
                request_channel = await guild.create_text_channel(REQUEST_CHANNEL_NAME)
                print(f"DEBUG: Created request channel #{request_channel.name} in {guild.name}")
            except discord.Forbidden:
                print(f"DEBUG: Missing permission to create request channel in {guild.name}")
                request_channel = None

        if request_channel:
            embed = discord.Embed(
                title="📝 Evaluation Testing Waitlist",
                description=(
                    "Upon applying, you will be added to a waitlist channel.\n"
                    "Here you will be pinged when a tester of your region is available.\n"
                    "If you are HT3 or higher, a high ticket will be created.\n\n"
                    "• Region should be the region of the server you wish to test on\n"
                    "• Username should be the name of the account you will be testing on\n\n"
                    "**🛑 Failure to provide authentic information will result in a denied test.**\n\n"
                ),
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=None)
            view.add_item(
                discord.ui.Button(label="Enter Waitlist",
                                  style=discord.ButtonStyle.success,
                                  custom_id="open_form"))

            try:
                await request_channel.purge(limit=100)
                print(f"DEBUG: Purged all messages in request-test channel")
            except Exception as e:
                print(f"DEBUG: Could not purge request-test channel: {e}")

            await request_channel.send(embed=embed, view=view)
            print(f"DEBUG: Created single request button in request-test channel")

        for region in waitlists:
            channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
            if channel:
                try:
                    await channel.purge(limit=100)
                    print(f"DEBUG: Purged messages in waitlist-{region}")
                except Exception as e:
                    print(f"DEBUG: Could not purge waitlist-{region}: {e}")

                _ensure_guild_queue_state(guild.id)
                opened_queues[guild.id].discard(region)
                await create_initial_waitlist_message(guild, region)

    if not refresh_messages.is_running():
        refresh_messages.start()
        print("DEBUG: Started refresh_messages task")

    if not cleanup_expired_cooldowns.is_running():
        cleanup_expired_cooldowns.start()
        print("DEBUG: Started cleanup_expired_cooldowns task")

    if not periodic_save_activities.is_running():
        periodic_save_activities.start()
        print("DEBUG: Started periodic_save_activities task")

    try:
        await rebuild_and_cache_vanilla()
    except Exception as e:
        print(f"DEBUG: initial vanilla rebuild failed: {e}")

    if not refresh_vanilla_export.is_running():
        refresh_vanilla_export.start()
        print("DEBUG: Started refresh_vanilla_export task")

    try:
        register_vanilla_callback(_vanilla_payload)
        print("DEBUG: /vanilla.json exporter registered")
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
            print(f"DEBUG: Rebuilt vanilla cache due to tier role change for {after} in guild {after.guild.id}")
        except Exception as e:
            print(f"DEBUG: on_member_update rebuild failed: {e}")

@bot.event
async def on_guild_join(guild):
    message_logs[guild.id] = []
    embed = discord.Embed(
        title="Thanks for adding me!",
        description=(
            "This bot is disabled by default on new servers.\n"
            "The owner <@836452038548127764> must run /authorize in this server to enable it."
        ),
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
            embed = discord.Embed(title="Unknown Command", description="Use `/commands` to see available commands.", color=discord.Color(15880807))
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(title="Missing Permissions", description="You don't have permission to use this command.", color=discord.Color(15880807))
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(title="Missing Arguments", description="Missing required arguments. Check `/commands` for proper usage.", color=discord.Color(15880807))
            await ctx.send(embed=embed)
        else:
            print(f"Error: {error}")
            embed = discord.Embed(title="Error", description=str(error), color=discord.Color(15880807))
            await ctx.send(embed=embed)
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
            print(f"Assigned 'Member' role to {member}")
        except Exception as e:
            print(f"Failed to assign role to {member}: {e}")
    else:
        print(f"'Member' role not found in {member.guild.name}")
    await update_user_count_channel(member.guild)

    log_entry = {
        "type": "member_join",
        "user": str(member),
        "user_id": member.id,
        "timestamp": datetime.datetime.now().isoformat()
    }
    if member.guild.id not in message_logs:
        message_logs[member.guild.id] = []
    message_logs[member.guild.id].append(log_entry)

@bot.event
async def on_member_remove(member):
    if not is_guild_authorized(member.guild.id):
        return
    await update_user_count_channel(member.guild)

    log_entry = {
        "type": "member_leave",
        "user": str(member),
        "user_id": member.id,
        "timestamp": datetime.datetime.now().isoformat()
    }
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

        discord_patterns = ["discord.gg/", "discord.com/invite/", "discordapp.com/invite/"]
        youtube_patterns = ["youtube.com/", "youtu.be/", "m.youtube.com/"]

        contains_discord_link = any(pattern in content_lower for pattern in discord_patterns)
        contains_youtube_link = any(pattern in content_lower for pattern in youtube_patterns)

        if contains_discord_link or contains_youtube_link:
            try:
                await message.delete()

                link_type = "Discord server invite" if contains_discord_link else "YouTube video"
                warning_message = f"⚠️ Your message in **{message.guild.name}** was deleted because it contained a {link_type} link. Please avoid sharing such links in the general chat."

                try:
                    await message.author.send(warning_message)
                except discord.Forbidden:
                    warn_embed = discord.Embed(
                        title="⚠️ Link Removed",
                        description=f"{message.author.mention}, please avoid sharing {link_type} links in this channel.",
                        color=discord.Color.orange()
                    )
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
                    "reason": f"Prohibited link ({link_type})",
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
                    embed = discord.Embed(
                        title="⛔ Access Denied",
                        description="You are currently restricted from entering the queue.",
                        color=discord.Color(15880807)
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                modal = WaitlistModal(get_brand_name(interaction.guild))
                await interaction.response.send_modal(modal)
                return

            for region in waitlists:
                if interaction.channel.name.lower() == f"waitlist-{region}":
                    if discord.utils.get(interaction.user.roles, name="Tierlist Restricted"):
                        embed = discord.Embed(
                            title="⛔ Access Denied",
                            description="You are currently restricted from joining the queue.",
                            color=discord.Color(15880807)
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    user_id = interaction.user.id
                    if user_id not in user_info:
                        embed = discord.Embed(title="Form Required", description="You must submit the form in the <#1407100169467727982> channel before joining the queue.", color=discord.Color(15880807))
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    user_region = user_info[user_id]["region"].lower()
                    if user_region != region:
                        embed = discord.Embed(title="Wrong Region", description=f"Your form was submitted for {user_region.upper()} region, but you're trying to join the {region.upper()} queue.", color=discord.Color(15880807))
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    if user_id in active_testing_sessions:
                        existing_channel_id = active_testing_sessions[user_id]
                        existing_channel = interaction.guild.get_channel(existing_channel_id)
                        if existing_channel:
                            embed = discord.Embed(title="Active Session Exists", description=f"You already have an active testing session in {existing_channel.mention}. Please complete that test first.", color=discord.Color(15880807))
                            await interaction.response.send_message(embed=embed, ephemeral=True)
                            return
                        else:
                            del active_testing_sessions[user_id]

                    if interaction.user.id in waitlists[region]:
                        embed = discord.Embed(
                            description="You are already in the queue. Do you wish to leave?\n-# Click Dismiss Message to cancel.",
                            color=discord.Color(15880807)
                        )
                        view = discord.ui.View(timeout=60)
                        leave_button = discord.ui.Button(label="Leave Queue", style=discord.ButtonStyle.danger)

                        async def leave_callback(button_interaction):
                            try:
                                waitlists[region].remove(interaction.user.id)
                                role = discord.utils.get(interaction.guild.roles, name=f"Waitlist-{region.upper()}")
                                if role and role < interaction.guild.me.top_role:
                                    try:
                                        await interaction.user.remove_roles(role)
                                    except discord.Forbidden:
                                        pass
                                await update_waitlist_message(interaction.guild, region)
                                await button_interaction.response.send_message(
                                    f"",
                                    ephemeral=True
                                )
                            except ValueError:
                                await button_interaction.response.send_message(
                                    "You were not in the queue.",
                                    ephemeral=True
                                )

                        leave_button.callback = leave_callback
                        view.add_item(leave_button)
                        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                        return

                    if len(waitlists[region]) >= MAX_WAITLIST:
                        embed = discord.Embed(title="⛔ Queue Full", description="Queue is full.", color=discord.Color(15880807))
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    waitlists[region].append(interaction.user.id)

                    role = discord.utils.get(interaction.guild.roles, name=f"Waitlist-{region.upper()}")
                    if role and role not in interaction.user.roles and role < interaction.guild.me.top_role:
                        try:
                            await interaction.user.add_roles(role)
                        except discord.Forbidden:
                            pass

                    embed = discord.Embed(
                        description="You have joined the queue!\nRemember, once your ticket is open you will be put on cooldown.\n-# Click the Join button again to leave.",
                        color=discord.Color(15880807)
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)

                    await log_queue_join(interaction.guild, interaction.user, region, len(waitlists[region]))
                    await update_waitlist_message(interaction.guild, region)
                    return

            embed = discord.Embed(title="Invalid Region", description="Invalid waitlist region.", color=discord.Color(15880807))
            await interaction.response.send_message(embed=embed, ephemeral=True)

# === AUTHORIZATION COMMAND ===

@bot.tree.command(name="authorize", description="Authorize the bot to operate in this server (Owner only)")
async def authorize(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        embed = discord.Embed(title="Not Allowed", description="Only the owner can authorize a server.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.guild is None:
        embed = discord.Embed(title="Server Only", description="This command must be used in a server.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.guild.id in authorized_guilds:
        embed = discord.Embed(title="Already Authorized", description="This server is already authorized.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    authorized_guilds.add(interaction.guild.id)
    save_authorized_guilds()
    await interaction.response.send_message(
            embed=discord.Embed(
                title="Server Authorized",
                description=f"Server **{interaction.guild.name}** (`{interaction.guild.id}`) is now authorized.",
                color=discord.Color.green()
            ),
        ephemeral=True
    )
    try:
        await interaction.channel.send(
            embed=discord.Embed(
                title="Server Authorized",
                description="This server has been authorized. Commands are now active.",
                color=discord.Color.green()
            )
        )
    except Exception:
        pass

# === WAITLIST COMMANDS ===

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
        embed = discord.Embed(title="ℹ️ Not in Queue", description="You are not in any waitlist.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="cdreset", description="Remove a user's cooldown before testing")
@app_commands.describe(member="Member to clear cooldown for")
async def removecooldown(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not (has_tester_role(interaction.user) or interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator):
        embed = discord.Embed(
            title="Permission Required",
            description="You must be a Tester or have the Manage Roles permission to use this command.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    had_cooldown = member.id in user_test_cooldowns
    if had_cooldown:
        try:
            del user_test_cooldowns[member.id]
            save_user_cooldowns()
        except Exception:
            pass

    if had_cooldown:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Cooldown Removed",
                description=f"The testing cooldown for {member.mention} has been cleared.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="ℹ️ No Active Cooldown",
                description=f"{member.mention} currently has no active cooldown.",
                color=discord.Color.orange()
            ),
            ephemeral=True
        )

@bot.tree.command(name="startqueue", description="Start the queue for testing (Tester role required)")
@app_commands.describe(channel="The waitlist channel to start the queue for")
async def startqueue(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if channel is None:
        channel = interaction.channel

    if not has_tester_role(interaction.user):
        embed = discord.Embed(
            title="❌ Tester Role Required",
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    region = get_region_from_channel(channel.name)
    if not region:
        embed = discord.Embed(
            title="❌ Invalid Channel",
            description=f"This is not a valid waitlist channel. Channel name: {channel.name}\n\nValid channels are: waitlist-na, waitlist-eu, waitlist-as, waitlist-au",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Clear only this guild's members from the waitlist when restarting the queue
    to_purge = [uid for uid in waitlists[region] if interaction.guild.get_member(uid)]
    cleared_count = len(to_purge)
    if cleared_count > 0:
        for user_id in to_purge:
            member = interaction.guild.get_member(user_id)
            if member:
                roles_to_remove = []
                for role_name in [
                    f"Waitlist-{region.upper()}",
                    f"{region.upper()} Waitlist",
                    # f"{region.upper()} Matchmaking",  # NE PAS enlever
                    f"waitlist-{region.upper()}",
                    f"waitlist-{region.lower()}",
                    f"{region.lower()} waitlist",
                    f"{region.lower()} matchmaking"
                ]:
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
        print(f"DEBUG: Cleared {cleared_count} users from {region} waitlist in guild {interaction.guild.id}")

    _ensure_guild_queue_state(interaction.guild.id)
    opened_queues[interaction.guild.id].add(region)

    _ensure_guild_activity_state(interaction.guild.id)
    last_region_activity[interaction.guild.id][region] = datetime.datetime.now()
    save_last_region_activity()
    print(f"DEBUG: Updated and saved last activity for guild {interaction.guild.id} {region.upper()}")

    if interaction.user.id not in active_testers[interaction.guild.id][region]:
        active_testers[interaction.guild.id][region].append(interaction.user.id)

    waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{region}")
    queue_status = f"\nCleared {cleared_count} users from the previous queue." if cleared_count > 0 else ""

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Queue Started",
            description=f"{region.upper()} waitlist is now active in {waitlist_channel.mention if waitlist_channel else f'#waitlist-{region}'}. You are now an active tester.{queue_status}",
            color=discord.Color(15880807)
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
        embed = discord.Embed(
            title="Tester Role Required",
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    region = get_region_from_channel(channel.name)
    if not region:
        embed = discord.Embed(
            title="Invalid Channel",
            description=f"This is not a valid waitlist channel. Channel name: {channel.name}\n\nValid channels are: waitlist-na, waitlist-eu, waitlist-as, waitlist-au",
            color = discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    _ensure_guild_queue_state(interaction.guild.id)
    if interaction.user.id in active_testers[interaction.guild.id][region]:
        active_testers[interaction.guild.id][region].remove(interaction.user.id)
        if not active_testers[interaction.guild.id][region]:
            opened_queues[interaction.guild.id].discard(region)
            _ensure_guild_activity_state(interaction.guild.id)
            last_region_activity[interaction.guild.id][region] = datetime.datetime.now()
            save_last_region_activity()
            print(f"DEBUG: Updated last test at for guild {interaction.guild.id} region {region.upper()} when queue closed")

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Left Active Testers",
                description=f"You have been removed from active testers for {region.upper()} in {channel.mention}.",
                color = discord.Color(15880807)
            ),
            ephemeral=True
        )
        try:
            await update_waitlist_message(interaction.guild, region)
        except Exception:
            pass
    else:
        embed = discord.Embed(
            title="Not Active",
            description=f"You are not an active tester for {region.upper()}.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="nextuser", description="Create a private channel for the next person in waitlist (Tester role required)")
@app_commands.describe(channel="The waitlist channel to get the next person from")
async def nextuser(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if channel is None:
        channel = interaction.channel

    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    region = get_region_from_channel(channel.name)
    if not region:
        embed = discord.Embed(title="Invalid Channel", description="This is not a valid waitlist channel.", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not waitlists[region]:
        embed = discord.Embed(title="Empty Queue", description=f"No one is in the {region.upper()} waitlist.", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    next_user_id = waitlists[region].pop(0)
    next_user = interaction.guild.get_member(next_user_id)
    if not next_user:
        embed = discord.Embed(title="User Not Found", description="Could not find the next user in the waitlist.", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if next_user_id in active_testing_sessions:
        existing_channel = interaction.guild.get_channel(active_testing_sessions[next_user_id])
        if existing_channel:
            embed = discord.Embed(title="Active Session Exists", description=f"{next_user.mention} already has an active testing session in {existing_channel.mention}.", color = discord.Color(15880807))
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            del active_testing_sessions[next_user_id]

    target_high = has_high_tier(next_user)
    primary_category_name = f"High Eval {region.upper()}" if target_high else f"Eval {region.upper()}"
    category = discord.utils.get(interaction.guild.categories, name=primary_category_name)
    if not category and target_high:
        category = discord.utils.get(interaction.guild.categories, name=f"Eval {region.upper()}")
    if not category:
        embed = discord.Embed(title="Category Missing", description=f"Could not find category {primary_category_name}.", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
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
        new_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites
        )

        active_testing_sessions[next_user_id] = new_channel.id

        to_remove = []
        for rn in [
            f"Waitlist-{region.upper()}",
            f"{region.upper()} Waitlist",
            # f"{region.upper()} Matchmaking",  # garder
            f"waitlist-{region.upper()}",
            f"waitlist-{region.lower()}",
            f"{region.lower()} waitlist",
            f"{region.lower()} matchmaking"
        ]:
            r = discord.utils.get(interaction.guild.roles, name=rn)
            if r and r in next_user.roles and r < interaction.guild.me.top_role:
                to_remove.append(r)
        for r in to_remove:
            try:
                await next_user.remove_roles(r)
            except Exception:
                pass

        await update_waitlist_message(interaction.guild, region)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Private Channel Created",
                description=f"Created {new_channel.mention} for {next_user.mention}.",
                color=discord.Color(15880807)
            ),
            ephemeral=True
        )

        # MODIFICATION: Appliquer le cooldown dès que le salon est créé
        cooldown_days = apply_cooldown(next_user_id, next_user)
        await send_eval_welcome_message(new_channel, region, next_user, interaction.user)

    except discord.Forbidden:
        embed = discord.Embed(title="Missing Permission", description="I don't have permission to create channels in that category.", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="Error", description=f"An error occurred while creating the channel: {str(e)}", color = discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="add", description="Add a user to the current eval channel (Tester role required)")
@app_commands.describe(member="Member to add to this eval channel")
async def add_to_eval(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        embed = discord.Embed(
            title="Tester Role Required",
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        embed = discord.Embed(
            title="Wrong Channel",
            description="This command can only be used in text channels.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    channel_name_lower = channel.name.lower()
    is_eval_channel = (
        channel_name_lower.startswith("eval ") or 
        channel_name_lower.startswith("eval-") or
        channel_name_lower.startswith("high-eval-") or
        "eval" in channel_name_lower
    )
    if not is_eval_channel:
        embed = discord.Embed(
            title="Wrong Channel",
            description="This command can only be used inside an eval channel.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    existing_channel_id = active_testing_sessions.get(member.id)
    if existing_channel_id:
        if existing_channel_id == channel.id:
            try:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
            except discord.Forbidden:
                pass
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Already Added",
                    description=f"{member.mention} already has an active session in this channel. Ensured access permissions.",
                    color=discord.Color(15880807)
                ),
                ephemeral=True
            )
            return
        else:
            existing_channel = interaction.guild.get_channel(existing_channel_id)
            place = existing_channel.mention if existing_channel else "another channel"
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Active Session Exists",
                    description=f"{member.mention} already has an active testing session in {place}.",
                    color=discord.Color(15880807)
                ),
                ephemeral=True
            )
            return

    try:
        await channel.set_permissions(member, read_messages=True, send_messages=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Missing Permission",
                description="I don't have permission to manage channel permissions here.",
                color=discord.Color(15880807)
            ),
            ephemeral=True
        )
        return
    except Exception as e:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Error",
                description=f"An error occurred while setting permissions: {e}",
                color=discord.Color(15880807)
            ),
            ephemeral=True
        )
        return

    removed_regions = []
    for r, queue in waitlists.items():
        if member.id in queue:
            queue.remove(member.id)
            removed_regions.append(r)
            try:
                await update_waitlist_message(interaction.guild, r)
            except Exception:
                pass

    roles_to_remove = []
    target_regions = []
    if channel.category:
        cat_name = channel.category.name.lower()
        for r in ["na", "eu", "as", "au"]:
            if r in cat_name:
                target_regions = [r]
                break
    if not target_regions:
        target_regions = ["na", "eu", "as", "au"]

    for r in target_regions:
        possible_role_names = [
            f"Waitlist-{r.upper()}",
            f"{r.upper()} Waitlist",
            # f"{r.upper()} Matchmaking",  # ne pas retirer
            f"waitlist-{r.upper()}",
            f"waitlist-{r.lower()}",
            f"{r.lower()} waitlist",
            f"{r.lower()} matchmaking"
        ]
        for role_name in possible_role_names:
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if role and role in member.roles and role < interaction.guild.me.top_role:
                roles_to_remove.append(role)

    for role in roles_to_remove:
        try:
            await member.remove_roles(role)
        except discord.Forbidden:
            pass
        except Exception:
            pass

    active_testing_sessions[member.id] = channel.id
    # MODIFICATION: Appliquer le cooldown dès que l'utilisateur est ajouté au salon
    cooldown_days = apply_cooldown(member.id, member)

    welcome_region = target_regions[0] if target_regions else "unknown"
    try:
        await send_eval_welcome_message(channel, welcome_region, member, interaction.user)
    except Exception:
        pass

    # Remove the confirmation message - just acknowledge the interaction silently
    await interaction.response.defer(ephemeral=True)

@bot.tree.command(name="remove", description="Remove a user from the current eval channel (Tester role required)")
@app_commands.describe(member="Member to remove from this eval channel")
async def remove_from_eval(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        embed = discord.Embed(
            title="Tester Role Required",
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        embed = discord.Embed(
            title="Wrong Channel",
            description="This command can only be used in text channels.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    channel_name_lower = channel.name.lower()
    is_eval_channel = (
        channel_name_lower.startswith("eval ") or 
        channel_name_lower.startswith("eval-") or
        channel_name_lower.startswith("high-eval-") or
        "eval" in channel_name_lower
    )
    if not is_eval_channel:
        embed = discord.Embed(
            title="Wrong Channel",
            description="This command can only be used inside an eval channel.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Check if member has access to this channel
    if not channel.permissions_for(member).read_messages:
        embed = discord.Embed(
            title="User Not Found",
            description=f"{member.mention} does not have access to this eval channel.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        # Remove channel permissions
        await channel.set_permissions(member, read_messages=False, send_messages=False)
        
        # Remove from active testing sessions
        if member.id in active_testing_sessions and active_testing_sessions[member.id] == channel.id:
            del active_testing_sessions[member.id]
        
        embed = discord.Embed(
            title="User Removed",
            description=f"{member.mention} has been removed from this eval channel.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="Missing Permission",
            description="I don't have permission to manage channel permissions here.",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(
            title="Error",
            description=f"An error occurred while removing permissions: {e}",
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="passeval", description="Passes a player's eval (Tester role required)")
async def passeval(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in text channels.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if "eval" not in ch.name.lower():
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in eval channels.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Find the player in this eval channel
    player = None
    for uid, cid in active_testing_sessions.items():
        if cid == ch.id:
            player = interaction.guild.get_member(uid)
            break
    
    if not player:
        embed = discord.Embed(title="No Player Found", description="Could not find a player in this eval channel.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Rename channel to high-eval-(username) format
    try:
        username = _slug_username(player.display_name)
        new_channel_name = f"high-eval-{username}"
        await ch.edit(name=new_channel_name, reason=f"Player {player.display_name} passed eval")
    except Exception as e:
        print(f"DEBUG: Failed to rename channel: {e}")
        # Continue even if renaming fails

    # Determine region from channel category
    region = "NA"
    if ch.category:
        cname = ch.category.name.lower()
        for r in ["na", "eu", "as", "au"]:
            if r in cname:
                region = r.upper()
                break

    # Get player info
    data = user_info.get(player.id, {}) if isinstance(user_info, dict) else {}
    ign = data.get("ign", player.display_name)
    
    try:
        # Post LT3 tier results
        await post_tier_results(
            interaction=interaction,
            user=player,
            ign=ign,
            region=region,
            gamemode="Crystal",
            current_rank="N/A",
            earned_rank="LT3",
            tester=interaction.user
        )
        
        # MODIFICATION: Nouvel embed avec nom du serveur et logo du serveur
        guild = interaction.guild
        server_name = get_brand_name(guild)
        server_logo_url = get_brand_logo_url(guild)
        
        embed = discord.Embed(
            title=server_name,
            description=f"Results posted for {player.mention} - LT3 tier earned!\nChannel renamed and role has been automatically assigned.",
            color=discord.Color(15880807)
        )
        
        if server_logo_url:
            embed.set_thumbnail(url=server_logo_url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        embed = discord.Embed(
            title="Error", 
            description=f"An error occurred while posting results: {str(e)}", 
            color=discord.Color(15880807)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="close", description="Close an eval channel (Tester role required)")
async def close(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in text channels.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    channel_name_lower = ch.name.lower()
    is_eval_channel = (
        channel_name_lower.startswith("eval ") or 
        channel_name_lower.startswith("eval-") or
        channel_name_lower.startswith("high-eval-") or
        "eval" in channel_name_lower
    )
    if not is_eval_channel:
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in eval channels.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title="Channel Closing",
        description="This channel will be closed in 5 seconds…",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

    try:
        sessions_to_remove = [uid for uid, cid in active_testing_sessions.items() if cid == ch.id]
        for uid in sessions_to_remove:
            del active_testing_sessions[uid]
            print(f"DEBUG: Cleaned up session for user {uid} in channel {ch.id}")
    except Exception:
        pass

    await asyncio.sleep(5)
    try:
        await ch.delete(reason=f"Eval closed by {interaction.user.name}")
    except Exception:
        pass

@bot.tree.command(name="results", description="Post tier test results")
@app_commands.describe(
    user="The user who took the test",
    ign="Minecraft IGN of the player",
    region="Region where the test was taken",
    gamemode="Game mode tested",
    current_rank="Current rank before the test",
    earned_rank="Rank earned from the test"
)
@app_commands.choices(
    region=[app_commands.Choice(name=n, value=n) for n in ["NA","EU","AS","AU"]],
    gamemode=[app_commands.Choice(name="Crystal", value="Crystal")],
    current_rank=[app_commands.Choice(name=n, value=n) for n in ["N/A","HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]],
    earned_rank=[app_commands.Choice(name=n, value=n) for n in ["HT1","LT1","HT2","LT2","HT3","LT3","HT4","LT4","HT5","LT5"]]
)
async def results(interaction: discord.Interaction, user: discord.Member, ign: str, region: str, gamemode: str, current_rank: str, earned_rank: str):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    channel_name_lower = interaction.channel.name.lower()
    is_eval_channel = (
        channel_name_lower.startswith("eval ") or 
        channel_name_lower.startswith("eval-") or
        channel_name_lower.startswith("high-eval-") or
        "eval" in channel_name_lower
    )
    if not is_eval_channel:
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in eval channels to prevent duplicate results.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    await post_tier_results(
        interaction=interaction,
        user=user,
        ign=ign,
        region=region,
        gamemode=gamemode,
        current_rank=current_rank,
        earned_rank=earned_rank,
        tester=interaction.user
    )

    confirmation_parts = [f"Results posted for {user.mention}"]
    if earned_rank in HIGH_TIERS:
        confirmation_parts.append("🔥 **HIGH TIER RESULT** - Posted in results channel!")
    confirmation_parts.append("Testing session completed")

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Results Posted",
            description="\n".join(confirmation_parts),
            color=discord.Color.green()
        ),
        ephemeral=True
    )

# === MODERATION COMMANDS ===
@bot.tree.command(name="purge", description="Delete recent messages")
@app_commands.describe(limit="Number of messages to delete")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, limit: int):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return
    if limit <= 0:
        embed = discord.Embed(title="Invalid Number", description="Please enter a number greater than 0.", color=discord.Color(15880807))
        await interaction.response.send_message(embed=embed)
        return
    await interaction.response.defer()
    deleted = await interaction.channel.purge(limit=limit)
    await interaction.followup.send(
        embed=discord.Embed(
            title="🧹 Purge Complete",
            description=f"Deleted {len(deleted)} messages.",
            color=discord.Color.orange()
        ),
        ephemeral=True
    )

@bot.tree.command(name="buildtiers", description="Build tiers (HT/LT priority) across both guilds; dedupe; export vanilla.json")
async def buildtiers_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        built = await build_tiers(bot)
        global VANILLA_CACHE
        VANILLA_CACHE = {
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **built,
        }
        payload = json.dumps(VANILLA_CACHE, indent=2).encode("utf-8")
        await interaction.followup.send(
            content="Here is your `vanilla.json` (includes HT/LT and IGNs; deduped across guilds).",
            file=discord.File(BytesIO(payload), filename="vanilla.json"),
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"Error while building tiers: `{e}`", ephemeral=True)

# === HELPERS (suite) ===

def get_region_from_channel(channel_name: str) -> str:
    channel_lower = channel_name.lower()
    for region in ["na", "eu", "as", "au"]:
        if f"waitlist-{region}" in channel_lower:
            return region
    return None

class WaitlistModal(discord.ui.Modal):
    def __init__(self, brand_name: str):
        super().__init__(title=f"Enter Waitlist - {brand_name}")

        self.minecraft_ign = discord.ui.TextInput(
            label="Enter Your Minecraft IGN",
            placeholder="heuxil",
            required=True,
            max_length=16)

        self.minecraft_server = discord.ui.TextInput(
            label="Preferred Minecraft Server (Must Be Known)",
            placeholder="Enter server name",
            required=True,
            max_length=100)

        self.region = discord.ui.TextInput(label="Region (NA/EU/AS/AU)",
                                           placeholder="NA",
                                           required=True,
                                           max_length=2)

        self.add_item(self.minecraft_ign)
        self.add_item(self.minecraft_server)
        self.add_item(self.region)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_guild_authorized(getattr(interaction.guild, "id", None)):
            embed = discord.Embed(
                title="⛔ Unauthorized Server",
                description="This server is not authorized to use this bot. Ask <@836452038548127764> to run /authorize.",
                color=discord.Color(15880807)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if discord.utils.get(interaction.user.roles, name="Tierlist Restricted"):
            embed = discord.Embed(
                title="⛔ Access Denied",
                description="You are currently restricted from entering the queue.",
                color=discord.Color(15880807)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id in user_test_cooldowns:
            cooldown_time = user_test_cooldowns[user_id]
            current_time = datetime.datetime.now()
            time_remaining = cooldown_time - current_time

            if time_remaining.total_seconds() > 0:
                days = time_remaining.days
                hours = time_remaining.seconds // 3600
                minutes = (time_remaining.seconds % 3600) // 60

                cooldown_embed = discord.Embed(
                    title="⏰ Cooldown Active",
                    description=f"You must wait **{days} days, {hours} hours, and {minutes} minutes** before you can test again.",
                    color=0xff0000
                )

                await interaction.response.send_message(embed=cooldown_embed, ephemeral=True)
                return
            else:
                del user_test_cooldowns[user_id]
                save_user_cooldowns()
                print(f"DEBUG: Removed expired cooldown for user {user_id}")

        if user_id in active_testing_sessions:
            existing_channel_id = active_testing_sessions[user_id]
            existing_channel = interaction.guild.get_channel(existing_channel_id)

            if existing_channel:
                embed = discord.Embed(title="⚠️ Active Session Exists", description=f"You already have an active testing session in {existing_channel.mention}. Please complete that test first.", color=discord.Color(15880807))
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            else:
                del active_testing_sessions[user_id]

        region_input = self.region.value.lower().strip()
        valid_regions = ["na", "eu", "as", "au"]
        if region_input not in valid_regions:
            embed = discord.Embed(title="❌ Invalid Region", description="Invalid region. Please use NA, EU, AS, or AU.", color=discord.Color(15880807))
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        user_info[user_id] = {
            "ign": self.minecraft_ign.value,
            "server": self.minecraft_server.value,
            "region": region_input.upper(),
            "updated_at": datetime.datetime.now().isoformat()
        }
        save_user_info()

        waitlist_role = discord.utils.get(
            interaction.guild.roles,
            name=f"Waitlist-{region_input.upper()}")
        if waitlist_role and waitlist_role < interaction.guild.me.top_role:
            try:
                await interaction.user.add_roles(waitlist_role)
            except discord.Forbidden:
                pass

        matchmaking_role = discord.utils.get(
            interaction.guild.roles,
            name=f"{region_input.upper()} Matchmaking")
        if matchmaking_role and matchmaking_role < interaction.guild.me.top_role:
            try:
                await interaction.user.add_roles(matchmaking_role)
            except discord.Forbidden:
                pass

        try:
            await rebuild_and_cache_vanilla()
        except Exception:
            pass

        waitlist_ch = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{region_input}")
        target_channel_text = waitlist_ch.mention if waitlist_ch else f"#waitlist-{region_input}"

        embed = discord.Embed(
            description=f"You have been added to the {target_channel_text}.",
            color=discord.Color(15880807)
        )
        embed.set_footer(text="Only you can see this • Dismiss message")

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def update_waitlist_message(guild: discord.Guild, region: str):
    if not is_guild_authorized(getattr(guild, "id", None)):
        return

    global last_test_session

    channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
    if not channel:
        return

    if guild.id not in waitlist_messages:
        waitlist_messages[guild.id] = {}
    if guild.id not in waitlist_message_ids:
        waitlist_message_ids[guild.id] = {}

    tester_ids = []
    guild_queue = opened_queues.get(guild.id, set())
    guild_testers = active_testers.get(guild.id, {}).get(region, [])
    if region in guild_queue:
        for tester_id in guild_testers:
            member = guild.get_member(tester_id)
            if member and member.status != discord.Status.offline:
                tester_ids.append(tester_id)

    per_guild_waitlist = [uid for uid in waitlists[region] if guild.get_member(uid)]
    queue_display = "\n".join(
        [f"{i+1}. <@{uid}>" for i, uid in enumerate(per_guild_waitlist)]
    ) or "*The queue is currently empty! Press below to join.*"

    testers_display = "\n".join(
        [f"{i+1}. <@{uid}>" for i, uid in enumerate(tester_ids)]
    ) or "*No testers online*"

    await maybe_notify_queue_top_change(guild, region)

    region_last_active = last_region_activity.get(guild.id, {}).get(region)
    if region_last_active:
        timestamp_unix = int(region_last_active.timestamp())
        timestamp = f"<t:{timestamp_unix}:R>"
    else:
        timestamp = "Never"

    if region in guild_queue and tester_ids:
        color = discord.Color.from_rgb(220, 80, 120)
        description = (
            f"## Tester(s) Available!\n\n"
            f"Use ``/leave`` if you wish to be removed from the waitlist or queue.\n"
            f"**Queue**\n{queue_display}\n\n"
            f"**Testers**\n{testers_display}"
        )
        show_button = True
        ping_content = "@here"
    else:
        color = discord.Color(15880807)
        description = (
            f"No testers for your region are available at this time.\n"
            f"You will be pinged when a tester is available.\n"
            f"Check back later!\n\n"
            f"Last Test At: {timestamp}"
        )
        show_button = False
        ping_content = None

    embed = discord.Embed(description=description, color=color)

    if not (region in guild_queue and tester_ids):
        embed.set_author(name=get_brand_name(guild), icon_url=get_brand_logo_url(guild))
        embed.title = "No Testers Online"

    view = discord.ui.View()
    if show_button:
        view.add_item(
            discord.ui.Button(label="Join Queue",
                              style=discord.ButtonStyle.primary,
                              custom_id="open_form"))

    try:
        guild_msgs = waitlist_messages[guild.id]
        guild_msg_ids = waitlist_message_ids[guild.id]

        if region in guild_msgs:
            try:
                stored_message = guild_msgs[region]
                await stored_message.edit(content=ping_content, embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                del guild_msgs[region]
                if region in guild_msg_ids:
                    del guild_msg_ids[region]

        if region in guild_msg_ids:
            try:
                message_id = guild_msg_ids[region]
                fetched_message = await channel.fetch_message(message_id)
                guild_msgs[region] = fetched_message
                await fetched_message.edit(content=ping_content, embed=embed, view=view)
                return
            except discord.NotFound:
                del guild_msg_ids[region]
            except Exception:
                if region in guild_msg_ids:
                    del guild_msg_ids[region]

        existing_message = None
        async for message in channel.history(limit=10):
            if message.author == bot.user and message.embeds:
                existing_message = message
                break

        if existing_message:
            guild_msgs[region] = existing_message
            guild_msg_ids[region] = existing_message.id
            await existing_message.edit(content=ping_content, embed=embed, view=view)

            message_count = 0
            async for message in channel.history(limit=20):
                if message.author == bot.user and message.id != existing_message.id:
                    try:
                        await message.delete()
                        message_count += 1
                        if message_count >= 3:
                            break
                    except:
                        pass
        else:
            new_message = await channel.send(content=ping_content, embed=embed, view=view)
            guild_msgs[region] = new_message
            guild_msg_ids[region] = new_message.id

    except Exception as e:
        print(f"DEBUG: Error in update_waitlist_message for {region} in guild {guild.id}: {e}")

async def log_queue_join(guild: discord.Guild, user: discord.Member, region: str, position: int):
    if not is_guild_authorized(getattr(guild, "id", None)):
        return
    try:
        _ensure_guild_queue_state(guild.id)
        testers = active_testers.get(guild.id, {}).get(region, []) or []
        testers_mentions = " ".join(f"<@{tid}>" for tid in testers)

        logs_channel = _get_logs_channel(guild)
        if not logs_channel:
            return

        waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
        waitlist_link = waitlist_channel.mention if waitlist_channel else f"#waitlist-{region}"

        embed = discord.Embed(
            title="Queue Join",
            description=f"{user.mention} joined the queue in {waitlist_link}",
            color = discord.Color(15880807)
        )

        if user.avatar:
            embed.set_thumbnail(url=user.avatar.url)
        else:
            embed.set_thumbnail(url=user.default_avatar.url)

        if testers_mentions:
            await logs_channel.send(content=testers_mentions, embed=embed)
        else:
            await logs_channel.send(embed=embed)
    except Exception as e:
        print(f"DEBUG: Error logging queue join: {e}")

async def maybe_notify_queue_top_change(guild: discord.Guild, region: str):
    if not is_guild_authorized(getattr(guild, "id", None)):
        return

    _ensure_first_tracker(guild.id)

    top_list_global = waitlists.get(region, [])
    per_guild_top_list = [uid for uid in top_list_global if guild.get_member(uid)]
    current_top_id = per_guild_top_list[0] if per_guild_top_list else None

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
            color = discord.Color(15880807)
        )
        embed.set_author(name=get_brand_name(guild), icon_url=get_brand_logo_url(guild))
        await member.send(embed=embed)
        print(f"DEBUG: Sent 'Queue Position Updated' DM to {member.name} for {region.upper()} region (guild {guild.id})")
    except discord.Forbidden:
        print(f"DEBUG: Could not DM {member} (privacy settings)")
    except Exception as e:
        print(f"DEBUG: Error sending top-of-queue DM: {e}")

async def notify_first_in_queue(guild: discord.Guild, region: str, tester: discord.Member):
    await maybe_notify_queue_top_change(guild, region)

async def send_eval_welcome_message(channel: discord.TextChannel, region: str, player: discord.Member | None, tester: discord.Member | None):
    try:
        user_data = user_info.get(player.id, {}) if player else {}
        ign = user_data.get('ign', 'N/A')
        server = user_data.get('server', 'N/A')
        player_mention = player.mention if player else "Player"
        tester_mention = tester.mention if tester else "a tester"

        info_embed = discord.Embed(
            title="Welcome to your Evaluation Session",
            description=(
                f"Hello {player_mention}! You have been selected for testing in the {region.upper()} region.\n\n"
                f"Your tester {tester_mention} will guide you through the process.\n\n"
                f"-# **IGN:** {ign}\n-# **Preferred Server:** {server}"
            ),
            color=discord.Color(15880807)
        )
        await channel.send(embed=info_embed)
    except Exception as e:
        print(f"DEBUG: Failed to send welcome message in {channel.id}: {e}")

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
        description=(
            f"No testers for your region are available at this time.\n"
            f"You will be pinged when a tester is available.\n"
            f"Check back later!\n\n"
            f"Last Test At: {timestamp}"
        ),
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
        print(f"DEBUG: Error creating initial message for {region} in guild {guild.id}: {e}")

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

# === TASKS ===

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
                print(f"DEBUG: Error refreshing waitlist message for {region}: {e}")

@tasks.loop(hours=1)
async def cleanup_expired_cooldowns():
    current_time = datetime.datetime.now()
    expired_users = [user_id for user_id, cooldown_time in user_test_cooldowns.items() if cooldown_time <= current_time]
    if expired_users:
        for user_id in expired_users:
            del user_test_cooldowns[user_id]
        save_user_cooldowns()
        print(f"DEBUG: Cleaned up {len(expired_users)} expired cooldowns")

@tasks.loop(minutes=30)
async def periodic_save_activities():
    save_last_region_activity()
    print("DEBUG: Periodic save of last region activities completed")

# === RUN BOT ===

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN manquant: définis la variable d'environnement TOKEN.")
    try:
        keep_alive()
    except Exception:
        pass
    run_with_backoff()
