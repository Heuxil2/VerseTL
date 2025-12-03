import discord
from discord.ext import commands
from discord import app_commands
import os
from threading import Thread
from flask import Flask

# Configuration
TOKEN = os.getenv('TOKEN')

if not TOKEN:
    raise ValueError("TOKEN environment variable is not set!")

# IDs of required roles - UPDATED
REQUIRED_ROLES = [
    1442696049851502813,
    1442696049893314581,
    1442696049893314582
]

# ID of the role to add
ROLE_TO_ADD = 1442696049801035923

# ID of the role that can use commands
COMMAND_ROLE_ID = 1442696049893314582

# IDs of roles that can use format command
FORMAT_COMMAND_ROLES = [
    1442696049893314581,
    1442696049893314582,
    1442696049851502807,
    1442696049851502808
]

# Log channel ID
LOG_CHANNEL_ID = 1442696052493914334

# Voice channel ID for member count - REMPLACEZ None PAR L'ID DE VOTRE SALON VOCAL
MEMBER_COUNT_CHANNEL_ID = 1445585263014318110

# ID of the user who can enable/disable format commands
ADMIN_USER_ID = 836452038548127764

# Global variable to enable/disable format commands
format_enabled = True

# Required intents
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Flask app pour Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is active!"

@app.route('/health')
def health():
    return {"status": "online", "bot": str(bot.user) if bot.user else "connecting"}

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# Custom check function for commands
def has_command_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        command_role = interaction.guild.get_role(COMMAND_ROLE_ID)
        if command_role in interaction.user.roles:
            return True
        return False
    return app_commands.check(predicate)

# Custom check function for format command
def has_format_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        user_role_ids = [role.id for role in interaction.user.roles]
        if any(role_id in FORMAT_COMMAND_ROLES for role_id in user_role_ids):
            return True
        return False
    return app_commands.check(predicate)

# Custom check for the admin who can enable/disable format commands
def is_format_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == ADMIN_USER_ID
    return app_commands.check(predicate)

async def log_command_usage(guild, user, command_name, channel):
    """Log command usage to the log channel"""
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    
    try:
        embed = discord.Embed(
            title="Command Used",
            description=f"{user.mention} used the command `/{command_name}` in {channel.mention}.",
            color=0x2F3136,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"User ID: {user.id}")
        
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Error logging command: {e}")

async def update_member_count(guild):
    """Update the voice channel name with current member count"""
    if not MEMBER_COUNT_CHANNEL_ID:
        return
    
    channel = guild.get_channel(MEMBER_COUNT_CHANNEL_ID)
    if not channel:
        print(f"Member count channel not found!")
        return
    
    try:
        member_count = guild.member_count
        new_name = f"👥〡Users: {member_count}"
        
        if channel.name != new_name:
            await channel.edit(name=new_name)
            print(f"Updated member count channel to: {new_name}")
    except discord.Forbidden:
        print("Error: No permission to edit voice channel")
    except discord.HTTPException as e:
        print(f"Error updating member count channel: {e}")

@bot.event
async def on_ready():
    print(f'{bot.user} is connected!')
    print(f'Bot ready to add role {ROLE_TO_ADD}')
    
    # Set bot status and activity
    activity = discord.Game(name=".gg/vanillatiers")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print('Status set to: .gg/vanillatiers')
    
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} slash command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')
    
    # Update member count on startup
    for guild in bot.guilds:
        await update_member_count(guild)

@bot.event
async def on_member_join(member):
    """Send welcome message when a new member joins"""
    welcome_channel_id = 1445596176039678164
    channel = member.guild.get_channel(welcome_channel_id)
    
    if channel:
        # Create embed
        embed = discord.Embed(
            description=(
                f"Hey {member.mention}, welcome to **{member.guild.name}!**\n"
                "Glad you're here! To get started:\n"
                "- **Request a test:** <#1442696050841354269>\n"
                "- **Ask for support:** <#1442696051361320996>\n"
                "- **Apply for staff/tester:** <#1442696051361320998>\n"
                "Take a look around, join the chats, and have fun!"
            ),
            color=0xCDB382
        )
        
        try:
            await channel.send(embed=embed)
            print(f'Welcome message sent for {member.name}')
        except Exception as e:
            print(f'Error sending welcome message: {e}')
    
    # Update member count
    await update_member_count(member.guild)

@bot.event
async def on_member_remove(member):
    """Update member count when a member leaves"""
    await update_member_count(member.guild)

