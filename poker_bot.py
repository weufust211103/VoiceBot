import discord
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
import random
from collections import namedtuple
from itertools import combinations
import asyncio
import math
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
from player_manager import PlayerManager

# Load environment variables
load_dotenv()
# Poker Hand Evaluation from Rosetta Code (adapted for Hold'em)
Card = namedtuple('Card', 'face, suit')

suits = ['♥', '♦', '♣', '♠']
faces = '2 3 4 5 6 7 8 9 10 j q k a'.split()
lowaces = 'a 2 3 4 5 6 7 8 9 10 j q k'.split()

def evaluate_hand(hand):
    # hand is list of 5 Cards
    handrankorder = (straightflush, fourofakind, fullhouse, flush_hand, straight, threeofakind, twopair, onepair, highcard)
    for func in handrankorder:
        result = func(hand)
        if result:
            return handrankorder.index(func), result[1]
    return None  # Should not happen

def best_hand(seven_cards):
    best_rank = math.inf
    best_tie = None
    best_key = None
    for five in combinations(seven_cards, 5):
        rank_index, tie = evaluate_hand(list(five))
        tie_indices = tuple(faces.index(f) for f in tie)
        current_key = (-rank_index, tie_indices)
        if best_key is None or current_key > best_key:
            best_rank = rank_index
            best_tie = tie
            best_key = current_key
    return best_rank, best_tie

# Hand check functions (from Rosetta Code)
def straightflush(hand):
    f, fs = (lowaces if any(card.face == '2' for card in hand) else faces, ' '.join(lowaces if any(card.face == '2' for card in hand) else faces))
    ordered = sorted(hand, key=lambda card: (faces.index(card.face), card.suit))
    first, rest = ordered[0], ordered[1:]
    if all(card.suit == first.suit for card in rest) and ' '.join(card.face for card in ordered) in fs:
        return 'straight-flush', [ordered[-1].face]
    return False

def fourofakind(hand):
    allfaces = [f for f, s in hand]
    allftypes = set(allfaces)
    if len(allftypes) != 2:
        return False
    for f in allftypes:
        if allfaces.count(f) == 4:
            allftypes.remove(f)
            return 'four-of-a-kind', [f, allftypes.pop()]
    return False

def fullhouse(hand):
    allfaces = [f for f, s in hand]
    allftypes = set(allfaces)
    if len(allftypes) != 2:
        return False
    for f in allftypes:
        if allfaces.count(f) == 3:
            allftypes.remove(f)
            return 'full-house', [f, allftypes.pop()]
    return False

def flush_hand(hand):  # renamed to avoid conflict with built-in flush
    allstypes = {s for f, s in hand}
    if len(allstypes) == 1:
        allfaces = [f for f, s in hand]
        return 'flush', sorted(allfaces, key=lambda f: faces.index(f), reverse=True)
    return False

def straight(hand):
    f, fs = (lowaces if any(card.face == '2' for card in hand) else faces, ' '.join(lowaces if any(card.face == '2' for card in hand) else faces))
    ordered = sorted(hand, key=lambda card: (faces.index(card.face), card.suit))
    if ' '.join(card.face for card in ordered) in fs:
        return 'straight', [ordered[-1].face]
    return False

def threeofakind(hand):
    allfaces = [f for f, s in hand]
    allftypes = set(allfaces)
    if len(allftypes) <= 2:
        return False
    for f in allftypes:
        if allfaces.count(f) == 3:
            allftypes.remove(f)
            return 'three-of-a-kind', [f] + sorted(allftypes, key=lambda f: faces.index(f), reverse=True)
    return False

def twopair(hand):
    allfaces = [f for f, s in hand]
    allftypes = set(allfaces)
    pairs = [f for f in allftypes if allfaces.count(f) == 2]
    if len(pairs) != 2:
        return False
    p0, p1 = sorted(pairs, key=lambda f: faces.index(f), reverse=True)
    other = list(allftypes - set(pairs))
    return 'two-pair', [p0, p1] + other

