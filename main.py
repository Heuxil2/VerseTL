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

# IDs of required roles
REQUIRED_ROLES = [
    1410039139805564928,
    1408061890441248788,
    1432163570757664778,
    1421342524596813955,
    1432038582318665890,
    1412240815274590208,
    1421317233413722133,
    1407179621950296196,
    1407096889954013305,
    1419404798561882212,
    1407111853997559919,
    1431068098429194311,
    1413275389589196862,
    1413275300908896316
]

# ID of the role to add
ROLE_TO_ADD = 1419413367222960148

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

@bot.event
async def on_member_join(member):
    """Send welcome message when a new member joins"""
    welcome_channel_id = 1442006827607789578
    channel = member.guild.get_channel(welcome_channel_id)
    
    if channel:
        # Create embed
        embed = discord.Embed(
            description=(
                f"🎉 Hey {member.mention}, welcome to **{member.guild.name}!** 🎉\n"
                "Glad you're here! To get started:\n"
                "- **Request a Test:** <#1441986636547231792>\n"
                "- **Ask for Support:** <#1441986636933103750>\n"
                "- **Report Staff Issues:** <#1441986636933103751>\n"
                "Take a look around, join the chats, and have fun! 🚀"
            ),
            color=0xCDB382
        )
        
        try:
            await channel.send(embed=embed)
            print(f'Welcome message sent for {member.name}')
        except Exception as e:
            print(f'Error sending welcome message: {e}')

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

@bot.tree.command(name="staffmovement", description="Announce a staff position change")
@app_commands.describe(
    user="The user who is changing position",
    old_position="Their previous role",
    new_position="Their new role",
    reason="Optional reason for the change"
)
@app_commands.checks.has_permissions(administrator=True)
async def staffmovement(
    interaction: discord.Interaction,
    user: discord.Member,
    old_position: discord.Role,
    new_position: discord.Role,
    reason: str = None
):
    """Announce a staff position change"""
    channel_id = 1441986637981548637
    ping_role_id = 1419360838208192542
    
    channel = interaction.guild.get_channel(channel_id)
    
    if not channel:
        await interaction.response.send_message("Channel not found!", ephemeral=True)
        return
    
    # Build the message
    message = f"{user.mention} **{old_position.name}** → **{new_position.name}**"
    
    if reason:
        message += f"\n**Reason:** {reason}"
    
    message += f"\n||<@&{ping_role_id}>||"
    
    try:
        await channel.send(message)
        await interaction.response.send_message(f"Staff movement announced for {user.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to send messages in that channel!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

@bot.tree.command(name="execute", description="Execute the bot function to add roles to eligible members")
@app_commands.checks.has_permissions(administrator=True)
async def execute(interaction: discord.Interaction):
    """Slash command to check and add the role to all eligible members"""
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
    
    # Fetch all members to ensure we have up-to-date data
    await interaction.guild.chunk()
    
    for member in interaction.guild.members:
        # Skip bots
        if member.bot:
            continue
            
        # Check if the member has at least one of the required roles
        member_role_ids = [role.id for role in member.roles]
        has_required_role = any(role_id in REQUIRED_ROLES for role_id in member_role_ids)
        
        if has_required_role and role_to_give not in member.roles:
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
    
    # Build result message
    result_message = f'Role added to **{count}** member(s)!'
    if errors > 0:
        result_message += f'\n**{errors}** error(s) occurred.'
        if error_details and len(error_details) <= 5:
            result_message += "\n\n**Errors:**\n" + "\n".join(error_details[:5])
        elif error_details:
            result_message += f"\n\n**First 5 errors:**\n" + "\n".join(error_details[:5])
    
    await interaction.followup.send(result_message)

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
@staffmovement.error
async def staffmovement_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need administrator permissions to use this command!", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred!", ephemeral=True)

@execute.error
async def execute_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need administrator permissions to use this command!", ephemeral=True)
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
