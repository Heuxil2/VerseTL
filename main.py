await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="Display user information")
@app_commands.describe(member="Member to get info about (yourself if not specified)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    if not await check_authorization(interaction):
        return
    
    if member is None:
        member = interaction.user

    embed = discord.Embed(title=f"👤 User Info - {member}", color=member.color)
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
    if not await check_authorization(interaction):
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
        await interaction.response.send_message("📊 No activities detected among server members.")
        return

    embed = discord.Embed(title="🎮 Server Activity Stats", color=discord.Colour.purple())

    sorted_activities = sorted(activities.items(), key=lambda x: x[1], reverse=True)[:10]
    for activity, count in sorted_activities:
        embed.add_field(name=activity, value=f"{count} member(s)", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="channel_stats", description="Show channel statistics")
async def channel_stats(interaction: discord.Interaction):
    if not await check_authorization(interaction):
        return
    
    guild = interaction.guild
    embed = discord.Embed(title="📈 Channel Statistics", color=discord.Colour.orange())

    embed.add_field(name="💬 Text Channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="🔊 Voice Channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="📁 Categories", value=len(guild.categories), inline=True)
    embed.add_field(name="📺 Stage Channels", value=len(guild.stage_channels), inline=True)
    embed.add_field(name="🎙️ Forum Channels", value=len([c for c in guild.channels if isinstance(c, discord.ForumChannel)]), inline=True)
    embed.add_field(name="📊 Total Channels", value=len(guild.channels), inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="commands", description="Show all available commands")
async def commands_list(interaction: discord.Interaction):
    if not await check_authorization(interaction):
        return
    
    embed = discord.Embed(title="📜 Available Commands", color=discord.Colour.green())

    # Authorization Commands (only for owner)
    if interaction.user.id == OWNER_ID:
        embed.add_field(name="🔑 **Authorization Commands (Owner Only)**", value="""
`/autorise` - Autoriser le bot sur ce serveur
`/desautorise` - Désautoriser le bot sur ce serveur
""", inline=False)

    # Waitlist Commands
    embed.add_field(name="🎯 **Waitlist Commands**", value="""
`/leave` - Leave all waitlists you're currently in
`/startqueue [channel]` - Start the queue for testing (Tester role)
`/stopqueue [channel]` - Remove yourself from active testers (Tester role)
`/nextuser [channel]` - Create private channel for next person (Tester role)
`/passeval` - Transfer eval channel to High Eval category (Tester role)
`/close` - Close an eval channel (Tester role)
`/results` - Post tier test results (Tester role)
""", inline=False)

    # Moderation Commands
    embed.add_field(name="🛡️ **Moderation Commands**", value="""
`/ban @user [reason]` - Ban a member
`/kick @user [reason]` - Kick a member
`/mute @user [reason]` - Mute a member
`/unmute @user` - Unmute a member
`/warn @user [reason]` - Warn a member
`/purge [number]` - Delete recent messages
""", inline=False)

    # Channel Management
    embed.add_field(name="📺 **Channel Management**", value="""
`/slowmode [seconds]` - Set channel slowmode
`/lockdown [channel]` - Lock a channel
`/unlock [channel]` - Unlock a channel
""", inline=False)

    # Role Management
    embed.add_field(name="🎭 **Role Management**", value="""
`/assign_role_to_all [role]` - Assign role to all members
`/remove_role_from_all [role]` - Remove role from all members
""", inline=False)

    # Information Commands
    embed.add_field(name="📊 **Information Commands**", value="""
`/serverinfo` - Display server information
`/userinfo [@user]` - Display user information
`/activity` - Show server activity statistics
`/channel_stats` - Show channel statistics
`/logs [limit]` - Show recent server logs
""", inline=False)

    # Utility
    embed.add_field(name="💾 **Utility**", value="""
`/info` - Bot creator and info
`/support` - Get support server link
""", inline=False)

    await interaction.response.send_message(embed=embed)

# === HELPER FUNCTIONS ===

class WaitlistModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Enter Waitlist - VerseTL")

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
        # Check if user is on cooldown with Booster role verification
        user_id = interaction.user.id
        if user_id in user_test_cooldowns:
            cooldown_time = user_test_cooldowns[user_id]
            current_time = datetime.datetime.now()
            time_remaining = cooldown_time - current_time

            if time_remaining.total_seconds() > 0:
                days = time_remaining.days
                hours = time_remaining.seconds // 3600
                minutes = (time_remaining.seconds % 3600) // 60

                # Display the type of cooldown in the message
                is_booster = has_booster_role(interaction.user)
                cooldown_type = "Booster (2 days)" if is_booster else "Regular (4 days)"

                cooldown_embed = discord.Embed(
                    title="⏰ Cooldown Active",
                    description=f"You must wait **{days} days, {hours} hours, and {minutes} minutes** before you can request another test.\n\n**Cooldown Type:** {cooldown_type}",
                    color=0xff0000
                )
                cooldown_embed.set_footer(text=f"Cooldown expires after {BOOSTER_COOLDOWN_DAYS if is_booster else REGULAR_COOLDOWN_DAYS} days from your last test")

                await interaction.response.send_message(embed=cooldown_embed, ephemeral=True)
                return
            else:
                # Automatically clean up expired cooldowns
                del user_test_cooldowns[user_id]
                save_user_cooldowns()
                print(f"DEBUG: Removed expired cooldown for user {user_id}")

        # Check if user already has an active testing session
        if user_id in active_testing_sessions:
            existing_channel_id = active_testing_sessions[user_id]
            existing_channel = interaction.guild.get_channel(existing_channel_id)

            if existing_channel:
                await interaction.response.send_message(
                    f"⚠️ You already have an active testing session in {existing_channel.mention}. Please complete that test first.",
                    ephemeral=True
                )
                return
            else:
                # Channel was deleted but still tracked, clean it up
                del active_testing_sessions[user_id]

        region_input = self.region.value.lower().strip()

        # Validate region
        valid_regions = ["na", "eu", "as", "au"]
        if region_input not in valid_regions:
            await interaction.response.send_message(
                "Invalid region. Please use NA, EU, AS, or AU.",
                ephemeral=True)
            return

        # Check if user is already in any waitlist
        user_regions = []
        for region, queue in waitlists.items():
            if interaction.user.id in queue:
                user_regions.append(region)

        # Also check if user already has submitted a form
        if interaction.user.id in user_info:
            existing_region = user_info[interaction.user.id]["region"].lower()
            await interaction.response.send_message(
                f"You have already submitted a form for the {existing_region.upper()} region. Visit <#waitlist-{existing_region}> to join the queue.",
                ephemeral=True)
            return

        if user_regions:
            if len(user_regions) == 1:
                existing_region = user_regions[0]
                await interaction.response.send_message(
                    f"You're already in a waitlist. Visit <#waitlist-{existing_region}> to see your position.",
                    ephemeral=True)
            else:
                regions_channels = ", ".join([f"<#waitlist-{region}>" for region in user_regions])
                await interaction.response.send_message(
                    f"You're already in multiple waitlists: {regions_channels}",
                    ephemeral=True)
            return

        # Store user information BUT DON'T ADD TO QUEUE YET
        user_info[interaction.user.id] = {
            "ign": self.minecraft_ign.value,
            "server": self.minecraft_server.value,
            "region": region_input.upper()
        }

        # Give waitlist role (with permission check)
        waitlist_role = discord.utils.get(
            interaction.guild.roles,
            name=f"Waitlist-{region_input.upper()}")
        if waitlist_role and waitlist_role < interaction.guild.me.top_role:
            try:
                await interaction.user.add_roles(waitlist_role)
            except discord.Forbidden:
                pass

        # Give matchmaking role (with permission check)
        matchmaking_role = discord.utils.get(
            interaction.guild.roles,
            name=f"{region_input.upper()} Matchmaking")
        if matchmaking_role and matchmaking_role < interaction.guild.me.top_role:
            try:
                await interaction.user.add_roles(matchmaking_role)
            except discord.Forbidden:
                pass

        # Display the type of cooldown in the confirmation message
        is_booster = has_booster_role(interaction.user)
        cooldown_info = f"\n\n💎 **Booster Perk:** You have a {BOOSTER_COOLDOWN_DAYS}-day cooldown instead of {REGULAR_COOLDOWN_DAYS} days!" if is_booster else f"\n\n⏰ **Cooldown:** {REGULAR_COOLDOWN_DAYS} days after test completion."

        # Send confirmation message
        embed = discord.Embed(
            description=f"✅ Form submitted successfully! You now have access to <#waitlist-{region_input}>.\n\n**Next step:** Go to <#waitlist-{region_input}> and click \"Join Queue\" to enter the testing queue.{cooldown_info}",
            color=discord.Color.green())
        embed.set_footer(text="Only you can see this • Dismiss message")

        await interaction.response.send_message(embed=embed, ephemeral=True)

def get_region_from_channel(channel_name: str):
    print(f"DEBUG: get_region_from_channel called with: {channel_name}")
    channel_lower = channel_name.lower()

    # Check for exact matches ONLY
    for key in waitlists:
        expected_name = f"waitlist-{key}"
        print(f"DEBUG: Comparing '{channel_lower}' with '{expected_name}'")
        if channel_lower == expected_name:
            print(f"DEBUG: Found exact match for region: {key}")
            return key

    print(f"DEBUG: No region found for channel: {channel_name}")
    return None

async def update_waitlist_message(guild: discord.Guild, region: str):
    global last_test_session

    channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
    if not channel:
        print(f"DEBUG: Channel waitlist-{region} not found")
        return

    # Only display testers who have done /startqueue AND who are online
    tester_ids = []
    # We check first if the queue is open AND if there are active testers
    if region in opened_queues:
        for tester_id in active_testers[region]:
            member = guild.get_member(tester_id)
            if member and member.status != discord.Status.offline:
                tester_ids.append(tester_id)

    queue_display = "\n".join(
        [f"{i+1}. <@{uid}>"
         for i, uid in enumerate(waitlists[region])]) or "*No one in queue*"
    testers_display = "\n".join(
        [f"{i+1}. <@{uid}>"
         for i, uid in enumerate(tester_ids)]) or "*No testers online*"

    # Use region-specific timestamp
    region_last_active = last_region_activity.get(region)
    timestamp = region_last_active.strftime(
        "%B %d, %Y %I:%M %p") if region_last_active else "Never"

    # Check if queue is opened and has testers
    if region in opened_queues and tester_ids:
        color = discord.Color.from_rgb(220, 80, 120)  # More red-tinted pink
        description = (
            f"**Tester(s) Available!**\n\n"
            f"Use /leave if you wish to be removed from the waitlist or queue.\n"
            f"**Queue**\n{queue_display}\n\n"
            f"**Testers**\n{testers_display}")
        show_button = True
        ping_content = "@here"
    else:
        # Queue is not opened OR no testers available
        color = discord.Color(15880807)  # Color from your example
        description = (
            f"No testers for your region are available at this time.\n"
            f"You will be pinged when a tester is available.\n"
            f"Check back later!\n\n"
            f"Last Test At: {timestamp}")
        show_button = False
        ping_content = None

    embed = discord.Embed(description=description, color=color)
    
    # Add author field for No Testers Online embed
    if not (region in opened_queues and tester_ids):
        embed.set_author(
            name="[1.21+] VerseTL",
            icon_url="https://upnow-prod.ff45e40d1a1c8f7e7de4e976d0c9e555.r2.cloudflarestorage.com/dzbRgzDeFWeXAQx0Q8EGh5FXSiF3/0670e4c9-d8d3-4f25-85cc-03717121a17d?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=2f488bd324502ec20fee5b40e9c9ed39%2F20250812%2Fauto%2Fs3%2Faws4_request&X-Amz-Date=20250812T161311Z&X-Amz-Expires=43200&X-Amz-Signature=7a14dab019355ab773cf5eb1c049322c48030aeb575ccd744d534081b61291b5&X-Amz-SignedHeaders=host&response-content-disposition=attachment%3B%20filename%3D%22bigger%20version%20Verse%20ranked%20logo.png%22"
        )
        embed.title = "No Testers Online"

    view = discord.ui.View()
    if show_button:
        view.add_item(
            discord.ui.Button(label="Join Queue",
                              style=discord.ButtonStyle.primary,
                              custom_id="open_form"))

    # Improved message management to prevent duplicates
    try:
        # Check if we have a stored message object that's still valid
        if region in waitlist_messages:
            try:
                stored_message = waitlist_messages[region]
                # Try to edit the stored message object directly
                await stored_message.edit(content=ping_content, embed=embed, view=view)
                print(f"DEBUG: Successfully edited stored message object for {region}")
                return
            except (discord.NotFound, discord.HTTPException) as e:
                print(f"DEBUG: Stored message object invalid for {region}: {e}")
                # Remove the invalid stored message
                del waitlist_messages[region]
                if region in waitlist_message_ids:
                    del waitlist_message_ids[region]

        # If we have a message ID but no stored object, try to fetch and store it
        if region in waitlist_message_ids:
            try:
                message_id = waitlist_message_ids[region]
                fetched_message = await channel.fetch_message(message_id)
                waitlist_messages[region] = fetched_message  # Store the message object
                await fetched_message.edit(content=ping_content, embed=embed, view=view)
                print(f"DEBUG: Successfully fetched and edited message {message_id} for {region}")
                return
            except discord.NotFound:
                print(f"DEBUG: Message ID {waitlist_message_ids[region]} not found for {region}")
                del waitlist_message_ids[region]
            except Exception as e:
                print(f"DEBUG: Error fetching message for {region}: {e}")
                if region in waitlist_message_ids:
                    del waitlist_message_ids[region]

        # If we get here, we need to find or create a message
        # Look for existing bot messages in the channel (limited to recent messages)
        existing_message = None
        async for message in channel.history(limit=10):  # Reduced limit to prevent conflicts
            if message.author == bot.user and message.embeds:
                existing_message = message
                break

        if existing_message:
            # Found an existing bot message, store and edit it
            waitlist_messages[region] = existing_message
            waitlist_message_ids[region] = existing_message.id
            await existing_message.edit(content=ping_content, embed=embed, view=view)
            print(f"DEBUG: Found and edited existing message {existing_message.id} for {region}")

            # Clean up other bot messages in the channel
            message_count = 0
            async for message in channel.history(limit=20):
                if message.author == bot.user and message.id != existing_message.id:
                    try:
                        await message.delete()
                        message_count += 1
                        if message_count >= 3:  # Limit cleanup to avoid rate limits
                            break
                    except:
                        pass
        else:
            # No existing message found, create a new one (this should be rare)
            new_message = await channel.send(content=ping_content, embed=embed, view=view)
            waitlist_messages[region] = new_message
            waitlist_message_ids[region] = new_message.id
            print(f"DEBUG: Created new message {new_message.id} for {region}")

    except Exception as e:
        print(f"DEBUG: Error in update_waitlist_message for {region}: {e}")

async def log_queue_join(guild: discord.Guild, user: discord.Member, region: str, position: int):
    """Log when a user joins a queue to the logs channel in Staff category"""
    try:
        # Find the Staff category
        staff_category = discord.utils.get(guild.categories, name="Staff")
        if not staff_category:
            staff_category = discord.utils.get(guild.categories, name="STAFF")

        if not staff_category:
            print("DEBUG: Staff category not found for logging")
            return

        # Find the logs channel in the Staff category
        logs_channel = None
        for channel in staff_category.text_channels:
            if "logs" in channel.name.lower():
                logs_channel = channel
                break

        if not logs_channel:
            print("DEBUG: Logs channel not found in Staff category")
            return

        # Get user information if available
        user_data = user_info.get(user.id, {})
        ign = user_data.get('ign', 'N/A')
        server = user_data.get('server', 'N/A')

        # Get the type of cooldown for the user
        is_booster = has_booster_role(user)
        cooldown_type = f"Booster ({BOOSTER_COOLDOWN_DAYS} days)" if is_booster else f"Regular ({REGULAR_COOLDOWN_DAYS} days)"

        # Create log embed
        embed = discord.Embed(
            title="📋 Queue Join Log",
            description=f"{user.mention} joined the {region.upper()} testing queue",
            color=0x00ff00,  # Green color
            timestamp=datetime.datetime.now()
        )

        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}` (ID: {user.id})", inline=True)
        embed.add_field(name="Region", value=region.upper(), inline=True)
        embed.add_field(name="Position", value=f"#{position}", inline=True)
        embed.add_field(name="IGN", value=ign, inline=True)
        embed.add_field(name="Preferred Server", value=server, inline=True)
        embed.add_field(name="Cooldown Type", value=cooldown_type, inline=True)
        embed.add_field(name="Account Created", value=user.created_at.strftime("%Y-%m-%d"), inline=True)

        # Add visual indicator for boosters
        if is_booster:
            embed.add_field(name="Special Status", value="💎 **Booster**", inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Queue Join Log", icon_url=guild.icon.url if guild.icon else None)

        await logs_channel.send(embed=embed)
        print(f"DEBUG: Logged queue join for {user.name} ({cooldown_type}) in {region.upper()} region")

    except Exception as e:
        print(f"DEBUG: Error logging queue join: {e}")

async def update_leaderboard(guild: discord.Guild):
    """Update the tester leaderboard in the testing-leaderboard channel"""
    leaderboard_channel = discord.utils.get(guild.text_channels, name="🏅┃testing-leaderboard")
    if not leaderboard_channel:
        print("DEBUG: Leaderboard channel not found")
        return

    # Sort testers by test count (descending) and take top 10
    sorted_testers = sorted(tester_stats.items(), key=lambda x: x[1], reverse=True)[:10]

    # Create leaderboard embed
    embed = discord.Embed(
        color=0x2f3136  # Dark gray color to match Discord's dark theme
    )

    # Add title as description with custom formatting
    embed.description = "## 🏆 **Top Testers Leaderboard**\n*Ranking of the most active testers*"

    if not sorted_testers:
        embed.add_field(
            name="",
            value="```\n📊 RANKING\n\n⚠️  No tests performed yet\n```",
            inline=False
        )
    else:
        # Create the leaderboard text with formatting
        leaderboard_text = "```\n📊 RANKING\n\n"

        for i, (tester_id, test_count) in enumerate(sorted_testers):
            member = guild.get_member(tester_id)
            if member:
                # Format rank with proper spacing
                rank_display = f"{i+1:2d}."
                username = member.display_name[:20]  # Limit username length
                tests_display = f"{test_count} test{'s' if test_count > 1 else ''}"

                leaderboard_text += f"{rank_display} {username:<20} {tests_display}\n"

        leaderboard_text += "```"

        embed.add_field(
            name="",
            value=leaderboard_text,
            inline=False
        )

    # Add footer with last update time
    embed.set_footer(
        text=f"Last updated: {datetime.datetime.now().strftime('%m/%d/%Y at %H:%M')}",
        icon_url="https://cdn.discordapp.com/emojis/1234567890123456789.png"  # Optional: add a small icon
    )

    try:
        # Better leaderboard message management
        existing_message = None
        async for message in leaderboard_channel.history(limit=10):
            if message.author == guild.me and message.embeds:
                if "Top Testers Leaderboard" in str(message.embeds[0].description):
                    existing_message = message
                    break

        if existing_message:
            await existing_message.edit(embed=embed)
            print("DEBUG: Updated existing leaderboard message")

            # Clean up any duplicate leaderboard messages
            message_count = 0
            async for message in leaderboard_channel.history(limit=20):
                if (message.author == guild.me and message.embeds and 
                    message.id != existing_message.id and 
                    "Top Testers Leaderboard" in str(message.embeds[0].description)):
                    try:
                        await message.delete()
                        message_count += 1
                        if message_count >= 3:
                            break
                    except:
                        pass
        else:
            # Create new leaderboard message
            await leaderboard_channel.send(embed=embed)
            print("DEBUG: Created new leaderboard message")

    except Exception as e:
        print(f"DEBUG: Error updating leaderboard: {e}")

