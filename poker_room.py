import discord
from dataclasses import dataclass
from enum import Enum
import random
import uuid
from typing import Dict
from discord import app_commands
from datetime import datetime
import os
from dotenv import load_dotenv

from player_manager import PlayerManager
from poker_table import PokerTable
from poker_actions import Action  # Import Action from our new file

# Load environment variables
load_dotenv()

class GameRound(Enum):  # Renamed from BettingRound to GameRound
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"

@dataclass
class BettingState:
    small_blind: int
    big_blind: int = 20
    current_bet: int = 0
    pot: int = 0
    last_raiser: int = None
    player_bets: dict = None

    def __post_init__(self):
        if self.player_bets is None:
            self.player_bets = {}

@dataclass
class RoomSettings:
    small_blind: int = 10
    big_blind: int = 20
    timer: int = 30
    min_buy_in: int = 1000
    max_buy_in: int = 10000
    max_players: int = 6

class PokerRoom:
    def __init__(self, channel, owner, settings=None):
        self.id = str(uuid.uuid4())[:8]
        self.channel = channel
        self.owner = owner
        self.settings = settings or RoomSettings()
        self.players = {}
        self.seated_players = []
        self.dealer_position = 0
        self.current_round = GameRound.PREFLOP
        self.betting_state = BettingState(
            small_blind=self.settings.small_blind,
            big_blind=self.settings.big_blind
        )
        self.action_position = 0
        self.deck = []
        self.community_cards = []
        self.player_hands = {}
        self.active = False

    def add_player(self, player: discord.Member, buy_in: int) -> None:
        """Add a player to the room with their buy-in amount"""
        # Validate buy-in amount
        if buy_in < self.settings.min_buy_in:
            raise ValueError(f"Buy-in must be at least {self.settings.min_buy_in} chips!")
        if buy_in > self.settings.max_buy_in:
            raise ValueError(f"Buy-in cannot exceed {self.settings.max_buy_in} chips!")
            
        # Check if room is full
        if len(self.seated_players) >= self.settings.max_players:
            raise ValueError("Room is full!")
            
        # Check if player is already seated
        if player in self.seated_players:
            raise ValueError("You are already seated!")
            
        # Add player to the room
        self.seated_players.append(player)
        self.players[player.id] = buy_in
        
        return True

    def remove_player(self, player: discord.Member) -> int:
        """Remove a player from the room and return their chips"""
        if player not in self.seated_players:
            return 0
            
        chips = self.players.get(player.id, 0)
        self.seated_players.remove(player)
        if player.id in self.players:
            del self.players[player.id]
            
        return chips

    def get_player_chips(self, player_id: int) -> int:
        """Get the number of chips a player has in the room"""
        return self.players.get(player_id, 0)

    def get_positions(self) -> Dict[str, discord.Member]:
        """Get player positions for the current hand"""
        positions = {}
        if not self.seated_players:
            return positions
            
        num_players = len(self.seated_players)
        
        # For heads-up (2 players)
        if num_players == 2:
            # Dealer is SB in heads-up
            positions["dealer"] = self.seated_players[self.dealer_position]
            positions["sb"] = self.seated_players[self.dealer_position]  # Dealer posts SB
            positions["bb"] = self.seated_players[(self.dealer_position + 1) % 2]  # Other player posts BB
            return positions
        
        # For 3-6 players
        if num_players >= 3:
            positions["dealer"] = self.seated_players[self.dealer_position]
            positions["sb"] = self.seated_players[(self.dealer_position + 1) % num_players]
            positions["bb"] = self.seated_players[(self.dealer_position + 2) % num_players]
            
            # Set UTG (Under The Gun) position
            positions["utg"] = self.seated_players[(self.dealer_position + 3) % num_players]
            
            # Additional positions for 4+ players
            if num_players >= 4:
                positions["mp"] = self.seated_players[(self.dealer_position + 4) % num_players]  # Middle Position
            if num_players >= 5:
                positions["co"] = self.seated_players[(self.dealer_position + 5) % num_players]  # Cut Off
    
        return positions

    async def start_new_hand(self):
        """Setup and start a new poker hand"""
        self.setup_deck()
        self.community_cards = []
        self.betting_state = BettingState(
            small_blind=self.settings.small_blind,
            big_blind=self.settings.big_blind
        )
        
        # Get positions first
        positions = self.get_positions()  # Remove await since it's not async anymore
        
        # Deal hole cards to players
        for player in self.seated_players:
            # Deal 2 cards to each player
            cards = [self.deck.pop() for _ in range(2)]
            self.player_hands[player.id] = cards
            
            # Send cards to player
            cards_str = " ".join([f"{rank}{suit}" for rank, suit in cards])
            embed = discord.Embed(
                title="🃏 Your Hole Cards",
                description=f"Your cards: {cards_str}",
                color=discord.Color.blue()
            )
            try:
                await player.send(embed=embed)
            except discord.Forbidden:
                await self.channel.send(
                    f"{player.mention}, I couldn't send you your cards. "
                    "Please enable DMs from server members."
                )
        
        # Post blinds
        if "sb" in positions:
            self.place_blind(positions["sb"], self.settings.small_blind)
        if "bb" in positions:
            self.place_blind(positions["bb"], self.settings.big_blind)
        
        self.active = True
        self.current_round = GameRound.PREFLOP
        self.action_position = 0

    def setup_deck(self):
        """Initialize and shuffle the deck"""
        suits = ['♥', '♦', '♣', '♠']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.deck = [(rank, suit) for suit in suits for rank in ranks]
        random.shuffle(self.deck)

    def place_blind(self, player: discord.Member, amount: int):
        """Place a blind bet for a player"""
        if player.id not in self.players:
            raise ValueError(f"{player.name} is not in the game!")
            
        if self.players[player.id] < amount:
            raise ValueError(f"{player.name} doesn't have enough chips for blind!")
            
        self.players[player.id] -= amount
        self.betting_state.pot += amount
        self.betting_state.current_bet = amount
        self.betting_state.player_bets[player.id] = amount

    def get_next_to_act(self) -> discord.Member:
        """Get the next player who should act based on current betting round"""
        if not self.seated_players:
            return None
            
        num_players = len(self.seated_players)
        
        # Heads-up (2 players) special case
        if num_players == 2:
            if self.current_round == GameRound.PREFLOP:
                # In heads-up preflop, BB acts first
                if self.action_position == 0:
                    self.action_position = (self.dealer_position + 1) % 2
            else:
                # Post-flop in heads-up, SB (dealer) acts first
                if self.action_position == 0:
                    self.action_position = self.dealer_position
        else:
            # 3+ players
            if self.current_round == GameRound.PREFLOP:
                # UTG acts first preflop (player after BB)
                if self.action_position == 0:
                    self.action_position = (self.dealer_position + 3) % num_players
            else:
                # First active player after dealer acts first post-flop
                if self.action_position == 0:
                    self.action_position = (self.dealer_position + 1) % num_players
        
        current_player = self.seated_players[self.action_position]
        self.action_position = (self.action_position + 1) % num_players
        
        return current_player

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
games = {}  # Add this decorator
active_rooms = {}
room_id_map = {}
DEFAULT_SETTINGS = RoomSettings()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

