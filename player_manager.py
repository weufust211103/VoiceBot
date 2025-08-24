import json
import os
from datetime import datetime

class PlayerManager:
    def __init__(self, data_dir="player_data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def get_player_file(self, guild_id):
        return os.path.join(self.data_dir, f"players_{guild_id}.json")

    def load_players(self, guild_id):
        """Load players from JSON file"""
        file_path = self.get_player_file(guild_id)
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        return {}

    def save_players(self, guild_id, players):
        """Save players to JSON file"""
        file_path = self.get_player_file(guild_id)
        with open(file_path, 'w') as f:
            json.dump(players, f, indent=4)

    def get_player_chips(self, guild_id, player_id):
        players = self.load_players(guild_id)
        return players.get(str(player_id), {"name": "Unknown", "chips": 1000})

    def update_player_chips(self, guild_id, player_id, chips):
        players = self.load_players(guild_id)
        players[str(player_id)] = {"name": self.get_player_name(guild_id, player_id), "chips": chips}
        self.save_players(guild_id, players)

    def get_player_name(self, guild_id, player_id):
        players = self.load_players(guild_id)
        return players.get(str(player_id), {}).get("name", "Unknown")

    def add_player(self, guild_id, player_id, player_name):
        players = self.load_players(guild_id)
        if str(player_id) not in players:
            players[str(player_id)] = {"name": player_name, "chips": 1000}
            self.save_players(guild_id, players)

    def is_registered(self, guild_id: int, player_id: int) -> bool:
        """Check if a player is registered"""
        players = self.load_players(guild_id)
        return str(player_id) in players

    def register_player(self, guild_id: int, player_id: int, player_name: str, email: str = None):
        """Register a new player with expanded data"""
        players = self.load_players(guild_id)
        if str(player_id) not in players:
            players[str(player_id)] = {
                "name": player_name,
                "chips": 0,
                "registered": True,
                "registration_date": datetime.now().isoformat(),
                "total_games": 0,
                "wins": 0
            }
            if email:
                players[str(player_id)]["email"] = email
            self.save_players(guild_id, players)

    def update_player_stats(self, guild_id: int, player_id: int, won: bool = False):
        """Update player game statistics"""
        players = self.load_players(guild_id)
        player_data = players.get(str(player_id), {})
        if player_data:
            player_data["total_games"] = player_data.get("total_games", 0) + 1
            if won:
                player_data["wins"] = player_data.get("wins", 0) + 1
            players[str(player_id)] = player_data
            self.save_players(guild_id, players)