async def create_initial_waitlist_message(guild: discord.Guild, region: str):
    """Create the initial waitlist message and store references to it"""
    channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
    if not channel:
        return

    # Create the initial embed content with region-specific timestamp
    region_last_active = last_region_activity.get(region)
    timestamp = region_last_active.strftime("%B %d, %Y %I:%M %p") if region_last_active else "Never"

    embed = discord.Embed(
        title="No Testers Online",
        description=(
            f"No testers for your region are available at this time.\n"
            f"You will be pinged when a tester is available.\n"
            f"Check back later!\n\n"
            f"Last Test At: `{timestamp}`"
        ),
        color=discord.Color(15880807)
    )
    
    embed.set_author(
        name="[1.21+] VerseTL",
        icon_url="https://upnow-prod.ff45e40d1a1c8f7e7de4e976d0c9e555.r2.cloudflarestorage.com/dzbRgzDeFWeXAQx0Q8EGh5FXSiF3/0670e4c9-d8d3-4f25-85cc-03717121a17d?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=2f488bd324502ec20fee5b40e9c9ed39%2F20250812%2Fauto%2Fs3%2Faws4_request&X-Amz-Date=20250812T161311Z&X-Amz-Expires=43200&X-Amz-Signature=7a14dab019355ab773cf5eb1c049322c48030aeb575ccd744d534081b61291b5&X-Amz-SignedHeaders=host&response-content-disposition=attachment%3B%20filename%3D%22bigger%20version%20Verse%20ranked%20logo.png%22"
    )

    # Create the initial message
    try:
        initial_message = await channel.send(embed=embed)

        # Store both the message object and ID
        waitlist_messages[region] = initial_message
        waitlist_message_ids[region] = initial_message.id

        print(f"DEBUG: Created and stored initial message {initial_message.id} for {region}")

    except Exception as e:
        print(f"DEBUG: Error creating initial message for {region}: {e}")

