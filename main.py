import discord
from discord import app_commands
import os
from player_manager import PlayerManager
from poker_table import PokerTable
from dotenv import load_dotenv
from discord import Embed
from datetime import datetime
from poker_room import PokerRoom, RoomSettings
from poker_actions import Action
from typing import Optional, Literal

# Load environment variables
load_dotenv()

# Bot setup with required intents
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True
intents.guilds = True  # Add this intent

# Initialize bot
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Global variables
ADMIN_ID = int(os.getenv('ADMIN_ID'))
player_manager = PlayerManager()
poker_table = PokerTable(bot)
games = {}
active_rooms = {}
room_id_map = {}

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

@bot.event
async def on_ready():
    print(f'====== Bot Status ======')
    print(f'Logged in as: {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    
    # Force sync all commands
    print("Syncing commands...")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    
    print(f'Connected to {len(bot.guilds)} servers')
    print(f'Active rooms: {len(active_rooms)}')
    print(f'Discord.py version: {discord.__version__}')
    print(f'=====================')
    

@tree.command(name="ping", description="Check if the bot is running")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency}ms")

@tree.command(name="start_poker", description="Start a poker game in a new voice channel (max 6 players).")
async def start_poker(interaction: discord.Interaction):
    if not interaction.user.voice:
        return await interaction.response.send_message("You must be in a voice channel to start the game.")
    
    guild = interaction.guild
    voice_channel = await poker_table.get_or_create_table(guild)
    players = [m for m in interaction.user.voice.channel.members if not m.bot][:6]
    
    if len(players) < 2:
        return await interaction.response.send_message("Need at least 2 players in the voice channel.")
    
    # Initialize player data
    for player in players:
        player_manager.add_player(guild.id, player.id, player.name)

    # Check minimum chips requirement
    MINIMUM_CHIPS = 100
    for player in players:
        chips = player_manager.get_player_chips(interaction.guild.id, player.id)["chips"]
        if chips < MINIMUM_CHIPS:
            return await interaction.response.send_message(
                f"{player.name} doesn't have enough chips to play! (Minimum: {MINIMUM_CHIPS})"
            )
    
    # Check if all players are registered
    for player in players:
        if not player_manager.is_registered(interaction.guild.id, player.id):
            return await interaction.response.send_message(
                f"{player.name} needs to register first! Use /register to create an account."
            )
    
    # Create full-featured poker game instance
    game = PokerGame(bot, guild, players, interaction.channel, voice_channel)
    games[guild.id] = game
    
    await interaction.response.send_message(f"Poker game started with {len(players)} players in {voice_channel.mention}!")
    
    # Start the game loop
    await game.play()
@tree.command(name="end_poker", description="End the current poker game.")
async def end_poker(interaction: discord.Interaction):
    if interaction.guild.id in games:
        del games[interaction.guild.id]
        await interaction.response.send_message("Poker game ended.")
    else:
        await interaction.response.send_message("No active game.")

@tree.command(name="check_chips", description="Check your chip count.")
async def check_chips(interaction: discord.Interaction):
    chips = player_manager.get_player_chips(interaction.guild.id, interaction.user.id)["chips"]
    await interaction.response.send_message(f"{interaction.user.name}, you have {chips} chips.")

@tree.command(name="bet", description="Place a bet")
async def bet(interaction: discord.Interaction, amount: int):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room!")
        
    room = active_rooms[interaction.channel.id]
    if not room.active:
        return await interaction.response.send_message("Game hasn't started!")
        
    if interaction.user != room.get_next_to_act():
        return await interaction.response.send_message("It's not your turn!")
        
    try:
        await room.handle_bet(interaction.user, amount)
        
        if room.betting_round.current_bet == 0:
            action_type = "bets"
        else:
            action_type = "raises to"
            
        await interaction.response.send_message(
            f"{interaction.user.mention} {action_type} {amount} chips\n"
            f"Pot: {room.betting_round.pot}"
        )
    except ValueError as e:
        await interaction.response.send_message(str(e))
