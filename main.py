# Standard library
import os
import json
import asyncio
from datetime import datetime, timedelta

# Discord
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.errors import HTTPException

# Env/hosting
from dotenv import load_dotenv

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

# Configuration
CHANNELS = {
    'request_test': 'request-test',
    'logs': 'logs',
    'waitlist_na': 'waitlist-na',
    'waitlist_euw': 'waitlist-euw',
    'waitlist_eune': 'waitlist-eune',
    'waitlist_br': 'waitlist-br',
    'waitlist_las': 'waitlist-las',
    'waitlist_lan': 'waitlist-lan',
    'waitlist_oce': 'waitlist-oce',
    'waitlist_ru': 'waitlist-ru',
    'waitlist_tr': 'waitlist-tr',
    'waitlist_jp': 'waitlist-jp',
    'waitlist_kr': 'waitlist-kr',
    'waitlist_ph': 'waitlist-ph',
    'waitlist_sg': 'waitlist-sg',
    'waitlist_tw': 'waitlist-tw',
    'waitlist_th': 'waitlist-th',
    'waitlist_vn': 'waitlist-vn'
}

ROLES = {
    'tester': 'Tester',
    'admin': 'Admin',
    'moderator': 'Moderator'
}

# Régions disponibles
REGIONS = ['NA', 'EUW', 'EUNE', 'BR', 'LAS', 'LAN', 'OCE', 'RU', 'TR', 'JP', 'KR', 'PH', 'SG', 'TW', 'TH', 'VN']

# Tiers
TIERS = ['Iron', 'Bronze', 'Silver', 'Gold', 'Platinum', 'Emerald', 'Diamond', 'Master', 'GrandMaster', 'Challenger']

# File de données
DATA_FILE = 'bot_data.json'