# === TASKS ===

@tasks.loop(minutes=1)
async def refresh_messages():
    global last_test_session
    # Update timestamp every minute
    last_test_session = datetime.datetime.now()

    print("DEBUG: Starting periodic refresh of waitlist messages")
    for guild in bot.guilds:
        # Skip unauthorized guilds
        if not is_guild_authorized(guild.id):
            continue
            
        for region in waitlists.keys():
            try:
                await update_waitlist_message(guild, region)
                print(f"DEBUG: Successfully refreshed waitlist message for {region}")
            except Exception as e:
                print(f"DEBUG: Error refreshing waitlist message for {region}: {e}")

@tasks.loop(hours=1)  # Check every hour
async def cleanup_expired_cooldowns():
    """Remove expired cooldowns from memory and file"""
    current_time = datetime.datetime.now()
    expired_users = []

    for user_id, cooldown_time in user_test_cooldowns.items():
        if cooldown_time <= current_time:
            expired_users.append(user_id)

    if expired_users:
        for user_id in expired_users:
            del user_test_cooldowns[user_id]

        save_user_cooldowns()
        print(f"DEBUG: Cleaned up {len(expired_users)} expired cooldowns")

@tasks.loop(minutes=30)  # Save every 30 minutes
async def periodic_save_activities():
    """Periodically save last region activities to file"""
    save_last_region_activity()
    print("DEBUG: Periodic save of last region activities completed")

# === RUN BOT ===

keep_alive()
bot.run(TOKEN)import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import json
import datetime
from dotenv import load_dotenv
from keep_alive import keep_alive
import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build
import googleapiclient.errors

load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0")) if os.getenv("GUILD_ID") else None

# NOUVEAU: Système d'autorisation
OWNER_ID = 836452038548127764  # Votre Discord ID
AUTHORIZED_GUILDS_FILE = "authorized_guilds.json"
authorized_guilds = set()  # Set des serveurs autorisés

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Store server backups and logs
server_backups = {}
message_logs = {}

# Waitlist system variables
waitlists = {"na": [], "eu": [], "as": [], "au": []}
MAX_WAITLIST = 20
waitlist_message_ids = {}  # Store message IDs for each region
waitlist_messages = {}  # Store actual message objects for each region
opened_queues = set()
active_testers = {"na": [], "eu": [], "as": [], "au": []}  # Track active testers per region
user_info = {}  # Store user form information {user_id: {"ign": str, "server": str, "region": str}}
last_test_session = datetime.datetime.now()  # Initialize with current time instead of None
last_region_activity = {"na": None, "eu": None, "as": None, "au": None}  # Track last activity per region
tester_stats = {}  # Track test counts for each tester {user_id: test_count}
STATS_FILE = "tester_stats.json"  # File to persist tester statistics
user_test_cooldowns = {}  # Store cooldown timestamps for users {user_id: datetime}
COOLDOWNS_FILE = "user_cooldowns.json"  # File pour persister les cooldowns
LAST_ACTIVITY_FILE = "last_region_activity.json"  # NOUVEAU: Fichier pour persister les dernières activités

# NEW: Track active testing sessions to prevent duplicates
active_testing_sessions = {}  # {user_id: channel_id}

# NOUVEAU: Constantes pour les durées de cooldown
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

# FIXED: High tier definitions (HT3 and above, including HT2, LT2, HT1, LT1)
HIGH_TIERS = ["HT1", "LT1", "HT2", "LT2", "HT3"]

# NOUVELLES FONCTIONS: Gestion des serveurs autorisés
def load_authorized_guilds():
    """Charger la liste des serveurs autorisés depuis le fichier"""
    global authorized_guilds
    try:
        if os.path.exists(AUTHORIZED_GUILDS_FILE):
            with open(AUTHORIZED_GUILDS_FILE, 'r') as f:
                data = json.load(f)
                authorized_guilds = set(data.get('guilds', []))
            print(f"DEBUG: Loaded {len(authorized_guilds)} authorized guilds")
        else:
            authorized_guilds = set()
            print("DEBUG: No authorized guilds file found, starting with empty list")
    except Exception as e:
        print(f"DEBUG: Error loading authorized guilds: {e}")
        authorized_guilds = set()

def save_authorized_guilds():
    """Sauvegarder la liste des serveurs autorisés dans le fichier"""
    try:
        data = {'guilds': list(authorized_guilds)}
        with open(AUTHORIZED_GUILDS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"DEBUG: Saved {len(authorized_guilds)} authorized guilds")
    except Exception as e:
        print(f"DEBUG: Error saving authorized guilds: {e}")

def is_guild_authorized(guild_id: int) -> bool:
    """Vérifier si un serveur est autorisé"""
    return guild_id in authorized_guilds

async def send_unauthorized_message(guild: discord.Guild):
    """Envoyer un message d'autorisation requise dans le serveur"""
    try:
        # Trouver un canal où le bot peut écrire
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="🚫 Autorisation Requise",
                    description=(
                        f"Ce bot n'est pas encore autorisé sur ce serveur.\n\n"
                        f"**Pour activer le bot :**\n"
                        f"• Contactez <@{OWNER_ID}> (Heuxil)\n"
                        f"• Il doit utiliser la commande `/autorise` dans ce serveur\n\n"
                        f"**Serveur :** {guild.name}\n"
                        f"**ID :** `{guild.id}`"
                    ),
                    color=discord.Color.red()
                )
                embed.set_footer(text="Le bot restera inactif jusqu'à autorisation")
                await channel.send(embed=embed)
                break
    except Exception as e:
        print(f"DEBUG: Could not send unauthorized message in {guild.name}: {e}")