# Add these new commands after existing commands
@tree.command(name="add_chips", description="[Admin Only] Add chips to a player")
async def add_chips(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Only admin can use this command!", ephemeral=True)
    
    current_chips = player_manager.get_player_chips(interaction.guild.id, user.id)["chips"]
    new_chips = current_chips + amount
    player_manager.update_player_chips(interaction.guild.id, user.id, new_chips)
    await interaction.response.send_message(f"Added {amount} chips to {user.name}. New balance: {new_chips}")

@tree.command(name="set_chips", description="[Admin Only] Set chips for a player")
async def set_chips(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Only admin can use this command!", ephemeral=True)
    
    player_manager.update_player_chips(interaction.guild.id, user.id, amount)
    await interaction.response.send_message(f"Set {user.name}'s chips to {amount}")

@tree.command(name="reset_chips", description="[Admin Only] Reset all players' chips")
async def reset_chips(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Only admin can use this command!", ephemeral=True)
    
    players = player_manager.load_players(interaction.guild.id)
    for player_id in players:
        player_manager.update_player_chips(interaction.guild.id, int(player_id), 0)
    await interaction.response.send_message("All players' chips have been reset to 0")

# Add these new commands
@tree.command(name="register", description="Register your account to play poker")
async def register(interaction: discord.Interaction, email: str = None):
    if player_manager.is_registered(interaction.guild.id, interaction.user.id):
        return await interaction.response.send_message(
            "You are already registered!", 
            ephemeral=True
        )
    
    player_manager.register_player(
        interaction.guild.id,
        interaction.user.id,
        interaction.user.name,
        email
    )
    
    embed = Embed(
        title="Registration Successful!", 
        color=discord.Color.green()
    )
    embed.add_field(
        name="Player", 
        value=interaction.user.mention, 
        inline=True
    )
    embed.add_field(
        name="Starting Chips", 
        value="0", 
        inline=True
    )
    embed.set_footer(
        text="Ask an admin to add chips to your account to start playing!"
    )
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="profile", description="View your poker profile")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    
    if not player_manager.is_registered(interaction.guild.id, target_user.id):
        return await interaction.response.send_message(
            f"{target_user.name} is not registered! Use /register to create an account.",
            ephemeral=True
        )
    
    player_data = player_manager.get_player_chips(interaction.guild.id, target_user.id)
    
    embed = Embed(
        title=f"Poker Profile - {target_user.name}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Chips", value=str(player_data["chips"]), inline=True)
    embed.add_field(name="Total Games", value=str(player_data.get("total_games", 0)), inline=True)
    embed.add_field(name="Wins", value=str(player_data.get("wins", 0)), inline=True)
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="clear_chips", description="[Admin Only] Clear chips for a specific player")
async def clear_chips(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message(
            "Only admin can use this command!", 
            ephemeral=True
        )
    
    if not player_manager.is_registered(interaction.guild.id, user.id):
        return await interaction.response.send_message(
            f"{user.name} is not registered!", 
            ephemeral=True
        )
    
    current_chips = player_manager.get_player_chips(interaction.guild.id, user.id)["chips"]
    player_manager.update_player_chips(interaction.guild.id, user.id, 0)
    
    embed = Embed(
        title="Chips Cleared",
        description=f"Cleared chips for {user.mention}",
        color=discord.Color.red()
    )
    embed.add_field(name="Previous Balance", value=str(current_chips), inline=True)
    embed.add_field(name="New Balance", value="0", inline=True)
    embed.set_footer(text=f"Cleared by {interaction.user.name}")
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="create_room", description="Create a poker room with custom settings")
async def create_room(
    interaction: discord.Interaction, 
    small_blind: int = 10, 
    big_blind: int = 20, 
    timer: int = 30,
    min_buy_in: int = 1000,
    max_buy_in: int = 10000
):
    if interaction.channel.id in active_rooms:
        return await interaction.response.send_message("A poker room already exists in this channel!")
    
    settings = RoomSettings(
        small_blind=small_blind,
        big_blind=big_blind,
        timer=timer,
        min_buy_in=min_buy_in,
        max_buy_in=max_buy_in
    )
    
    room = PokerRoom(interaction.channel, interaction.user, settings)
    active_rooms[interaction.channel.id] = room
    room_id_map[room.id] = interaction.channel.id
    
    embed = Embed(
        title="🎲 Poker Room Created",
        description=f"Room ID: `{room.id}`",
        color=discord.Color.green()
    )
    embed.add_field(name="Small Blind", value=str(small_blind), inline=True)
    embed.add_field(name="Big Blind", value=str(big_blind), inline=True)
    embed.add_field(name="Timer", value=f"{timer}s", inline=True)
    embed.add_field(name="Buy-in Range", value=f"{min_buy_in} - {max_buy_in}", inline=True)
    embed.add_field(name="Room ID", value=f"`{room.id}`", inline=True)
    embed.set_footer(text=f"Created by {interaction.user.name}")
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="join_room", description="Join the poker room")
async def join_room(interaction: discord.Interaction, buy_in: int):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room in this channel!")
    
    room = active_rooms[interaction.channel.id]
    player_data = player_manager.get_player_chips(interaction.guild.id, interaction.user.id)
    
    if not player_manager.is_registered(interaction.guild.id, interaction.user.id):
        return await interaction.response.send_message("You need to register first! Use /register")
    
    if player_data["chips"] < buy_in:
        return await interaction.response.send_message("You don't have enough chips!")
    
    try:
        room.add_player(interaction.user, buy_in)
        player_manager.update_player_chips(
            interaction.guild.id, 
            interaction.user.id, 
            player_data["chips"] - buy_in
        )
        await interaction.response.send_message(f"{interaction.user.mention} joined with {buy_in} chips!")
    except ValueError as e:
        await interaction.response.send_message(str(e))