class BotData:
    """Gestion des données persistantes du bot"""
    
    def __init__(self):
        self.data = self.load_data()
    
    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    return json.load(f)
            except:
                return self.get_default_data()
        return self.get_default_data()
    
    def get_default_data(self):
        return {
            'waitlists': {},  # {guild_id: {region: [user_ids]}}
            'active_testers': {},  # {guild_id: {user_id: {'region': str, 'timestamp': str}}}
            'warnings': {},  # {guild_id: {user_id: count}}
            'muted_users': {},  # {guild_id: [user_ids]}
            'locked_channels': {},  # {guild_id: [channel_ids]}
            'activity_stats': {},  # {guild_id: {user_id: {'messages': int, 'voice_minutes': int}}}
            'first_in_queue_notified': {}  # {guild_id: {region: bool}}
        }
    
    def save_data(self):
        with open(DATA_FILE, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get_guild_waitlist(self, guild_id: int, region: str) -> list[int]:
        guild_id = str(guild_id)
        if guild_id not in self.data['waitlists']:
            self.data['waitlists'][guild_id] = {}
        if region not in self.data['waitlists'][guild_id]:
            self.data['waitlists'][guild_id][region] = []
        return self.data['waitlists'][guild_id][region]
    
    def add_to_waitlist(self, guild_id: int, region: str, user_id: int):
        waitlist = self.get_guild_waitlist(guild_id, region)
        if user_id not in waitlist:
            waitlist.append(user_id)
            self.save_data()
            return True
        return False
    
    def remove_from_waitlist(self, guild_id: int, region: str, user_id: int):
        waitlist = self.get_guild_waitlist(guild_id, region)
        if user_id in waitlist:
            waitlist.remove(user_id)
            self.save_data()
            return True
        return False
    
    def get_user_position(self, guild_id: int, region: str, user_id: int) -> int | None:
        waitlist = self.get_guild_waitlist(guild_id, region)
        if user_id in waitlist:
            return waitlist.index(user_id) + 1
        return None
    
    def set_active_tester(self, guild_id: int, user_id: int, region: str):
        guild_id = str(guild_id)
        if guild_id not in self.data['active_testers']:
            self.data['active_testers'][guild_id] = {}
        self.data['active_testers'][guild_id][str(user_id)] = {
            'region': region,
            'timestamp': datetime.now().isoformat()
        }
        self.save_data()
    
    def remove_active_tester(self, guild_id: int, user_id: int):
        guild_id = str(guild_id)
        user_id = str(user_id)
        if guild_id in self.data['active_testers']:
            if user_id in self.data['active_testers'][guild_id]:
                del self.data['active_testers'][guild_id][user_id]
                self.save_data()
    
    def get_active_testers(self, guild_id: int, region: str = None) -> list[int]:
        guild_id = str(guild_id)
        if guild_id not in self.data['active_testers']:
            return []
        
        testers = []
        for user_id, info in self.data['active_testers'][guild_id].items():
            if region is None or info['region'] == region:
                testers.append(int(user_id))
        return testers
    
    def was_first_in_queue_notified(self, guild_id: int, region: str) -> bool:
        guild_id = str(guild_id)
        if guild_id not in self.data['first_in_queue_notified']:
            self.data['first_in_queue_notified'][guild_id] = {}
        return self.data['first_in_queue_notified'][guild_id].get(region, False)
    
    def set_first_in_queue_notified(self, guild_id: int, region: str, notified: bool):
        guild_id = str(guild_id)
        if guild_id not in self.data['first_in_queue_notified']:
            self.data['first_in_queue_notified'][guild_id] = {}
        self.data['first_in_queue_notified'][guild_id][region] = notified
        self.save_data()

# ============ DISCORD SETUP ============

intents = discord.Intents.all()

class DiscordBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.bot_data = BotData()
        self.synced = False
    
    async def setup_hook(self):
        """Configuration initiale du bot"""
        # Ajouter la vue persistante
        self.add_view(RequestWaitlistView())
        
        # Synchroniser les commandes
        if not self.synced:
            await self.tree.sync()
            self.synced = True
            print("DEBUG: Slash commands synced")
    
    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord!')
        
        # Enregistrer la vue persistante au démarrage
        self.add_view(RequestWaitlistView())
        
        # Setup initial des canaux
        for guild in self.guilds:
            await self.setup_guild_channels(guild)
        
        # Démarrer les tâches périodiques
        if not self.cleanup_inactive_testers.is_running():
            self.cleanup_inactive_testers.start()
    
    async def setup_guild_channels(self, guild: discord.Guild):
        """Configuration des canaux pour un serveur"""
        # Vérifier/créer le canal request-test
        request_channel = discord.utils.get(guild.text_channels, name=CHANNELS['request_test'])
        if request_channel:
            # Purger les anciens messages et poster le nouveau
            await request_channel.purge(limit=100)
            
            embed = discord.Embed(
                title="🎮 Join Testing Waitlist",
                description=(
                    "Click the button below to join the testing waitlist.\n\n"
                    "**Requirements:**\n"
                    "• Valid League of Legends account\n"
                    "• Available for testing session\n"
                    "• Discord voice enabled\n\n"
                    "**How it works:**\n"
                    "1. Click 'Enter Waitlist'\n"
                    "2. Fill in your information\n"
                    "3. Wait for a tester to contact you\n"
                    "4. Join voice channel when invited"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="Bot created by Frédéric")
            
            # Utiliser la vue persistante
            view = RequestWaitlistView()
            await request_channel.send(embed=embed, view=view)
    
    @tasks.loop(hours=1)
    async def cleanup_inactive_testers(self):
        """Nettoyer les testeurs inactifs après 2 heures"""
        for guild in self.guilds:
            guild_id = str(guild.id)
            if guild_id in self.bot_data.data['active_testers']:
                to_remove = []
                for user_id, info in self.bot_data.data['active_testers'][guild_id].items():
                    timestamp = datetime.fromisoformat(info['timestamp'])
                    if datetime.now() - timestamp > timedelta(hours=2):
                        to_remove.append(int(user_id))
                
                for user_id in to_remove:
                    self.bot_data.remove_active_tester(guild.id, user_id)
                    print(f"DEBUG: Removed inactive tester {user_id} from guild {guild.id}")

# Initialisation du bot
bot = DiscordBot()

# ============ VIEWS ============

class WaitlistModal(discord.ui.Modal, title='Join Waitlist'):
    """Modal pour rejoindre la liste d'attente"""
    
    summoner_name = discord.ui.TextInput(
        label='Summoner Name',
        placeholder='Enter your summoner name',
        required=True,
        max_length=50
    )
    
    region = discord.ui.TextInput(
        label='Region',
        placeholder='NA, EUW, EUNE, etc.',
        required=True,
        max_length=4
    )
    
    rank = discord.ui.TextInput(
        label='Current Rank',
        placeholder='e.g., Gold 2, Diamond 4',
        required=True,
        max_length=30
    )
    
    def __init__(self, bot_instance):
        super().__init__()
        self.bot = bot_instance
    
    async def on_submit(self, interaction: discord.Interaction):
        region = self.region.value.upper()
        
        # Vérification de la région
        if region not in REGIONS:
            await interaction.response.send_message(
                f"Invalid region. Please use one of: {', '.join(REGIONS)}",
                ephemeral=True
            )
            return
        
        # Ajouter à la liste d'attente
        bot_data = self.bot.bot_data
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Vérifier si déjà dans une liste
        for r in REGIONS:
            if user_id in bot_data.get_guild_waitlist(guild_id, r):
                await interaction.response.send_message(
                    f"You are already in the {r} waitlist. Please leave it first.",
                    ephemeral=True
                )
                return
        
        # Ajouter à la liste
        bot_data.add_to_waitlist(guild_id, region, user_id)
        position = bot_data.get_user_position(guild_id, region, user_id)
        
        # Créer l'embed de confirmation
        embed = discord.Embed(
            title="✅ Successfully Joined Waitlist",
            description=f"You have been added to the **{region}** waitlist",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Summoner Name", value=self.summoner_name.value, inline=True)
        embed.add_field(name="Region", value=region, inline=True)
        embed.add_field(name="Rank", value=self.rank.value, inline=True)
        embed.add_field(name="Position in Queue", value=f"#{position}", inline=True)
        embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Logger l'ajout
        await self.log_queue_join(interaction.guild, interaction.user, region, position)
        
        # Poster dans le canal waitlist de la région
        await self.post_to_waitlist_channel(interaction.guild, interaction.user, region, position)
    
    async def log_queue_join(self, guild: discord.Guild, user: discord.User, region: str, position: int):
        """Log quand quelqu'un rejoint une queue"""
        logs_channel = discord.utils.get(guild.text_channels, name=CHANNELS['logs'])
        if logs_channel:
            embed = discord.Embed(
                title="User Joined Queue",
                description=f"{user.mention} joined the **{region}** waitlist",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Position", value=f"#{position}", inline=True)
            embed.add_field(name="Region", value=region, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await logs_channel.send(embed=embed)
    
    async def post_to_waitlist_channel(self, guild: discord.Guild, user: discord.User, region: str, position: int):
        """Poster dans le canal waitlist spécifique à la région - SANS ping des testeurs"""
        channel_name = f'waitlist-{region.lower()}'
        waitlist_channel = discord.utils.get(guild.text_channels, name=channel_name)
        
        if waitlist_channel:
            embed = discord.Embed(
                title="New Player in Queue",
                description=f"{user.mention} joined the waitlist",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Position", value=f"#{position}", inline=True)
            embed.set_footer(text="A tester will contact you when available")
            
            # Notification pour le premier de la file uniquement
            bot_data = self.bot.bot_data
            if position == 1 and not bot_data.was_first_in_queue_notified(guild.id, region):
                embed.add_field(
                    name="⚡ First in Queue!", 
                    value="You're first! A tester should be available soon.",
                    inline=False
                )
                bot_data.set_first_in_queue_notified(guild.id, region, True)
            
            await waitlist_channel.send(embed=embed)

class RequestWaitlistView(discord.ui.View):
    """Vue persistante pour le bouton Enter Waitlist"""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='Enter Waitlist', style=discord.ButtonStyle.primary, custom_id='open_form')
    async def enter_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Vérifier que c'est bien le bon canal
        if interaction.channel.name != CHANNELS['request_test']:
            await interaction.response.send_message(
                "This button can only be used in the request-test channel.",
                ephemeral=True
            )
            return
        
        # Vérifier que l'utilisateur n'a pas le rôle Tester
        tester_role = discord.utils.get(interaction.guild.roles, name=ROLES['tester'])
        if tester_role and tester_role in interaction.user.roles:
            await interaction.response.send_message(
                "Testers cannot join the waitlist.",
                ephemeral=True
            )
            return
        
        # Ouvrir le modal
        modal = WaitlistModal(interaction.client)
        await interaction.response.send_modal(modal)

# ====== COMMANDES SLASH ======



@bot.tree.command(name='queue', description='Check your position in the waitlist')
async def queue(interaction: discord.Interaction):
    user_id = interaction.user.id
    guild_id = interaction.guild.id
    
    # Chercher dans quelle région l'utilisateur est
    for region in REGIONS:
        position = bot.bot_data.get_user_position(guild_id, region, user_id)
        if position:
            waitlist = bot.bot_data.get_guild_waitlist(guild_id, region)
            embed = discord.Embed(
                title="Queue Position",
                description=f"You are in the **{region}** waitlist",
                color=discord.Color.blue()
            )
            embed.add_field(name="Your Position", value=f"#{position}", inline=True)
            embed.add_field(name="Total in Queue", value=len(waitlist), inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
    
    await interaction.response.send_message(
        "You are not in any waitlist. Use the button in #request-test to join.",
        ephemeral=True
    )

@bot.tree.command(name='leave', description='Leave the waitlist')
async def leave(interaction: discord.Interaction):
    user_id = interaction.user.id
    guild_id = interaction.guild.id
    
    # Chercher et retirer de toutes les listes
    removed = False
    for region in REGIONS:
        if bot.bot_data.remove_from_waitlist(guild_id, region, user_id):
            # Réinitialiser la notification first-in-queue si la liste devient vide
            waitlist = bot.bot_data.get_guild_waitlist(guild_id, region)
            if len(waitlist) == 0:
                bot.bot_data.set_first_in_queue_notified(guild_id, region, False)
            
            await interaction.response.send_message(
                f"✅ You have been removed from the **{region}** waitlist.",
                ephemeral=True
            )
            
            # Logger
            logs_channel = discord.utils.get(interaction.guild.text_channels, name=CHANNELS['logs'])
            if logs_channel:
                embed = discord.Embed(
                    title="User Left Queue",
                    description=f"{interaction.user.mention} left the **{region}** waitlist",
                    color=discord.Color.orange(),
                    timestamp=datetime.now()
                )
                await logs_channel.send(embed=embed)
            
            removed = True
            break
    
    if not removed:
        await interaction.response.send_message(
            "You are not in any waitlist.",
            ephemeral=True
        )

@bot.tree.command(name='next', description='[Tester] Get the next person in queue')
@app_commands.describe(region='Region to get next person from')
async def next_in_queue(interaction: discord.Interaction, region: str):
    # Vérifier les permissions
    tester_role = discord.utils.get(interaction.guild.roles, name=ROLES['tester'])
    if not tester_role or tester_role not in interaction.user.roles:
        await interaction.response.send_message(
            "You need the Tester role to use this command.",
            ephemeral=True
        )
        return
    
    region = region.upper()
    if region not in REGIONS:
        await interaction.response.send_message(
            f"Invalid region. Use one of: {', '.join(REGIONS)}",
            ephemeral=True
        )
        return
    
    waitlist = bot.bot_data.get_guild_waitlist(interaction.guild.id, region)
    if not waitlist:
        await interaction.response.send_message(
            f"The **{region}** waitlist is empty.",
            ephemeral=True
        )
        return
    
    # Prendre le premier de la liste
    next_user_id = waitlist[0]
    next_user = interaction.guild.get_member(next_user_id)
    
    if not next_user:
        # L'utilisateur a quitté le serveur
        bot.bot_data.remove_from_waitlist(interaction.guild.id, region, next_user_id)
        await interaction.response.send_message(
            f"The next user in queue has left the server. Try again.",
            ephemeral=True
        )
        return
    
    # Retirer de la liste et marquer le testeur comme actif
    bot.bot_data.remove_from_waitlist(interaction.guild.id, region, next_user_id)
    bot.bot_data.set_active_tester(interaction.guild.id, interaction.user.id, region)
    
    # Réinitialiser la notification first-in-queue si la liste devient vide
    if len(waitlist) == 1:  # Elle sera vide après le retrait
        bot.bot_data.set_first_in_queue_notified(interaction.guild.id, region, False)
    
    embed = discord.Embed(
        title="Next Player",
        description=f"You are now testing with {next_user.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="Player", value=next_user.mention, inline=True)
    embed.add_field(name="Region", value=region, inline=True)
    embed.add_field(name="Remaining in Queue", value=len(waitlist) - 1, inline=True)
    embed.set_footer(text="Use /close when the test is complete")
    
    await interaction.response.send_message(embed=embed)
    
    # Notifier l'utilisateur
    try:
        await next_user.send(
            f"🎮 **Your turn!** {interaction.user.mention} is ready to test with you in **{region}**.\n"
            f"Please join the appropriate voice channel."
        )
    except:
        pass  # L'utilisateur a peut-être désactivé les DMs
    
    # Logger
    logs_channel = discord.utils.get(interaction.guild.text_channels, name=CHANNELS['logs'])
    if logs_channel:
        embed = discord.Embed(
            title="Test Started",
            description=f"{interaction.user.mention} started testing with {next_user.mention}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Region", value=region, inline=True)
        await logs_channel.send(embed=embed)

@bot.tree.command(name='close', description='[Tester] Close the testing session')
@app_commands.describe(
    previous_tier='Previous tier of the tested player',
    earned_tier='New tier earned by the player'
)
async def close(interaction: discord.Interaction, 
                previous_tier: str | None = None, 
                earned_tier: str | None = None):
    # Vérifier les permissions
    tester_role = discord.utils.get(interaction.guild.roles, name=ROLES['tester'])
    if not tester_role or tester_role not in interaction.user.roles:
        await interaction.response.send_message(
            "You need the Tester role to use this command.",
            ephemeral=True
        )
        return
    
    # Retirer le testeur de la liste des actifs
    bot.bot_data.remove_active_tester(interaction.guild.id, interaction.user.id)
    
    # Si des tiers sont fournis, afficher les résultats et fermer après 5 secondes
    if previous_tier and earned_tier:
        # Vérifier que les tiers sont valides
        if previous_tier not in TIERS or earned_tier not in TIERS:
            await interaction.response.send_message(
                f"Invalid tier. Use one of: {', '.join(TIERS)}",
                ephemeral=True
            )
            return
        
        # Créer l'embed de résultats
        embed = discord.Embed(
            title="🏆 Test Results",
            description="The testing session has been completed!",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Previous Tier", value=previous_tier, inline=True)
        embed.add_field(name="Earned Tier", value=earned_tier, inline=True)
        
        # Déterminer si c'est une progression
        prev_index = TIERS.index(previous_tier)
        earned_index = TIERS.index(earned_tier)
        
        if earned_index > prev_index:
            embed.add_field(
                name="Result", 
                value=f"✅ Promoted! (+{earned_index - prev_index} tier{'s' if earned_index - prev_index > 1 else ''})",
                inline=False
            )
        elif earned_index == prev_index:
            embed.add_field(name="Result", value="➡️ Maintained current tier", inline=False)
        else:
            embed.add_field(
                name="Result",
                value=f"⬇️ Demoted ({prev_index - earned_index} tier{'s' if prev_index - earned_index > 1 else ''})",
                inline=False
            )
        
        embed.set_footer(text="This channel will be closed in 5 seconds")
        
        await interaction.response.send_message(embed=embed)
        
        # Logger
        logs_channel = discord.utils.get(interaction.guild.text_channels, name=CHANNELS['logs'])
        if logs_channel:
            log_embed = discord.Embed(
                title="Test Completed",
                description=f"{interaction.user.mention} completed a testing session",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            log_embed.add_field(name="Previous Tier", value=previous_tier, inline=True)
            log_embed.add_field(name="Earned Tier", value=earned_tier, inline=True)
            await logs_channel.send(embed=log_embed)
        
        # Attendre 5 secondes puis fermer
        await asyncio.sleep(5)
        
        # Si c'est un thread ou un canal temporaire, le supprimer
        if isinstance(interaction.channel, discord.Thread):
            await interaction.channel.delete()
        elif interaction.channel.name.startswith('test-'):
            try:
                await interaction.channel.delete()
            except:
                pass  # Le canal n'est peut-être pas supprimable
    else:
        # Pas de paramètres, fermer immédiatement
        await interaction.response.send_message("✅ Testing session closed.", ephemeral=True)
        
        # Logger
        logs_channel = discord.utils.get(interaction.guild.text_channels, name=CHANNELS['logs'])
        if logs_channel:
            log_embed = discord.Embed(
                title="Test Session Closed",
                description=f"{interaction.user.mention} closed a testing session",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            await logs_channel.send(embed=log_embed)
        
        # Si c'est un thread ou un canal temporaire, le supprimer immédiatement
        if isinstance(interaction.channel, discord.Thread):
            await interaction.channel.delete()
        elif interaction.channel.name.startswith('test-'):
            try:
                await interaction.channel.delete()
            except:
                pass

@bot.tree.command(name='waitlist', description='[Admin] View the waitlist for a region')
@app_commands.describe(region='Region to view waitlist for')
async def view_waitlist(interaction: discord.Interaction, region: str):
    # Vérifier les permissions
    if not interaction.user.guild_permissions.administrator:
        tester_role = discord.utils.get(interaction.guild.roles, name=ROLES['tester'])
        if not tester_role or tester_role not in interaction.user.roles:
            await interaction.response.send_message(
                "You need Administrator permissions or the Tester role to use this command.",
                ephemeral=True
            )
            return
    
    region = region.upper()
    if region not in REGIONS:
        await interaction.response.send_message(
            f"Invalid region. Use one of: {', '.join(REGIONS)}",
            ephemeral=True
        )
        return
    
    waitlist = bot.bot_data.get_guild_waitlist(interaction.guild.id, region)
    
    if not waitlist:
        await interaction.response.send_message(
            f"The **{region}** waitlist is empty.",
            ephemeral=True
        )
        return
    
    # Créer la liste des utilisateurs
    description = ""
    for i, user_id in enumerate(waitlist[:25], 1):  # Limiter à 25 pour éviter les embeds trop longs
        user = interaction.guild.get_member(user_id)
        if user:
            description += f"{i}. {user.mention} ({user.name})\n"
        else:
            description += f"{i}. Unknown User (ID: {user_id})\n"
    
    if len(waitlist) > 25:
        description += f"\n*And {len(waitlist) - 25} more...*"
    
    embed = discord.Embed(
        title=f"Waitlist for {region}",
        description=description,
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.set_footer(text=f"Total: {len(waitlist)} players")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='clear_waitlist', description='[Admin] Clear a region waitlist')
@app_commands.describe(region='Region to clear waitlist for')
async def clear_waitlist(interaction: discord.Interaction, region: str):
    # Vérifier les permissions admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You need Administrator permissions to use this command.",
            ephemeral=True
        )
        return
    
    region = region.upper()
    if region not in REGIONS:
        await interaction.response.send_message(
            f"Invalid region. Use one of: {', '.join(REGIONS)}",
            ephemeral=True
        )
        return
    
    # Vider la liste
    guild_id = str(interaction.guild.id)
    if guild_id in bot.bot_data.data['waitlists']:
        if region in bot.bot_data.data['waitlists'][guild_id]:
            count = len(bot.bot_data.data['waitlists'][guild_id][region])
            bot.bot_data.data['waitlists'][guild_id][region] = []
            bot.bot_data.set_first_in_queue_notified(interaction.guild.id, region, False)
            bot.bot_data.save_data()
            
            await interaction.response.send_message(
                f"✅ Cleared **{count}** players from the **{region}** waitlist.",
                ephemeral=True
            )
            
            # Logger
            logs_channel = discord.utils.get(interaction.guild.text_channels, name=CHANNELS['logs'])
            if logs_channel:
                embed = discord.Embed(
                    title="Waitlist Cleared",
                    description=f"{interaction.user.mention} cleared the **{region}** waitlist",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                embed.add_field(name="Players Removed", value=count, inline=True)
                await logs_channel.send(embed=embed)
            return
    
    await interaction.response.send_message(
        f"The **{region}** waitlist is already empty.",
        ephemeral=True
    )

# ====== COMMANDES DE MODÉRATION ======









# ====== COMMANDES D'INFORMATION ======




# Lancer le bot
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN manquant: définis la variable d'environnement TOKEN.")
    bot.run(TOKEN)