# NOUVELLE FONCTION: Vérifier si un utilisateur a le rôle Booster
def has_booster_role(member: discord.Member) -> bool:
    """Check if a member has the Booster role"""
    booster_role = discord.utils.get(member.roles, name="Booster")
    return booster_role is not None

# NOUVELLE FONCTION: Obtenir la durée de cooldown appropriée
def get_cooldown_duration(member: discord.Member) -> int:
    """Get the appropriate cooldown duration based on user roles"""
    if has_booster_role(member):
        return BOOSTER_COOLDOWN_DAYS
    else:
        return REGULAR_COOLDOWN_DAYS

# NOUVELLE FONCTION: Appliquer le cooldown avec la durée appropriée
def apply_cooldown(user_id: int, member: discord.Member):
    """Apply cooldown with appropriate duration based on user roles"""
    cooldown_days = get_cooldown_duration(member)
    cooldown_end = datetime.datetime.now() + datetime.timedelta(days=cooldown_days)
    user_test_cooldowns[user_id] = cooldown_end
    save_user_cooldowns()

    role_type = "Booster" if has_booster_role(member) else "Regular"
    print(f"DEBUG: Applied {cooldown_days}-day cooldown for {role_type} user {member.name} (ID: {user_id}) until {cooldown_end}")
    return cooldown_days

def save_tester_stats():
    """Save tester statistics to JSON file"""
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump(tester_stats, f, indent=2)
        print(f"DEBUG: Saved tester stats to {STATS_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving tester stats: {e}")

def load_tester_stats():
    """Load tester statistics from JSON file"""
    global tester_stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                loaded_stats = json.load(f)
                # Convert string keys back to integers (JSON keys are always strings)
                tester_stats = {int(user_id): count for user_id, count in loaded_stats.items()}
            print(f"DEBUG: Loaded {len(tester_stats)} tester stats from {STATS_FILE}")
        else:
            print(f"DEBUG: No existing stats file found, starting fresh")
            tester_stats = {}
    except Exception as e:
        print(f"DEBUG: Error loading tester stats: {e}")
        tester_stats = {}

def save_user_cooldowns():
    """Save user cooldowns to JSON file"""
    try:
        # Convert datetime objects to ISO format strings for JSON serialization
        cooldowns_data = {}
        for user_id, cooldown_time in user_test_cooldowns.items():
            cooldowns_data[str(user_id)] = cooldown_time.isoformat()

        with open(COOLDOWNS_FILE, 'w') as f:
            json.dump(cooldowns_data, f, indent=2)
        print(f"DEBUG: Saved {len(cooldowns_data)} user cooldowns to {COOLDOWNS_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving user cooldowns: {e}")

def load_user_cooldowns():
    """Load user cooldowns from JSON file"""
    global user_test_cooldowns
    try:
        if os.path.exists(COOLDOWNS_FILE):
            with open(COOLDOWNS_FILE, 'r') as f:
                loaded_cooldowns = json.load(f)

            # Convert string keys back to integers and ISO strings back to datetime objects
            user_test_cooldowns = {}
            current_time = datetime.datetime.now()

            for user_id_str, cooldown_str in loaded_cooldowns.items():
                try:
                    user_id = int(user_id_str)
                    cooldown_time = datetime.datetime.fromisoformat(cooldown_str)

                    # Only keep cooldowns that haven't expired yet
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

# NOUVEAU: Fonctions pour sauvegarder et charger les dernières activités
def save_last_region_activity():
    """Save last region activity to JSON file"""
    try:
        # Convert datetime objects to ISO format strings for JSON serialization
        activity_data = {}
        for region, last_time in last_region_activity.items():
            if last_time is not None:
                activity_data[region] = last_time.isoformat()
            else:
                activity_data[region] = None

        with open(LAST_ACTIVITY_FILE, 'w') as f:
            json.dump(activity_data, f, indent=2)
        print(f"DEBUG: Saved last region activities to {LAST_ACTIVITY_FILE}")
    except Exception as e:
        print(f"DEBUG: Error saving last region activities: {e}")

def load_last_region_activity():
    """Load last region activity from JSON file"""
    global last_region_activity
    try:
        if os.path.exists(LAST_ACTIVITY_FILE):
            with open(LAST_ACTIVITY_FILE, 'r') as f:
                loaded_activities = json.load(f)

            # Convert ISO strings back to datetime objects
            for region in last_region_activity.keys():
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
            # Keep the existing None values
    except Exception as e:
        print(f"DEBUG: Error loading last region activities: {e}")

def get_sheets_service():
    """Get Google Sheets service using service account credentials"""
    try:
        # Try to get service account credentials from environment
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

async def add_ign_to_sheet(ign: str, tier: str):
    """Add IGN to the appropriate tier column in the Google Sheet"""
    try:
        service = get_sheets_service()
        if not service:
            print("DEBUG: Google Sheets service not available")
            return False

        # Get the column letter for the tier
        column = TIER_COLUMNS.get(tier.upper())
        if not column:
            print(f"DEBUG: Unknown tier: {tier}")
            return False

        # First, get all existing values in the column to find the next empty row
        range_name = f"'VerseTL Crystal'!{column}:{column}"
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()

        values = result.get('values', [])
        next_row = len(values) + 1  # Next empty row

        # Add the IGN to the next empty row in the appropriate column
        range_name = f"'VerseTL Crystal'!{column}{next_row}"
        body = {
            'values': [[ign]]
        }

        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()

        print(f"DEBUG: Successfully added {ign} to {tier} column at row {next_row}")
        return True

    except googleapiclient.errors.HttpError as e:
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

@bot.event
async def on_ready():
    print(f"{bot.user.name} is online and ready!")
    
    # Charger les serveurs autorisés
    load_authorized_guilds()
    
    # Initialize logs for all guilds
    for guild in bot.guilds:
        if guild.id not in message_logs:
            message_logs[guild.id] = []
        
        # Vérifier l'autorisation pour chaque serveur
        if not is_guild_authorized(guild.id):
            print(f"DEBUG: Guild {guild.name} (ID: {guild.id}) is not authorized")
            await send_unauthorized_message(guild)
            continue  # Skip initialization for unauthorized guilds
    
    # Load tester statistics, user cooldowns ET last region activities from files
    load_tester_stats()
    load_user_cooldowns()
    load_last_region_activity()

    # Reset all queues and testers on startup to ensure "No tester online" state
    global opened_queues, active_testers, waitlists, waitlist_message_ids, waitlist_messages, active_testing_sessions
    opened_queues.clear()
    for region in active_testers:
        active_testers[region].clear()
    # Also clear all waitlists on startup
    for region in waitlists:
        waitlists[region].clear()
    # Clear message IDs and objects to prevent conflicts
    waitlist_message_ids.clear()
    waitlist_messages.clear()
    # Clear active testing sessions on startup
    active_testing_sessions.clear()
    print("DEBUG: Cleared all opened queues, active testers, waitlists, message references, and active testing sessions on startup")

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        
        # Sync specifically for this server if GUILD_ID is defined
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced_guild = await bot.tree.sync(guild=guild)
            print(f"DEBUG: Synced {len(synced_guild)} slash command(s) for guild {GUILD_ID}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    for guild in bot.guilds:
        # Skip initialization for unauthorized guilds
        if not is_guild_authorized(guild.id):
            continue
            
        # Clean up request channel to prevent duplicate buttons
        request_channel = discord.utils.get(guild.text_channels, name="📨┃request-test")
        if request_channel:
            embed = discord.Embed(
                title="📋 Evaluation Testing Waitlist",
                description=
                ("Upon applying, you will be added to a waitlist channel.\n"
                 "Here you will be pinged when a tester of your region is available.\n"
                 "If you are HT3 or higher, a high ticket will be created.\n\n"
                 "• Region should be the region of the server you wish to test on\n"
                 "• Username should be the name of the account you will be testing on\n\n"
                 "**🛑 Failure to provide authentic information will result in a denied test.**\n\n"
                 ),
                color=discord.Color.red())
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(label="Enter Waitlist",
                                  style=discord.ButtonStyle.success,
                                  custom_id="open_form"))

            # Clean up ALL messages in request channel to ensure only one button exists
            try:
                await request_channel.purge(limit=100)
                print(f"DEBUG: Purged all messages in request-test channel")
            except Exception as e:
                print(f"DEBUG: Could not purge request-test channel: {e}")

            await request_channel.send(embed=embed, view=view)
            print(f"DEBUG: Created single request button in request-test channel with Booster cooldown info")

        # Setup initial waitlist messages in all existing channels
        for region in waitlists:
            channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
            if channel:
                try:
                    # Clean up any existing messages first to prevent duplicates
                    await channel.purge(limit=100)
                    print(f"DEBUG: Purged messages in waitlist-{region}")
                except Exception as e:
                    print(f"DEBUG: Could not purge waitlist-{region}: {e}")

                # Ensure region is NOT in opened_queues when creating initial message
                opened_queues.discard(region)

                # Create the initial message and store it properly
                await create_initial_waitlist_message(guild, region)

        # Initialize leaderboard
        await update_leaderboard(guild)

    # Start all refresh tasks
    if not refresh_messages.is_running():
        refresh_messages.start()
        print("DEBUG: Started refresh_messages task")

    # Start cleanup task for expired cooldowns
    if not cleanup_expired_cooldowns.is_running():
        cleanup_expired_cooldowns.start()
        print("DEBUG: Started cleanup_expired_cooldowns task")

    # Start periodic save task for activities
    if not periodic_save_activities.is_running():
        periodic_save_activities.start()
        print("DEBUG: Started periodic_save_activities task")

