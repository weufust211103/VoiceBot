from enum import Enum
from dataclasses import dataclass
import asyncio
from discord import ButtonStyle
from discord.ui import Button, View, Modal, TextInput
import discord
import random
from collections import namedtuple
from itertools import combinations
import math

# Poker Hand Evaluation
Card = namedtuple('Card', 'face, suit')
suits = ['♥', '♦', '♣', '♠']
faces = '2 3 4 5 6 7 8 9 10 j q k a'.split()
lowaces = 'a 2 3 4 5 6 7 8 9 10 j q k'.split()

def evaluate_hand(hand):
    handrankorder = (straightflush, fourofakind, fullhouse, flush_hand, straight, threeofakind, twopair, onepair, highcard)
    for func in handrankorder:
        result = func(hand)
        if result:
            return handrankorder.index(func), result[1]
    return None

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

def flush_hand(hand):
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

class Action(Enum):
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    FOLD = "fold"

@dataclass
class BettingRound:
    def __init__(self, small_blind: int, big_blind: int):
        self.current_bet = big_blind  # Start preflop bet at BB
        self.pot = 0
        self.last_raiser = None
        self.min_bet = big_blind
        self.last_raise_amount = big_blind
        self.player_bets = {}  # player_id: amount_bet

    def validate_bet(self, amount: int) -> bool:
        return amount >= self.min_bet

    def validate_raise(self, amount: int) -> bool:
        raise_size = amount - self.current_bet
        return raise_size >= self.last_raise_amount

    def get_call_amount(self, player_id: int) -> int:
        player_bet = self.player_bets.get(player_id, 0)
        return self.current_bet - player_bet

    def all_called(self, player_ids: list) -> bool:
        return all(self.player_bets.get(pid, 0) == self.current_bet for pid in player_ids if pid not in self.last_raiser)

