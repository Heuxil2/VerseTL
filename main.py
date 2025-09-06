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
# Priority: HT1 > LT1 > HT2 > LT2 > HT3 > LT3 > HT4 > LT4 > HT5 > LT5
# Display buckets remain Tier 1..5 (HTx/LTx collapse to Tier x)

def _split_ids(env_value: str | None):
    if not env_value:
        return []
    return [s.strip() for s in env_value.split(",") if s.strip()]

def _role_id_ranks_from_env():
    """
    role_id (str) -> (rank, display_tier, exact_label)
    Accepte des listes d'IDs séparées par des virgules pour chaque tier,
    afin d'inclure les IDs des rôles de tes deux serveurs.
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
    # username réel (pas le surnom serveur)
    return m.name

def _member_best_rank(member: discord.Member):
    best = None  # (rank, display_tier, exact_label)
    if ROLE_ID_RANKS:
        ids = {str(r.id) for r in member.roles}
        for rid in ids:
            if rid in ROLE_ID_RANKS:
                rnk = ROLE_ID_RANKS[rid]  # triple
                if (best is None) or (rnk[0] < best[0]):
                    best = rnk
    if best is None:
        for r in member.roles:
            key = _normalize_role_name(r.name)
            if key in NAME_RANKS:
                rank, disp = NAME_RANKS[key]
                rnk = (rank, disp, key)  # key est "HT3", "LT3", etc.
                if (best is None) or (rnk[0] < best[0]):
                    best = rnk
    return best  # (rank, display_tier, exact_label)

async def build_tiers(bot: commands.Bot) -> dict:
    guild_ids = _env_guild_ids()
    if not guild_ids:
        raise RuntimeError("No GUILD_ID_1/GUILD_ID_2 (or GUILD_ID) configured")

    users = {}  # user_id -> {"discord": str, "ign": str|None, "rank": int, "display_tier": int, "exact": str}
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
waitlist_message_ids = {}  # Store message IDs for each region (per guild)
waitlist_messages = {}  # Store actual message objects for each region (per guild)
# Per-guild queue state
opened_queues = {}  # {guild_id: set(region)}
active_testers = {}  # {guild_id: {"na": [], "eu": [], "as": [], "au": []}}
user_info = {}  # {user_id: {"ign": str, "server": str, "region": str}}
last_test_session = datetime.datetime.now()
last_region_activity = {"na": None, "eu": None, "as": None, "au": None}
tester_stats = {}  # {user_id: test_count}
STATS_FILE = "tester_stats.json"
USER_INFO_FILE = "user_info.json"
user_test_cooldowns = {}  # {user_id: datetime}
COOLDOWNS_FILE = "user_cooldowns.json"
LAST_ACTIVITY_FILE = "last_region_activity.json"

def _ensure_guild_queue_state(guild_id: int):
    """Ensure per-guild queue structures exist."""
    if guild_id not in opened_queues:
        opened_queues[guild_id] = set()
    if guild_id not in active_testers:
        active_testers[guild_id] = {"na": [], "eu": [], "as": [], "au": []}

# ====== Export web vanilla.json (cache + tâches) ======
VANILLA_CACHE = {
    "updated_at": None,
    "tiers": {f"tier{i}": [] for i in range(1, 6)},
    "tiers_ign": {f"tier{i}": [] for i in range(1, 6)},
    "tiers_detailed": {f"tier{i}": [] for i in range(1, 6)},
    "exact_tiers": {k: [] for k in EXACT_KEYS},
    "exact_tiers_ign": {k: [] for k in EXACT_KEYS},
}

async def rebuild_and_cache_vanilla():
    """Reconstruit le JSON tiers et le met en cache pour l'export web."""
    global VANILLA_CACHE
    built = await build_tiers(bot)
    VANILLA_CACHE = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **built,
    }
    total = sum(len(v) for v in built["tiers"].values())
    print(f"DEBUG: Rebuilt vanilla cache with {total} users")

@tasks.loop(minutes=10)  # ajuste si tu veux
async def refresh_vanilla_export():
    try:
        await rebuild_and_cache_vanilla()
    except Exception as e:
        print(f"DEBUG: refresh_vanilla_export failed: {e}")

def _vanilla_payload():
    # Exposé via /vanilla.json (keep_alive)
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

# High tier definitions (HT3 and above, including HT2, LT2, HT1, LT1)
HIGH_TIERS = ["HT1", "LT1", "HT2", "LT2", "HT3"]

# Branding for embeds
VERSE_LOGO_URL = os.getenv("VERSE_LOGO_URL")

def get_brand_logo_url(guild: discord.Guild | None = None) -> str | None:
    """
    Renvoie l'URL du logo:
    - d'abord VERSE_LOGO_URL si défini
    - sinon l'icône du serveur (si disponible)
    """
    url = VERSE_LOGO_URL
    if url and url.strip():
        return url.strip()
    try:
        return guild.icon.url if guild and guild.icon else None
    except Exception:
        return None

def get_brand_name(guild: discord.Guild | None = None) -> str:
    """
    Nom de marque affiché (par défaut: nom du serveur, fallback 'VerseTL' si inconnu).
    """
    try:
        return guild.name if guild else "VerseTL"
    except Exception:
        return "VerseTL"

# Track the current #1 we have already notified per region
FIRST_IN_QUEUE_TRACKER = {"na": None, "eu": None, "as": None, "au": None}

# Request channel configuration (robust lookup)
REQUEST_CHANNEL_ID = os.getenv("REQUEST_CHANNEL_ID")  # optional: numeric channel ID
REQUEST_CHANNEL_NAME = os.getenv("REQUEST_CHANNEL_NAME", "request-test")

def _normalize_channel_name(name: str) -> str:
    # Keep only alphanumeric chars to tolerate emojis, separators, spaces, dashes, etc.
    return "".join(ch for ch in name.lower() if ch.isalnum())

def _get_request_channel(guild: discord.Guild) -> discord.TextChannel | None:
    # 1) by ID if provided
    if REQUEST_CHANNEL_ID:
        try:
            ch = guild.get_channel(int(REQUEST_CHANNEL_ID))
            if isinstance(ch, discord.TextChannel):
                return ch
        except Exception:
            pass
    # 2) by normalized name (tolerates variations)
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

def has_booster_role(member: discord.Member) -> bool:
    # Updated to check for "VT • Server Booster" instead of "Booster"
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
    # Priorité aux IDs si *_ROLE_IDS sont configurés
    if str(role.id) in ROLE_ID_RANKS:
        return True
    # Sinon par nom (HT1..LT5)
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
        activity_data = {}
        for region, last_time in last_region_activity.items():
            activity_data[region] = last_time.isoformat() if last_time is not None else None

        with open(LAST_ACTIVITY_FILE, 'w') as f:
            json.dump(activity_data, f, indent=2)
        print(f"DEBUG: Saved last region activities to {LAST_ACTIVITY_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving last region activities: {e}")

def load_last_region_activity():
    global last_region_activity
    try:
        if os.path.exists(LAST_ACTIVITY_FILE):
            with open(LAST_ACTIVITY_FILE, 'r') as f:
                loaded_activities = json.load(f)

            for region in list(last_region_activity.keys()):
                if region in loaded_activities and loaded_activities[region] is not None:
                    try:
                        last_region_activity[region] = datetime.datetime.fromisoformat(loaded_activities[region])
                        time_ago = datetime.datetime.now() - last_region_activity[region]
                        print(f"DEBUG: Loaded last activity for {region.upper()}: {time_ago.days} days ago")
                    except (ValueError, TypeError) as e:
                        print(f"DEBUG: Error parsing last activity for {region}: {e}")
                        last_region_activity[region] = None
                else:
                    last_region_activity[region] = None

            print(f"DEBUG: Loaded last region activities from {LAST_ACTIVITY_FILE}")
        else:
            print(f"DEBUG: No existing last activity file found, starting fresh")
    except Exception as e:
        print(f"DEBUG: Error loading last region activities: {e}")