@bot.event
async def on_guild_join(guild):
    print(f"DEBUG: Bot joined guild {guild.name} (ID: {guild.id})")
    
    # Le serveur n'est pas autorisé par défaut
    message_logs[guild.id] = []
    await send_unauthorized_message(guild)
    print(f"DEBUG: Sent unauthorized message to {guild.name}")

# NOUVELLE COMMANDE: Autoriser un serveur
@bot.tree.command(name="autorise", description="Autoriser le bot sur ce serveur (Owner seulement)")
async def autorise(interaction: discord.Interaction):
    # Vérifier que c'est bien le propriétaire du bot
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ Seul le propriétaire du bot peut utiliser cette commande.", 
            ephemeral=True
        )
        return
    
    guild_id = interaction.guild.id
    
    if guild_id in authorized_guilds:
        await interaction.response.send_message(
            f"✅ Ce serveur (**{interaction.guild.name}**) est déjà autorisé!", 
            ephemeral=True
        )
        return
    
    # Autoriser le serveur
    authorized_guilds.add(guild_id)
    save_authorized_guilds()
    
    # Envoyer une confirmation
    embed = discord.Embed(
        title="✅ Serveur Autorisé!",
        description=(
            f"**Serveur :** {interaction.guild.name}\n"
            f"**ID :** `{guild_id}`\n\n"
            f"Le bot est maintenant actif sur ce serveur!\n"
            f"Tous les canaux et fonctionnalités seront initialisés."
        ),
        color=discord.Color.green()
    )
    
    await interaction.response.send_message(embed=embed)
    
    # Initialiser le serveur maintenant qu'il est autorisé
    guild = interaction.guild
    
    # Initialize logs if not already done
    if guild.id not in message_logs:
        message_logs[guild.id] = []
    
    # Initialize all the channels and features for this guild
    try:
        # Clean up request channel to prevent duplicate buttons
        request_channel = discord.utils.get(guild.text_channels, name="📨┃request-test")
        if request_channel:
            embed = discord.Embed(
                title="📋 Evaluation Testing Waitlist",
                description=
                ("Upon applying, you will be added to a waitlist channel.\n"
                 "Here you will be pinged when a tester of your region is available.\n"
                 "If you are HT3 or higher, a high ticket will be created.\n\n"
                 "• Region should be the region of the server you wish to test on\n"
                 "• Username should be the name of the account you will be testing on\n\n"
                 "**🛑 Failure to provide authentic information will result in a denied test.**\n\n"
                 ),
                color=discord.Color.red())
            view = discord.ui.View()
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

        # Setup initial waitlist messages in all existing channels
        for region in waitlists:
            channel = discord.utils.get(guild.text_channels, name=f"waitlist-{region}")
            if channel:
                try:
                    await channel.purge(limit=100)
                    print(f"DEBUG: Purged messages in waitlist-{region}")
                except Exception as e:
                    print(f"DEBUG: Could not purge waitlist-{region}: {e}")

                opened_queues.discard(region)
                await create_initial_waitlist_message(guild, region)

        # Initialize leaderboard
        await update_leaderboard(guild)
        
        print(f"DEBUG: Successfully initialized authorized guild {guild.name}")
        
    except Exception as e:
        print(f"DEBUG: Error initializing guild {guild.name}: {e}")

# NOUVELLE COMMANDE: Désautoriser un serveur
@bot.tree.command(name="desautorise", description="Désautoriser le bot sur ce serveur (Owner seulement)")
async def desautorise(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ Seul le propriétaire du bot peut utiliser cette commande.", 
            ephemeral=True
        )
        return
    
    guild_id = interaction.guild.id
    
    if guild_id not in authorized_guilds:
        await interaction.response.send_message(
            f"⚠️ Ce serveur (**{interaction.guild.name}**) n'est pas autorisé.", 
            ephemeral=True
        )
        return
    
    # Désautoriser le serveur
    authorized_guilds.discard(guild_id)
    save_authorized_guilds()
    
    embed = discord.Embed(
        title="❌ Serveur Désautorisé",
        description=(
            f"**Serveur :** {interaction.guild.name}\n"
            f"**ID :** `{guild_id}`\n\n"
            f"Le bot est maintenant inactif sur ce serveur."
        ),
        color=discord.Color.red()
    )
    
    await interaction.response.send_message(embed=embed)