@tree.command(name="join_room_by_id", description="Join a poker room using its ID")
async def join_room_by_id(interaction: discord.Interaction, room_id: str, buy_in: int):
    if room_id not in room_id_map:
        return await interaction.response.send_message("Invalid room ID!")
    
    channel_id = room_id_map[room_id]
    room = active_rooms[channel_id]
    
    player_data = player_manager.get_player_chips(interaction.guild.id, interaction.user.id)
    
    if not player_manager.is_registered(interaction.guild.id, interaction.user.id):
        return await interaction.response.send_message("You need to register first! Use /register")
    
    if player_data["chips"] < buy_in:
        return await interaction.response.send_message("You don't have enough chips!")
    
    try:
        room.add_player(interaction.user, buy_in)
        player_manager.update_player_chips(
            interaction.guild.id, 
            interaction.user.id, 
            player_data["chips"] - buy_in
        )
        await interaction.response.send_message(
            f"{interaction.user.mention} joined room {room_id} with {buy_in} chips!"
        )
    except ValueError as e:
        await interaction.response.send_message(str(e))

@tree.command(name="leave_room", description="Leave the poker room")
async def leave_room(interaction: discord.Interaction):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room in this channel!")
    
    room = active_rooms[interaction.channel.id]
    chips_returned = room.remove_player(interaction.user)
    
    if chips_returned > 0:
        player_data = player_manager.get_player_chips(interaction.guild.id, interaction.user.id)
        player_manager.update_player_chips(
            interaction.guild.id,
            interaction.user.id,
            player_data["chips"] + chips_returned
        )
        await interaction.response.send_message(f"{interaction.user.mention} left with {chips_returned} chips!")
    else:
        await interaction.response.send_message("You're not in this room!")
@tree.command(name="view_rooms", description="View all active poker rooms")
async def view_rooms(interaction: discord.Interaction):
    if not active_rooms:
        return await interaction.response.send_message("No active poker rooms!")
    
    embed = Embed(
        title="🎲 Active Poker Rooms",
        description=f"Total Rooms: {len(active_rooms)}",
        color=discord.Color.blue()
    )
    
    for channel_id, room in active_rooms.items():
        channel = room.channel
        players_str = "\n".join([
            f"• {player.name} ({room.players[player.id]} chips)"
            for player in room.seated_players
        ]) or "No players"
        
        field_value = (
            f"**Room ID:** `{room.id}`\n"
            f"**Owner:** {room.owner.mention}\n"
            f"**Settings:**\n"
            f"• Small Blind: {room.settings.small_blind}\n"
            f"• Big Blind: {room.settings.big_blind}\n"
            f"• Timer: {room.settings.timer}s\n"
            f"• Buy-in: {room.settings.min_buy_in} - {room.settings.max_buy_in}\n"
            f"**Players:**\n{players_str}"
        )
        
        embed.add_field(
            name=f"📍 {channel.name}",
            value=field_value,
            inline=False
        )
        
        # Add status indicator
        status = "🟢 Active" if room.active else "⚪ Waiting"
        embed.add_field(
            name="Status",
            value=status,
            inline=True
        )
        
        # Add player count
        embed.add_field(
            name="Players",
            value=f"{len(room.seated_players)}/{room.settings.max_players}",
            inline=True
        )
        
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for spacing
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="close_room", description="Close a poker room")
async def close_room(interaction: discord.Interaction):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room in this channel!")
    
    room = active_rooms[interaction.channel.id]
    if interaction.user != room.owner and not is_admin(interaction.user.id):
        return await interaction.response.send_message("Only the room owner or admin can close the room!")
    
    # Return chips to all players
    for player_id, chips in room.players.items():
        player_data = player_manager.get_player_chips(interaction.guild.id, player_id)
        player_manager.update_player_chips(
            interaction.guild.id,
            player_id,
            player_data["chips"] + chips
        )
    
    # Clean up room data
    room_id = room.id
    del active_rooms[interaction.channel.id]
    del room_id_map[room_id]
    
    await interaction.response.send_message("Room closed and all chips returned to players.")