def get_sheets_service():
    """Get Google Sheets service using service account credentials"""
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

# --- NEW: Persist user_info (IGN, server, region) ---
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
    base = 600  # 10 minutes; Cloudflare 1015 aime bien un cooldown long
    while True:
        try:
            bot.run(TOKEN, reconnect=True)
            break  # sortie propre quand le bot se ferme volontairement
        except HTTPException as e:
            if getattr(e, "status", None) == 429:
                delay = base + random.randint(30, 120)
                print(f"[WARN] Rate limited (429/1015). Sleeping {delay}s before retry.")
                time.sleep(delay)
                base = min(int(base * 1.5), 3600)  # augmente jusqu'à 1h max
                continue
            raise  # autres erreurs: on laisse remonter pour les voir

# ============ HELPER FUNCTIONS FOR NEW FEATURES ============

def _slug_username(name: str) -> str:
    """Transforme le pseudo en nom de salon lisible/valide"""
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "user"

async def post_tier_results(interaction: discord.Interaction, user: discord.Member, ign: str,
                            region: str, gamemode: str, current_rank: str, earned_rank: str,
                            tester: discord.Member, *, force_results_to_standard: bool = False):
    """Réutilisable par /results et le menu /close: envoie l'embed, met à jour stats/feuille, donne le rôle."""
    guild = interaction.guild

    # Détermine le bon salon de résultats
    is_high_result = earned_rank in HIGH_TIERS
    if force_results_to_standard:
        # Forcer l'envoi dans le salon results même pour les high tiers
        results_channel = discord.utils.get(guild.text_channels, name="🏆┃results") or \
                          discord.utils.get(guild.text_channels, name="results")
    else:
        if is_high_result:
            results_channel = discord.utils.get(guild.text_channels, name="🏆┃high-results")
        else:
            results_channel = discord.utils.get(guild.text_channels, name="🏆┃results")

    if not results_channel:
        # Pas de salon dédié -> ne rien faire pour éviter les erreurs visibles
        return

    # Embed
    embed_color = 0x00ff00 if is_high_result else 0xff0000
    embed = discord.Embed(title=f"{ign}'s Test Results", color=embed_color)
    title_prefix = "🔥 **HIGH TIER** 🔥\n" if is_high_result else ""
    embed.description = (
        f"{title_prefix}"
        f"**Tester:**\n{tester.mention}\n"
        f"**Region:**\n{region}\n"
        f"**Minecraft IGN:**\n{ign}\n"
        f"**Previous Tier:**\n{current_rank}\n"
        f"**Tier Earned:**\n{earned_rank}"
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/head/{ign}/100")

    sent = await results_channel.send(content=user.mention, embed=embed)

    try:
        for e in (["👑", "🔥", "⚡", "💎", "✨"] if is_high_result else ["👑", "🤯", "👀", "😱", "🔥"]):
            await sent.add_reaction(e)
    except Exception:
        pass

    # Stats testeur
    tester_id = tester.id
    if tester_id not in tester_stats:
        tester_stats[tester_id] = 0
    tester_stats[tester_id] += 1
    save_tester_stats()

    # Feuille Google (best-effort)
    try:
        await add_ign_to_sheet(ign, earned_rank)
    except Exception:
        pass

    # Leaderboard
    try:
        await update_leaderboard(guild)
    except Exception:
        pass

    # Donne le rôle gagné et retire les anciens
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

    # Rebuild cache vanilla
    try:
        await rebuild_and_cache_vanilla()
    except Exception:
        pass

    # Nettoyage session active
    try:
        if user.id in active_testing_sessions:
            del active_testing_sessions[user.id]
    except Exception:
        pass

# ============ DROPDOWN VIEW FOR /CLOSE ============

class TierSelectView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, tester: discord.Member):
        super().__init__(timeout=60)
        self.channel = channel
        self.tester = tester
        self.player = None
        # Retrouve l'utilisateur testé via le mapping session -> channel
        for uid, cid in active_testing_sessions.items():
            if cid == channel.id:
                self.player = channel.guild.get_member(uid)
                break

    @discord.ui.select(
        placeholder="Choose the tier earned or close only…",
        options=[
            discord.SelectOption(label="HT1", value="HT1"),
            discord.SelectOption(label="LT1", value="LT1"),
            discord.SelectOption(label="HT2", value="HT2"),
            discord.SelectOption(label="LT2", value="LT2"),
            discord.SelectOption(label="HT3", value="HT3"),
            discord.SelectOption(label="LT3", value="LT3"),
            discord.SelectOption(label="HT4", value="HT4"),
            discord.SelectOption(label="LT4", value="LT4"),
            discord.SelectOption(label="HT5", value="HT5"),
            discord.SelectOption(label="LT5", value="LT5"),
            discord.SelectOption(label="Only Close", value="only_close", description="Close channel without posting results"),
        ]
    )
    async def select_tier(self, interaction: discord.Interaction, select: discord.ui.Select):
        earned = select.values[0]
        
        # Si "only close" est sélectionné, fermer sans poster de résultats
        if earned == "only_close":
            embed = discord.Embed(
                title="Channel Closing",
                description="This channel will be closed in 5 seconds…",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Nettoie la session active
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
        
        # Sinon, poster les résultats normalement
        if self.player:
            data = user_info.get(self.player.id, {}) if isinstance(user_info, dict) else {}
            ign = data.get("ign", self.player.display_name)
            # Trouve la région depuis la catégorie du salon
            region = "NA"
            if self.channel.category:
                cname = self.channel.category.name.lower()
                for r in ["na","eu","as","au"]:
                    if r in cname:
                        region = r.upper()
                        break

            # Post résultats
            try:
                await post_tier_results(
                    interaction=interaction,
                    user=self.player,
                    ign=ign,
                    region=region,
                    gamemode="Crystal",
                    current_rank="N/A",
                    earned_rank=earned,
                    tester=self.tester
                )
            except Exception as e:
                print(f"DEBUG: post_tier_results error: {e}")

        # Message et fermeture après 5s
        embed = discord.Embed(
            title="Channel Closing",
            description=f"Results posted for {earned}.\nThis channel will be deleted in 5 seconds…",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Nettoie la session active
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

# ============ GLOBAL CHECK FOR SLASH COMMANDS ============

async def global_app_check(interaction: discord.Interaction) -> bool:
    # Allow /authorize by owner anywhere
    if interaction.command and interaction.command.name == "authorize" and interaction.user.id == OWNER_ID:
        return True

    # DM interactions allowed
    if interaction.guild is None:
        return True

    # Block other commands if guild not authorized
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

    global opened_queues, active_testers, waitlists, waitlist_message_ids, waitlist_messages, active_testing_sessions
    opened_queues.clear()
    active_testers.clear()
    for region in waitlists:
        waitlists[region].clear()
    waitlist_message_ids.clear()
    waitlist_messages.clear()
    active_testing_sessions.clear()
    print("DEBUG: Cleared all opened queues, active testers, waitlists, message references, and active testing sessions on startup")

    # Register global check once
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

    # Auto-authorize all guilds on startup (persists to file)
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

        # Robust lookup (by ID or normalized name) and auto-create if missing
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
                title="📋 Evaluation Testing Waitlist",
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
            print(f"DEBUG: Created single request button in request-test channel with VT • Server Booster cooldown info")

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

    # Build initial du vanilla.json + start scheduler + route HTTP /vanilla.json
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
            embed = discord.Embed(title="Unknown Command", description="Use `/commands` to see available commands.", color=discord.Color.red())
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(title="Missing Permissions", description="You don't have permission to use this command.", color=discord.Color.red())
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(title="Missing Arguments", description="Missing required arguments. Check `/commands` for proper usage.", color=discord.Color.red())
            await ctx.send(embed=embed)
        else:
            print(f"Error: {error}")
            embed = discord.Embed(title="Error", description=str(error), color=discord.Color.red())
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

        discord_patterns = [
            "discord.gg/",
            "discord.com/invite/",
            "discordapp.com/invite/"
        ]

        youtube_patterns = [
            "youtube.com/",
            "youtu.be/",
            "m.youtube.com/"
        ]

        contains_discord_link = any(pattern in content_lower for pattern in discord_patterns)
        contains_youtube_link = any(pattern in content_lower for pattern in youtube_patterns)

        if contains_discord_link or contains_youtube_link:
            try:
                await message.delete()

                link_type = "Discord server invite" if contains_discord_link else "YouTube video"
                warning_message = f"Your message in **{message.guild.name}** was deleted because it contained a {link_type} link. Please avoid sharing such links in the general chat."

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
    """Clean up tracking when eval channels are deleted"""
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
    # Early allow for /authorize by owner
    if (interaction.type == discord.InteractionType.application_command
        and interaction.command and interaction.command.name == "authorize"
        and interaction.user.id == OWNER_ID):
        pass
    else:
        if interaction.guild and not is_guild_authorized(interaction.guild.id):
            if interaction.type == discord.InteractionType.component:
                return

    print(f"DEBUG: Interaction received - Type: {interaction.type}, Data: {getattr(interaction, 'data', 'No data')}")

    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]

        if custom_id == "open_form":
            # Use robust channel check instead of exact name
            if _is_request_channel(interaction.channel):
                # Blocage si rôle "Tierlist Restricted"
                restricted_role = discord.utils.get(interaction.user.roles, name="Tierlist Restricted")
                if restricted_role:
                    embed = discord.Embed(
                        title="Access Denied",
                        description="You are currently restricted from entering the queue.",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                modal = WaitlistModal(get_brand_name(interaction.guild))
                await interaction.response.send_modal(modal)
                return

            for region in waitlists:
                if interaction.channel.name.lower() == f"waitlist-{region}":
                    # Blocage sécurité aussi dans les salons waitlist-...
                    if discord.utils.get(interaction.user.roles, name="Tierlist Restricted"):
                        embed = discord.Embed(
                            title="Access Denied",
                            description="You are currently restricted from joining the queue.",
                            color=discord.Color.red()
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    user_id = interaction.user.id
                    if user_id not in user_info:
                        embed = discord.Embed(title="Form Required", description="You must submit the form in <#📨┃request-test> before joining the queue.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    user_region = user_info[user_id]["region"].lower()
                    if user_region != region:
                        embed = discord.Embed(title="Wrong Region", description=f"Your form was submitted for {user_region.upper()} region, but you're trying to join the {region.upper()} queue.", color=discord.Color.red())
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
                        embed = discord.Embed(title="Already in Queue", description="You're already in the queue.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    if len(waitlists[region]) >= MAX_WAITLIST:
                        embed = discord.Embed(title="Queue Full", description="Queue is full.", color=discord.Color.red())
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    waitlists[region].append(interaction.user.id)

                    role = discord.utils.get(interaction.guild.roles,
                                             name=f"Waitlist-{region.upper()}")
                    if role and role not in interaction.user.roles and role < interaction.guild.me.top_role:
                        try:
                            await interaction.user.add_roles(role)
                        except discord.Forbidden:
                            pass

                    await interaction.response.send_message(
                        f"Successfully joined the {region.upper()} queue! You are position #{len(waitlists[region])} in line.",
                        ephemeral=True)

                    await log_queue_join(interaction.guild, interaction.user, region, len(waitlists[region]))

                    await update_waitlist_message(interaction.guild, region)
                    return
            embed = discord.Embed(title="Invalid Region", description="Invalid waitlist region.", color=discord.Color.red())
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

            role = discord.utils.get(interaction.guild.roles,
                                     name=f"Waitlist-{region.upper()}")
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
        embed = discord.Embed(title="ℹ️ Not in Queue", description="You are not in any waitlist.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="removecooldown", description="Remove a user's cooldown before testing")
@app_commands.describe(member="Member to clear cooldown for")
async def removecooldown(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    # Allow Testers or users with Manage Roles/Admin
    if not (has_tester_role(interaction.user) or interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator):
        embed = discord.Embed(
            title="Permission Required",
            description="You must be a Tester or have the Manage Roles permission to use this command.",
            color=discord.Color.red()
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

    print(f"DEBUG: /startqueue called by {interaction.user.name} for channel {channel.name}")

    if not has_tester_role(interaction.user):
        embed = discord.Embed(
            title="❌ Tester Role Required", 
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", 
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        print(f"DEBUG: User {interaction.user.name} does not have tester role. Roles: {[role.name for role in interaction.user.roles]}")
        return

    print(f"DEBUG: User has Tester role, checking channel name: {channel.name}")
    region = get_region_from_channel(channel.name)
    print(f"DEBUG: Detected region: {region}")

    if not region:
        embed = discord.Embed(
            title="Invalid Channel", 
            description=f"This is not a valid waitlist channel. Channel name: {channel.name}\n\nValid channels are: waitlist-na, waitlist-eu, waitlist-as, waitlist-au", 
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Clear only this guild's members from the waitlist when restarting the queue
    to_purge = [uid for uid in waitlists[region] if interaction.guild.get_member(uid)]
    cleared_count = len(to_purge)
    if cleared_count > 0:
        # Remove waitlist roles from all users in queue (for this guild only)
        for user_id in to_purge:
            member = interaction.guild.get_member(user_id)
            if member:
                roles_to_remove = []
                for role_name in [
                    f"Waitlist-{region.upper()}", f"{region.upper()} Waitlist", f"{region.upper()} Matchmaking",
                    f"waitlist-{region.upper()}", f"waitlist-{region.lower()}",
                    f"{region.lower()} waitlist", f"{region.lower()} matchmaking"
                ]:
                    role = discord.utils.get(interaction.guild.roles, name=role_name)
                    if role and role in member.roles and role < interaction.guild.me.top_role:
                        roles_to_remove.append(role)
                for role in roles_to_remove:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        pass
        # Remove those users from the shared waitlist
        for uid in to_purge:
            try:
                waitlists[region].remove(uid)
            except ValueError:
                pass
        print(f"DEBUG: Cleared {cleared_count} users from {region} waitlist in guild {interaction.guild.id}")

    _ensure_guild_queue_state(interaction.guild.id)
    opened_queues[interaction.guild.id].add(region)

    last_region_activity[region] = datetime.datetime.now()
    save_last_region_activity()
    print(f"DEBUG: Updated and saved last activity for {region.upper()}")

    if interaction.user.id not in active_testers[interaction.guild.id][region]:
        active_testers[interaction.guild.id][region].append(interaction.user.id)

    print(f"DEBUG: Added {region} to opened_queues for guild {interaction.guild.id}: {opened_queues[interaction.guild.id]}")
    print(f"DEBUG: Active testers for {region} in guild {interaction.guild.id}: {active_testers[interaction.guild.id][region]}")

    waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{region}")

    queue_status = f"\n🧹 Cleared {cleared_count} users from the previous queue." if cleared_count > 0 else ""
    
    await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Queue Started",
                description=f"{region.upper()} waitlist is now active in {waitlist_channel.mention if waitlist_channel else f'#waitlist-{region}'}. You are now an active tester.{queue_status}",
                color=discord.Color.green()
            ),
        ephemeral=True
    )

    print(f"DEBUG: Successfully started queue for {region}")

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
            title="❌ Tester Role Required", 
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", 
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        print(f"DEBUG: User {interaction.user.name} does not have tester role. Roles: {[role.name for role in interaction.user.roles]}")
        return

    region = get_region_from_channel(channel.name)
    print(f"DEBUG: Detected region: {region}")
    
    if not region:
        embed = discord.Embed(
            title="Invalid Channel", 
            description=f"This is not a valid waitlist channel. Channel name: {channel.name}\n\nValid channels are: waitlist-na, waitlist-eu, waitlist-as, waitlist-au", 
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    _ensure_guild_queue_state(interaction.guild.id)
    if interaction.user.id in active_testers[interaction.guild.id][region]:
        active_testers[interaction.guild.id][region].remove(interaction.user.id)
        print(f"DEBUG: Removed user {interaction.user.name} from active testers for {region} in guild {interaction.guild.id}")

        if not active_testers[interaction.guild.id][region]:
            opened_queues[interaction.guild.id].discard(region)
            print(f"DEBUG: No more active testers for {region} in guild {interaction.guild.id}, removed from opened_queues")

        await interaction.response.send_message(
            embed=discord.Embed(
                title="👋 Left Active Testers",
                description=f"You have been removed from active testers for {region.upper()} in {channel.mention}.",
                color=discord.Color.blurple()
            ),
            ephemeral=True
        )
        print(f"DEBUG: Successfully stopped queue for {region}")
    else:
        embed = discord.Embed(
            title="Not Active", 
            description=f"You are not an active tester for {region.upper()}.", 
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        print(f"DEBUG: User {interaction.user.name} was not active tester for {region}")

@bot.tree.command(name="nextuser", description="Create a private channel for the next person in waitlist (Tester role required)")
@app_commands.describe(channel="The waitlist channel to get the next person from")
async def nextuser(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if channel is None:
        channel = interaction.channel

    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    region = get_region_from_channel(channel.name)
    if not region:
        embed = discord.Embed(title="Invalid Channel", description="This is not a valid waitlist channel.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not waitlists[region]:
        embed = discord.Embed(title="Empty Queue", description=f"No one is in the {region.upper()} waitlist.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    next_user_id = waitlists[region].pop(0)
    next_user = interaction.guild.get_member(next_user_id)
    if not next_user:
        embed = discord.Embed(title="User Not Found", description="Could not find the next user in the waitlist.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Empêche les doublons de tickets
    if next_user_id in active_testing_sessions:
        existing_channel = interaction.guild.get_channel(active_testing_sessions[next_user_id])
        if existing_channel:
            embed = discord.Embed(title="Active Session Exists", description=f"{next_user.mention} already has an active testing session in {existing_channel.mention}.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            del active_testing_sessions[next_user_id]

    target_high = has_high_tier(next_user)
    primary_category_name = f"High Eval {region.upper()}" if target_high else f"Eval {region.upper()}"
    category = discord.utils.get(interaction.guild.categories, name=primary_category_name)

    if not category and target_high:
        # fallback sur Eval si pas de catégorie High Eval
        category = discord.utils.get(interaction.guild.categories, name=f"Eval {region.upper()}")

    if not category:
        embed = discord.Embed(title="Category Missing", description=f"Could not find category {primary_category_name}.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # NOMMAGE NOUVEAU: Eval (nom discord) ou High-Eval-(nom discord)
    username = next_user.display_name
    if target_high:
        channel_name = f"High-Eval-{username}"
    else:
        channel_name = f"Eval {username}"

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

        # Nettoie les rôles d'attente
        to_remove = []
        for rn in [
            f"Waitlist-{region.upper()}", f"{region.upper()} Waitlist", f"{region.upper()} Matchmaking",
            f"waitlist-{region.upper()}", f"waitlist-{region.lower()}",
            f"{region.lower()} waitlist", f"{region.lower()} matchmaking"
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
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        cooldown_days = apply_cooldown(next_user_id, next_user)
        print(f"DEBUG: Applied {cooldown_days}-day cooldown for {'VT • Server Booster' if has_booster_role(next_user) else 'regular'} user {next_user.name}")

        await send_eval_welcome_message(new_channel, region, next_user, interaction.user)

    except discord.Forbidden:
        embed = discord.Embed(title="Missing Permission", description="I don't have permission to create channels in that category.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="Error", description=f"An error occurred while creating the channel: {str(e)}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- NEW: Add user to current eval channel ---
@bot.tree.command(name="add", description="Add a user to the current eval channel (Tester role required)")
@app_commands.describe(member="Member to add to this eval channel")
async def add_to_eval(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    # Only testers can use this command
    if not has_tester_role(interaction.user):
        embed = discord.Embed(
            title="❌ Tester Role Required",
            description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Must be used inside an eval channel (either eval- or high-eval-)
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel) or not (channel.name.startswith("Eval ") or channel.name.startswith("High-Eval-")):
        embed = discord.Embed(
            title="❌ Wrong Channel",
            description="This command can only be used inside an eval channel.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # If the user already has an active session
    existing_channel_id = active_testing_sessions.get(member.id)
    if existing_channel_id:
        if existing_channel_id == channel.id:
            try:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
            except discord.Forbidden:
                pass
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="ℹ️ Already Added",
                    description=f"{member.mention} already has an active session in this channel. Ensured access permissions.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return
        else:
            existing_channel = interaction.guild.get_channel(existing_channel_id)
            place = existing_channel.mention if existing_channel else "another channel"
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Active Session Exists",
                    description=f"{member.mention} already has an active testing session in {place}.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

    # Grant access to this channel
    try:
        await channel.set_permissions(member, read_messages=True, send_messages=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Missing Permission",
                description="I don't have permission to manage channel permissions here.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    except Exception as e:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Error",
                description=f"An error occurred while setting permissions: {e}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    # Remove from waitlists and update messages
    removed_regions = []
    for r, queue in waitlists.items():
        if member.id in queue:
            queue.remove(member.id)
            removed_regions.append(r)
            try:
                await update_waitlist_message(interaction.guild, r)
            except Exception:
                pass

    # Remove waitlist roles
    roles_to_remove = []
    # Try infer region from category name ("Eval NA", "High Eval NA", etc.)
    target_regions = []
    if channel.category:
        cat_name = channel.category.name.lower()
        for r in ["na", "eu", "as", "au"]:
            if r in cat_name:
                target_regions = [r]
                break
    if not target_regions:
        # If unknown, attempt cleanup for all regions
        target_regions = ["na", "eu", "as", "au"]

    for r in target_regions:
        possible_role_names = [
            f"Waitlist-{r.upper()}",
            f"{r.upper()} Waitlist",
            f"{r.upper()} Matchmaking",
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

    # Mark session as active
    active_testing_sessions[member.id] = channel.id

    # Apply cooldown as after a tier test
    cooldown_days = apply_cooldown(member.id, member)

    # Send welcome message
    welcome_region = target_regions[0] if target_regions else "unknown"
    try:
        await send_eval_welcome_message(channel, welcome_region, member, interaction.user)
    except Exception:
        pass

    parts = [
        f"✅ {member.mention} has been added to this eval channel.",
        f"⏰ Applied a {cooldown_days}-day cooldown.",
    ]
    if removed_regions:
        parts.append(f"🧹 Removed from waitlist(s): {', '.join(r.upper() for r in removed_regions)}")
    if roles_to_remove:
        parts.append(f"🗑️ Removed waitlist role(s): {', '.join(r.name for r in roles_to_remove)}")

    await interaction.response.send_message(
        embed=discord.Embed(
            title="User Added",
            description="\n".join(parts),
            color=discord.Color.green()
        ),
        ephemeral=True
    )

@bot.tree.command(name="passeval", description="Transfer eval channel to High Eval category (Tester role required)")
async def passeval(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in text channels.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Check if channel name contains "eval" (case insensitive) to be more flexible
    channel_name_lower = ch.name.lower()
    if "eval" not in channel_name_lower:
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in eval channels.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    current_category = ch.category
    if not current_category:
        embed = discord.Embed(title="No Category", description="Channel must be in a category to determine region.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    region = None
    cname = current_category.name.lower()
    for r in ["na","eu","as","au"]:
        if r in cname:
            region = r
            break
    if not region:
        embed = discord.Embed(title="Unknown Region", description="Could not determine region from current category.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    high_eval_category_name = f"High Eval {region.upper()}"
    high_eval_category = discord.utils.get(interaction.guild.categories, name=high_eval_category_name)
    if not high_eval_category:
        embed = discord.Embed(title="Category Missing", description=f"Could not find {high_eval_category_name} category.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Renommage: plus flexible pour différents patterns
    old = ch.name
    if old.lower().startswith("high-eval-"):
        new_name = old  # déjà bon
    elif old.lower().startswith("eval "):
        new_name = f"High-Eval-{old[5:]}"  # Remplace "Eval " par "High-Eval-"
    elif old.lower().startswith("eval-"):
        new_name = f"High-{old}"  # eval-xxx -> High-eval-xxx
    else:
        # autre pattern: on préfixe simplement
        new_name = f"High-Eval-{old}"

    try:
        await ch.edit(category=high_eval_category, name=new_name)
        await interaction.response.send_message(f"✅ This channel has been transferred to {high_eval_category_name} and renamed to `{new_name}`.", ephemeral=True)

        embed = discord.Embed(
            title="High Evaluation",
            description=f"This evaluation has been transferred to **{high_eval_category_name}** by {interaction.user.mention}.",
            color=0xff6600
        )
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(title="Missing Permission", description="I don't have permission to move/rename this channel.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="Error", description=f"An error occurred while moving/renaming the channel: {str(e)}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="close", description="Close an eval channel with tier selection (Tester role required)")
async def close(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        embed = discord.Embed(title="❌ Wrong Channel", description="This command can only be used in text channels.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Check if channel name contains "eval" to be more flexible
    if "eval" not in ch.name.lower():
        embed = discord.Embed(title="❌ Wrong Channel", description="This command can only be used in eval channels.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = TierSelectView(ch, interaction.user)
    embed = discord.Embed(
        title="Select Tier Result or Close",
        description="Choose the tier earned to post results, or select 'Only Close' to close without posting results. The channel will close 5 seconds after your selection.",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
    region=[
        app_commands.Choice(name="NA", value="NA"),
        app_commands.Choice(name="EU", value="EU"),
        app_commands.Choice(name="AS", value="AS"),
        app_commands.Choice(name="AU", value="AU")
    ],
    gamemode=[
        app_commands.Choice(name="Crystal", value="Crystal")
    ],
    current_rank=[
        app_commands.Choice(name="N/A", value="N/A"),
        app_commands.Choice(name="HT1", value="HT1"),
        app_commands.Choice(name="LT1", value="LT1"),
        app_commands.Choice(name="HT2", value="HT2"),
        app_commands.Choice(name="LT2", value="LT2"),
        app_commands.Choice(name="HT3", value="HT3"),
        app_commands.Choice(name="LT3", value="LT3"),
        app_commands.Choice(name="HT4", value="HT4"),
        app_commands.Choice(name="LT4", value="LT4"),
        app_commands.Choice(name="HT5", value="HT5"),
        app_commands.Choice(name="LT5", value="LT5")
    ],
    earned_rank=[
        app_commands.Choice(name="HT1", value="HT1"),
        app_commands.Choice(name="LT1", value="LT1"),
        app_commands.Choice(name="HT2", value="HT2"),
        app_commands.Choice(name="LT2", value="LT2"),
        app_commands.Choice(name="HT3", value="HT3"),
        app_commands.Choice(name="LT3", value="LT3"),
        app_commands.Choice(name="HT4", value="HT4"),
        app_commands.Choice(name="LT4", value="LT4"),
        app_commands.Choice(name="HT5", value="HT5"),
        app_commands.Choice(name="LT5", value="LT5")
    ]
)
async def results(interaction: discord.Interaction, user: discord.Member, ign: str, region: str, gamemode: str, current_rank: str, earned_rank: str):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if not has_tester_role(interaction.user):
        embed = discord.Embed(title="❌ Tester Role Required", description="You must have a Tester role to use this command.\nAccepted roles: Tester, Verified Tester, Staff Tester", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not (interaction.channel.name.startswith("Eval ") or interaction.channel.name.startswith("High-Eval-")):
        embed = discord.Embed(title="Wrong Channel", description="This command can only be used in eval channels to prevent duplicate results.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Use the helper function (force posting into standard results channel)
    await post_tier_results(
        interaction=interaction,
        user=user,
        ign=ign,
        region=region,
        gamemode=gamemode,
        current_rank=current_rank,
        earned_rank=earned_rank,
        tester=interaction.user,
        force_results_to_standard=True
    )

    # Send confirmation message
    confirmation_parts = [f"✅ Results posted for {user.mention}"]
    if earned_rank in HIGH_TIERS:
        confirmation_parts.append("🔥 **HIGH TIER RESULT** - Posted in results channel!")
    confirmation_parts.append("✅ Testing session completed")

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Results Posted",
            description="\n".join(confirmation_parts),
            color=discord.Color.green()
        ),
        ephemeral=True
    )

# === MODERATION COMMANDS ===

@bot.tree.command(name="assign_role_to_all", description="Assign role to all members")
@app_commands.describe(role_name="Name of the role to assign")
@app_commands.default_permissions(manage_roles=True)
async def assign_role_to_all(interaction: discord.Interaction, role_name: str):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    await interaction.response.defer()

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        embed = discord.Embed(title="Role Not Found", description="Role not found.", color=discord.Color.red())
        await interaction.followup.send(embed=embed)
        return
    count = 0
    for member in interaction.guild.members:
        if not member.bot and role not in member.roles:
            try:
                await member.add_roles(role)
                count += 1
            except:
                pass
    await interaction.followup.send(
        embed=discord.Embed(
            title="✅ Role Assigned",
            description=f"Role `{role.name}` assigned to {count} members.",
            color=discord.Color.green()
        )
    )

@bot.tree.command(name="remove_role_from_all", description="Remove role from all members")
@app_commands.describe(role_name="Name of the role to remove")
@app_commands.default_permissions(manage_roles=True)
async def remove_role_from_all(interaction: discord.Interaction, role_name: str):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    await interaction.response.defer()

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        embed = discord.Embed(title="❌ Role Not Found", description="Role not found.", color=discord.Color.red())
        await interaction.followup.send(embed=embed)
        return
    count = 0
    for member in interaction.guild.members:
        if not member.bot and role in member.roles:
            try:
                await member.remove_roles(role)
                count += 1
            except:
                pass
    await interaction.followup.send(
        embed=discord.Embed(
            title="🗑️ Role Removed",
            description=f"Role `{role.name}` removed from {count} members.",
            color=discord.Color.orange()
        )
    )

@bot.tree.command(name="purge", description="Delete recent messages")
@app_commands.describe(limit="Number of messages to delete")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, limit: int):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if limit <= 0:
        embed = discord.Embed(title="Invalid Number", description="Please enter a number greater than 0.", color=discord.Color.red())
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

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Reason for the ban")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔨 User Banned",
                description=f"{member.mention} has been banned.\nReason: {reason}",
                color=discord.Color.red()
            )
        )

        log_entry = {
            "type": "ban",
            "user": str(member),
            "user_id": member.id,
            "moderator": str(interaction.user),
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat()
        }
        message_logs[interaction.guild.id].append(log_entry)
    except discord.Forbidden:
        embed = discord.Embed(title="Missing Permission", description="I do not have permission to ban this user.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        embed = discord.Embed(title="Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for the kick")
@app_commands.default_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="👢 User Kicked",
                description=f"{member.mention} has been kicked.\nReason: {reason}",
                color=discord.Color.orange()
            )
        )

        log_entry = {
            "type": "kick",
            "user": str(member),
            "user_id": member.id,
            "moderator": str(interaction.user),
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat()
        }
        message_logs[interaction.guild.id].append(log_entry)
    except discord.Forbidden:
        embed = discord.Embed(title="Missing Permission", description="I do not have permission to kick this user.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        embed = discord.Embed(title="⚠️ Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="mute", description="Mute a member")
@app_commands.describe(member="Member to mute", reason="Reason for the mute")
@app_commands.default_permissions(manage_roles=True)
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await interaction.guild.create_role(name="Muted", reason="Mute role created by bot")
        for channel in interaction.guild.channels:
            if "waitlist" not in channel.name.lower():
                await channel.set_permissions(mute_role, send_messages=False, speak=False)

    try:
        await member.add_roles(mute_role, reason=reason)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔇 User Muted",
                description=f"{member.mention} has been muted.\nReason: {reason}",
                color=discord.Color.orange()
            )
        )

        log_entry = {
            "type": "mute",
            "user": str(member),
            "user_id": member.id,
            "moderator": str(interaction.user),
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat()
        }
        message_logs[interaction.guild.id].append(log_entry)
    except Exception as e:
        embed = discord.Embed(title="⚠️ Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unmute", description="Unmute a member")
@app_commands.describe(member="Member to unmute")
@app_commands.default_permissions(manage_roles=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        embed = discord.Embed(title="Role Missing", description="No mute role found.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        return

    try:
        await member.remove_roles(mute_role)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="User Unmuted",
                description=f"{member.mention} has been unmuted.",
                color=discord.Color.green()
            )
        )

        log_entry = {
            "type": "unmute",
            "user": str(member),
            "user_id": member.id,
            "moderator": str(interaction.user),
            "timestamp": datetime.datetime.now().isoformat()
        }
        message_logs[interaction.guild.id].append(log_entry)
    except Exception as e:
        embed = discord.Embed(title="⚠️ Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
@app_commands.default_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    try:
        await member.send(f"⚠️ You have been warned in {interaction.guild.name}.\nReason: {reason}")
        await interaction.response.send_message(
            embed=discord.Embed(
                title="User Warned",
                description=f"{member.mention} has been warned.\nReason: {reason}",
                color=discord.Color.orange()
            )
        )

        log_entry = {
            "type": "warn",
            "user": str(member),
            "user_id": member.id,
            "moderator": str(interaction.user),
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat()
        }
        message_logs[interaction.guild.id].append(log_entry)
    except discord.Forbidden:
        embed = discord.Embed(title="DM Failed", description="I couldn't send a DM to this user, but the warning has been issued here.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.describe(seconds="Slowmode delay in seconds (0 to disable)")
@app_commands.default_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int = 0):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if seconds < 0 or seconds > 21600:
        embed = discord.Embed(title="Invalid Slowmode", description="Slowmode must be between 0 and 21600 seconds (6 hours).", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        return

    try:
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🚀 Slowmode Disabled",
                    description="Slowmode is now off for this channel.",
                    color=discord.Color.green()
                )
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🌀 Slowmode Set",
                    description=f"Slowmode set to {seconds} seconds.",
                    color=discord.Color.blurple()
                )
            )
    except Exception as e:
        embed = discord.Embed(title="⚠️ Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="lockdown", description="Lock a channel")
@app_commands.describe(channel="Channel to lock (current channel if not specified)")
@app_commands.default_permissions(manage_channels=True)
async def lockdown(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if channel is None:
        channel = interaction.channel

    try:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔒 Channel Locked",
                description=f"{channel.mention} has been locked down.",
                color=discord.Color.dark_grey()
            )
        )
    except Exception as e:
        embed = discord.Embed(title="⚠️ Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unlock", description="Unlock a channel")
@app_commands.describe(channel="Channel to unlock (current channel if not specified)")
@app_commands.default_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if channel is None:
        channel = interaction.channel

    try:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔓 Channel Unlocked",
                description=f"{channel.mention} has been unlocked.",
                color=discord.Color.green()
            )
        )
    except Exception as e:
        embed = discord.Embed(title="⚠️ Error", description=f"An error occurred: {e}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="logs", description="Show recent server logs")
@app_commands.describe(limit="Number of logs to show")
async def logs(interaction: discord.Interaction, limit: int = 10):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if interaction.guild.id not in message_logs:
        embed = discord.Embed(title="❌ No Logs", description="No logs available for this server.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        return

    last_logs = message_logs[interaction.guild.id][-limit:]
    if not last_logs:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📝 No Recent Logs",
                description="There are no recent logs to display.",
                color=discord.Color.blurple()
            )
        )
        return

    embed = discord.Embed(title="Recent Server Logs", color=discord.Colour.blue())
    for log in last_logs:
        timestamp = datetime.datetime.fromisoformat(log["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        if log["type"] == "member_join":
            embed.add_field(name=f"Member Joined - {timestamp}", value=f"{log['user']}", inline=False)
        elif log["type"] == "member_leave":
            embed.add_field(name=f"Member Left - {timestamp}", value=f"{log['user']}", inline=False)
        elif log["type"] == "message_delete":
            embed.add_field(name=f"Message Deleted - {timestamp}", value=f"User: {log['user']}\nChannel: {log['channel']}\nContent: {log['content']}", inline=False)
        elif log["type"] in ["ban", "kick", "mute", "warn"]:
            embed.add_field(name=f"{log['type'].title()} - {timestamp}", value=f"User: {log['user']}\nModerator: {log['moderator']}\nReason: {log['reason']}", inline=False)
        elif log["type"] == "unmute":
            embed.add_field(name=f"Unmute - {timestamp}", value=f"User: {log['user']}\nModerator: {log['moderator']}", inline=False)
        elif log["type"] == "auto_moderation":
            embed.add_field(name=f"Auto-Moderation - {timestamp}", value=f"User: {log['user']}\nChannel: {log['channel']}\nReason: {log['reason']}\nContent: {log['content']}", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="info", description="Bot creator and info")
async def info(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    embed = discord.Embed(title="VerseBot Info", description="Created by <@836452038548127764>", color=discord.Colour.blue())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="support", description="Get support server link")
async def support(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title="📩 Support",
            description="Need help? Join our support server: https://discord.gg/krzwaTsWUu",
            color=discord.Color.blurple()
        )
    )

@bot.tree.command(name="serverinfo", description="Display server information")
async def serverinfo(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    guild = interaction.guild
    embed = discord.Embed(title=f"Server Info - {guild.name}", color=discord.Colour.green())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

    embed.add_field(name="🏆 Server ID", value=guild.id, inline=True)
    embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="📅 Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="👥 Members", value=guild.member_count, inline=True)
    embed.add_field(name="💬 Text Channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="🔊 Voice Channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="📁 Categories", value=len(guild.categories), inline=True)
    embed.add_field(name="📺 Stage Channels", value=len(guild.stage_channels), inline=True)
    embed.add_field(name="🎙️ Forum Channels", value=len([c for c in guild.channels if isinstance(c, discord.ForumChannel)]), inline=True)
    embed.add_field(name="📊 Total Channels", value=len(guild.channels), inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="Display user information")
@app_commands.describe(member="Member to get info about (yourself if not specified)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    if member is None:
        member = interaction.user

    embed = discord.Embed(title=f"User Info - {member}", color=member.color)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

    embed.add_field(name="🏆 User ID", value=member.id, inline=True)
    embed.add_field(name="📅 Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="📅 Joined Server", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="🎭 Roles", value=len(member.roles) - 1, inline=True)
    embed.add_field(name="🤖 Bot", value="Yes" if member.bot else "No", inline=True)
    embed.add_field(name="📱 Status", value=str(member.status).title(), inline=True)

    if member.activity:
        embed.add_field(name="🎮 Activity", value=f"{member.activity.type.name.title()}: {member.activity.name}", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="activity", description="Show server activity statistics")
async def activity(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    guild = interaction.guild
    activities = {}

    for member in guild.members:
        if member.activity and not member.bot:
            activity_name = member.activity.name
            if activity_name in activities:
                activities[activity_name] += 1
            else:
                activities[activity_name] = 1

    if not activities:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📊 No Activity",
                description="No activities detected among server members.",
                color=discord.Color.blurple()
            )
        )
        return

    embed = discord.Embed(title="Server Activity Stats", color=discord.Colour.purple())

    sorted_activities = sorted(activities.items(), key=lambda x: x[1], reverse=True)[:10]
    for activity, count in sorted_activities:
        embed.add_field(name=activity, value=f"{count} member(s)", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="channel_stats", description="Show channel statistics")
async def channel_stats(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    guild = interaction.guild
    embed = discord.Embed(title="Channel Statistics", color=discord.Colour.orange())

    embed.add_field(name="💬 Text Channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="🔊 Voice Channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="📁 Categories", value=len(guild.categories), inline=True)
    embed.add_field(name="📺 Stage Channels", value=len(guild.stage_channels), inline=True)
    embed.add_field(name="🎙️ Forum Channels", value=len([c for c in guild.channels if isinstance(c, discord.ForumChannel)]), inline=True)
    embed.add_field(name="📊 Total Channels", value=len(guild.channels), inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="commands", description="Show all available commands")
async def commands_list(interaction: discord.Interaction):
    if not is_guild_authorized(getattr(interaction.guild, "id", None)):
        return

    embed = discord.Embed(title="Available Commands", color=discord.Colour.green())

    embed.add_field(name="🎯 **Waitlist Commands**", value="""
`/leave` - Leave all waitlists you're currently in
`/startqueue [channel]` - Start the queue for testing (Tester role)
`/stopqueue [channel]` - Remove yourself from active testers (Tester role)
`/nextuser [channel]` - Create private channel for next person (Tester role)
`/passeval` - Transfer eval channel to High Eval category (Tester role)
`/close` - Close an eval channel (Tester role)
`/results` - Post tier test results (Tester role)
`/removecooldown @user` - Remove a user's test cooldown
`/add @user` - add a user to an eval channel
""", inline=False)

    embed.add_field(name="🛡️ **Moderation Commands**", value="""
`/ban @user [reason]` - Ban a member
`/kick @user [reason]` - Kick a member
`/mute @user [reason]` - Mute a member
`/unmute @user` - Unmute a member
`/warn @user [reason]` - Warn a member
`/purge [number]` - Delete recent messages
""", inline=False)

    embed.add_field(name="📺 **Channel Management**", value="""
`/slowmode [seconds]` - Set channel slowmode
`/lockdown [channel]` - Lock a channel
`/unlock [channel]` - Unlock a channel
""", inline=False)

    embed.add_field(name="🎭 **Role Management**", value="""
`/assign_role_to_all [role]` - Assign role to all members
`/remove_role_from_all [role]` - Remove role from all members
""", inline=False)

    embed.add_field(name="📊 **Information Commands**", value="""
`/serverinfo` - Display server information
`/userinfo [@user]` - Display user information
`/activity` - Show server activity statistics
`/channel_stats` - Show channel statistics
`/logs [limit]` - Show recent server logs
""", inline=False)

    embed.add_field(name="💾 **Utility**", value="""
`/info` - Bot creator and info
`/support` - Get support server link
""", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="buildtiers", description="Build tiers (HT/LT priority) across both guilds; dedupe; export vanilla.json")
async def buildtiers_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        built = await build_tiers(bot)
        # Optionnel: synchroniser le cache exposé
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

# === HELPER FUNCTIONS ===

def get_region_from_channel(channel_name: str) -> str:
    """Extract region from channel name"""
    print(f"DEBUG: get_region_from_channel called with: {channel_name}")
    channel_lower = channel_name.lower()
    for region in ["na", "eu", "as", "au"]:
        if f"waitlist-{region}" in channel_lower:
            print(f"DEBUG: Found region {region} in channel {channel_name}")
            return region
    print(f"DEBUG: No region found for channel: {channel_name}")
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
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Blocage également ici si "Tierlist Restricted"
        if discord.utils.get(interaction.user.roles, name="Tierlist Restricted"):
            embed = discord.Embed(
                title="⛔ Access Denied",
                description="You are currently restricted from entering the queue.",
                color=discord.Color.red()
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

                is_booster = has_booster_role(interaction.user)
                cooldown_type = "VT • Server Booster (2 days)" if is_booster else "Regular (4 days)"

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
                embed = discord.Embed(title="⚠️ Active Session Exists", description=f"You already have an active testing session in {existing_channel.mention}. Please complete that test first.", color=discord.Color.red())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            else:
                del active_testing_sessions[user_id]

        region_input = self.region.value.lower().strip()
        valid_regions = ["na", "eu", "as", "au"]
        if region_input not in valid_regions:
            embed = discord.Embed(title="❌ Invalid Region", description="Invalid region. Please use NA, EU, AS, or AU.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Sauvegarde/MAJ des infos (toujours autorisée)
        existing = user_info.get(user_id)
        previous_region = (existing or {}).get("region")
        previous_ign = (existing or {}).get("ign")

        user_info[user_id] = {
            "ign": self.minecraft_ign.value,
            "server": self.minecraft_server.value,
            "region": region_input.upper(),
            "updated_at": datetime.datetime.now().isoformat()
        }
        save_user_info()

        # Rôles d'accès aux salons de waitlist
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

        # Message de confirmation
        is_booster = has_booster_role(interaction.user)
        cooldown_info = f"\n\n💎 **VT • Server Booster Perk:** You have a {BOOSTER_COOLDOWN_DAYS}-day cooldown instead of {REGULAR_COOLDOWN_DAYS} days!" if is_booster else f"\n\n⏰ **Cooldown:** {REGULAR_COOLDOWN_DAYS} days after test completion."

        changed_ign = (previous_ign and previous_ign != self.minecraft_ign.value)
        changed_region = (previous_region and previous_region != region_input.upper())

        extra = []
        if changed_ign:
            extra.append("✏️ Your IGN has been updated and will be reflected everywhere (leaderboard, exports) on the next refresh.")
        if changed_region:
            # Si dans la mauvaise queue, on le mentionne
            user_regions = []
            for r, queue in waitlists.items():
                if interaction.user.id in queue:
                    user_regions.append(r.upper())
            if user_regions and region_input.upper() not in user_regions:
                extra.append(f"🔁 You changed region to {region_input.upper()}. If you are queued in {', '.join(user_regions)}, use /leave then join <#waitlist-{region_input}>.")
        extra_text = ("\n\n" + "\n".join(extra)) if extra else ""

        embed = discord.Embed(
            description=f"✅ Your form has been saved! You have been added to #waitlist-{region_input}.{cooldown_info}{extra_text}",
            color=discord.Color.green())
        embed.set_footer(text="Only you can see this • Dismiss message")

        # Rebuild cache (pour refléter rapidement l'IGN)
        try:
            await rebuild_and_cache_vanilla()
        except Exception:
            pass

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def update_waitlist_message(guild: discord.Guild, region: str):
    if not is_guild_authorized(getattr(guild, "id", None)):
        return

    global last_test_session

    channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
    if not channel:
        print(f"DEBUG: Channel waitlist-{region} not found")
        return

    if guild.id not in waitlist_messages:
        waitlist_messages[guild.id] = {}
    if guild.id not in waitlist_message_ids:
        waitlist_message_ids[guild.id] = {}

    tester_ids = []
    # Per-guild testers/queues
    guild_queue = opened_queues.get(guild.id, set())
    guild_testers = active_testers.get(guild.id, {}).get(region, [])
    if region in guild_queue:
        for tester_id in guild_testers:
            member = guild.get_member(tester_id)
            if member and member.status != discord.Status.offline:
                tester_ids.append(tester_id)

    queue_display = "\n".join(
        [f"{i+1}. <@{uid}>"
         for i, uid in enumerate(waitlists[region])]) or "*No one in queue*"
    testers_display = "\n".join(
        [f"{i+1}. <@{uid}>"
         for i, uid in enumerate(tester_ids)]) or "*No testers online*"

    await maybe_notify_queue_top_change(guild, region)

    region_last_active = last_region_activity.get(region)
    if region_last_active:
        timestamp_unix = int(region_last_active.timestamp())
        timestamp = f"<t:{timestamp_unix}:R>"
    else:
        timestamp = "Never"

    if region in guild_queue and tester_ids:
        color = discord.Color.from_rgb(220, 80, 120)
        description = (
            f"**Tester(s) Available!**\n\n"
            f"Use /leave if you wish to be removed from the waitlist or queue.\n"
            f"**Queue**\n{queue_display}\n\n"
            f"**Testers**\n{testers_display}")
        show_button = True
        ping_content = "@here"
    else:
        color = discord.Color(15880807)
        description = (
            f"No testers for your region are available at this time.\n"
            f"You will be pinged when a tester is available.\n"
            f"Check back later!\n\n"
            f"Last Test At: {timestamp}")
        show_button = False
        ping_content = None

    embed = discord.Embed(description=description, color=color)

    if not (region in opened_queues and tester_ids):
        embed.set_author(
            name=get_brand_name(guild),
            icon_url=get_brand_logo_url(guild)
        )
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
                print(f"DEBUG: Successfully edited stored message object for {region} in guild {guild.id}")
                return
            except (discord.NotFound, discord.HTTPException) as e:
                print(f"DEBUG: Stored message object invalid for {region} in guild {guild.id}: {e}")
                del guild_msgs[region]
                if region in guild_msg_ids:
                    del guild_msg_ids[region]

        if region in guild_msg_ids:
            try:
                message_id = guild_msg_ids[region]
                fetched_message = await channel.fetch_message(message_id)
                guild_msgs[region] = fetched_message
                await fetched_message.edit(content=ping_content, embed=embed, view=view)
                print(f"DEBUG: Successfully fetched and edited message {message_id} for {region} in guild {guild.id}")
                return
            except discord.NotFound:
                print(f"DEBUG: Message ID {guild_msg_ids[region]} not found for {region} in guild {guild.id}")
                del guild_msg_ids[region]
            except Exception as e:
                print(f"DEBUG: Error fetching message for {region} in guild {guild.id}: {e}")
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
            print(f"DEBUG: Found and edited existing message {existing_message.id} for {region} in guild {guild.id}")

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
            print(f"DEBUG: Created new message {new_message.id} for {region} in guild {guild.id}")

    except Exception as e:
        print(f"DEBUG: Error in update_waitlist_message for {region} in guild {guild.id}: {e}")

async def log_queue_join(guild: discord.Guild, user: discord.Member, region: str, position: int):
    """Log when a user joins a queue to the logs channel in Staff category"""
    if not is_guild_authorized(getattr(guild, "id", None)):
        return

    try:
        staff_category = discord.utils.get(guild.categories, name="Staff")
        if not staff_category:
            staff_category = discord.utils.get(guild.categories, name="STAFF")

        if not staff_category:
            print("DEBUG: Staff category not found for logging")
            return

        logs_channel = None
        for channel in staff_category.text_channels:
            if "logs" in channel.name.lower():
                logs_channel = channel
                break

        if not logs_channel:
            print("DEBUG: Logs channel not found in Staff category")
            return

        user_data = user_info.get(user.id, {})
        ign = user_data.get('ign', 'N/A')
        server = user_data.get('server', 'N/A')

        is_booster = has_booster_role(user)
        cooldown_type = f"VT • Server Booster ({BOOSTER_COOLDOWN_DAYS} days)" if is_booster else f"Regular ({REGULAR_COOLDOWN_DAYS} days)"

        embed = discord.Embed(
            title="📋 Queue Join Log",
            description=f"{user.mention} joined the {region.upper()} testing queue",
            color=0x00ff00,
            timestamp=datetime.datetime.now()
        )

        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}` (ID: {user.id})", inline=True)
        embed.add_field(name="Region", value=region.upper(), inline=True)
        embed.add_field(name="Position", value=f"#{position}", inline=True)
        embed.add_field(name="IGN", value=ign, inline=True)
        embed.add_field(name="Preferred Server", value=server, inline=True)
        embed.add_field(name="Cooldown Type", value=cooldown_type, inline=True)
        embed.add_field(name="Account Created", value=user.created_at.strftime("%Y-%m-%d"), inline=True)

        if is_booster:
            embed.add_field(name="Special Status", value="💎 **VT • Server Booster**", inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Queue Join Log", icon_url=guild.icon.url if guild.icon else None)

        await logs_channel.send(embed=embed)
        print(f"DEBUG: Logged queue join for {user.name} ({cooldown_type}) in {region.upper()} region")

    except Exception as e:
        print(f"DEBUG: Error logging queue join: {e}")

async def maybe_notify_queue_top_change(guild: discord.Guild, region: str):
    """Send a 'Queue Position Updated' DM when a new user becomes #1 for a region."""
    if not is_guild_authorized(getattr(guild, "id", None)):
        return

    top_list = waitlists.get(region, [])
    current_top_id = top_list[0] if top_list else None

    if FIRST_IN_QUEUE_TRACKER.get(region) == current_top_id:
        return

    FIRST_IN_QUEUE_TRACKER[region] = current_top_id

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
        print(f"DEBUG: Sent 'Queue Position Updated' DM to {member.name} for {region.upper()} region")
    except discord.Forbidden:
        print(f"DEBUG: Could not DM {member} (privacy settings)")
    except Exception as e:
        print(f"DEBUG: Error sending top-of-queue DM: {e}")

async def notify_first_in_queue(guild: discord.Guild, region: str, tester: discord.Member):
    await maybe_notify_queue_top_change(guild, region)

async def send_eval_welcome_message(channel: discord.TextChannel, region: str, player: discord.Member | None, tester: discord.Member | None):
    """Send the standard welcome message in an eval channel (works for normal and high eval)."""
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
                f"**IGN:** {ign}\n**Preferred Server:** {server}"
            ),
            color=0x00ff7f
        )
        await channel.send(embed=info_embed)
    except Exception as e:
        print(f"DEBUG: Failed to send welcome message in {channel.id}: {e}")

async def create_initial_waitlist_message(guild: discord.Guild, region: str):
    """Create the initial waitlist message and store references to it"""
    if not is_guild_authorized(getattr(guild, "id", None)):
        return

    channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
    if not channel:
        return

    region_last_active = last_region_activity.get(region)
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

    embed.set_author(
        name=get_brand_name(guild),
        icon_url=get_brand_logo_url(guild)
    )

    try:
        initial_message = await channel.send(embed=embed)

        if guild.id not in waitlist_messages:
            waitlist_messages[guild.id] = {}
        if guild.id not in waitlist_message_ids:
            waitlist_message_ids[guild.id] = {}

        waitlist_messages[guild.id][region] = initial_message
        waitlist_message_ids[guild.id][region] = initial_message.id

        print(f"DEBUG: Created and stored initial message {initial_message.id} for {region} in guild {guild.id}")

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
    """Update a simple tester leaderboard if a suitable channel exists. Uses IGN if available."""
    try:
        if not tester_stats:
            return
        channel = (discord.utils.get(guild.text_channels, name="🏆┃leaderboard")
                   or discord.utils.get(guild.text_channels, name="leaderboard"))
        if not channel:
            print("DEBUG: Leaderboard channel not found; skipping update")
            return

        top = sorted(tester_stats.items(), key=lambda kv: kv[1], reverse=True)[:10]
        lines = []
        for idx, (uid, count) in enumerate(top, 1):
            display = _display_name_or_ign(uid, guild)
            lines.append(f"{idx}. {display} — {count} test(s)")

        embed = discord.Embed(title="Tester Leaderboard", description="\n".join(lines) or "*No data*", color=discord.Color.gold())

        # Try to edit the last leaderboard embed; otherwise send a new one
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

    print("DEBUG: Starting periodic refresh of waitlist messages")
    for guild in bot.guilds:
        if not is_guild_authorized(getattr(guild, "id", None)):
            continue
        for region in waitlists.keys():
            try:
                await update_waitlist_message(guild, region)
                print(f"DEBUG: Successfully refreshed waitlist message for {region}")
            except Exception as e:
                print(f"DEBUG: Error refreshing waitlist message for {region}: {e}")

@tasks.loop(hours=1)
async def cleanup_expired_cooldowns():
    """Remove expired cooldowns from memory and file"""
    current_time = datetime.datetime.now()
    expired_users = []

    for user_id, cooldown_time in list(user_test_cooldowns.items()):
        if cooldown_time <= current_time:
            expired_users.append(user_id)

    if expired_users:
        for user_id in expired_users:
            del user_test_cooldowns[user_id]

        save_user_cooldowns()
        print(f"DEBUG: Cleaned up {len(expired_users)} expired cooldowns")

@tasks.loop(minutes=30)
async def periodic_save_activities():
    """Periodically save last region activities to file"""
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