# NOUVEAU: Middleware pour vérifier l'autorisation sur toutes les commandes
async def check_authorization(interaction: discord.Interaction) -> bool:
    """Vérifier si le serveur est autorisé avant d'exécuter une commande"""
    if interaction.guild is None:
        return True  # Allow DM commands
    
    # Permettre les commandes d'autorisation même si le serveur n'est pas autorisé
    if interaction.data.get('name') in ['autorise', 'desautorise']:
        return True
    
    if not is_guild_authorized(interaction.guild.id):
        embed = discord.Embed(
            title="🚫 Serveur Non Autorisé",
            description=(
                f"Ce serveur n'est pas autorisé à utiliser ce bot.\n\n"
                f"**Pour activer le bot :**\n"
                f"• Contactez <@{OWNER_ID}> (Heuxil)\n"
                f"• Il doit utiliser `/autorise` dans ce serveur"
            ),
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    
    return True

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command. Use `/commands` to see available commands.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing required arguments. Check `/commands` for proper usage.")
    else:
        print(f"Error: {error}")

@bot.event
async def on_member_join(member):
    if member.bot:
        return
    
    # Vérifier l'autorisation du serveur
    if not is_guild_authorized(member.guild.id):
        return
        
    # Find the "Member" role by name instead of hardcoded ID
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

    # Log member join
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
    # Vérifier l'autorisation du serveur
    if not is_guild_authorized(member.guild.id):
        return
        
    await update_user_count_channel(member.guild)

    # Log member leave
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
    
    # Vérifier l'autorisation du serveur
    if message.guild and not is_guild_authorized(message.guild.id):
        return
    
    # Check if message is in general channel
    if message.channel.name == "💬┃general":
        content_lower = message.content.lower()
        
        # Check for Discord invite links
        discord_patterns = [
            "discord.gg/",
            "discord.com/invite/",
            "discordapp.com/invite/"
        ]
        
        # Check for YouTube links
        youtube_patterns = [
            "youtube.com/",
            "youtu.be/",
            "m.youtube.com/"
        ]
        
        # Check if message contains prohibited links
        contains_discord_link = any(pattern in content_lower for pattern in discord_patterns)
        contains_youtube_link = any(pattern in content_lower for pattern in youtube_patterns)
        
        if contains_discord_link or contains_youtube_link:
            try:
                # Delete the message
                await message.delete()
                
                # Send warning to user via DM
                link_type = "Discord server invite" if contains_discord_link else "YouTube video"
                warning_message = f"⚠️ Your message in **{message.guild.name}** was deleted because it contained a {link_type} link. Please avoid sharing such links in the general chat."
                
                try:
                    await message.author.send(warning_message)
                except discord.Forbidden:
                    # If DM fails, send warning in channel (ephemeral style with quick deletion)
                    warning_in_channel = await message.channel.send(f"⚠️ {message.author.mention}, please avoid sharing {link_type} links in this channel.")
                    # Delete the warning message after 10 seconds
                    await asyncio.sleep(10)
                    try:
                        await warning_in_channel.delete()
                    except discord.NotFound:
                        pass
                
                # Log the moderation action
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
                # Message was already deleted
                pass
            except Exception as e:
                print(f"Error in auto-moderation: {e}")

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    
    # Vérifier l'autorisation du serveur
    if message.guild and not is_guild_authorized(message.guild.id):
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
    # Vérifier l'autorisation du serveur
    if not is_guild_authorized(channel.guild.id):
        return
        
    if channel.name.startswith("eval-"):
        # Remove from active testing sessions if it exists
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
    print(f"DEBUG: Interaction received - Type: {interaction.type}, Data: {getattr(interaction, 'data', 'No data')}")

    # Vérifier l'autorisation pour les interactions de composants
    if (interaction.type == discord.InteractionType.component and 
        interaction.guild and not is_guild_authorized(interaction.guild.id)):
        
        embed = discord.Embed(
            title="🚫 Serveur Non Autorisé",
            description=(
                f"Ce serveur n'est pas autorisé à utiliser ce bot.\n\n"
                f"**Pour activer le bot :**\n"
                f"• Contactez <@{OWNER_ID}> (Heuxil)\n"
                f"• Il doit utiliser `/autorise` dans ce serveur"
            ),
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]

        # Handle Enter Waitlist button from request-test channel
        if custom_id == "open_form":
            # Check if this is from the request-test channel
            if interaction.channel.name == "📨┃request-test":
                modal = WaitlistModal()
                await interaction.response.send_modal(modal)
                return

            # Handle Join Queue button from waitlist channels
            for region in waitlists:
                if interaction.channel.name.lower() == f"waitlist-{region}":
                    # Check if user has submitted the form first
                    user_id = interaction.user.id
                    if user_id not in user_info:
                        await interaction.response.send_message(
                            "❌ You must submit the form in <#📨┃request-test> before joining the queue.",
                            ephemeral=True
                        )
                        return

                    # Check if the form was submitted for the correct region
                    user_region = user_info[user_id]["region"].lower()
                    if user_region != region:
                        await interaction.response.send_message(
                            f"❌ Your form was submitted for {user_region.upper()} region, but you're trying to join the {region.upper()} queue.",
                            ephemeral=True
                        )
                        return

                    # Check if user already has an active testing session
                    if user_id in active_testing_sessions:
                        existing_channel_id = active_testing_sessions[user_id]
                        existing_channel = interaction.guild.get_channel(existing_channel_id)

                        if existing_channel:
                            await interaction.response.send_message(
                                f"⚠️ You already have an active testing session in {existing_channel.mention}. Please complete that test first.",
                                ephemeral=True
                            )
                            return
                        else:
                            # Channel was deleted but still tracked, clean it up
                            del active_testing_sessions[user_id]

                    # Check if user is already in this queue
                    if interaction.user.id in waitlists[region]:
                        await interaction.response.send_message(
                            "You're already in the queue.", ephemeral=True)
                        return

                    # Check if queue is full
                    if len(waitlists[region]) >= MAX_WAITLIST:
                        await interaction.response.send_message(
                            "Queue is full.", ephemeral=True)
                        return

                    # NOW add user to the actual queue
                    waitlists[region].append(interaction.user.id)

                    # Roles should already be given from the form submission
                    # But we can double-check and add them if missing
                    role = discord.utils.get(interaction.guild.roles,
                                             name=f"Waitlist-{region.upper()}")
                    if role and role not in interaction.user.roles and role < interaction.guild.me.top_role:
                        try:
                            await interaction.user.add_roles(role)
                        except discord.Forbidden:
                            pass

                    await interaction.response.send_message(
                        f"✅ Successfully joined the {region.upper()} queue! You are position #{len(waitlists[region])} in line.",
                        ephemeral=True)

                    # Log queue join
                    await log_queue_join(interaction.guild, interaction.user, region, len(waitlists[region]))

                    # Now update the waitlist message to show the user in queue
                    await update_waitlist_message(interaction.guild, region)

@bot.tree.command(name="stopqueue", description="Remove yourself from active testers (Tester role required)")
@app_commands.describe(channel="The waitlist channel to leave as tester")
async def stopqueue(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_authorization(interaction):
        return
    
    if channel is None:
        channel = interaction.channel

    # Check if user has Tester role
    tester_role = discord.utils.get(interaction.user.roles, name="Tester")
    if not tester_role:
        await interaction.response.send_message("You must have the Tester role to use this command.", ephemeral=True)
        return

    region = get_region_from_channel(channel.name)
    if not region:
        await interaction.response.send_message("This is not a valid waitlist channel.", ephemeral=True)
        return

    # Remove only this tester from active testers
    if interaction.user.id in active_testers[region]:
        active_testers[region].remove(interaction.user.id)

        # If no more active testers, remove the region from opened queues
        if not active_testers[region]:
            opened_queues.discard(region)
            waitlists[region] = []  # Clear waitlist when no testers left

        await update_waitlist_message(interaction.guild, region)
        await interaction.response.send_message(f"You have been removed from active testers for {region.upper()} in {channel.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"You are not an active tester for {region.upper()}.", ephemeral=True)

@bot.tree.command(name="nextuser", description="Create a private channel for the next person in waitlist (Tester role required)")
@app_commands.describe(channel="The waitlist channel to get the next person from")
async def nextuser(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_authorization(interaction):
        return
    
    if channel is None:
        channel = interaction.channel

    # Check if user has Tester role
    tester_role = discord.utils.get(interaction.user.roles, name="Tester")
    if not tester_role:
        await interaction.response.send_message("You must have the Tester role to use this command.", ephemeral=True)
        return

    region = get_region_from_channel(channel.name)
    if not region:
        await interaction.response.send_message("This is not a valid waitlist channel.", ephemeral=True)
        return

    # Check if there's someone in the waitlist
    if not waitlists[region]:
        await interaction.response.send_message(f"No one is in the {region.upper()} waitlist.", ephemeral=True)
        return

    # Get the next person in line
    next_user_id = waitlists[region].pop(0)
    next_user = interaction.guild.get_member(next_user_id)

    if not next_user:
        await interaction.response.send_message("Could not find the next user in the waitlist.", ephemeral=True)
        return

    # Check if user already has an active testing session
    if next_user_id in active_testing_sessions:
        existing_channel_id = active_testing_sessions[next_user_id]
        existing_channel = interaction.guild.get_channel(existing_channel_id)

        if existing_channel:
            await interaction.response.send_message(
                f"{next_user.mention} already has an active testing session in {existing_channel.mention}.", 
                ephemeral=True
            )
            return
        else:
            # Channel was deleted but still tracked, clean it up
            del active_testing_sessions[next_user_id]

    # Find the appropriate category based on region
    category_name = f"Eval {region.upper()}"
    category = discord.utils.get(interaction.guild.categories, name=category_name)

    if not category:
        await interaction.response.send_message(f"Could not find category {category_name}.", ephemeral=True)
        return

    # Create unique channel name to avoid conflicts
    timestamp = int(datetime.datetime.now().timestamp())
    channel_name = f"eval-{next_user.display_name.lower().replace(' ', '-')}-{timestamp}"

    # Set permissions for the private channel
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        next_user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    # Give access to all users with Tester role
    tester_role = discord.utils.get(interaction.guild.roles, name="Tester")
    if tester_role:
        overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        # Create the channel
        new_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites
        )

        # Track the active testing session
        active_testing_sessions[next_user_id] = new_channel.id

        # Remove waitlist/matchmaking roles
        roles_to_remove = []
        possible_role_names = [
            f"Waitlist-{region.upper()}",
            f"{region.upper()} Waitlist",
            f"{region.upper()} Matchmaking",
            f"waitlist-{region.upper()}",
            f"waitlist-{region.lower()}",
            f"{region.lower()} waitlist",
            f"{region.lower()} matchmaking"
        ]

        for role_name in possible_role_names:
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if role and role in next_user.roles and role < interaction.guild.me.top_role:
                roles_to_remove.append(role)

        for role in roles_to_remove:
            try:
                await next_user.remove_roles(role)
                print(f"DEBUG: Successfully removed role '{role.name}' from {next_user.name}")
            except discord.Forbidden:
                print(f"DEBUG: No permission to remove role '{role.name}' from {next_user.name}")
            except Exception as e:
                print(f"DEBUG: Error removing role '{role.name}': {e}")

        # Update waitlist message
        await update_waitlist_message(interaction.guild, region)

        # Send confirmation to the tester
        await interaction.response.send_message(f"Created private channel {new_channel.mention} for {next_user.mention}.", ephemeral=True)

        # Apply cooldown with appropriate duration
        cooldown_days = apply_cooldown(next_user_id, next_user)
        role_type = "Booster" if has_booster_role(next_user) else "regular"
        print(f"DEBUG: Applied {cooldown_days}-day cooldown for {role_type} user {next_user.name}")

        # Send user info embed in the new channel
        user_data = user_info.get(next_user_id, {})

        if user_data:
            info_embed = discord.Embed(
                title="Welcome to your Evaluation Session",
                description=f"Hello {next_user.mention}! You have been selected for testing in the {region.upper()} region.\n\nYour tester {interaction.user.mention} will guide you through the process.\n\n**IGN:** {user_data.get('ign', 'N/A')}\n**Preferred Server:** {user_data.get('server', 'N/A')}",
                color=0x00ff7f
            )
            await new_channel.send(embed=info_embed)
        else:
            info_embed = discord.Embed(
                title="Welcome to your Evaluation Session",
                description=f"Hello {next_user.mention}! You have been selected for testing in the {region.upper()} region.\n\nYour tester {interaction.user.mention} will guide you through the process.\n\n**IGN:** N/A\n**Preferred Server:** N/A",
                color=0x00ff7f
            )
            await new_channel.send(embed=info_embed)

    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to create channels in that category.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred while creating the channel: {str(e)}", ephemeral=True)

@bot.tree.command(name="passeval", description="Transfer eval channel to High Eval category (Tester role required)")
async def passeval(interaction: discord.Interaction):
    if not await check_authorization(interaction):
        return
    
    # Check if user has Tester role
    tester_role = discord.utils.get(interaction.user.roles, name="Tester")
    if not tester_role:
        await interaction.response.send_message("You must have the Tester role to use this command.", ephemeral=True)
        return

    # Check if this is an eval channel (starts with "eval-")
    if not interaction.channel.name.startswith("eval-"):
        await interaction.response.send_message("This command can only be used in eval channels.", ephemeral=True)
        return

    # Determine region from current category
    current_category = interaction.channel.category
    if not current_category:
        await interaction.response.send_message("Channel must be in a category to determine region.", ephemeral=True)
        return

    # Extract region from category name (e.g., "Eval NA" -> "na")
    category_name = current_category.name.lower()
    region = None
    for r in ["na", "eu", "as", "au"]:
        if r in category_name:
            region = r
            break

    if not region:
        await interaction.response.send_message("Could not determine region from current category.", ephemeral=True)
        return

    # Find the High Eval category for this region
    high_eval_category_name = f"High Eval {region.upper()}"
    high_eval_category = discord.utils.get(interaction.guild.categories, name=high_eval_category_name)

    if not high_eval_category:
        await interaction.response.send_message(f"Could not find {high_eval_category_name} category.", ephemeral=True)
        return

    try:
        # Move the channel to High Eval category
        await interaction.channel.edit(category=high_eval_category)

        # Send confirmation message
        await interaction.response.send_message(f"✅ This channel has been transferred to {high_eval_category_name}.", ephemeral=True)

        # Send notification in the channel
        embed = discord.Embed(
            title="🔥 High Evaluation",
            description=f"This evaluation has been transferred to **{high_eval_category_name}** by {interaction.user.mention}.",
            color=0xff6600  # Orange color
        )
        await interaction.followup.send(embed=embed)

    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to move this channel.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred while moving the channel: {str(e)}", ephemeral=True)

@bot.tree.command(name="close", description="Close an eval channel (Tester role required)")
async def close(interaction: discord.Interaction):
    if not await check_authorization(interaction):
        return
    
    # Check if user has Tester role
    tester_role = discord.utils.get(interaction.user.roles, name="Tester")
    if not tester_role:
        await interaction.response.send_message("You must have the Tester role to use this command.", ephemeral=True)
        return

    # Check if this is an eval channel (starts with "eval-")
    if not interaction.channel.name.startswith("eval-"):
        await interaction.response.send_message("This command can only be used in eval channels.", ephemeral=True)
        return

    try:
        # Clean up active testing session when closing channel
        channel_id = interaction.channel.id
        user_to_remove = None
        for user_id, active_channel_id in active_testing_sessions.items():
            if active_channel_id == channel_id:
                user_to_remove = user_id
                break

        if user_to_remove:
            del active_testing_sessions[user_to_remove]
            print(f"DEBUG: Removed active testing session for user {user_to_remove}")

        # Send confirmation message before deleting
        embed = discord.Embed(
            title="🔒 Channel Closing",
            description=f"This evaluation channel is being closed by {interaction.user.mention}.\n\nChannel will be deleted in 5 seconds...",
            color=0xff0000  # Red color
        )

        await interaction.response.send_message(embed=embed)

        # Wait 5 seconds then delete the channel
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Eval channel closed by {interaction.user.name}")

    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to delete this channel.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred while closing the channel: {str(e)}", ephemeral=True)

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
    if not await check_authorization(interaction):
        return
    
    # Check if user has Tester role
    tester_role = discord.utils.get(interaction.user.roles, name="Tester")
    if not tester_role:
        await interaction.response.send_message("You must have the Tester role to use this command.", ephemeral=True)
        return

    # Check if this is an eval channel to prevent duplicate results
    if not interaction.channel.name.startswith("eval-"):
        await interaction.response.send_message("This command can only be used in eval channels to prevent duplicate results.", ephemeral=True)
        return

    # Determine which results channel to use based on tier
    if earned_rank in HIGH_TIERS:
        results_channel = discord.utils.get(interaction.guild.text_channels, name="🏆┃high-results")
        is_high_result = True
    else:
        results_channel = discord.utils.get(interaction.guild.text_channels, name="🏆┃results")
        is_high_result = False

    if not results_channel:
        channel_type = "high-results" if is_high_result else "results"
        await interaction.response.send_message(f"{channel_type.title()} channel not found.", ephemeral=True)
        return

    # Check for duplicate results for this user in recent messages
    duplicate_found = False
    async for message in results_channel.history(limit=50):  # Check last 50 messages
        if message.embeds and message.embeds[0].title:
            if f"{ign}'s Test Results" in message.embeds[0].title:
                # Check if it's a recent duplicate (within last hour)
                time_diff = datetime.datetime.now(datetime.timezone.utc) - message.created_at
                if time_diff.total_seconds() < 3600:  # 1 hour in seconds
                    duplicate_found = True
                    break

    if duplicate_found:
        await interaction.response.send_message(f"⚠️ A result for {ign} was already posted recently. Please check {results_channel.mention} to avoid duplicates.", ephemeral=True)
        return

    # Create embed with different color for high results
    embed_color = 0x00ff00 if is_high_result else 0xff0000  # Green for high tiers, red for others

    embed = discord.Embed(
        title=f"{ign}'s Test Results",
        color=embed_color
    )

    # Add special indicator for high tier results
    title_prefix = "🔥 **HIGH TIER** 🔥\n" if is_high_result else ""

    # Format the description
    description = (
        f"{title_prefix}"
        f"**Tester:**\n{interaction.user.mention}\n"
        f"**Region:**\n{region}\n"
        f"**Minecraft IGN:**\n{ign}\n"
        f"**Previous Tier:**\n{current_rank}\n"
        f"**Tier Earned:**\n{earned_rank}"
    )

    embed.description = description

    # Add Minecraft head as thumbnail using the IGN
    minecraft_head_url = f"https://mc-heads.net/head/{ign}/100"
    embed.set_thumbnail(url=minecraft_head_url)

    # Send the embed to the appropriate results channel with mention above
    sent_message = await results_channel.send(content=user.mention, embed=embed)

    # Add automatic emoji reactions
    if is_high_result:
        emojis = ["👑", "🔥", "⚡", "💎", "✨"]
    else:
        emojis = ["👑", "🤯", "👀", "😱", "🔥"]

    try:
        for emoji in emojis:
            await sent_message.add_reaction(emoji)
    except discord.Forbidden:
        print("Bot doesn't have permission to add reactions")
    except Exception as e:
        print(f"Error adding reactions: {e}")

    # Update tester stats
    tester_id = interaction.user.id
    if tester_id not in tester_stats:
        tester_stats[tester_id] = 0
    tester_stats[tester_id] += 1

    # Save stats to file immediately after updating
    save_tester_stats()

    # Add IGN to Google Sheet in the appropriate tier column
    sheet_success = await add_ign_to_sheet(ign, earned_rank)

    # Update leaderboard
    await update_leaderboard(interaction.guild)

    # Clean up active testing session after results are posted
    user_id = user.id
    if user_id in active_testing_sessions:
        del active_testing_sessions[user_id]
        print(f"DEBUG: Removed active testing session for user {user_id} after results posted")

    # Role management - remove all previous tier roles and give new one
    role_given = False
    earned_role = discord.utils.get(interaction.guild.roles, name=earned_rank)

    if earned_role and earned_role < interaction.guild.me.top_role:
        try:
            # Complete list of all possible tier roles
            all_tier_roles = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5"]
            roles_to_remove = []

            # Remove ALL existing tier roles before assigning the new one
            for tier_role_name in all_tier_roles:
                existing_tier_role = discord.utils.get(interaction.guild.roles, name=tier_role_name)
                if existing_tier_role and existing_tier_role in user.roles:
                    roles_to_remove.append(existing_tier_role)

            # Remove all old tier roles
            if roles_to_remove:
                await user.remove_roles(*roles_to_remove, reason=f"Removing all previous tier roles before giving {earned_rank}")
                print(f"DEBUG: Removed old tier roles {[role.name for role in roles_to_remove]} from {user.name}")

            # Add the new earned tier role
            await user.add_roles(earned_role, reason=f"Earned {earned_rank} from tier test")
            role_given = True
            print(f"DEBUG: Successfully gave {earned_rank} role to {user.name}")

        except discord.Forbidden:
            print(f"DEBUG: No permission to manage roles for {user.name}")
        except Exception as e:
            print(f"DEBUG: Error managing roles for {user.name}: {e}")
    else:
        print(f"DEBUG: Role {earned_rank} not found or bot doesn't have sufficient permissions")

    # Confirm to the tester with Sheet, Role, and Channel status
    confirmation_parts = [f"✅ Results posted for {user.mention} in {results_channel.mention}"]

    if is_high_result:
        confirmation_parts.append("🔥 **HIGH TIER RESULT** - Posted in high-results channel!")

    if sheet_success:
        confirmation_parts.append(f"✅ IGN added to {earned_rank} tier in spreadsheet")
    else:
        confirmation_parts.append("⚠️ Could not add IGN to spreadsheet (check configuration)")

    if role_given:
        confirmation_parts.append(f"✅ {earned_rank} role given to {user.mention}")
    else:
        confirmation_parts.append(f"⚠️ Could not give {earned_rank} role (check permissions/role exists)")

    confirmation_parts.append("✅ Testing session completed")

    await interaction.response.send_message("\n".join(confirmation_parts), ephemeral=True)

# === MODERATION COMMANDS ===

@bot.tree.command(name="assign_role_to_all", description="Assign role to all members")
@app_commands.describe(role_name="Name of the role to assign")
@app_commands.default_permissions(manage_roles=True)
async def assign_role_to_all(interaction: discord.Interaction, role_name: str):
    if not await check_authorization(interaction):
        return
    
    await interaction.response.defer()
    
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        await interaction.followup.send("❌ Role not found.")
        return
    count = 0
    for member in interaction.guild.members:
        if not member.bot and role not in member.roles:
            try:
                await member.add_roles(role)
                count += 1
            except:
                pass
    await interaction.followup.send(f"✅ Role `{role.name}` assigned to {count} members.")

@bot.tree.command(name="remove_role_from_all", description="Remove role from all members")
@app_commands.describe(role_name="Name of the role to remove")
@app_commands.default_permissions(manage_roles=True)
async def remove_role_from_all(interaction: discord.Interaction, role_name: str):
    if not await check_authorization(interaction):
        return
    
    await interaction.response.defer()
    
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        await interaction.followup.send("❌ Role not found.")
        return
    count = 0
    for member in interaction.guild.members:
        if not member.bot and role in member.roles:
            try:
                await member.remove_roles(role)
                count += 1
            except:
                pass
    await interaction.followup.send(f"🗑️ Role `{role.name}` removed from {count} members.")

@bot.tree.command(name="purge", description="Delete recent messages")
@app_commands.describe(limit="Number of messages to delete")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, limit: int):
    if not await check_authorization(interaction):
        return
    
    if limit <= 0:
        await interaction.response.send_message("❌ Please enter a number greater than 0.")
        return
    
    await interaction.response.defer()
    deleted = await interaction.channel.purge(limit=limit)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Reason for the ban")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_authorization(interaction):
        return
    
    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 {member.mention} has been banned. Reason: {reason}")

        # Log ban
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
        await interaction.response.send_message("❌ I do not have permission to ban this user.")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for the kick")
@app_commands.default_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_authorization(interaction):
        return
    
    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 {member.mention} has been kicked. Reason: {reason}")

        # Log kick
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
        await interaction.response.send_message("❌ I do not have permission to kick this user.")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="mute", description="Mute a member")
@app_commands.describe(member="Member to mute", reason="Reason for the mute")
@app_commands.default_permissions(manage_roles=True)
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_authorization(interaction):
        return
    
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await interaction.guild.create_role(name="Muted", reason="Mute role created by bot")
        for channel in interaction.guild.channels:
            # Skip channels with "waitlist" in their name
            if "waitlist" not in channel.name.lower():
                await channel.set_permissions(mute_role, send_messages=False, speak=False)

    try:
        await member.add_roles(mute_role, reason=reason)
        await interaction.response.send_message(f"🔇 {member.mention} has been muted. Reason: {reason}")

        # Log mute
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
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="unmute", description="Unmute a member")
@app_commands.describe(member="Member to unmute")
@app_commands.default_permissions(manage_roles=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if not await check_authorization(interaction):
        return
    
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        await interaction.response.send_message("❌ No mute role found.")
        return

    try:
        await member.remove_roles(mute_role)
        await interaction.response.send_message(f"🔊 {member.mention} has been unmuted.")

        # Log unmute
        log_entry = {
            "type": "unmute",
            "user": str(member),
            "user_id": member.id,
            "moderator": str(interaction.user),
            "timestamp": datetime.datetime.now().isoformat()
        }
        message_logs[interaction.guild.id].append(log_entry)
    except Exception as e:
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
@app_commands.default_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_authorization(interaction):
        return
    
    try:
        await member.send(f"⚠️ You have been warned in {interaction.guild.name}.\nReason: {reason}")
        await interaction.response.send_message(f"⚠️ {member.mention} has been warned. Reason: {reason}")

        # Log warn
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
        await interaction.response.send_message("❌ I couldn't send a DM to this user, but the warning has been issued here.")

@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.describe(seconds="Slowmode delay in seconds (0 to disable)")
@app_commands.default_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int = 0):
    if not await check_authorization(interaction):
        return
    
    if seconds < 0 or seconds > 21600:
        await interaction.response.send_message("❌ Slowmode must be between 0 and 21600 seconds (6 hours).")
        return

    try:
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("🚀 Slowmode disabled.")
        else:
            await interaction.response.send_message(f"🌀 Slowmode set to {seconds} seconds.")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="lockdown", description="Lock a channel")