@bot.event
async def on_member_update(before, after):
    """Detects when a member receives or loses a role"""
    # Check if roles have changed
    added_roles = set(after.roles) - set(before.roles)
    removed_roles = set(before.roles) - set(after.roles)
    
    role_to_give = after.guild.get_role(ROLE_TO_ADD)
    if not role_to_give:
        return
    
    # Check if a required role was added
    if added_roles:
        for role in added_roles:
            if role.id in REQUIRED_ROLES:
                if role_to_give not in after.roles:
                    try:
                        await after.add_roles(role_to_give, reason="User received a required role")
                        print(f'Role {role_to_give.name} added to {after.name}')
                    except discord.Forbidden:
                        print(f'Error: Insufficient permissions to add role to {after.name}')
                    except Exception as e:
                        print(f'Error adding role to {after.name}: {e}')
                break
    
    # Check if a required role was removed AND user has no other required roles
    if removed_roles:
        for role in removed_roles:
            if role.id in REQUIRED_ROLES:
                # Check if user still has any required roles
                member_role_ids = [r.id for r in after.roles]
                has_any_required_role = any(role_id in REQUIRED_ROLES for role_id in member_role_ids)
                
                # If they don't have any required roles anymore, remove the special role
                if not has_any_required_role and role_to_give in after.roles:
                    try:
                        await after.remove_roles(role_to_give, reason="User no longer has any required roles")
                        print(f'Role {role_to_give.name} removed from {after.name}')
                    except discord.Forbidden:
                        print(f'Error: Insufficient permissions to remove role from {after.name}')
                    except Exception as e:
                        print(f'Error removing role from {after.name}: {e}')
                break

@bot.tree.command(name="enableformat", description="Enable format commands")
@is_format_admin()
async def enableformat(interaction: discord.Interaction):
    """Enable format commands"""
    global format_enabled
    
    if format_enabled:
        await interaction.response.send_message("Format commands are already enabled!", ephemeral=True)
        return
    
    format_enabled = True
    await interaction.response.send_message("✅ Format commands have been **enabled**!", ephemeral=True)
    print(f"Format commands enabled by {interaction.user.name}")

@bot.tree.command(name="disableformat", description="Disable format commands")
@is_format_admin()
async def disableformat(interaction: discord.Interaction):
    """Disable format commands"""
    global format_enabled
    
    if not format_enabled:
        await interaction.response.send_message("Format commands are already disabled!", ephemeral=True)
        return
    
    format_enabled = False
    await interaction.response.send_message("🚫 Format commands have been **disabled**!", ephemeral=True)
    print(f"Format commands disabled by {interaction.user.name}")

@bot.tree.command(name="execute", description="Execute the bot function to add roles to eligible members")
@has_command_role()
async def execute(interaction: discord.Interaction):
    """Slash command to check and add the role to all eligible members"""
    # Log command usage
    await log_command_usage(interaction.guild, interaction.user, "execute", interaction.channel)
    
    await interaction.response.defer(ephemeral=True)
    
    role_to_give = interaction.guild.get_role(ROLE_TO_ADD)
    
    if not role_to_give:
        await interaction.followup.send("The role to add does not exist!")
        return
    
    # Check bot permissions
    bot_member = interaction.guild.get_member(bot.user.id)
    if not bot_member.guild_permissions.manage_roles:
        await interaction.followup.send("I don't have the 'Manage Roles' permission!")
        return
    
    # Check if bot's role is high enough
    if role_to_give >= bot_member.top_role:
        await interaction.followup.send(f"My role is not high enough to assign {role_to_give.mention}! Please move my role above it in the server settings.")
        return
    
    count = 0
    errors = 0
    error_details = []
    eligible_count = 0
    
    # Send initial status
    await interaction.followup.send("Fetching all members... This may take a moment.")
    
    # Fetch all members to ensure we have up-to-date data
    try:
        members = []
        async for member in interaction.guild.fetch_members(limit=None):
            members.append(member)
        print(f"Fetched {len(members)} members from guild")
    except Exception as e:
        print(f"Error fetching members: {e}")
        members = interaction.guild.members
        print(f"Using cached members: {len(members)}")
    
    # Debug: Check required roles
    print(f"Required role IDs: {REQUIRED_ROLES}")
    print(f"Role to add ID: {ROLE_TO_ADD}")
    
    for member in members:
        # Skip bots
        if member.bot:
            continue
            
        # Check if the member has at least one of the required roles
        member_role_ids = [role.id for role in member.roles]
        has_required_role = any(role_id in REQUIRED_ROLES for role_id in member_role_ids)
        
        if has_required_role:
            eligible_count += 1
            print(f"{member.name} is eligible (has required role)")
            
            if role_to_give not in member.roles:
                print(f"Attempting to add role to {member.name}")
                try:
                    await member.add_roles(role_to_give, reason="Automatic role assignment via /execute")
                    count += 1
                    print(f'Role added to {member.name}')
                except discord.Forbidden:
                    errors += 1
                    error_details.append(f"{member.name}: Permission denied")
                    print(f'Permission denied for {member.name}')
                except discord.HTTPException as e:
                    errors += 1
                    error_details.append(f"{member.name}: {str(e)}")
                    print(f'HTTP error for {member.name}: {e}')
                except Exception as e:
                    errors += 1
                    error_details.append(f"{member.name}: {str(e)}")
                    print(f'Error for {member.name}: {e}')
            else:
                print(f"{member.name} already has the role")
    
    # Build result message
    result_message = f'**Scan Complete!**\n\n'
    result_message += f'Eligible members found: **{eligible_count}**\n'
    result_message += f'Role added to: **{count}** member(s)\n'
    
    if errors > 0:
        result_message += f'\n**{errors}** error(s) occurred.'
        if error_details and len(error_details) <= 10:
            result_message += "\n\n**Errors:**\n" + "\n".join(error_details[:10])
        elif error_details:
            result_message += f"\n\n**First 10 errors:**\n" + "\n".join(error_details[:10])
    
    await interaction.edit_original_response(content=result_message)

