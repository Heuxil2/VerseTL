import discord
from discord.ext import commands
import os

# Configuration
TOKEN = os.environ.get('DISCORD_TOKEN')  # Token from Render environment variable

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

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} is connected!')
    print(f'Bot ready to add role {ROLE_TO_ADD}')

@bot.event
async def on_member_update(before, after):
    """Detects when a member receives a new role"""
    # Check if new roles have been added
    added_roles = set(after.roles) - set(before.roles)
    
    if added_roles:
        # Check if one of the added roles is in the list
        for role in added_roles:
            if role.id in REQUIRED_ROLES:
                # Get the role to add
                role_to_give = after.guild.get_role(ROLE_TO_ADD)
                
                if role_to_give and role_to_give not in after.roles:
                    try:
                        await after.add_roles(role_to_give)
                        print(f'Role {role_to_give.name} added to {after.name}')
                    except discord.Forbidden:
                        print(f'Error: Insufficient permissions to add role to {after.name}')
                    except Exception as e:
                        print(f'Error: {e}')
                break

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
async def info(ctx):
    """Displays bot information"""
    embed = discord.Embed(
        title="Bot Information",
        description="Automatic role assignment bot",
        color=discord.Color.blue()
    )
    embed.add_field(name="Monitored roles", value=f"{len(REQUIRED_ROLES)} roles", inline=True)
    embed.add_field(name="Role to add", value=f"<@&{ROLE_TO_ADD}>", inline=True)
    embed.add_field(name="Commands", value="`!verify_roles` - Check all members\n`!info` - Display this information", inline=False)
    
    await ctx.send(embed=embed)

# Start the bot
bot.run(TOKEN)