@app_commands.describe(channel="Channel to lock (current channel if not specified)")
@app_commands.default_permissions(manage_channels=True)
async def lockdown(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_authorization(interaction):
        return
    
    if channel is None:
        channel = interaction.channel

    try:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔒 {channel.mention} has been locked down.")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="unlock", description="Unlock a channel")
@app_commands.describe(channel="Channel to unlock (current channel if not specified)")
@app_commands.default_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_authorization(interaction):
        return
    
    if channel is None:
        channel = interaction.channel

    try:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔓 {channel.mention} has been unlocked.")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ An error occurred: {e}")

@bot.tree.command(name="logs", description="Show recent server logs")
@app_commands.describe(limit="Number of logs to show")
async def logs(interaction: discord.Interaction, limit: int = 10):
    if not await check_authorization(interaction):
        return
    
    if interaction.guild.id not in message_logs:
        await interaction.response.send_message("❌ No logs available for this server.")
        return

    logs = message_logs[interaction.guild.id][-limit:]
    if not logs:
        await interaction.response.send_message("📝 No recent logs found.")
        return

    embed = discord.Embed(title="📝 Recent Server Logs", color=discord.Colour.blue())
    for log in logs:
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
    embed = discord.Embed(title="VerseBot Info", description="Created by <@836452038548127764>", color=discord.Colour.blue())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="support", description="Get support server link")
