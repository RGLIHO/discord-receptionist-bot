# -*- coding: utf-8 -*-
import datetime
from typing import Literal
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Modal, TextInput, View, Button, Select


class MinecraftCoordsModal(Modal):
    def __init__(self, cog, edit_id=None, zaznam=None):
        title = "✏️ Upravit Minecraft Pozici" if edit_id is not None else "🌍 Uložit Minecraft Pozici"
        super().__init__(title=title)
        self.cog = cog
        self.edit_id = edit_id

        zaznam = zaznam or {}

        self.nazev = TextInput(
            label="Název lokace",
            placeholder="Např. Slime farma, End portál...",
            max_length=100,
            default=zaznam.get("nazev", "")
        )
        self.souradnice = TextInput(
            label="Souřadnice (X Y Z)",
            placeholder="150 64 -300",
            default=zaznam.get("coords", "")
        )
        self.dimenze = TextInput(
            label="Dimenze",
            placeholder="Overworld / Nether / End",
            default=zaznam.get("dimenze", "Overworld")
        )

        self.add_item(self.nazev)
        self.add_item(self.souradnice)
        self.add_item(self.dimenze)

    async def on_submit(self, interaction: discord.Interaction):
        nazev = self.nazev.value
        coords = self.souradnice.value
        dimenze = self.dimenze.value
        verze = "1.21.11"
        datum = datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y")

        if self.edit_id is not None:
            await self.cog.bot.db.execute(
                "UPDATE mc_coords SET nazev=?, coords=?, dimenze=?, verze=?, datum=? WHERE id=?",
                (nazev, coords, dimenze, verze, datum, self.edit_id)
            )
            titulek = "✏️ Pozice úspěšně upravena"
        else:
            await self.cog.bot.db.execute(
                "INSERT INTO mc_coords (nazev, coords, dimenze, verze, datum) VALUES (?, ?, ?, ?, ?)",
                (nazev, coords, dimenze, verze, datum)
            )
            titulek = "📍 Pozice úspěšně uložena"

        await self.cog.bot.db.commit()

        embed = discord.Embed(title=titulek, color=discord.Color.dark_green())
        embed.add_field(name=nazev, value=f"**XYZ:** {coords}\n**Dimenze:** {dimenze}\n**Verze:** {verze}",
                        inline=False)
        await interaction.response.send_message(embed=embed)