@bot.event
async def on_ready():
    print(f'====== Bot Status ======')
    print(f'Logged in as: {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print(f'Connected to {len(bot.guilds)} servers')
    print(f'Active rooms: {len(active_rooms)}')
    print(f'Discord.py version: {discord.__version__}')
    print(f'=====================')
    try:
        await tree.sync()
        print('Command tree synced!')
    except Exception as e:
        print(f'Error syncing commands: {e}')

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
        return await interaction.response.send_message("You are already registered!", ephemeral=True)
    
    player_manager.register_player(
        interaction.guild.id,
        interaction.user.id,
        interaction.user.name,
        email
    )
    
    # Send DM with registration details
    try:
        await interaction.user.send(
            f"✅ **Registration Successful!**\n"
            f"Welcome to the poker game, {interaction.user.name}!\n"
            f"Your account has been created. You can now join poker rooms and start playing!\n\n"
            f"🔑 **Account Details:**\n"
            f"• **User ID:** {interaction.user.id}\n"
            f"• **Email:** {email}\n\n"
            f"♠️ ♥️ ♦️ ♣️ **Get Started:** ♠️ ♥️ ♦️ ♣️\n"
            f"Join a voice channel and use `/start_poker` to create a new game.\n"
            f"Or, use `/join_room` to join an existing game.\n\n"
            f"📜 **Rules:**\n"
            f"Please make sure to read the game rules before you start playing. Use `/rules` to view the rules.\n\n"
            f"Good luck at the tables!",
            embed=embed
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "Registration successful, but I couldn't send you a DM with your details. Please check your DM settings.",
            ephemeral=True
        )
    
    await interaction.response.send_message(
        "Registration successful! Please check your DMs for your account details.",
        ephemeral=True
    )

@tree.command(name="profile", description="View your poker profile")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    
    if not player_manager.is_registered(interaction.guild.id, target_user.id):
        return await interaction.response.send_message(
            f"{target_user.name} is not registered! Use /register to create an account.",
            ephemeral=True
        )
    
    player_data = player_manager.get_player_chips(interaction.guild.id, target_user.id)
    embed = discord.Embed(
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
        return await interaction.response.send_message("Only admin can use this command!", ephemeral=True)
    
    if not player_manager.is_registered(interaction.guild.id, user.id):
        return await interaction.response.send_message(
            f"{user.name} is not registered!",
            ephemeral=True
        )
    
    current_chips = player_manager.get_player_chips(interaction.guild.id, user.id)["chips"]
    player_manager.update_player_chips(interaction.guild.id, user.id, 0)
    
    embed = discord.Embed(
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
    
    embed = discord.Embed(
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
        await room.add_player(interaction.user, buy_in)
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
        await interaction.response.send_message(f"{interaction.user.mention} left the room.")

@tree.command(name="view_rooms", description="View all active poker rooms")
async def view_rooms(interaction: discord.Interaction):
    if not active_rooms:
        return await interaction.response.send_message("No active poker rooms!")
    
    embed = discord.Embed(
        title="🎲 Active Poker Rooms",
        description=f"Total Rooms: {len(active_rooms)}",
        color=discord.Color.blue()
    )
    
    for room in active_rooms.values():
        players_str = "\n".join([f"• {player.name} ({room.players[player.id]} chips)" for player in room.seated_players]) or "No players"
        embed.add_field(
            name=f"📍 {room.channel.name}",
            value=(
                f"**Room ID:** `{room.id}`\n"
                f"**Owner:** {room.owner.mention}\n"
                f"**Settings:**\n"
                f"• Small Blind: {room.settings.small_blind}\n"
                f"• Big Blind: {room.settings.big_blind}\n"
                f"• Timer: {room.settings.timer}s\n"
                f"• Buy-in: {room.settings.min_buy_in} - {room.settings.max_buy_in}\n"
                f"**Players:**\n{players_str}"
            ),
            inline=False
        )
    
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
    embed.add_field(name="Dealer", value=positions["dealer"].mention, inline=True)
    embed.add_field(name="Small Blind", value=f"{positions['sb'].mention} ({room.settings.small_blind})", inline=True)
    embed.add_field(name="Big Blind", value=f"{positions['bb'].mention} ({room.settings.big_blind})", inline=True)
    embed.add_field(name="Next to Act", value=room.get_next_to_act().mention, inline=False)
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="call", description="Call the current bet")
async def call(interaction: discord.Interaction):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room!")
    
    room = active_rooms[interaction.channel.id]
    if not room.active:
        return await interaction.response.send_message("Game hasn't started!")
    
    if interaction.user != room.get_next_to_act():
        return await interaction.response.send_message("It's not your turn!")
    
    try:
        await room.handle_call(interaction.user)
        call_amount = room.betting_round.current_bet
        await interaction.response.send_message(
            f"{interaction.user.mention} calls {call_amount}\n"
            f"Pot: {room.betting_round.pot}"
        )
    except ValueError as e:
        await interaction.response.send_message(str(e))

@tree.command(name="raise", description="Raise the current bet")
async def raise_bet(interaction: discord.Interaction, amount: int):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room!")
    
    room = active_rooms[interaction.channel.id]
    if not room.active:
        return await interaction.response.send_message("Game hasn't started!")
    
    if interaction.user != room.get_next_to_act():
        return await interaction.response.send_message("It's not your turn!")
    
    try:
        await room.handle_raise(interaction.user, amount)
        await interaction.response.send_message(
            f"{interaction.user.mention} raises to {amount}\n"
            f"Pot: {room.betting_round.pot}"
        )
    except ValueError as e:
        await interaction.response.send_message(str(e))

@tree.command(name="check", description="Check the current bet")
async def check(interaction: discord.Interaction):
    if interaction.channel.id not in active_rooms:
        return await interaction.response.send_message("No active poker room!")
    
    room = active_rooms[interaction.channel.id]
    if not room.active:
        return await interaction.response.send_message("Game hasn't started!")
    
    if interaction.user != room.get_next_to_act():
        return await interaction.response.send_message("It's not your turn!")
    
    try:
        await room.handle_check(interaction.user)
        await interaction.response.send_message(f"{interaction.user.mention} checks")
    except ValueError as e:
        await interaction.response.send_message(str(e))