@tree.command(name="start_game", description="Start the poker game in this room")
async def start_game(interaction: discord.Interaction):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room in this channel!")
    
    room = active_rooms[interaction.channel.id]
    if interaction.user != room.owner:
        return await interaction.response.send_message("Only the room owner can start the game!")
    
    if len(room.seated_players) < 2:
        return await interaction.response.send_message("Need at least 2 players to start!")

    # Set room as active and start new hand
    room.active = True
    await room.start_new_hand()
    positions = room.get_positions()
    
    # Create status embed
    embed = discord.Embed(
        title="🎮 New Hand Started!",
        description="The game has begun!",
        color=discord.Color.green()
    )

    # Add dealer position
    if "dealer" in positions:
        embed.add_field(
            name="Dealer", 
            value=positions["dealer"].mention, 
            inline=True
        )

    # Add small blind position if exists
    if "sb" in positions:
        embed.add_field(
            name="Small Blind", 
            value=f"{positions['sb'].mention} ({room.settings.small_blind})", 
            inline=True
        )

    # Add big blind position if exists
    if "bb" in positions:
        embed.add_field(
            name="Big Blind", 
            value=f"{positions['bb'].mention} ({room.settings.big_blind})", 
            inline=True
        )

    # Get next player to act
    next_player = room.get_next_to_act()
    if next_player:
        embed.add_field(
            name="Next to Act", 
            value=next_player.mention, 
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@tree.command()
@app_commands.describe(
    action="Choose your action (check, call, bet, raise, or fold)",
    amount="Amount for bet/raise (if applicable)"
)
async def action(
    interaction: discord.Interaction,
    action: Literal["check", "call", "bet", "raise", "fold"],
    amount: Optional[int] = None
):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("❌ No active poker room!", ephemeral=True)
    
    room = active_rooms[interaction.channel.id]
    if not room.active:
        return await interaction.response.send_message("❌ Game hasn't started!", ephemeral=True)
    
    current_player = room.get_next_to_act()
    if interaction.user != current_player:
        return await interaction.response.send_message("❌ It's not your turn!", ephemeral=True)
    
    try:
        action_result = None
        if action == "check":
            action_result = await room.handle_check(interaction.user)
        elif action == "call":
            action_result = await room.handle_call(interaction.user)
        elif action == "bet":
            if amount is None:
                return await interaction.response.send_message("❌ You must specify an amount for bet!", ephemeral=True)
            action_result = await room.handle_bet(interaction.user, amount)
        elif action == "raise":
            if amount is None:
                return await interaction.response.send_message("❌ You must specify an amount for raise!", ephemeral=True)
            action_result = await room.handle_raise(interaction.user, amount)
        elif action == "fold":
            action_result = await room.handle_fold(interaction.user)
        
        # Create action embed
        embed = discord.Embed(
            title="Player Action",
            description=f"{interaction.user.mention} chose to {action}",
            color=discord.Color.blue()
        )
        
        if amount:
            embed.add_field(name="Amount", value=str(amount), inline=True)
        
        embed.add_field(name="Pot", value=str(room.betting_state.pot), inline=True)
        
        # Get next player
        next_player = room.get_next_to_act()
        if next_player:
            embed.add_field(name="Next to Act", value=next_player.mention, inline=False)
        
        await interaction.response.send_message(embed=embed)
        
    except ValueError as e:
        await interaction.response.send_message(f"❌ {str(e)}", ephemeral=True)

if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        raise ValueError("No Discord token found in .env file")
    bot.run(TOKEN.strip())  # Add strip() to remove any whitespace