# -*- coding: utf-8 -*-
import os
import io
import json
import asyncio
import tempfile
import datetime
import calendar
from collections import Counter
from typing import Literal

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput

import matplotlib.pyplot as plt
import numpy as np
import aiosqlite

DB_NAME = "school_data.db"

CESKE_DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
CESKE_MESICE = ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen", "Červenec", "Srpen", "Září", "Říjen",
                "Listopad", "Prosinec"]


class PridejUkolModal(Modal, title='📝 Přidat nový školní úkol'):
    predmet = TextInput(label='Předmět', placeholder='Např. Matematika, Fyzika...', max_length=50)
    ukol = TextInput(label='Zadání úkolu', style=discord.TextStyle.paragraph,
                     placeholder='Napiš, co přesně máš udělat...', max_length=500)
    datum = TextInput(label='Datum odevzdání (YYYY-MM-DD)', placeholder='2026-05-20', min_length=10, max_length=10)
    cas = TextInput(label='Čas odevzdání (HH:MM)', placeholder='12:00', default='12:00', max_length=5)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            datetime.datetime.strptime(self.datum.value, "%Y-%m-%d")
            uid = str(interaction.user.id)
            if uid not in self.cog.ukoly_dict:
                self.cog.ukoly_dict[uid] = []
            self.cog.ukoly_dict[uid].append({
                "predmet": self.predmet.value, "ukol": self.ukol.value,
                "deadline": self.datum.value, "time": self.cas.value, "stav": "aktivní"
            })
            await self.cog.uloz_ukoly()
            embed = discord.Embed(title="✅ Úkol úspěšně uložen", color=discord.Color.green())
            embed.add_field(name=self.predmet.value,
                            value=f"{self.ukol.value}\n📅 {self.datum.value} v {self.cas.value}")
            await interaction.response.send_message(embed=embed)
        except ValueError:
            await interaction.response.send_message("❌ Špatný formát data! Použij YYYY-MM-DD (např. 2026-05-20).",
                                                    ephemeral=True)


