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
        file_path = self.get_player_file(guild_id)
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        return {}

    def save_players(self, guild_id, players):
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

    def is_registered(self, guild_id, player_id):
        players = self.load_players(guild_id)
        return str(player_id) in players and players[str(player_id)].get("registered", False)

    def register_player(self, guild_id, player_id, player_name, email=None):
        players = self.load_players(guild_id)
        players[str(player_id)] = {
            "name": player_name,
            "chips": 0,
            "registered": True,
            "email": email,
            "registration_date": datetime.now().isoformat(), 
            "total_games": 0, 
            "wins": 0
        }        
        self.save_players(guild_id, players)