@bot.command()
@commands.has_permissions(administrator=True)
async def verify_roles(ctx):
    """Command to check and add the role to all eligible members"""
    role_to_give = ctx.guild.get_role(ROLE_TO_ADD)
    
    if not role_to_give:
        await ctx.send("The role to add does not exist!")
        return
    
    count = 0
    for member in ctx.guild.members:
        # Check if the member has at least one of the required roles
        member_role_ids = [role.id for role in member.roles]
        has_required_role = any(role_id in REQUIRED_ROLES for role_id in member_role_ids)
        
        if has_required_role and role_to_give not in member.roles:
            try:
                await member.add_roles(role_to_give)
                count += 1
            except Exception as e:
                print(f'Error for {member.name}: {e}')
    
    await ctx.send(f'Role added to {count} member(s)!')

@bot.tree.command(name="format", description="Generate test result format based on channel name")
@has_format_role()
async def format_slash(interaction: discord.Interaction):
    """Generate test result format"""
    # Check if format is enabled
    if not format_enabled:
        await interaction.response.send_message("This command is currently disabled.", ephemeral=True)
        return
    
    # Log command usage
    await log_command_usage(interaction.guild, interaction.user, "format", interaction.channel)
    
    channel_name = interaction.channel.name.lower()
    
    # Parse channel name (tier-player-region)
    parts = channel_name.split('-')
    
    if len(parts) < 3:
        await interaction.response.send_message(
            "Invalid channel name format! Expected: `(tier)-(player)-(region)`\n"
            "Example: `ht3-heuxil-eu`",
            ephemeral=True
        )
        return
    
    tier = parts[0]
    player = parts[1]
    region = parts[2]
    
    # Validate tier
    valid_tiers = ['ht1', 'lt1', 'ht2', 'lt2', 'ht3']
    if tier not in valid_tiers:
        await interaction.response.send_message(
            f"Invalid tier: `{tier}`\n"
            f"Valid tiers: {', '.join(valid_tiers)}",
            ephemeral=True
        )
        return
    
    # Validate region
    valid_regions = ['na', 'eu', 'as']
    if region not in valid_regions:
        await interaction.response.send_message(
            f"Invalid region: `{region}`\n"
            f"Valid regions: {', '.join(valid_regions)}",
            ephemeral=True
        )
        return
    
    # Generate format based on tier
    ping_role_id = 1442696049402712220
    
    if tier == 'ht3':
        message = f"@testee - ign - **Failed/Passed High Tier 3**\n*Passed Evaluation*\n\n"
        message += f"**__HT3 Fights:__**\n"
        message += f"> Lost/won ft3 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'lt2':
        message = f"@testee - ign - **Failed/Passed Low Tier 2**\n\n"
        message += f"**__LT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__HT3 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'ht2':
        message = f"@testee - ign - **Failed/Passed High Tier 2**\n\n"
        message += f"**__HT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__LT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'lt1':
        message = f"@testee - ign - **Failed/Passed Low Tier 1**\n\n"
        message += f"**__LT1 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__HT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'ht1':
        message = f"@testee - ign - **Failed/Passed High Tier 1**\n\n"
        message += f"**__HT1 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__LT1 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    try:
        await interaction.response.send_message(message)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