def onepair(hand):
    allfaces = [f for f, s in hand]
    allftypes = set(allfaces)
    pairs = [f for f in allftypes if allfaces.count(f) == 2]
    if len(pairs) != 1:
        return False
    allftypes.remove(pairs[0])
    return 'one-pair', pairs + sorted(allftypes, key=lambda f: faces.index(f), reverse=True)

def highcard(hand):
    allfaces = [f for f, s in hand]
    return 'high-card', sorted(allfaces, key=lambda f: faces.index(f), reverse=True)

# Poker Game Class
class PokerGame:
    def __init__(self, bot, guild, players, text_channel, voice_channel):
        self.bot = bot
        self.guild = guild
        self.players = players
        self.text_channel = text_channel
        self.voice_channel = voice_channel
        self.player_manager = PlayerManager()
        # Initialize chips from PlayerManager instead of fixed 1000
        self.player_chips = {
            p.id: self.player_manager.get_player_chips(guild.id, p.id)["chips"] 
            for p in players
        }
        self.player_cards = {}
        self.community = []
        self.deck = []
        self.pot = 0
        self.current_bet = 0
        self.player_bets = {}
        self.folded = set()
        self.all_in = set()
        self.dealer_index = 0
        self.sb_amount = 10
        self.bb_amount = 20

    def create_deck(self):
        return [Card(r, s) for s in suits for r in faces]

    async def start_hand(self):
        self.deck = self.create_deck()
        random.shuffle(self.deck)
        self.community = []
        self.pot = 0
        self.current_bet = 0
        self.player_bets = {p.id: 0 for p in self.players}
        self.folded = set()
        self.all_in = set()

        # Deal hole cards
        for p in self.players:
            cards = [self.deck.pop() for _ in range(2)]
            self.player_cards[p.id] = cards
            await p.send(f"Your hole cards: {cards[0]} {cards[1]}")

        # Post blinds
        sb_index = (self.dealer_index + 1) % len(self.players)
        bb_index = (sb_index + 1) % len(self.players)
        await self.place_bet(self.players[sb_index], self.sb_amount)
        await self.place_bet(self.players[bb_index], self.bb_amount)
        self.current_bet = self.bb_amount

        # Preflop betting
        await self.betting_round((bb_index + 1) % len(self.players))

        if self.get_active_count() > 1:
            self.deck.pop()  # burn
            self.community.extend([self.deck.pop() for _ in range(3)])
            await self.update_table()
            await self.betting_round((self.dealer_index + 1) % len(self.players))

        if self.get_active_count() > 1:
            self.deck.pop()
            self.community.append(self.deck.pop())
            await self.update_table()
            await self.betting_round((self.dealer_index + 1) % len(self.players))

        if self.get_active_count() > 1:
            self.deck.pop()
            self.community.append(self.deck.pop())
            await self.update_table()
            await self.betting_round((self.dealer_index + 1) % len(self.players))

        if self.get_active_count() > 1:
            await self.showdown()

        # Rotate dealer
        self.dealer_index = (self.dealer_index + 1) % len(self.players)

        # Remove busted players
        self.players = [p for p in self.players if self.player_chips[p.id] > 0]

    async def play(self):
        while len(self.players) > 1:
            await self.start_hand()
        if self.players:
            await self.text_channel.send(f"Game over! {self.players[0].mention} wins!")
        else:
            await self.text_channel.send("Game over! No winners.")

    def get_active_count(self):
        return len([p for p in self.players if p.id not in self.folded])

    # Modify the place_bet method to update PlayerManager
    async def place_bet(self, player, amount):
        if amount > self.player_chips[player.id]:
            amount = self.player_chips[player.id]
            self.all_in.add(player.id)
        self.player_chips[player.id] -= amount
        self.player_bets[player.id] += amount
        self.pot += amount
        # Update chips in PlayerManager
        self.player_manager.update_player_chips(
            self.guild.id, 
            player.id, 
            self.player_chips[player.id]
        )

    async def betting_round(self, start_index):
        i = start_index
        while True:
            active_players = [p for p in self.players if p.id not in self.folded]
            if all(self.player_bets[p.id] == self.current_bet or p.id in self.all_in for p in active_players):
                break
            p = self.players[i % len(self.players)]
            if p.id in self.folded or (p.id in self.all_in and self.player_bets[p.id] >= self.current_bet):
                i += 1
                continue
            embed = self.get_table_embed()
            view = PokerView(self, p)
            await self.text_channel.send(f"{p.mention}'s turn.", embed=embed, view=view)
            await view.wait()
            i += 1

    def get_table_embed(self):
        embed = discord.Embed(title="Poker Table", color=discord.Color.green())
        community_str = ' '.join(f"{c.face.upper()}{c.suit}" for c in self.community) or "None"
        embed.add_field(name="Community Cards", value=community_str, inline=False)
        embed.add_field(name="Pot", value=self.pot, inline=False)
        for p in self.players:
            status = " (Folded)" if p.id in self.folded else " (All-in)" if p.id in self.all_in else ""
            embed.add_field(name=p.name + status, value=f"Chips: {self.player_chips[p.id]}\nBet: {self.player_bets[p.id]}", inline=True)
        return embed

    async def update_table(self):
        embed = self.get_table_embed()
        await self.text_channel.send(embed=embed)

    # Modify the showdown method to update PlayerManager
    async def showdown(self):
        remaining = [p for p in self.players if p.id not in self.folded]
        hands = {}
        for p in remaining:
            seven = self.player_cards[p.id] + self.community
            hands[p.id] = best_hand(seven)
        key_func = lambda pid: (-hands[pid][0], tuple(faces.index(f) for f in hands[pid][1]))
        max_key = max([pid for pid in hands], key=key_func)
        max_value = key_func(max_key)
        winners = [pid for pid in hands if key_func(pid) == max_value]
        share = self.pot // len(winners)
        for wid in winners:
            self.player_chips[wid] += share
            # Update chips in PlayerManager
            self.player_manager.update_player_chips(
                self.guild.id,
                wid,
                self.player_chips[wid]
            )
        winner_names = ', '.join(self.guild.get_member(wid).name for wid in winners)
        await self.text_channel.send(f"Showdown! Winners: {winner_names} each get {share}")

