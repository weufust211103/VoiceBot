import discord
from discord import app_commands
import json
import os
from datetime import datetime, timezone

# File for storing data
DATA_FILE = 'data.json'

# Load data from JSON or initialize
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {'channels': {}}

# Save data to JSON
def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # For tracking voice changes
intents.members = True  # For member info
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# In-memory tracking for join times (user_id: {channel_id: join_time})
join_times = {}

# Load persistent data
data = load_data()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    # Sync slash commands (replace GUILD_ID with your server ID for testing)
    GUILD_ID = 774316666095009812  # Set to your guild ID for guild-specific sync, or None for global
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            await tree.sync(guild=guild)
            print(f'Successfully synced commands to guild {GUILD_ID}')
        else:
            await tree.sync()
            print('Successfully synced global commands')
        # List registered commands for debugging
        commands = await tree.fetch_commands(guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
        print(f'Registered commands: {[cmd.name for cmd in commands]}')
    except Exception as e:
        print(f'Error syncing commands: {e}')
    # Ensure all voice channels are in data
    for guild in bot.guilds:
        for channel in guild.voice_channels:
            channel_id = str(channel.id)
            if channel_id not in data['channels']:
                data['channels'][channel_id] = {'name': channel.name, 'users': {}}
    save_data(data)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return  # Ignore bots

    now = datetime.now(timezone.utc)
    user_id = str(member.id)

    # User left a channel
    if before.channel and not after.channel:
        channel_id = str(before.channel.id)
        if user_id in join_times and channel_id in join_times[user_id]:
            join_time = join_times[user_id][channel_id]
            time_spent = (now - join_time).total_seconds()
            exp_gained = int(time_spent // 60)  # 1 EXP per minute

            # Update data
            if channel_id in data['channels']:
                if user_id not in data['channels'][channel_id]['users']:
                    data['channels'][channel_id]['users'][user_id] = {'name': member.name, 'time_spent': 0, 'exp': 0}
                data['channels'][channel_id]['users'][user_id]['time_spent'] += time_spent
                data['channels'][channel_id]['users'][user_id]['exp'] += exp_gained
                save_data(data)

            # Clean up join_times
            del join_times[user_id][channel_id]
            if not join_times[user_id]:
                del join_times[user_id]

    # User joined a channel
    elif not before.channel and after.channel:
        channel_id = str(after.channel.id)
        if user_id not in join_times:
            join_times[user_id] = {}
        join_times[user_id][channel_id] = now

        # Ensure channel is in data
        if channel_id not in data['channels']:
            data['channels'][channel_id] = {'name': after.channel.name, 'users': {}}
            save_data(data)

@tree.command(name="create_vc", description="Create a new voice channel.")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(name="The name of the voice channel to create")
async def create_vc(interaction: discord.Interaction, name: str):
    guild = interaction.guild
    #target_category_id = 1394670392953798716
    target_category_id = 869053206599184434
    target_category = guild.get_channel(target_category_id)

    if not target_category or not isinstance(target_category, discord.CategoryChannel):
        await interaction.response.send_message("The specified category could not be found or is not a category.", ephemeral=True)
        return

    # Place the channel under the specified category
    channel = await guild.create_voice_channel(name, category=target_category, position=len(target_category.channels))
    # Add to data
    channel_id = str(channel.id)
    data['channels'][channel_id] = {'name': name, 'users': {}}
    save_data(data)
    await interaction.response.send_message(f'Created voice channel: {channel.mention}')

@create_vc.error
async def create_vc_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need 'Manage Channels' permission.", ephemeral=True)
    else:
        await interaction.response.send_message("Error creating voice channel.", ephemeral=True)

@tree.command(name="stats", description="Show EXP and time stats for a voice channel.")
@app_commands.describe(channel_name="The name of the voice channel")
async def stats(interaction: discord.Interaction, channel_name: str):
    found = False
    for channel_id, channel_data in data['channels'].items():
        if channel_data['name'].lower() == channel_name.lower():
            found = True
            embed = discord.Embed(title=f"Stats for {channel_data['name']}", color=discord.Color.green())
            
            if not channel_data['users']:
                embed.description = "No users have spent time here yet."
            else:
                # Sort users by EXP descending
                sorted_users = sorted(channel_data['users'].items(), key=lambda x: x[1]['exp'], reverse=True)
                for user_id, user_data in sorted_users:
                    time_min = int(user_data['time_spent'] // 60)
                    embed.add_field(
                        name=user_data['name'],
                        value=f"EXP: {user_data['exp']} | Time: {time_min} min",
                        inline=False
                    )
            await interaction.response.send_message(embed=embed)
            break
    
    if not found:
        await interaction.response.send_message(f"No voice channel found with name '{channel_name}'.", ephemeral=True)

@tree.command(name="help", description="List all available commands.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="Bot Commands", color=discord.Color.blue())
    commands = await tree.fetch_commands()
    for cmd in commands:
        embed.add_field(
            name=f"/{cmd.name}",
            value=cmd.description or "No description available.",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Run the bot
bot.run('MTQwODgzNjc1OTg4NTk3NTU2NA.G0GXhW.Cr2jCziFEy6603mh-yT0ZIS5HknbVkHzGyoM7s')