@bot.command(name='format')
async def format_command(ctx):
    """Generate test result format (prefix command)"""
    # Check if format is enabled
    if not format_enabled:
        await ctx.send("This command is currently disabled.", delete_after=5)
        return
    
    # Check if user has any of the required roles
    user_role_ids = [role.id for role in ctx.author.roles]
    has_required_role = any(role_id in FORMAT_COMMAND_ROLES for role_id in user_role_ids)
    
    if not has_required_role:
        await ctx.send("You don't have the required role to use this command!", delete_after=5)
        return
    
    # Log command usage
    await log_command_usage(ctx.guild, ctx.author, "format", ctx.channel)
    
    channel_name = ctx.channel.name.lower()
    
    # Parse channel name (tier-player-region)
    parts = channel_name.split('-')
    
    if len(parts) < 3:
        await ctx.send(
            "Invalid channel name format! Expected: `(tier)-(player)-(region)`\n"
            "Example: `ht3-feardesto-eu`"
        )
        return
    
    tier = parts[0]
    player = parts[1]
    region = parts[2]
    
    # Validate tier
    valid_tiers = ['ht1', 'lt1', 'ht2', 'lt2', 'ht3']
    if tier not in valid_tiers:
        await ctx.send(
            f"Invalid tier: `{tier}`\n"
            f"Valid tiers: {', '.join(valid_tiers)}"
        )
        return
    
    # Validate region
    valid_regions = ['na', 'eu', 'as']
    if region not in valid_regions:
        await ctx.send(
            f"Invalid region: `{region}`\n"
            f"Valid regions: {', '.join(valid_regions)}"
        )
        return
    
    # Generate format based on tier
    ping_role_id = 1419360899709272176
    
    if tier == 'ht3':
        message = f"@testee - ign - **Failed/Passed High Tier 3**\n*Passed Evaluation*\n\n"
        message += f"**__HT3 Fights:__**\n"
        message += f"> Lost/won ft3 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'lt2':
        message = f"@testee - ign - **Failed/Passed Low Tier 2**\n\n"
        message += f"**__LT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__HT3 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'ht2':
        message = f"@testee - ign - **Failed/Passed High Tier 2**\n\n"
        message += f"**__HT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__LT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'lt1':
        message = f"@testee - ign - **Failed/Passed Low Tier 1**\n\n"
        message += f"**__LT1 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__HT2 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    elif tier == 'ht1':
        message = f"@testee - ign - **Failed/Passed High Tier 1**\n\n"
        message += f"**__HT1 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"**__LT1 Fights:__**\n"
        message += f"> Lost/won ft4 vs **IGN**\n"
        message += f"> Lost/won ft4 vs **IGN**\n\n"
        message += f"<@&{ping_role_id}>"
    
    try:
        await ctx.send(message)
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def sync(ctx):
    """Sync slash commands"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f'Synced {len(synced)} command(s)!')
    except Exception as e:
        await ctx.send(f'Failed to sync: {e}')

# Error handling for slash commands
@enableformat.error
async def enableformat_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            else:
                await interaction.followup.send("You don't have permission to use this command!", ephemeral=True)
        except:
            print(f"Could not send error message for enableformat")

@disableformat.error
async def disableformat_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
            else:
                await interaction.followup.send("You don't have permission to use this command!", ephemeral=True)
        except:
            print(f"Could not send error message for disableformat")

@format_slash.error
async def format_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("You don't have the required role to use this command!", ephemeral=True)
            else:
                await interaction.followup.send("You don't have the required role to use this command!", ephemeral=True)
        except discord.errors.NotFound:
            print(f"Interaction expired for format command by user {interaction.user.name}")
        except Exception as e:
            print(f"Could not send error message for format: {e}")
    else:
        print(f"Format command error: {type(error).__name__}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"An error occurred: {type(error).__name__}", ephemeral=True)
            else:
                await interaction.followup.send(f"An error occurred: {type(error).__name__}", ephemeral=True)
        except:
            print("Failed to send error message to user")

@execute.error
async def execute_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message("You don't have the required role to use this command!", ephemeral=True)
        else:
            await interaction.followup.send("You don't have the required role to use this command!", ephemeral=True)
    else:
        # Log the full error for debugging
        print(f"Execute command error: {type(error).__name__}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"An error occurred: {type(error).__name__}", ephemeral=True)
            else:
                await interaction.followup.send(f"An error occurred: {type(error).__name__}", ephemeral=True)
        except:
            print("Failed to send error message to user")

# Start Flask server in background
keep_alive()

# Start the bot
try:
    bot.run(TOKEN)
except Exception as e:
    print(f'Failed to start bot: {e}')
    raise
