# -*- coding: utf-8 -*-
import os
import json
import datetime
import discord
import aiosqlite
from discord.ext import commands

# Automatický pokus o načtení .env souboru
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
OWNER_NAME = os.getenv("OWNER_NAME", "Majitel")

RECIPIENTS_RAW = os.getenv("RECIPIENTS")
if RECIPIENTS_RAW:
    try:
        RECIPIENTS = json.loads(RECIPIENTS_RAW)
    except Exception:
        print("⚠️ Chyba při parsování RECIPIENTS z .env. Používám výchozí nastavení.")
        RECIPIENTS = {OWNER_NAME: OWNER_ID}
else:
    RECIPIENTS = {OWNER_NAME: OWNER_ID}


class RecepcniBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

        # Globální vlastnosti bota sdílené napříč Cogy
        self.owner_id_custom = OWNER_ID
        self.owner_name_custom = OWNER_NAME
        self.recipients_custom = RECIPIENTS
        self.start_time_custom = datetime.datetime.now(datetime.timezone.utc)
        self.party_channels = set()
        self.db = None

    async def setup_hook(self):
        # Inicializace asynchronní databáze a vytvoření tabulek
        self.db = await aiosqlite.connect("bot.db")
        await self.db.execute('''CREATE TABLE IF NOT EXISTS mc_coords (id INTEGER PRIMARY KEY AUTOINCREMENT, nazev TEXT, coords TEXT, dimenze TEXT, verze TEXT, datum TEXT)''')
        await self.db.execute('''CREATE TABLE IF NOT EXISTS offline_status (user_id TEXT PRIMARY KEY, is_offline INTEGER)''')
        await self.db.execute('''CREATE TABLE IF NOT EXISTS inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT, from_id INTEGER, from_name TEXT, text TEXT, timestamp TEXT, owner_reply INTEGER, reply_text TEXT, reply_timestamp TEXT)''')
        await self.db.execute('''CREATE TABLE IF NOT EXISTS pripominky (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, cas TEXT, text TEXT)''')
        await self.db.commit()

        # Vytvoření složky pro cogy, pokud neexistuje
        if not os.path.exists("cogs"):
            os.makedirs("cogs")

        extensions = ["cogs.school", "cogs.reception", "cogs.minecraft", "cogs.voice"]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"Modul {ext} byl úspěšně načten.")
            except Exception as e:
                print(f"Selhalo načtení modulu {ext}: {e}")

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

    async def on_ready(self):
        print(f"Bot běží jako {self.user} (ID: {self.user.id})")
        try:
            await self.tree.sync()
            print("Slash příkazy byly úspěšně celosvětově synchronizovány.")
        except Exception as e:
            print(f"Chyba při synchronizaci slash příkazů: {e}")

        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name="zvonek na recepci 🛎️")
        )


if __name__ == "__main__":
    if not TOKEN:
        print("Chybí DISCORD_TOKEN v proměnných prostředí. Ukončuji.")
    else:
        bot = RecepcniBot()
        bot.run(TOKEN)