async def support(interaction: discord.Interaction):
    await interaction.response.send_message("📩 Need help? Join our support server: https://discord.gg/krzwaTsWUu")

@bot.tree.command(name="serverinfo", description="Display server information")
async def serverinfo(interaction: discord.Interaction):
    if not await check_authorization(interaction):
        return
    
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 Server Info - {guild.name}", color=discord.Colour.green())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

    embed.add_field(name="🏆 Server ID", value=guild.id, inline=True)
    embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="📅 Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="👥 Members", value=guild.member_count, inline=True)
    embed.add_field(name="💬 Text Channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="🔊 Voice Channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="🚀 Boost Level", value=guild.premium_tier, inline=True)
    embed.add_field(name="💎 Boosters", value=guild.premium_subscription_count, inline=True)

    await interaction.response.send_message(embed=embed)
                    return
            await interaction.response.send_message(
                "Invalid waitlist region.", ephemeral=True)

# === WAITLIST COMMANDS ===

@bot.tree.command(name="leave", description="Leave all waitlists you're currently in")
async def leave(interaction: discord.Interaction):
    if not await check_authorization(interaction):
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
        await interaction.response.send_message("You are not in any waitlist.", ephemeral=True)

@bot.tree.command(name="startqueue", description="Start the queue for testing (Tester role required)")
@app_commands.describe(channel="The waitlist channel to start the queue for")
async def startqueue(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_authorization(interaction):
        return
    
    if channel is None:
        channel = interaction.channel

    print(f"DEBUG: /startqueue called by {interaction.user.name} for channel {channel.name}")

    # Check if user has Tester role
    tester_role = discord.utils.get(interaction.user.roles, name="Tester")
    if not tester_role:
        print(f"DEBUG: User {interaction.user.name} doesn't have Tester role")
        await interaction.response.send_message("You must have the Tester role to use this command.", ephemeral=True)
        return

    print(f"DEBUG: User has Tester role, checking channel name: {channel.name}")
    region = get_region_from_channel(channel.name)
    print(f"DEBUG: Detected region: {region}")

    if not region:
        await interaction.response.send_message(f"This is not a valid waitlist channel. Channel name: {channel.name}", ephemeral=True)
        return

    opened_queues.add(region)

    # Update the last activity time for this region and save
    last_region_activity[region] = datetime.datetime.now()
    save_last_region_activity()
    print(f"DEBUG: Updated and saved last activity for {region.upper()}")

    # Add the tester to active testers if not already there
    if interaction.user.id not in active_testers[region]:
        active_testers[region].append(interaction.user.id)

    print(f"DEBUG: Added {region} to opened_queues: {opened_queues}")
    print(f"DEBUG: Active testers for {region}: {active_testers[region]}")

    waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{region}")

    # Send response first to avoid interaction error
    await interaction.response.send_message(f"{region.upper()} waitlist is now active in {waitlist_channel.mention}. You are now an active tester.", ephemeral=True)

    # Then update the existing message (no purge, so it will update instead of recreating)
    await update_waitlist_message(interaction.guild, region)
