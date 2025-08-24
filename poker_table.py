import discord
from discord.utils import get
import random

class PokerTable:
    def __init__(self, bot):
        self.bot = bot
        self.category_name = "Poker Event Voice"
        self.deck = []
        self.player_hands = {}
        self.community_cards = []

    def setup_deck(self):
        """Initialize and shuffle the deck"""
        suits = ['♥', '♦', '♣', '♠']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.deck = [(rank, suit) for suit in suits for rank in ranks]
        random.shuffle(self.deck)

    async def deal_cards_to_players(self, players):
        """Deal two cards to each player"""
        self.setup_deck()
        self.player_hands.clear()
        
        for player in players:
            # Deal 2 cards to each player
            cards = [self.deck.pop() for _ in range(2)]
            self.player_hands[player.id] = cards
            
            # Send cards to player in DM
            cards_str = " ".join([f"{rank}{suit}" for rank, suit in cards])
            try:
                embed = discord.Embed(
                    title="Your Poker Hand",
                    description=f"Your cards: {cards_str}",
                    color=discord.Color.blue()
                )
                await player.send(embed=embed)
            except discord.Forbidden:
                # If we can't DM the player, send a message to the channel
                channel = player.voice.channel
                await channel.send(
                    f"{player.mention} I couldn't send you your cards. "
                    "Please enable DMs from server members."
                )

    async def deal_community_cards(self, count: int):
        """Deal community cards"""
        new_cards = [self.deck.pop() for _ in range(count)]
        self.community_cards.extend(new_cards)
        return new_cards

    async def get_or_create_table(self, guild):
        """Get or create a poker table voice channel"""
        # Find or create category
        category = get(guild.categories, name=self.category_name)
        if not category:
            category = await guild.create_category(self.category_name)

        # Create unique poker table name
        table_name = f"Poker-Table-{len(category.voice_channels) + 1}"

        # Create voice channel
        voice_channel = await guild.create_voice_channel(
            name=table_name,
            category=category,
            user_limit=6  # Max players for poker
        )

        await self.setup_deck()  # Initialize deck when creating table
        return voice_channel

    async def delete_table(self, voice_channel):
        """Delete a poker table voice channel"""
        try:
            await voice_channel.delete()
            return True
        except discord.NotFound:
            return False
        except Exception as e:
            print(f"Error deleting voice channel: {e}")
            return False

    async def move_players_to_table(self, players, voice_channel):
        """Move players to the poker table voice channel"""
        for player in players:
            try:
                await player.move_to(voice_channel)
            except Exception as e:
                print(f"Error moving {player.name}: {e}")

    async def cleanup_empty_tables(self, guild):
        """Remove empty poker tables"""
        category = get(guild.categories, name=self.category_name)
        if category:
            for channel in category.voice_channels:
                if len(channel.members) == 0:
                    await self.delete_table(channel)