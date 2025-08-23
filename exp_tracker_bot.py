import discord
from discord.ext import commands
import json
import os
from datetime import datetime

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
bot = commands.Bot(command_prefix='!', intents=intents)

# In-memory tracking for join times (user_id: {channel_id: join_time})
join_times = {}

# Load persistent data
data = load_data()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
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

    now = datetime.utcnow()
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

@bot.command()
@commands.has_permissions(manage_channels=True)
async def create_vc(ctx, *, name: str):
    """Create a new voice channel."""
    guild = ctx.guild
    channel = await guild.create_voice_channel(name)
    await ctx.send(f'Created voice channel: {channel.mention}')
    # Add to data
    channel_id = str(channel.id)
    data['channels'][channel_id] = {'name': name, 'users': {}}
    save_data(data)

@create_vc.error
async def create_vc_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need 'Manage Channels' permission.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: !create_vc <name>")

@bot.command()
async def stats(ctx, *, channel_name: str):
    """Show EXP and time stats for a voice channel."""
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
            await ctx.send(embed=embed)
            break
    
    if not found:
        await ctx.send(f"No voice channel found with name '{channel_name}'.")

@stats.error
async def stats_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: !stats <channel_name>")

# Run the bot
bot.run('MTQwODgzNjc1OTg4NTk3NTU2NA.G0GXhW.Cr2jCziFEy6603mh-yT0ZIS5HknbVkHzGyoM7s')