class UpravitUkolModal(Modal):
    def __init__(self, cog, uid: str, task_idx: int, task_data: dict):
        super().__init__(title="✏️ Upravit existující úkol")
        self.cog = cog
        self.uid = uid
        self.task_idx = task_idx

        self.predmet = TextInput(label='Předmět', default=task_data.get('predmet', ''), max_length=50)
        self.ukol = TextInput(label='Zadání úkolu', style=discord.TextStyle.paragraph,
                              default=task_data.get('ukol', ''), max_length=500)
        self.datum = TextInput(label='Datum (YYYY-MM-DD)', default=task_data.get('deadline', ''), max_length=10)

        self.add_item(self.predmet)
        self.add_item(self.ukol)
        self.add_item(self.datum)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            datetime.datetime.strptime(self.datum.value, "%Y-%m-%d")
            self.cog.ukoly_dict[self.uid][self.task_idx].update({
                "predmet": self.predmet.value, "ukol": self.ukol.value, "deadline": self.datum.value
            })
            await self.cog.uloz_ukoly()
            await interaction.response.send_message(f"✅ Úkol **{self.predmet.value}** byl úspěšně upraven.",
                                                    ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Špatný formát data! Použij YYYY-MM-DD.", ephemeral=True)


class SchoolUkolyView(View):
    def __init__(self, cog, user: discord.User, active_ukoly: list, original_ukoly: list):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user
        self.active_ukoly = active_ukoly
        self.original_ukoly = original_ukoly
        self._build_select()

    def _build_select(self):
        self.clear_items()
        if not self.active_ukoly:
            return

        options = []
        for u in self.active_ukoly[:25]:
            try:
                orig_idx = self.original_ukoly.index(u)
                options.append(discord.SelectOption(
                    label=f"{u['predmet']} - {u['ukol'][:30]}",
                    description=f"Odevzdat do: {u['deadline']}",
                    value=str(orig_idx)
                ))
            except ValueError:
                continue

        if options:
            select = Select(placeholder="🏆 Rychle označit úkol za SPLNĚNÝ...", options=options)

            async def select_cb(interaction: discord.Interaction):
                if interaction.user.id != self.user.id:
                    return await interaction.response.send_message("❌ Toto není tvůj přehled úkolů.", ephemeral=True)

                idx = int(select.values[0])
                if idx < len(self.original_ukoly):
                    self.original_ukoly[idx]["stav"] = "dokončený"
                    await self.cog.uloz_ukoly()

                    embed = self.cog.generuj_ukoly_embed(self.user)
                    nove_aktivni = [u for u in self.original_ukoly if u.get("stav") == "aktivní"]
                    self.active_ukoly = nove_aktivni
                    self._build_select()

                    if nove_aktivni:
                        await interaction.message.edit(embed=embed, view=self)
                    else:
                        empty_embed = discord.Embed(title="📭 Žádné úkoly", description="Nemáš žádné aktivní úkoly. 🎉",
                                                    color=discord.Color.green())
                        await interaction.message.edit(embed=empty_embed, view=None)

                    await interaction.response.send_message(f"🎉 Úkol byl označen jako hotový!", ephemeral=True)

            select.callback = select_cb
            self.add_item(select)


class TydenniKalendarView(discord.ui.View):
    def __init__(self, cog, user: discord.User, start_date: datetime.date, message: discord.Message = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.start_date = start_date
        self.message = message
        self._build()

    def _build(self):
        self.clear_items()
        prev_btn = Button(label="⬅️ Týden zpět", style=discord.ButtonStyle.secondary)
        next_btn = Button(label="Týden vpřed ➡️", style=discord.ButtonStyle.secondary)
        prev_btn.callback = self._prev_week
        next_btn.callback = self._next_week
        self.add_item(prev_btn)
        self.add_item(next_btn)

        for i in range(7):
            den = self.start_date + datetime.timedelta(days=i)
            label = f"{CESKE_DNY[den.weekday()]} {den.day:02d}"
            ukoly = self.cog.ukoly_dict.get(str(self.user.id), [])
            ma_ukol = any(u.get("deadline") == den.strftime("%Y-%m-%d") and u.get("stav") == "aktivní" for u in ukoly)

            style = discord.ButtonStyle.success if ma_ukol else discord.ButtonStyle.primary
            btn = Button(label=label, style=style)

            async def day_cb(interaction: discord.Interaction, datum=den):
                if interaction.user.id != self.user.id:
                    return await interaction.response.send_message("❌ Toto není tvoje volba.", ephemeral=True)
                await self.cog.posli_ukoly_na_den(self.user, datum)
                try:
                    await interaction.response.defer()
                except Exception:
                    pass

            btn.callback = day_cb
            self.add_item(btn)

        if self.message:
            mesic_nazev = CESKE_MESICE[self.start_date.month - 1]
            embed = discord.Embed(title=f"📅 Týdenní kalendář – {mesic_nazev} {self.start_date.year}",
                                  description="Zvýrazněné dny obsahují aktivní úkoly. Kliknutím zobrazíš detaily.",
                                  color=discord.Color.blurple())
            asyncio.create_task(self.message.edit(embed=embed, view=self))

    async def _prev_week(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("❌ Omezeno.", ephemeral=True)
        self.start_date -= datetime.timedelta(days=7)
        self._build()
        await interaction.response.edit_message(view=self)

    async def _next_week(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("❌ Omezeno.", ephemeral=True)
        self.start_date += datetime.timedelta(days=7)
        self._build()
        await interaction.response.edit_message(view=self)


class SchoolCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ukoly_dict = {}
        self.tlumeni_dict = {}
        self.posledni_poslani_datum = None
        # Spuštění inicializace DB
        self.bot.loop.create_task(self.init_db())
        self.pripomenuti_ukolu.start()

    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ukoly_data (
                    user_id TEXT PRIMARY KEY,
                    data TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tlumeni_data (
                    user_id TEXT PRIMARY KEY,
                    je_ztlumeno INTEGER
                )
            """)
            await db.commit()
        # Načtení dat po vytvoření tabulek
        await self.load_data()

    async def load_data(self):
        async with aiosqlite.connect(DB_NAME) as db:
            # Načtení úkolů
            async with db.execute("SELECT user_id, data FROM ukoly_data") as cursor:
                async for row in cursor:
                    self.ukoly_dict[row[0]] = json.loads(row[1])
            # Načtení tlumení
            async with db.execute("SELECT user_id, je_ztlumeno FROM tlumeni_data") as cursor:
                async for row in cursor:
                    self.tlumeni_dict[row[0]] = bool(row[1])

    async def uloz_ukoly(self):
        """Uloží aktuální stav paměti do DB."""
        async with aiosqlite.connect(DB_NAME) as db:
            for uid, data in self.ukoly_dict.items():
                await db.execute(
                    "INSERT OR REPLACE INTO ukoly_data (user_id, data) VALUES (?, ?)",
                    (uid, json.dumps(data, ensure_ascii=False))
                )
            await db.commit()

    async def uloz_tlumeni(self):
        """Uloží aktuální stav tlumení do DB."""
        async with aiosqlite.connect(DB_NAME) as db:
            for uid, val in self.tlumeni_dict.items():
                await db.execute(
                    "INSERT OR REPLACE INTO tlumeni_data (user_id, je_ztlumeno) VALUES (?, ?)",
                    (uid, 1 if val else 0)
                )
            await db.commit()

    def cog_unload(self):
        self.pripomenuti_ukolu.cancel()

    def spocitej_workload(self, user_id: int) -> Counter:
        dnes = datetime.date.today()
        workload = Counter()
        ukoly = self.ukoly_dict.get(str(user_id), [])
        for u in ukoly:
            if u.get("stav") in ["vypršelý", "dokončený"]:
                continue
            try:
                deadline = datetime.datetime.strptime(u["deadline"], "%Y-%m-%d").date()
            except Exception:
                continue
            dny = (deadline - dnes).days
            if dny >= 0:
                workload[deadline] += 1
        return workload

    def predikuj_workload(self, user_id: int) -> str:
        workload = self.spocitej_workload(user_id)
        if not workload:
            return "✅ Nemáš žádné aktivní úkoly."
        zpravy = []
        for den, pocet in sorted(workload.items()):
            den_text = f"{den.strftime('%d.%m')} ({CESKE_DNY[den.weekday()]})"
            if pocet >= 3:
                zpravy.append(f"⚠️ {den_text}: Hodně úkolů ({pocet})")
            elif pocet == 1:
                zpravy.append(f"📌 {den_text}: Máš {pocet} úkol.")
            else:
                zpravy.append(f"📌 {den_text}: Máš {pocet} úkoly.")
        return "\n".join(zpravy)

    def workload_trend(self, user_id: int, period_days: int = 14, predict_days: int = 5, alpha: float = 0.3) -> str:
        dnes = datetime.date.today()
        start_date = dnes - datetime.timedelta(days=period_days - 1)
        ukoly = self.ukoly_dict.get(str(user_id), [])
        workload = {}
        for u in ukoly:
            if u.get("stav") in ["vypršelý", "dokončený"]:
                continue
            try:
                deadline = datetime.datetime.strptime(u["deadline"], "%Y-%m-%d").date()
            except Exception:
                continue
            workload[deadline] = workload.get(deadline, 0) + 1

        vsechny_dny = [start_date + datetime.timedelta(days=i) for i in range(period_days)]
        hodnoty = np.array([workload.get(d, 0) for d in vsechny_dny], dtype=float)

        ewma = np.zeros_like(hodnoty)
        if len(hodnoty) > 0:
            ewma[0] = hodnoty[0]
            for i in range(1, len(hodnoty)):
                ewma[i] = alpha * hodnoty[i] + (1 - alpha) * ewma[i - 1]

        x = np.arange(len(hodnoty))
        if len(x) >= 3:
            coef = np.polyfit(x, ewma, 2)
        elif len(x) == 2:
            coef = [0.0, *np.polyfit(x, ewma, 1)]
        elif len(x) == 1:
            coef = [0.0, 0.0, ewma[0]]
        else:
            coef = [0.0, 0.0, 0.0]

        trend_posledni = coef[0] * (len(x) - 1) ** 2 + coef[1] * (len(x) - 1) + coef[2] if len(x) > 0 else 0.0

        zprava = f"📊 Analýza trendu workloadu ({start_date.strftime('%d.%m')} – {dnes.strftime('%d.%m')}):\n"
        zprava += f"Celkem aktivních úkolů: {int(np.sum(hodnoty))}\n"
        zprava += f"Průměrně na den: {np.mean(hodnoty):.2f}\n"

        if trend_posledni > (ewma[-1] if len(ewma) > 0 else 0) + 0.5:
            zprava += "📈 Trend: Workload rychle roste – bude to náročné!\n"
        elif trend_posledni < (ewma[-1] if len(ewma) > 0 else 0) - 0.5:
            zprava += "📉 Trend: Workload klesá – dny budou klidnější.\n"
        else:
            zprava += "➡️ Trend: Workload je stabilní.\n"

        predikce = []
        last_x = len(x) - 1
        for i in range(1, predict_days + 1):
            xi = last_x + i
            pred = coef[0] * xi ** 2 + coef[1] * xi + coef[2]
            pred = max(0, int(round(pred + np.random.uniform(-0.2, 0.2) * max(pred, 1))))
            predikce.append(pred)

        pred_dny = [dnes + datetime.timedelta(days=i) for i in range(1, predict_days + 1)]
        pred_text = ", ".join(f"{d.strftime('%d.%m')}: {p}" for d, p in zip(pred_dny, predikce))
        zprava += f"🔮 Predikce příštích {predict_days} dní: {pred_text}"
        return zprava

    async def workload_graf(self, user_id: int):
        ukoly = self.ukoly_dict.get(str(user_id), [])
        aktivni = [u for u in ukoly if u.get("stav") == "aktivní"]
        if not aktivni: return None

        workload = Counter(u.get("deadline") for u in aktivni if "deadline" in u)
        dny = list(sorted(workload.keys()))
        hodnoty = [workload[d] for d in dny]

        labels = [
            f"{datetime.datetime.strptime(d, '%Y-%m-%d').strftime('%d.%m')} ({CESKE_DNY[datetime.datetime.strptime(d, '%Y-%m-%d').weekday()]})"
            for d in dny]

        plt.figure(figsize=(9, 4))
        plt.bar(labels, hodnoty, color="tab:blue", edgecolor="black")
        plt.title("📊 Aktuální workload (počet aktivních úkolů)")
        plt.xlabel("Datum")
        plt.ylabel("Počet úkolů")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()
        return buf

    def generuj_ukoly_embed(self, user: discord.User) -> discord.Embed:
        dnes = datetime.date.today()
        ukoly = self.ukoly_dict.get(str(user.id), [])

        zmena = False
        for u in ukoly:
            if u.get("stav") == "aktivní":
                try:
                    dl = datetime.datetime.strptime(u["deadline"], "%Y-%m-%d").date()
                    if dl < dnes:
                        u["stav"] = "vypršelý"
                        zmena = True
                except Exception:
                    pass
        if zmena:
            asyncio.create_task(self.uloz_ukoly())

        aktivni_ukoly = [u for u in ukoly if u.get("stav") == "aktivní"]

        if not aktivni_ukoly:
            return discord.Embed(title="📭 Žádné úkoly", description="Nemáš žádné aktivní úkoly. 🎉",
                                 color=discord.Color.green())

        embed = discord.Embed(title="📚 Tvoje aktivní úkoly", description=f"Dnes je **{dnes.strftime('%d.%m.%Y')}**",
                              color=discord.Color.blurple())

        for u in aktivni_ukoly[:25]:
            try:
                deadline = datetime.datetime.strptime(u["deadline"], "%Y-%m-%d").date()
            except Exception:
                continue
            dny_zbyva = (deadline - dnes).days

            if dny_zbyva == 0:
                stav = f"⚠️ **MUSÍŠ odevzdat dnes!** ({u['deadline']} v {u.get('time', '12:00')})"
            elif dny_zbyva == 1:
                stav = f"⏳ Zítra musíš odevzdat ({u['deadline']})"
            else:
                stav = f"📌 Zbývá {dny_zbyva} dní (do {u['deadline']})"

            embed.add_field(name=f"**{u.get('predmet', 'Nezařazeno')}** – {u.get('ukol', '(bez popisu)')}", value=stav,
                            inline=False)

        embed.set_footer(text="💡 Můžeš využít rychlé menu níže, nebo příkazy /hotovo, /smaz.")
        return embed

    async def posli_ukoly(self, user: discord.User, interaction: discord.Interaction = None):
        embed = self.generuj_ukoly_embed(user)
        ukoly = self.ukoly_dict.get(str(user.id), [])
        aktivni_ukoly = [u for u in ukoly if u.get("stav") == "aktivní"]

        view = SchoolUkolyView(self, user, aktivni_ukoly, ukoly) if aktivni_ukoly else None

        try:
            if interaction:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                await user.send(embed=embed, view=view)
        except Exception:
            pass

    async def posli_ukoly_na_den(self, user: discord.User, datum: datetime.date):
        ukoly = self.ukoly_dict.get(str(user.id), [])
        embed = discord.Embed(title=f"Úkoly na {datum.strftime('%d.%m.%Y')} ({CESKE_DNY[datum.weekday()]})",
                              color=discord.Color.blue())
        denni_ukoly = [u for u in ukoly if
                       u.get("deadline") == datum.strftime("%Y-%m-%d") and u.get("stav") == "aktivní"]

        if denni_ukoly:
            for u in denni_ukoly:
                embed.add_field(name=f"{u.get('predmet', 'Nezařazeno')} – {u.get('ukol', '(bez popisu)')}",
                                value=f"Čas odevzdání: {u.get('time', '12:00')}", inline=False)
        else:
            embed.description = "🎉 Žádné aktivní úkoly na tento den."
        try:
            await user.send(embed=embed)
        except Exception:
            pass

    @tasks.loop(seconds=30)
    async def pripomenuti_ukolu(self):
        ted = datetime.datetime.now(datetime.timezone.utc)
        if ted.hour == 18 and ted.minute == 0:
            if self.posledni_poslani_datum == ted.date(): return
            for user_id in list(self.ukoly_dict.keys()):
                if self.tlumeni_dict.get(str(user_id), False): continue
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    if user:
                        await self.posli_ukoly(user)
                        pred = self.predikuj_workload(int(user_id))
                        await user.send(f"🔮 **Předpověď na další dny:**\n{pred}")
                except Exception:
                    pass
            self.posledni_poslani_datum = ted.date()

    @app_commands.command(name="pridej", description="Otevře rychlý formulář pro přidání nového úkolu.")
    async def pridej_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PridejUkolModal(self))

    @app_commands.command(name="upravit", description="Umožní upravit existující úkol přes čistý formulář.")
    async def upravit_slash(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        ukoly = self.ukoly_dict.get(uid, [])
        if not ukoly:
            return await interaction.response.send_message("⚠️ Nemáš žádné úkoly k úpravě.", ephemeral=True)

        options = [discord.SelectOption(label=f"{u['predmet']} - {u['ukol'][:30]}", value=str(i)) for i, u in
                   enumerate(ukoly)]
        select = Select(placeholder="Vyber úkol k úpravě", options=options[:25])

        async def cb(inter: discord.Interaction):
            if inter.user.id != interaction.user.id: return
            idx = int(select.values[0])
            await inter.response.send_modal(UpravitUkolModal(self, uid, idx, ukoly[idx]))

        select.callback = cb
        v = View()
        v.add_item(select)
        await interaction.response.send_message("Zvol úkol k editaci:", view=v, ephemeral=True)

    @app_commands.command(name="smaz", description="Kompletně odstraní vybraný úkol z databáze úkolů.")
    async def smaz_slash(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        ukoly = self.ukoly_dict.get(uid, [])
        if not ukoly:
            return await interaction.response.send_message("⚠️ Nemáš žádné úkoly ke smazání.", ephemeral=True)

        options = [discord.SelectOption(label=f"{u['predmet']} - {u['ukol'][:30]}", value=str(i)) for i, u in
                   enumerate(ukoly)]
        select = Select(placeholder="Zvol úkol ke smazání", options=options[:25])

        async def cb(inter: discord.Interaction):
            if inter.user.id != interaction.user.id: return
            idx = int(select.values[0])
            odstranen = ukoly.pop(idx)
            await self.uloz_ukoly()
            await inter.response.edit_message(content=f"🗑️ Úkol **{odstranen.get('ukol')}** byl permanentně smazán.",
                                              view=None)

        select.callback = cb
        v = View()
        v.add_item(select)
        await interaction.response.send_message("Vyber úkol k odstranění:", view=v, ephemeral=True)

    @app_commands.command(name="smaz_vse",
                          description="Pročistí databázi od starých, vypršelých nebo dokončených úkolů.")
    async def smaz_vse_slash(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        ukoly = self.ukoly_dict.get(uid, [])
        puvodni_pocet = len(ukoly)
        self.ukoly_dict[uid] = [u for u in ukoly if u.get("stav") == "aktivní"]
        await self.uloz_ukoly()
        smazano = puvodni_pocet - len(self.ukoly_dict[uid])
        await interaction.response.send_message(
            f"🧹 Databáze pročištěna. Smazáno {smazano} archivovaných/vypršelých úkolů.", ephemeral=True)

    @app_commands.command(name="ukoly", description="Vypíše přehledný seznam všech aktuálně aktivních školních úkolů.")
    async def ukoly_slash(self, interaction: discord.Interaction):
        await self.posli_ukoly(interaction.user, interaction=interaction)

    @app_commands.command(name="hotovo", description="Označí školní úkol za dokončený a uloží ho do statistik.")
    async def hotovo_slash(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        ukoly = self.ukoly_dict.get(uid, [])
        aktivni = [u for u in ukoly if u.get("stav") == "aktivní"]
        if not aktivni:
            return await interaction.response.send_message("✅ Nemáš žádné aktivní úkoly k dokončení.", ephemeral=True)

        options = [discord.SelectOption(label=f"{u['predmet']} - {u['ukol'][:40]}", value=str(i)) for i, u in
                   enumerate(ukoly) if u.get("stav") == "aktivní"]
        select = Select(placeholder="Vyber splněný úkol", options=options[:25])

        async def cb(inter: discord.Interaction):
            if inter.user.id != interaction.user.id: return
            idx = int(select.values[0])
            ukoly[idx]["stav"] = "dokončený"
            await self.uloz_ukoly()
            await inter.response.edit_message(content=f"🎉 Úkol **{ukoly[idx]['ukol']}** byl splněn! Dobrá práce.",
                                              view=None)

        select.callback = cb
        v = View()
        v.add_item(select)
        await interaction.response.send_message("🏆 Který úkol jsi dokončil?", view=v, ephemeral=True)

    @app_commands.command(name="statistiky", description="Ukáže tvou úspěšnost a rozpad plnění úkolů podle předmětů.")
    async def statistiky_slash(self, interaction: discord.Interaction):
        ukoly = self.ukoly_dict.get(str(interaction.user.id), [])
        if not ukoly:
            return await interaction.response.send_message("📊 Zatím nemáš v databázi žádná data o úkolech.",
                                                           ephemeral=True)

        celkem = len(ukoly)
        splneno = sum(1 for u in ukoly if u.get("stav") == "dokončený")
        aktivni = sum(1 for u in ukoly if u.get("stav") == "aktivní")
        prosle = sum(1 for u in ukoly if u.get("stav") == "vypršelý")

        rate = (splneno / (splneno + prosle) * 100) if (splneno + prosle) > 0 else 100

        embed = discord.Embed(title="📊 Moje studijní statistiky", color=discord.Color.teal())
        embed.add_field(name="📈 Přehled",
                        value=f"• Aktivní úkoly: **{aktivni}**\n• Splněné úkoly: **{splneno}** 🎉\n• Prošlé úkoly: **{prosle}**\n• Celková úspěšnost: **{rate:.1f}%**",
                        inline=False)

        sub_stats = {}
        for u in ukoly:
            p = u.get("predmet", "Nezařazeno")
            if p not in sub_stats: sub_stats[p] = {"splneno": 0, "celkem": 0}
            sub_stats[p]["celkem"] += 1
            if u.get("stav") == "dokončený": sub_stats[p]["splneno"] += 1

        text_subs = ""
        for s, data in sub_stats.items():
            text_subs += f"• **{s}**: {data['splneno']}/{data['celkem']} hotovo\n"

        embed.add_field(name="📚 Úspěšnost podle předmětů", value=text_subs or "Žádná data", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="workload", description="Zobrazí podrobnou matematickou analýzu vytížení a graf.")
    async def workload_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        zprava = self.predikuj_workload(interaction.user.id)
        predikce = self.workload_trend(interaction.user.id)
        graf = await self.workload_graf(interaction.user.id)
        obsah = f"📊 **Aktuální přehled tvého workloadu:**\n{zprava}\n\n{predikce}"

        if graf:
            await interaction.followup.send(content=obsah, file=discord.File(graf, "workload.png"))
        else:
            await interaction.followup.send(content=obsah)

    @app_commands.command(name="tlum", description="Ztlumí nebo aktivuje automatické večerní zasílání úkolů.")
    async def tlum_slash(self, interaction: discord.Interaction, stav: Literal["on", "off"]):
        uid = str(interaction.user.id)
        if stav == "on":
            self.tlumeni_dict[uid] = True
            await interaction.response.send_message("🔕 Připomenutí úkolů byla ztlumena.", ephemeral=True)
        else:
            self.tlumeni_dict[uid] = False
            await interaction.response.send_message("🔔 Připomenutí úkolů jsou nyní aktivní.", ephemeral=True)
        await self.uloz_tlumeni()

    @app_commands.command(name="kalendar",
                          description="Zobrazí přehledný textový kalendář na tento měsíc se zvýrazněným dneškem.")
    async def kalendar_slash(self, interaction: discord.Interaction):
        dnes = datetime.date.today()
        mesic_nazev = CESKE_MESICE[dnes.month - 1]
        rok = dnes.year

        cal_text = f"      {mesic_nazev} {rok}\n\n"
        cal_text += " Po  Út  St  Čt  Pá  So  Ne \n"

        weeks = calendar.monthcalendar(rok, dnes.month)
        for week in weeks:
            week_strs = []
            for day in week:
                if day == 0:
                    week_strs.append("    ")
                elif day == dnes.day:
                    week_strs.append(f"[{day:2}]")
                else:
                    week_strs.append(f" {day:2} ")
            cal_text += "".join(week_strs) + "\n"

        embed = discord.Embed(title="📅 Kalendář recepce", description=f"```text\n{cal_text}\n```",
                              color=discord.Color.blurple())
        embed.set_footer(text="Dnešní den je zvýrazněn v [závorkách].")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kalendar_tyden",
                          description="Zašle plně interaktivní týdenní kalendář přímo do tvých DM.")
    async def kalendar_tyden_slash(self, interaction: discord.Interaction):
        start = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        view = TydenniKalendarView(self, interaction.user, start)
        try:
            msg = await interaction.user.send(
                embed=discord.Embed(title="📅 Týdenní kalendář", color=discord.Color.blurple()), view=view)
            view.message = msg
            view._build()
            await interaction.response.send_message("✅ Tým odeslal interaktivní kalendář do tvých DM.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ Nelze odeslat zprávu do tvých DM. Povol si soukromé zprávy.",
                                                    ephemeral=True)


async def setup(bot):
    await bot.add_cog(SchoolCog(bot))