class MinecraftSeznamView(View):
    def __init__(self, cog, interaction: discord.Interaction, dimenze: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.author = interaction.user
        self.dimenze = dimenze
        self.page = 0
        self.per_page = 5
        self.filtrovane = []

    async def aktualizuj_data_z_db(self):
        query = "SELECT id, nazev, coords, dimenze, verze, datum FROM mc_coords"
        params = ()
        if self.dimenze != "Vše":
            query += " WHERE dimenze = ?"
            params = (self.dimenze,)

        async with self.cog.bot.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        self.filtrovane = [
            {"id": r[0], "nazev": r[1], "coords": r[2], "dimenze": r[3], "verze": r[4], "datum": r[5]}
            for r in rows
        ]

    def generuj_embed(self) -> discord.Embed:
        max_pages = max(1, (len(self.filtrovane) + self.per_page - 1) // self.per_page)
        if self.page >= max_pages:
            self.page = max_pages - 1

        embed = discord.Embed(
            title=f"🌍 Minecraft Souřadnice – {self.dimenze} (Strana {self.page + 1}/{max_pages})",
            color=discord.Color.green()
        )

        start = self.page * self.per_page
        end = start + self.per_page
        stranka_data = self.filtrovane[start:end]

        if not stranka_data:
            embed.description = "📭 Žádné uložené pozice."
            return embed

        for c in stranka_data:
            embed.add_field(
                name=f"📍 [ID: {c['id']}] {c.get('nazev', 'Bez názvu')}",
                value=f"**XYZ:** `{c.get('coords')}`\n**Dimenze:** {c.get('dimenze')}\n*Verze: {c.get('verze')} | Datum: {c.get('datum')}*",
                inline=False
            )
        return embed

    def obnov_komponenty(self):
        self.clear_items()
        max_pages = max(1, (len(self.filtrovane) + self.per_page - 1) // self.per_page)

        prev_btn = Button(label="⬅️ Předchozí", style=discord.ButtonStyle.blurple, disabled=(self.page == 0))
        next_btn = Button(label="Další ➡️", style=discord.ButtonStyle.blurple, disabled=(self.page >= max_pages - 1))

        async def prev_cb(inter: discord.Interaction):
            if inter.user.id != self.author.id:
                return await inter.response.send_message("❌ Tohle menu neovládáš.", ephemeral=True)
            self.page -= 1
            self.obnov_komponenty()
            await inter.response.edit_message(embed=self.generuj_embed(), view=self)

        async def next_cb(inter: discord.Interaction):
            if inter.user.id != self.author.id:
                return await inter.response.send_message("❌ Tohle menu neovládáš.", ephemeral=True)
            self.page += 1
            self.obnov_komponenty()
            await inter.response.edit_message(embed=self.generuj_embed(), view=self)

        prev_btn.callback = prev_cb
        next_btn.callback = next_cb
        self.add_item(prev_btn)
        self.add_item(next_btn)

        start = self.page * self.per_page
        end = start + self.per_page
        stranka_data = self.filtrovane[start:end]

        if stranka_data:
            options_upravit = [
                discord.SelectOption(label=f"Upravit: {c.get('nazev')[:20]}", value=f"uprav_{c['id']}")
                for c in stranka_data
            ]
            options_smazat = [
                discord.SelectOption(label=f"Smazat: {c.get('nazev')[:20]}", value=f"smaz_{c['id']}")
                for c in stranka_data
            ]

            select_action = Select(placeholder="⚙️ Vyber lokaci pro úpravu nebo smazání...",
                                   options=options_upravit + options_smazat)

            async def action_cb(inter: discord.Interaction):
                if inter.user.id != self.author.id:
                    return await inter.response.send_message("❌ Tohle menu neovládáš.", ephemeral=True)
                val = select_action.values[0]
                akce, db_id_str = val.split("_")
                db_id = int(db_id_str)
                vybrany_zaznam = next((x for x in self.filtrovane if x["id"] == db_id), None)

                if akce == "uprav":
                    await inter.response.send_modal(
                        MinecraftCoordsModal(self.cog, edit_id=db_id, zaznam=vybrany_zaznam))
                elif akce == "smaz":
                    await self.cog.bot.db.execute("DELETE FROM mc_coords WHERE id=?", (db_id,))
                    await self.cog.bot.db.commit()
                    await self.aktualizuj_data_z_db()
                    self.obnov_komponenty()
                    nazev = vybrany_zaznam.get("nazev") if vybrany_zaznam else "Neznámá lokace"
                    await inter.response.edit_message(content=f"🗑️ Lokace **{nazev}** byla smazána.",
                                                      embed=self.generuj_embed(), view=self)

            select_action.callback = action_cb
            self.add_item(select_action)


class MinecraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mc_pozice",
                          description="Uloží souřadnice zajímavých lokací nebo redstone staveb v Minecraftu.")
    async def mc_pozice_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftCoordsModal(self))

    @app_commands.command(name="mc_seznam",
                          description="Zobrazí přehledný, stránkovaný seznam uložených Minecraft souřadnic.")
    @app_commands.describe(dimenze="Filtrovat podle dimenze (Vše/Overworld/Nether/End)")
    async def mc_seznam_slash(self, interaction: discord.Interaction,
                              dimenze: Literal["Vše", "Overworld", "Nether", "End"] = "Vše"):
        view = MinecraftSeznamView(self, interaction, dimenze)
        await view.aktualizuj_data_z_db()

        async with self.bot.db.execute("SELECT COUNT(*) FROM mc_coords") as cursor:
            total_count = (await cursor.fetchone())[0]

        if total_count == 0:
            return await interaction.response.send_message("📭 Nejsou uloženy žádné Minecraft souřadnice.",
                                                           ephemeral=True)

        if not view.filtrovane:
            return await interaction.response.send_message(f"📭 V dimenzi **{dimenze}** nemáš žádné uložené pozice.",
                                                           ephemeral=True)

        view.obnov_komponenty()
        await interaction.response.send_message(embed=view.generuj_embed(), view=view)


async def setup(bot):
    await bot.add_cog(MinecraftCog(bot))