class ActionView(View):
    def __init__(self, game, player, timeout=30):
        super().__init__(timeout=timeout)
        self.game = game
        self.player = player
        self.action = None
        self.amount = 0
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        betting_round = self.game.betting_round
        call_amount = betting_round.get_call_amount(self.player.id)

        # Preflop special case for BB
        is_preflop = len(self.game.community) == 0
        is_bb = self.game.players.index(self.player) == (self.game.dealer_index + 1) % len(self.game.players)
        all_called = betting_round.all_called([p.id for p in self.game.players])

        if is_preflop and is_bb and all_called and betting_round.current_bet == self.game.bb_amount:
            self.add_item(Button(label="Check", style=ButtonStyle.secondary, custom_id="check"))
        elif betting_round.current_bet == 0:
            self.add_item(Button(label="Check", style=ButtonStyle.secondary, custom_id="check"))
            self.add_item(Button(label="Bet", style=ButtonStyle.primary, custom_id="bet"))
        else:
            self.add_item(Button(label=f"Call {call_amount}", style=ButtonStyle.primary, custom_id="call"))
            self.add_item(Button(label="Raise", style=ButtonStyle.primary, custom_id="raise"))

        self.add_item(Button(label="Fold", style=ButtonStyle.danger, custom_id="fold"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.id

    @discord.ui.button(label="Check", style=ButtonStyle.secondary, custom_id="check")
    async def check(self, interaction: discord.Interaction, button: Button):
        self.action = Action.CHECK
        await interaction.response.send_message(f"{self.player.name} checked.")
        self.stop()

    @discord.ui.button(label="Bet", style=ButtonStyle.primary, custom_id="bet")
    async def bet(self, interaction: discord.Interaction, button: Button):
        modal = BetModal(self.game, self.player, minimum=self.game.bb_amount)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.amount:
            self.action = Action.BET
            self.amount = modal.amount
            await self.game.place_bet(self.player, self.amount)
            self.game.betting_round.current_bet = self.amount
            self.game.betting_round.last_raise_amount = self.amount - self.game.bb_amount
            await interaction.followup.send(f"{self.player.name} bet {self.amount}.")
        self.stop()

    @discord.ui.button(label="Call", style=ButtonStyle.primary, custom_id="call")
    async def call(self, interaction: discord.Interaction, button: Button):
        call_amount = self.game.betting_round.get_call_amount(self.player.id)
        self.action = Action.CALL
        self.amount = call_amount
        await self.game.place_bet(self.player, call_amount)
        await interaction.response.send_message(f"{self.player.name} called {call_amount}.")
        self.stop()

    @discord.ui.button(label="Raise", style=ButtonStyle.primary, custom_id="raise")
    async def raise_bet(self, interaction: discord.Interaction, button: Button):
        modal = BetModal(self.game, self.player, minimum=self.game.betting_round.current_bet + self.game.betting_round.last_raise_amount)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.amount:
            self.action = Action.RAISE
            self.amount = modal.amount
            raise_amount = self.amount - self.game.betting_round.current_bet
            await self.game.place_bet(self.player, raise_amount)
            self.game.betting_round.current_bet = self.amount
            self.game.betting_round.last_raise_amount = raise_amount
            self.game.betting_round.last_raiser = self.player.id
            await interaction.followup.send(f"{self.player.name} raised to {self.amount}.")
        self.stop()

    @discord.ui.button(label="Fold", style=ButtonStyle.danger, custom_id="fold")
    async def fold(self, interaction: discord.Interaction, button: Button):
        self.action = Action.FOLD
        self.game.folded.add(self.player.id)
        await interaction.response.send_message(f"{self.player.name} folded.")
        self.stop()

class BetModal(Modal, title="Raise/Bet Amount"):
    bet_amount = TextInput(label="Enter amount", style=discord.TextStyle.short, required=True)

    def __init__(self, game, player, minimum):
        super().__init__()
        self.game = game
        self.player = player
        self.amount = 0
        self.minimum = minimum

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.amount = int(self.bet_amount.value)
            if self.amount < self.minimum:
                await interaction.response.send_message(f"Minimum amount is {self.minimum}", ephemeral=True)
                return
            max_chips = self.game.player_chips[self.player.id]
            if self.amount > max_chips:
                self.amount = max_chips
                self.game.all_in.add(self.player.id)
            self.stop()
        except ValueError:
            await interaction.response.send_message("Invalid amount.", ephemeral=True)

class PokerGame:
    def __init__(self, bot, guild, players, text_channel, voice_channel, player_manager):
        self.bot = bot
        self.guild = guild
        self.players = players
        self.text_channel = text_channel
        self.voice_channel = voice_channel
        self.player_manager = player_manager
        self.player_chips = {p.id: player_manager.get_player_chips(guild.id, p.id)["chips"] for p in players}
        self.player_cards = {}
        self.community = []
        self.deck = []
        self.pot = 0
        self.betting_round = BettingRound(10, 20)  # SB=10, BB=20
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
        self.betting_round = BettingRound(self.sb_amount, self.bb_amount)  # Reset betting round
        self.folded.clear()
        self.all_in.clear()
        self.player_bets = {p.id: 0 for p in self.players}

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

        # Rotate dealer and update chips
        self.dealer_index = (self.dealer_index + 1) % len(self.players)
        for p in self.players:
            self.player_manager.update_player_chips(self.guild.id, p.id, self.player_chips[p.id])

    async def play(self):
        while len(self.players) > 1:
            await self.start_hand()
        if self.players:
            await self.text_channel.send(f"Game over! {self.players[0].mention} wins!")
        else:
            await self.text_channel.send("Game over! No winners.")

    def get_active_count(self):
        return len([p for p in self.players if p.id not in self.folded])

    async def place_bet(self, player, amount):
        if amount > self.player_chips[player.id]:
            amount = self.player_chips[player.id]
            self.all_in.add(player.id)
        self.player_chips[player.id] -= amount
        self.player_bets[player.id] += amount
        self.pot += amount
        self.betting_round.player_bets[player.id] = self.player_bets[player.id]

    async def betting_round(self, start_index):
        i = start_index
        while True:
            active_players = [p for p in self.players if p.id not in self.folded]
            if not active_players:
                break

            # Post-preflop condition: End only when all active players match current_bet or are all-in
            is_postflop = len(self.community) > 0
            if is_postflop:
                if all(self.betting_round.player_bets.get(p.id, 0) == self.betting_round.current_bet or p.id in self.all_in for p in active_players):
                    break
            # Preflop condition: Allow BB to check if all called
            else:
                is_bb = self.players[i % len(self.players)] == self.players[(self.dealer_index + 1) % len(self.players)]
                all_called = self.betting_round.all_called([p.id for p in self.players])
                if is_bb and all_called and self.betting_round.current_bet == self.bb_amount:
                    break

            p = self.players[i % len(self.players)]
            if p.id in self.folded or (p.id in self.all_in and self.betting_round.player_bets.get(p.id, 0) >= self.betting_round.current_bet):
                i += 1
                continue

            embed = self.get_table_embed()
            view = ActionView(self, p)
            await self.text_channel.send(f"{p.mention}'s turn.", embed=embed, view=view)
            await view.wait()
            if view.action == Action.CHECK:
                pass
            elif view.action == Action.CALL:
                await self.place_bet(p, view.amount)
            elif view.action == Action.BET:
                await self.place_bet(p, view.amount)
                self.betting_round.current_bet = view.amount
                self.betting_round.last_raise_amount = view.amount - self.bb_amount
                self.betting_round.last_raiser = p.id
            elif view.action == Action.RAISE:
                await self.place_bet(p, view.amount - self.betting_round.current_bet)
                self.betting_round.current_bet = view.amount
                self.betting_round.last_raise_amount = view.amount - self.betting_round.current_bet
                self.betting_round.last_raiser = p.id
            elif view.action == Action.FOLD:
                self.folded.add(p.id)
            i += 1

    def get_table_embed(self):
        embed = discord.Embed(title="Poker Table", color=discord.Color.green())
        community_str = ' '.join(f"{c.face.upper()}{c.suit}" for c in self.community) or "None"
        embed.add_field(name="Community Cards", value=community_str, inline=False)
        embed.add_field(name="Pot", value=self.pot, inline=False)
        for p in self.players:
            status = " (Folded)" if p.id in self.folded else " (All-in)" if p.id in self.all_in else ""
            embed.add_field(name=p.name + status, value=f"Chips: {self.player_chips[p.id]}\nBet: {self.player_bets.get(p.id, 0)}", inline=True)
        return embed

    async def update_table(self):
        embed = self.get_table_embed()
        await self.text_channel.send(embed=embed)

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
        winner_names = ', '.join(self.guild.get_member(wid).name for wid in winners)
        await self.text_channel.send(f"Showdown! Winners: {winner_names} each get {share}")