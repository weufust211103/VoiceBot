from enum import Enum
from dataclasses import dataclass
import asyncio
from discord import ButtonStyle
from discord.ui import Button, View
import discord

class Action(Enum):
    CHECK = "check"
    BET = "bet"
    RAISE = "raise"
    FOLD = "fold"
    CALL = "call"

@dataclass
class BettingRound:
    def __init__(self, small_blind: int, big_blind: int):
        self.current_bet = 0
        self.pot = 0
        self.last_raiser = None
        self.min_bet = big_blind  # Minimum bet must be at least the big blind
        self.last_raise_amount = big_blind  # Track the last raise amount
        self.player_bets = {}  # Track how much each player has bet this round

    def validate_bet(self, amount: int) -> bool:
        """Validate if a bet amount is legal"""
        return amount >= self.min_bet

    def validate_raise(self, amount: int) -> bool:
        """Validate if a raise amount is legal"""
        # Raise must be at least the size of the last raise
        raise_size = amount - self.current_bet
        return raise_size >= self.last_raise_amount

    def get_call_amount(self, player_id: int) -> int:
        """Get amount needed to call for a player"""
        player_bet = self.player_bets.get(player_id, 0)
        return self.current_bet - player_bet

class ActionView(View):
    def __init__(self, room, player, timeout=30):
        super().__init__(timeout=timeout)
        self.room = room
        self.player = player
        self.action = None
        self.amount = 0
        self.update_buttons()
        
    def update_buttons(self):
        self.clear_items()
        betting_round = self.room.betting_round
        
        if betting_round.current_bet == 0:
            # Can check or bet
            self.add_item(Button(label="Check", style=ButtonStyle.secondary, custom_id="check"))
            self.add_item(Button(label="Bet", style=ButtonStyle.primary, custom_id="bet"))
        else:
            # Must call, raise, or fold
            call_amount = betting_round.get_call_amount(self.player.id)
            self.add_item(Button(label=f"Call {call_amount}", style=ButtonStyle.primary, custom_id="call"))
            self.add_item(Button(label="Raise", style=ButtonStyle.primary, custom_id="raise"))
            
        # Can always fold
        self.add_item(Button(label="Fold", style=ButtonStyle.danger, custom_id="fold"))
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.id
        
    @discord.ui.button(label="Check", style=ButtonStyle.secondary, custom_id="check")
    async def check(self, interaction: discord.Interaction, button: Button):
        self.action = Action.CHECK
        self.stop()
        
    @discord.ui.button(label="Bet", style=ButtonStyle.primary, custom_id="bet")
    async def bet(self, interaction: discord.Interaction, button: Button):
        modal = BetModal(self.room, minimum=self.room.settings.big_blind)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.amount:
            self.action = Action.BET
            self.amount = modal.amount
        self.stop()