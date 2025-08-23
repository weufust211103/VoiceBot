import discord

class PokerTable:
    def __init__(self, bot):
        self.bot = bot
        self.category_name = "Poker Event Voice"
        self.table_channel = None

    async def create_table(self, guild):
        category = discord.utils.get(guild.categories, name=self.category_name)
        if not category:
            category = await guild.create_category(self.category_name)
            await guild.text_channels[0].send(f"Created category: {self.category_name}")
        
        voice_channels = [ch for ch in category.voice_channels]
        position = len(voice_channels)
        self.table_channel = await guild.create_voice_channel("Poker Table", category=category, position=position)
        await guild.text_channels[0].send(f"Created poker table voice channel: {self.table_channel.mention}")
        return self.table_channel

    async def get_or_create_table(self, guild):
        if not self.table_channel or not self.table_channel in guild.voice_channels:
            self.table_channel = await self.create_table(guild)
        return self.table_channel