class PokerView(View):
    def __init__(self, game, player):
        super().__init__(timeout=300)
        self.game = game
        self.player = player
        self.add_item(Button(label="Fold", style=discord.ButtonStyle.red, callback=self.fold))
        call_label = "Check" if game.player_bets[player.id] == game.current_bet else "Call"
        self.add_item(Button(label=call_label, style=discord.ButtonStyle.green, callback=self.call_check))
        self.add_item(Button(label="Raise", style=discord.ButtonStyle.primary, callback=self.raise_bet))

    async def fold(self, interaction: discord.Interaction):
        if interaction.user != self.player:
            return await interaction.response.send_message("Not your turn!", ephemeral=True)
        self.game.folded.add(self.player.id)
        await interaction.response.send_message(f"{self.player.name} folded.")
        self.stop()

    async def call_check(self, interaction: discord.Interaction):
        if interaction.user != self.player:
            return await interaction.response.send_message("Not your turn!", ephemeral=True)
        amount = self.game.current_bet - self.game.player_bets[self.player.id]
        await self.game.place_bet(self.player, amount)
        action = "checked" if amount == 0 else "called"
        await interaction.response.send_message(f"{self.player.name} {action}.")
        self.stop()

    async def raise_bet(self, interaction: discord.Interaction):
        if interaction.user != self.player:
            return await interaction.response.send_message("Not your turn!", ephemeral=True)
        modal = BetModal(self.game, self.player)
        await interaction.response.send_modal(modal)

class BetModal(Modal, title="Raise Amount"):
    bet_amount = TextInput(label="Enter raise amount", style=discord.TextStyle.short)

    def __init__(self, game, player):
        super().__init__()
        self.game = game
        self.player = player

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value)
            min_raise = self.game.current_bet * 2 - self.game.player_bets[self.player.id]
            if amount < min_raise:
                return await interaction.response.send_message(f"Minimum raise is {min_raise}", ephemeral=True)
            add_amount = amount - self.game.player_bets[self.player.id]
            await self.game.place_bet(self.player, add_amount)
            self.game.current_bet = amount
            await interaction.response.send_message(f"{self.player.name} raised to {amount}.")
        except ValueError:
            await interaction.response.send_message("Invalid amount.", ephemeral=True)
