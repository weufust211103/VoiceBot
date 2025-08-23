from dataclasses import dataclass
from datetime import datetime, timedelta
import uuid
from typing import List, Dict, Tuple
import discord
from enum import Enum
from poker_actions import Action, BettingRound, ActionView
import asyncio
import random

class BettingRound(Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"

@dataclass
class RoomSettings:
    small_blind: int = 10
    big_blind: int = 20
    timer: int = 30  # seconds per action
    min_buy_in: int = 1000
    max_buy_in: int = 10000
    max_players: int = 6

class PokerRoom:
    def __init__(self, channel, owner, settings=None):
        self.id = str(uuid.uuid4())[:8]  # Create a shorter unique ID
        self.channel = channel
        self.owner = owner
        self.settings = settings or RoomSettings()
        self.players = {}  # {player_id: chips_in_play}
        self.seated_players = []  # Players in order
        self.dealer_position = 0  # Position of dealer button
        self.current_round = BettingRound.PREFLOP
        self.action_position = 0  # Current player to act
        self.last_aggressor = None  # Position of last player who bet/raised
        self.created_at = datetime.now()
        self.active = False
        self.current_turn_start = None
        self.current_player_idx = None
        self.betting_round = BettingRound(settings.small_blind, settings.big_blind)
        self.action_timeout = settings.timer if settings else 30
        self.turn_message = None  # Store the current turn message
        self.deck = []
        self.community_cards = []
        self.player_hands = {}  # {player_id: [card1, card2]}

    def add_player(self, player, buy_in):
        if len(self.players) >= self.settings.max_players:
            raise ValueError("Room is full")
        if buy_in < self.settings.min_buy_in or buy_in > self.settings.max_buy_in:
            raise ValueError(f"Buy-in must be between {self.settings.min_buy_in} and {self.settings.max_buy_in}")
        
        self.players[player.id] = buy_in
        self.seated_players.append(player)

    def remove_player(self, player):
        if player.id in self.players:
            chips = self.players.pop(player.id)
            self.seated_players.remove(player)
            return chips
        return 0

    def rotate_dealer(self):
        """Move dealer button to next player"""
        self.dealer_position = (self.dealer_position + 1) % len(self.seated_players)
        
    def get_positions(self) -> Dict[str, discord.Member]:
        """Get all special positions for current hand"""
        num_players = len(self.seated_players)
        if num_players < 2:
            return {}
            
        positions = {
            "dealer": self.seated_players[self.dealer_position],
            "sb": self.seated_players[(self.dealer_position + 1) % num_players],
            "bb": self.seated_players[(self.dealer_position + 2) % num_players],
        }
        
        # UTG (Under The Gun) is first to act preflop
        positions["utg"] = self.seated_players[(self.dealer_position + 3) % num_players]
        
        return positions
        
    def get_next_to_act(self) -> discord.Member:
        """Get the next player who should act based on current betting round"""
        if not self.seated_players:
            return None
            
        num_players = len(self.seated_players)
        
        if self.current_round == BettingRound.PREFLOP:
            # Preflop: Start with UTG (player after BB)
            if self.action_position == 0:  # First action
                self.action_position = (self.dealer_position + 3) % num_players
        else:
            # Post-flop: Start with first player after dealer
            if self.action_position == 0:  # First action
                self.action_position = (self.dealer_position + 1) % num_players
                
        current_player = self.seated_players[self.action_position]
        self.action_position = (self.action_position + 1) % num_players
        
        return current_player
        
    def setup_deck(self):
        """Initialize and shuffle deck"""
        suits = ['♥', '♦', '♣', '♠']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.deck = [(rank, suit) for suit in suits for rank in ranks]
        random.shuffle(self.deck)
        
    def deal_hole_cards(self):
        """Deal 2 cards to each player"""
        for player in self.seated_players:
            self.player_hands[player.id] = [self.deck.pop() for _ in range(2)]
            
    async def show_hole_cards(self, player: discord.Member):
        """Send player their hole cards in DM"""
        cards = self.player_hands.get(player.id, [])
        if cards:
            card_str = " ".join([f"{rank}{suit}" for rank, suit in cards])
            try:
                await player.send(f"Your hole cards: {card_str}")
            except discord.Forbidden:
                await self.channel.send(
                    f"{player.mention} I couldn't DM you. Please enable DMs from server members."
                )
                
    async def deal_community_cards(self, count: int):
        """Deal community cards and display them"""
        new_cards = [self.deck.pop() for _ in range(count)]
        self.community_cards.extend(new_cards)
        
        card_str = " ".join([f"{rank}{suit}" for rank, suit in new_cards])
        board_str = " ".join([f"{rank}{suit}" for rank, suit in self.community_cards])
        
        embed = discord.Embed(
            title="Community Cards",
            description=f"New: {card_str}\nBoard: {board_str}",
            color=discord.Color.blue()
        )
        await self.channel.send(embed=embed)
        
    def start_new_hand(self):
        """Setup for a new hand"""
        self.rotate_dealer()
        self.current_round = BettingRound.PREFLOP
        self.action_position = 0
        self.last_aggressor = None
        
        # Get positions for this hand
        positions = self.get_positions()
        
        # Post blinds
        if "sb" in positions:
            self.place_blind(positions["sb"], self.settings.small_blind)
        if "bb" in positions:
            self.place_blind(positions["bb"], self.settings.big_blind)
            
    def place_blind(self, player: discord.Member, amount: int):
        """Place blind bet for player"""
        if player.id in self.players:
            self.players[player.id] -= amount
            return True
        return False
        
    def next_betting_round(self):
        """Move to next betting round"""
        rounds = list(BettingRound)
        current_index = rounds.index(self.current_round)
        if current_index < len(rounds) - 1:
            self.current_round = rounds[current_index + 1]
            self.action_position = 0
            self.last_aggressor = None
            return True
        return False

    def is_turn_timeout(self):
        if not self.current_turn_start:
            return False
        return datetime.now() - self.current_turn_start > timedelta(seconds=self.settings.timer)

    def next_turn(self):
        if self.current_player_idx is None:
            self.current_player_idx = 0
        else:
            self.current_player_idx = (self.current_player_idx + 1) % len(self.seated_players)
        self.current_turn_start = datetime.now()
        return self.seated_players[self.current_player_idx]

    async def get_player_action(self, player):
        """Get action from player with timeout"""
        view = ActionView(self, player, timeout=self.action_timeout)
        message = await self.channel.send(
            f"{player.mention}'s turn to act! ({self.action_timeout}s)",
            view=view
        )
        
        try:
            await view.wait()
            action = view.action
            amount = view.amount
        except asyncio.TimeoutError:
            # Handle timeout
            if self.betting_round.current_bet == 0:
                action = Action.CHECK
                amount = 0
            else:
                action = Action.FOLD
                amount = 0
                
        await message.delete()
        return action, amount
        
    async def process_betting_round(self):
        """Handle a complete betting round"""
        players_to_act = self.seated_players.copy()
        while players_to_act:
            current_player = self.get_next_to_act()
            if current_player not in players_to_act:
                continue
                
            action, amount = await self.get_player_action(current_player)
            
            if action == Action.FOLD:
                self.handle_fold(current_player)
                players_to_act.remove(current_player)
                
            elif action == Action.CHECK:
                if self.betting_round.current_bet > 0:
                    # Can't check when there's a bet
                    self.handle_fold(current_player)
                players_to_act.remove(current_player)
                
            elif action == Action.BET:
                self.handle_bet(current_player, amount)
                self.betting_round.last_raiser = current_player.id
                # Everyone except bettor needs to act again
                players_to_act = [p for p in self.seated_players if p != current_player]
                
            elif action == Action.RAISE:
                if not self.is_valid_raise(amount):
                    self.handle_fold(current_player)
                else:
                    self.handle_raise(current_player, amount)
                    self.betting_round.last_raiser = current_player.id
                    # Everyone except raiser needs to act again
                    players_to_act = [p for p in self.seated_players if p != current_player]
                    
            elif action == Action.CALL:
                self.handle_call(current_player)
                players_to_act.remove(current_player)
                
        # Betting round complete
        return len(self.seated_players) > 1
    
    def handle_fold(self, player):
        """Remove player from hand"""
        self.seated_players.remove(player)
        
    async def handle_bet(self, player, amount):
        """Process an initial bet"""
        if self.betting_round.current_bet > 0:
            raise ValueError("Cannot bet when there's already a bet! Use call or raise.")
            
        if not self.betting_round.validate_bet(amount):
            raise ValueError(f"Minimum bet must be {self.betting_round.min_bet} chips")

        if amount > self.players[player.id]:
            raise ValueError("Not enough chips!")

        self.players[player.id] -= amount
        self.betting_round.pot += amount
        self.betting_round.current_bet = amount
        self.betting_round.player_bets[player.id] = amount
        self.betting_round.last_raiser = player.id
        
    async def handle_raise(self, player, amount):
        """Process a raise"""
        if self.betting_round.current_bet == 0:
            raise ValueError("Cannot raise when there's no bet! Use bet instead.")
            
        if not self.betting_round.validate_raise(amount):
            min_raise = self.betting_round.current_bet + self.betting_round.last_raise_amount
            raise ValueError(f"Minimum raise must be {min_raise} chips")

        if amount > self.players[player.id]:
            raise ValueError("Not enough chips!")

        raise_size = amount - self.betting_round.current_bet
        self.betting_round.last_raise_amount = raise_size
        
        # Remove any previous bet from this player
        previous_bet = self.betting_round.player_bets.get(player.id, 0)
        additional_chips = amount - previous_bet
        
        self.players[player.id] -= additional_chips
        self.betting_round.pot += additional_chips
        self.betting_round.current_bet = amount
        self.betting_round.player_bets[player.id] = amount
        self.betting_round.last_raiser = player.id

    async def handle_call(self, player):
        """Process a call"""
        if self.betting_round.current_bet == 0:
            raise ValueError("Cannot call when there's no bet!")

        call_amount = self.betting_round.get_call_amount(player.id)
        if call_amount == 0:
            raise ValueError("You have already called!")
            
        if call_amount > self.players[player.id]:
            raise ValueError("Not enough chips!")

        self.players[player.id] -= call_amount
        self.betting_round.pot += call_amount
        self.betting_round.player_bets[player.id] = self.betting_round.current_bet

    async def notify_turn(self, player: discord.Member):
        """Notify player that it's their turn and show available actions"""
        # Delete previous turn message if it exists
        if self.turn_message:
            try:
                await self.turn_message.delete()
            except discord.NotFound:
                pass

        embed = discord.Embed(
            title="🎮 Your Turn to Act!",
            description=f"{player.mention}, it's your turn!",
            color=discord.Color.green()
        )

        # Show available actions based on current betting round
        available_actions = []
        if self.betting_round.current_bet == 0:
            available_actions.extend(["/check", "/bet"])
        else:
            call_amount = self.betting_round.get_call_amount(player.id)
            available_actions.extend([f"/call ({call_amount} chips)", "/raise"])
        available_actions.append("/fold")

        embed.add_field(
            name="Available Actions",
            value="\n".join(available_actions),
            inline=False
        )
        
        # Show current pot and bet information
        embed.add_field(name="Current Pot", value=str(self.betting_round.pot), inline=True)
        embed.add_field(name="Current Bet", value=str(self.betting_round.current_bet), inline=True)
        embed.add_field(name="Your Chips", value=str(self.players.get(player.id, 0)), inline=True)
        
        # Add timer warning
        embed.set_footer(text=f"⏰ You have {self.settings.timer} seconds to act!")
        
        self.turn_message = await self.channel.send(
            content=f"{player.mention}", 
            embed=embed
        )

        # Start timer
        await asyncio.sleep(self.settings.timer - 5)  # Notify at 5 seconds remaining
        try:
            await self.turn_message.reply(
                f"⚠️ {player.mention} 5 seconds remaining to act!"
            )
        except discord.NotFound:
            pass  # Message might have been deleted if player already acted

    async def process_round_end(self):
        """Handle end of betting round and move to next stage"""
        if self.current_round == BettingRound.PREFLOP:
            # Deal flop
            await self.channel.send("**--- FLOP ---**")
            await self.deal_community_cards(3)
            self.current_round = BettingRound.FLOP
            
        elif self.current_round == BettingRound.FLOP:
            # Deal turn
            await self.channel.send("**--- TURN ---**")
            await self.deal_community_cards(1)
            self.current_round = BettingRound.TURN
            
        elif self.current_round == BettingRound.TURN:
            # Deal river
            await self.channel.send("**--- RIVER ---**")
            await self.deal_community_cards(1)
            self.current_round = BettingRound.RIVER
            
        elif self.current_round == BettingRound.RIVER:
            # Show down
            await self.showdown()
            return True
            
        # Reset betting round
        self.betting_round = BettingRound(self.settings.small_blind, self.settings.big_blind)
        self.action_position = 0
        return False
        
    async def showdown(self):
        """Handle showdown and determine winner"""
        # Show all hands
        embed = discord.Embed(
            title="🏆 Showdown",
            description="Community Cards: " + " ".join([f"{r}{s}" for r, s in self.community_cards]),
            color=discord.Color.gold()
        )
        
        for player in self.seated_players:
            cards = self.player_hands.get(player.id, [])
            hand_str = " ".join([f"{r}{s}" for r, s in cards])
            embed.add_field(
                name=player.name,
                value=hand_str,
                inline=True
            )
            
        await self.channel.send(embed=embed)
        
        # TODO: Implement hand evaluation logic
        # For now, just end the hand
        await self.channel.send("Hand complete! Starting new hand...")
        self.start_new_hand()
        
    async def start_new_hand(self):
        """Setup for a new hand"""
        self.rotate_dealer()
        self.current_round = BettingRound.PREFLOP
        self.action_position = 0
        self.last_aggressor = None
        
        # Get positions for this hand
        positions = self.get_positions()
        
        # Setup deck and deal hole cards
        self.setup_deck()
        self.community_cards = []
        self.player_hands = {}
        
        self.deal_hole_cards()
        for player in self.seated_players:
            await self.show_hole_cards(player)
            
        # Post blinds
        if "sb" in positions:
            self.place_blind(positions["sb"], self.settings.small_blind)
        if "bb" in positions:
            self.place_blind(positions["bb"], self.settings.big_blind)