# -*- coding: utf-8 -*-
import os
import io
import json
import asyncio
import tempfile
import logging
import calendar
import datetime
import platform
import time
from collections import Counter
from typing import Literal

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput

import matplotlib.pyplot as plt
import numpy as np

# Automatický pokus o načtení .env souboru
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------- Konfigurace ----------
UKOLY_FILE = "ukoly.json"
TLUMENI_FILE = "tlumeni.json"
OFFLINE_FILE = "offline.json"
INBOX_FILE = "inbox.json"
PRIPOMINKY_FILE = "pripominky.json"
COORDS_FILE = "coords.json"  # Nový soubor pro Minecraft
LOG_LEVEL = logging.INFO
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("recepcni_bot")

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
OWNER_NAME = os.getenv("OWNER_NAME", "Majitel")

# Načtení příjemců z .env
RECIPIENTS_RAW = os.getenv("RECIPIENTS")
if RECIPIENTS_RAW:
    try:
        RECIPIENTS = json.loads(RECIPIENTS_RAW)
    except Exception:
        logger.error("⚠️ Chyba při parsování RECIPIENTS z .env. Používám výchozí nastavení.")
        RECIPIENTS = {OWNER_NAME: OWNER_ID}
else:
    # Tady se uplatní tvůj nápad! Dynamicky se vytvoří {"TvůjNick": TvojeID}
    RECIPIENTS = {OWNER_NAME: OWNER_ID}

BOT_START_TIME = datetime.datetime.now(datetime.timezone.utc)

CESKE_DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
CESKE_MESICE = ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen", "Červenec", "Srpen", "Září", "Říjen",
                "Listopad", "Prosinec"]


# ---------- Bezpečný zápis a načítání JSON ----------
def atomic_write_json(path, data):
    dirn = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", delete=False, dir=dirn, encoding="utf-8") as tf:
        json.dump(data, tf, ensure_ascii=False, indent=4)
        tmpname = tf.name
    os.replace(tmpname, path)


def _load_json(path, default_type=dict):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception(f"Chyba při načítání {path}, inicializuji prázdný objekt.")
            return default_type()
    return default_type()


ukoly_dict = _load_json(UKOLY_FILE, dict)
tlumeni_dict = _load_json(TLUMENI_FILE, dict)
offline_dict = _load_json(OFFLINE_FILE, dict)
inbox_dict = _load_json(INBOX_FILE, dict)
pripominky_list = _load_json(PRIPOMINKY_FILE, list)
coords_list = _load_json(COORDS_FILE, list)


def uloz_ukoly(): atomic_write_json(UKOLY_FILE, ukoly_dict)


def uloz_tlumeni(): atomic_write_json(TLUMENI_FILE, tlumeni_dict)


def uloz_offline(): atomic_write_json(OFFLINE_FILE, offline_dict)


def uloz_inbox(): atomic_write_json(INBOX_FILE, inbox_dict)


def uloz_pripominky(): atomic_write_json(PRIPOMINKY_FILE, pripominky_list)


def uloz_coords(): atomic_write_json(COORDS_FILE, coords_list)


# ---------- Bot Inicializace ----------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
party_channels = set()


# ---------- Pomocné funkce pro Workload & Statistiky ----------
def spocitej_workload(user_id: int) -> Counter:
    dnes = datetime.date.today()
    workload = Counter()
    ukoly = ukoly_dict.get(str(user_id), [])
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


def predikuj_workload(user_id: int) -> str:
    workload = spocitej_workload(user_id)
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


def workload_trend(user_id: int, period_days: int = 14, predict_days: int = 5, alpha: float = 0.3) -> str:
    dnes = datetime.date.today()
    start_date = dnes - datetime.timedelta(days=period_days - 1)
    ukoly = ukoly_dict.get(str(user_id), [])
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


async def posli_ukoly(user: discord.User):
    dnes = datetime.date.today()
    ukoly = ukoly_dict.get(str(user.id), [])

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
    if zmena: uloz_ukoly()

    aktivni_ukoly = [u for u in ukoly if u.get("stav") == "aktivní"]

    if not aktivni_ukoly:
        embed = discord.Embed(title="📭 Žádné úkoly", description="Nemáš žádné aktivní úkoly. 🎉",
                              color=discord.Color.green())
        try:
            await user.send(embed=embed)
        except Exception:
            pass
        return

    embed = discord.Embed(title="📚 Tvoje aktivní úkoly", description=f"Dnes je **{dnes.strftime('%d.%m.%Y')}**",
                          color=discord.Color.blurple())

    for u in aktivni_ukoly:
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

    embed.set_footer(text="💡 K ovládání úkolů použij příkazy /hotovo, /smaz nebo /pridej.")
    try:
        await user.send(embed=embed)
    except Exception:
        pass


async def posli_ukoly_na_den(user: discord.User, datum: datetime.date):
    ukoly = ukoly_dict.get(str(user.id), [])
    embed = discord.Embed(title=f"Úkoly na {datum.strftime('%d.%m.%Y')} ({CESKE_DNY[datum.weekday()]})",
                          color=discord.Color.blue())
    denni_ukoly = [u for u in ukoly if u.get("deadline") == datum.strftime("%Y-%m-%d") and u.get("stav") == "aktivní"]

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


async def workload_graf(user_id: int):
    ukoly = ukoly_dict.get(str(user_id), [])
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


# ---------- Týdenní Kalendář View ----------
class TydenniKalendarView(discord.ui.View):
    def __init__(self, user: discord.User, start_date: datetime.date, message: discord.Message = None):
        super().__init__(timeout=None)
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
            ukoly = ukoly_dict.get(str(self.user.id), [])
            ma_ukol = any(u.get("deadline") == den.strftime("%Y-%m-%d") and u.get("stav") == "aktivní" for u in ukoly)

            style = discord.ButtonStyle.success if ma_ukol else discord.ButtonStyle.primary
            btn = Button(label=label, style=style)

            async def day_cb(interaction: discord.Interaction, datum=den):
                if interaction.user.id != self.user.id:
                    return await interaction.response.send_message("❌ Toto není tvoje volba.", ephemeral=True)
                await posli_ukoly_na_den(self.user, datum)
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
        if interaction.user.id != self.user.id: return await interaction.response.send_message("❌ Omezeno.",
                                                                                               ephemeral=True)
        self.start_date -= datetime.timedelta(days=7)
        self._build()
        await interaction.response.edit_message(view=self)

    async def _next_week(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id: return await interaction.response.send_message("❌ Omezeno.",
                                                                                               ephemeral=True)
        self.start_date += datetime.timedelta(days=7)
        self._build()
        await interaction.response.edit_message(view=self)


# ---------- MODALY (Formuláře Recepce & Úkoly) ----------
class SchuzkaModal(Modal, title='Žádost o schůzku / hovor'):
    tema = TextInput(label='Téma schůzky / hovoru', placeholder='O čem se budeme bavit?', max_length=100)
    termin = TextInput(label='Navrhovaný termín', placeholder='Kdy se ti to hodí? (např. Zítra v 16:00)',
                       max_length=100)
    detail = TextInput(label='Další detaily', style=discord.TextStyle.paragraph, required=False, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        now = datetime.datetime.utcnow().isoformat()
        zprava = f"🤝 **ŽÁDOST O SCHŮZKU**\n• **Téma:** {self.tema.value}\n• **Termín:** {self.termin.value}\n• **Detaily:** {self.detail.value or 'Bez detailů'}"

        if str(OWNER_ID) not in inbox_dict:
            inbox_dict[str(OWNER_ID)] = []
        inbox_dict[str(OWNER_ID)].append({
            "from_id": interaction.user.id,
            "from_name": interaction.user.display_name,
            "text": zprava,
            "timestamp": now,
            "owner_reply": False
        })
        uloz_inbox()

        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(
                f"🛎️ **CINK!** Nová žádost o schůzku od {interaction.user.mention}!\nZkontroluj si `/inbox`.")
        except Exception:
            pass

        await interaction.response.send_message("✅ Recepční zapsal tvou žádost o schůzku. Brzy se ti ozveme!",
                                                ephemeral=True)


class ReplyModal(discord.ui.Modal, title='Odpověď na zprávu'):
    reply_text = discord.ui.TextInput(
        label='Tvoje odpověď',
        style=discord.TextStyle.paragraph,
        placeholder='Napiš svou odpověď sem...',
        required=True,
        max_length=2000
    )

    def __init__(self, target_id: int, target_name: str):
        super().__init__(title=f"Odpověď pro {target_name}")
        self.target_id = target_id
        self.target_name = target_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target = await bot.fetch_user(self.target_id)
            await target.send(
                f"✉️ Odpověď od uživatele **{interaction.user.display_name}**:\n\n{self.reply_text.value}")

            for m in inbox_dict.get(str(OWNER_ID), []):
                if m["from_id"] == self.target_id and not m.get("owner_reply"):
                    m["owner_reply"] = True
                    m["reply_text"] = self.reply_text.value
                    m["reply_timestamp"] = datetime.datetime.utcnow().isoformat()
            uloz_inbox()

            await interaction.response.send_message(f"✅ Odpověď úspěšně odeslána uživateli **{self.target_name}**.",
                                                    ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ Nepodařilo se zprávu doručit (uživatel mohl zablokovat bota).",
                                                    ephemeral=True)


class SingleReplyView(discord.ui.View):
    def __init__(self, target_id: int, target_name: str):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.target_name = target_name

    @discord.ui.button(label="Odpovědět", style=discord.ButtonStyle.success, emoji="✉️")
    async def reply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("❌ Nemáš oprávnění.", ephemeral=True)

        await interaction.response.send_modal(ReplyModal(self.target_id, self.target_name))

        button.disabled = True
        button.label = "Odpovídáš..."
        button.style = discord.ButtonStyle.secondary
        await interaction.edit_original_response(view=self)


class DMReceptionView(View):
    def __init__(self, author: discord.User, text: str):
        super().__init__(timeout=60)
        self.author = author
        self.text = text

        for name, uid in RECIPIENTS.items():
            btn = Button(label=f"Poslat uživateli {name}", style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(uid, name)
            self.add_item(btn)

    def make_callback(self, uid, name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            target_user = await bot.fetch_user(uid)
            try:
                embed = discord.Embed(title="📩 Nová zpráva z recepce", description=self.text,
                                      color=discord.Color.blue())
                embed.set_author(name=self.author.display_name, icon_url=self.author.display_avatar.url)
                await target_user.send(embed=embed)
                await interaction.followup.send(f"✅ Tvoje zpráva byla bezpečně předána uživateli **{name}**.",
                                                ephemeral=True)

                now = datetime.datetime.utcnow().isoformat()
                target_key = str(uid)
                entry = {
                    "from_id": self.author.id, "from_name": self.author.display_name,
                    "text": self.text, "timestamp": now, "owner_reply": False,
                    "reply_text": None, "reply_timestamp": None
                }
                if target_key not in inbox_dict: inbox_dict[target_key] = []
                inbox_dict[target_key].append(entry)
                uloz_inbox()

                if offline_dict.get(str(uid), False):
                    embed_off = discord.Embed(
                        title=f"🙇 Uživatel {name} je offline",
                        description=f"Tvou zprávu dostane, ale odpoví ti později.\n\n🌐 Mezitím se můžeš podívat na:\n• [Oficiální Web](https://rgliho.cz)\n• [YouTube Kanál](https://rgliho.cz/youtube)",
                        color=discord.Color.orange()
                    )
                    await self.author.send(embed=embed_off)
            except Exception:
                await interaction.followup.send("⚠️ Nepodařilo se zprávu doručit.", ephemeral=True)
            self.stop()

        return callback


class PridejUkolModal(Modal, title='📝 Přidat nový školní úkol'):
    predmet = TextInput(label='Předmět', placeholder='Např. Matematika, Fyzika...', max_length=50)
    ukol = TextInput(label='Zadání úkolu', style=discord.TextStyle.paragraph,
                     placeholder='Napiš, co přesně máš udělat...', max_length=500)
    datum = TextInput(label='Datum odevzdání (YYYY-MM-DD)', placeholder='2026-05-20', min_length=10, max_length=10)
    cas = TextInput(label='Čas odevzdání (HH:MM)', placeholder='12:00', default='12:00', max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            datetime.datetime.strptime(self.datum.value, "%Y-%m-%d")
            uid = str(interaction.user.id)
            if uid not in ukoly_dict: ukoly_dict[uid] = []
            ukoly_dict[uid].append({
                "predmet": self.predmet.value, "ukol": self.ukol.value,
                "deadline": self.datum.value, "time": self.cas.value, "stav": "aktivní"
            })
            uloz_ukoly()
            embed = discord.Embed(title="✅ Úkol úspěšně uložen", color=discord.Color.green())
            embed.add_field(name=self.predmet.value,
                            value=f"{self.ukol.value}\n📅 {self.datum.value} v {self.cas.value}")
            await interaction.response.send_message(embed=embed)
        except ValueError:
            await interaction.response.send_message("❌ Špatný formát data! Použij YYYY-MM-DD (např. 2026-05-20).",
                                                    ephemeral=True)


class UpravitUkolModal(Modal):
    def __init__(self, uid: str, task_idx: int, task_data: dict):
        super().__init__(title="✏️ Upravit existující úkol")
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
            ukoly_dict[self.uid][self.task_idx].update({
                "predmet": self.predmet.value, "ukol": self.ukol.value, "deadline": self.datum.value
            })
            uloz_ukoly()
            await interaction.response.send_message(f"✅ Úkol **{self.predmet.value}** byl úspěšně upraven.",
                                                    ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Špatný formát data! Použij YYYY-MM-DD.", ephemeral=True)


class PoslatZpravuModal(Modal):
    def __init__(self, target_id: int, target_name: str):
        super().__init__(title=f"📩 Zpráva pro {target_name}")
        self.target_id = target_id
        self.target_name = target_name
        self.text = TextInput(label='Text zprávy', style=discord.TextStyle.paragraph, placeholder='Co chceš vyřídit?',
                              required=True)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        target = await bot.fetch_user(self.target_id)
        try:
            await target.send(f"📩 Přeposlaná zpráva od **{interaction.user.display_name}**:\n{self.text.value}")
            uid_str = str(self.target_id)
            if uid_str not in inbox_dict: inbox_dict[uid_str] = []
            inbox_dict[uid_str].append(
                {"from_id": interaction.user.id, "from_name": interaction.user.display_name, "text": self.text.value,
                 "timestamp": datetime.datetime.utcnow().isoformat(), "owner_reply": False})
            uloz_inbox()
            await interaction.response.send_message(f"✅ Zpráva pro uživatele {self.target_name} byla doručena.",
                                                    ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ Nepodařilo se doručit zprávu.", ephemeral=True)


class MinecraftCoordsModal(Modal, title="🌍 Uložit Minecraft Pozici"):
    nazev = TextInput(label="Název lokace", placeholder="Např. Slime farma, End portál...", max_length=100)
    souradnice = TextInput(label="Souřadnice (X Y Z)", placeholder="150 64 -300")
    dimenze = TextInput(label="Dimenze", placeholder="Overworld / Nether / End", default="Overworld")

    async def on_submit(self, interaction: discord.Interaction):
        zaznam = {
            "nazev": self.nazev.value,
            "coords": self.souradnice.value,
            "dimenze": self.dimenze.value,
            "verze": "1.21.11",
            "datum": datetime.datetime.now().strftime("%d.%m.%Y")
        }
        coords_list.append(zaznam)
        uloz_coords()

        embed = discord.Embed(title="📍 Pozice úspěšně uložena", color=discord.Color.dark_green())
        embed.add_field(name=zaznam["nazev"],
                        value=f"**XYZ:** {zaznam['coords']}\n**Dimenze:** {zaznam['dimenze']}\n**Verze:** {zaznam['verze']}",
                        inline=False)
        await interaction.response.send_message(embed=embed)


# ---------- Events & Background Tasks ----------
@bot.event
async def on_ready():
    logger.info(f"Bot běží jako {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync()
        logger.info("Slash příkazy byly úspěšně celosvětově synchronizovány.")
    except Exception:
        logger.exception("Chyba při synchronizaci slash příkazů.")

    if not pripomenuti_ukolu.is_running(): pripomenuti_ukolu.start()
    if not kontrola_pripominek.is_running(): kontrola_pripominek.start()

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="zvonek na recepci 🛎️"))


posledni_poslani_datum = None


@tasks.loop(seconds=30)
async def pripomenuti_ukolu():
    global posledni_poslani_datum
    ted = datetime.datetime.now()
    if ted.hour == 18 and ted.minute == 0:
        if posledni_poslani_datum == ted.date(): return
        for user_id in list(ukoly_dict.keys()):
            if tlumeni_dict.get(str(user_id), False): continue
            try:
                user = await bot.fetch_user(int(user_id))
                if user:
                    await posli_ukoly(user)
                    pred = predikuj_workload(int(user_id))
                    await user.send(f"🔮 **Předpověď na další dny:**\n{pred}")
            except Exception:
                pass
        posledni_poslani_datum = ted.date()


@tasks.loop(seconds=30)
async def kontrola_pripominek():
    global pripominky_list
    now = datetime.datetime.now()
    zmena = False
    zbyvajici = []

    for p in pripominky_list:
        try:
            cas_obj = datetime.datetime.strptime(p["cas"], "%Y-%m-%d %H:%M:%S")
            if now >= cas_obj:
                user = await bot.fetch_user(p["user_id"])
                if user:
                    embed = discord.Embed(title="🔔 Připomínka!", description=p["text"], color=discord.Color.gold(),
                                          timestamp=datetime.datetime.utcnow())
                    await user.send(embed=embed)
                zmena = True
            else:
                zbyvajici.append(p)
        except Exception:
            zmena = True

    if zmena:
        pripominky_list = zbyvajici
        uloz_pripominky()


# ---------- Slash Commands Implementation ----------

@bot.tree.command(name="pridej", description="Otevře rychlý formulář pro přidání nového úkolu.")
async def pridej_slash(interaction: discord.Interaction):
    await interaction.response.send_modal(PridejUkolModal())


@bot.tree.command(name="upravit", description="Umožní upravit existující úkol přes čistý formulář.")
async def upravit_slash(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ukoly = ukoly_dict.get(uid, [])
    if not ukoly:
        return await interaction.response.send_message("⚠️ Nemáš žádné úkoly k úpravě.", ephemeral=True)

    options = [discord.SelectOption(label=f"{u['predmet']} - {u['ukol'][:30]}", value=str(i)) for i, u in
               enumerate(ukoly)]
    select = Select(placeholder="Vyber úkol k úpravě", options=options[:25])

    async def cb(inter: discord.Interaction):
        if inter.user.id != interaction.user.id: return
        idx = int(select.values[0])
        await inter.response.send_modal(UpravitUkolModal(uid, idx, ukoly[idx]))

    select.callback = cb
    v = View();
    v.add_item(select)
    await interaction.response.send_message("Zvol úkol k editaci:", view=v, ephemeral=True)


@bot.tree.command(name="smaz", description="Kompletně odstraní vybraný úkol z databáze úkolů.")
async def smaz_slash(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ukoly = ukoly_dict.get(uid, [])
    if not ukoly:
        return await interaction.response.send_message("⚠️ Nemáš žádné úkoly ke smazání.", ephemeral=True)

    options = [discord.SelectOption(label=f"{u['predmet']} - {u['ukol'][:30]}", value=str(i)) for i, u in
               enumerate(ukoly)]
    select = Select(placeholder="Zvol úkol ke smazání", options=options[:25])

    async def cb(inter: discord.Interaction):
        if inter.user.id != interaction.user.id: return
        idx = int(select.values[0])
        odstranen = ukoly.pop(idx)
        uloz_ukoly()
        await inter.response.edit_message(content=f"🗑️ Úkol **{odstranen.get('ukol')}** byl permanentně smazán.",
                                          view=None)

    select.callback = cb
    v = View();
    v.add_item(select)
    await interaction.response.send_message("Vyber úkol k odstranění:", view=v, ephemeral=True)


@bot.tree.command(name="smaz_vse", description="Pročistí databázi od starých, vypršelých nebo dokončených úkolů.")
async def smaz_vse_slash(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ukoly = ukoly_dict.get(uid, [])
    puvodni_pocet = len(ukoly)
    ukoly_dict[uid] = [u for u in ukoly if u.get("stav") == "aktivní"]
    uloz_ukoly()
    smazano = puvodni_pocet - len(ukoly_dict[uid])
    await interaction.response.send_message(f"🧹 Databáze pročištěna. Smazáno {smazano} archivovaných/vypršelých úkolů.",
                                            ephemeral=True)


@bot.tree.command(name="ukoly", description="Vypíše přehledný seznam všech aktuálně aktivních školních úkolů.")
async def ukoly_slash(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Kontroluji a generuji seznam úkolů...", ephemeral=True)
    await posli_ukoly(interaction.user)


@bot.tree.command(name="hotovo", description="Označí školní úkol za dokončený a uloží ho do statistik.")
async def hotovo_slash(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ukoly = ukoly_dict.get(uid, [])
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
        uloz_ukoly()
        await inter.response.edit_message(content=f"🎉 Úkol **{ukoly[idx]['ukol']}** byl splněn! Dobrá práce.",
                                          view=None)

    select.callback = cb
    v = View();
    v.add_item(select)
    await interaction.response.send_message("🏆 Který úkol jsi dokončil?", view=v, ephemeral=True)


@bot.tree.command(name="statistiky", description="Ukáže tvou úspěšnost a rozpad plnění úkolů podle předmětů.")
async def statistiky_slash(interaction: discord.Interaction):
    ukoly = ukoly_dict.get(str(interaction.user.id), [])
    if not ukoly:
        return await interaction.response.send_message("📊 Zatím nemáš v databázi žádná data o úkolech.", ephemeral=True)

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


@bot.tree.command(name="workload", description="Zobrazí podrobnou matematickou analýzu vytížení a graf.")
async def workload_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    zprava = predikuj_workload(interaction.user.id)
    predikce = workload_trend(interaction.user.id)
    graf = await workload_graf(interaction.user.id)
    obsah = f"📊 **Aktuální přehled tvého workloadu:**\n{zprava}\n\n{predikce}"

    if graf:
        await interaction.followup.send(content=obsah, file=discord.File(graf, "workload.png"))
    else:
        await interaction.followup.send(content=obsah)


@bot.tree.command(name="tlum", description="Ztlumí nebo aktivuje automatické večerní zasílání úkolů.")
async def tlum_slash(interaction: discord.Interaction, stav: Literal["on", "off"]):
    uid = str(interaction.user.id)
    if stav == "on":
        tlumeni_dict[uid] = True
        await interaction.response.send_message("🔕 Připomenutí úkolů byla ztlumena.", ephemeral=True)
    else:
        tlumeni_dict[uid] = False
        await interaction.response.send_message("🔔 Připomenutí úkolů jsou nyní aktivní.", ephemeral=True)
    uloz_tlumeni()


@bot.tree.command(name="offline", description="Přepne tvůj status bota do offline režimu s automatickou omluvou.")
async def offline_slash(interaction: discord.Interaction, stav: Literal["on", "off"]):
    uid = str(interaction.user.id)
    if stav == "on":
        offline_dict[uid] = True
        await interaction.response.send_message("🔕 Tvůj **offline režim** byl aktivován.", ephemeral=True)
    else:
        offline_dict[uid] = False
        await interaction.response.send_message("🔔 Tvůj **offline režim** byl vypnut.", ephemeral=True)
    uloz_offline()


@bot.tree.command(name="posli", description="Odešle zprávu vybranému uživateli přes recepční formulář.")
async def posli_slash(interaction: discord.Interaction):
    options = [discord.SelectOption(label=name, value=str(uid)) for name, uid in RECIPIENTS.items()]
    select = Select(placeholder="Komu chceš napsat?", options=options)

    async def cb(inter: discord.Interaction):
        if inter.user.id != interaction.user.id: return
        target_uid = int(select.values[0])
        name = next(n for n, u in RECIPIENTS.items() if u == target_uid)
        await inter.response.send_modal(PoslatZpravuModal(target_uid, name))

    select.callback = cb
    v = View();
    v.add_item(select)
    await interaction.response.send_message("Vyber příjemce zprávy:", view=v, ephemeral=True)


@bot.tree.command(name="inbox", description="Zobrazí nové doručené zprávy v recepci a umožní na ně odpovědět.")
async def inbox_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("❌ Nemáš oprávnění k tomuto příkazu.", ephemeral=True)

    msgs = inbox_dict.get(str(OWNER_ID), [])

    new_msgs_by_user = {}
    for m in msgs:
        if not m.get("owner_reply"):
            uid = m["from_id"]
            if uid not in new_msgs_by_user:
                new_msgs_by_user[uid] = []
            new_msgs_by_user[uid].append(m)

    if not new_msgs_by_user:
        return await interaction.response.send_message("📭 Tvůj inbox je prázdný, nemáš žádné nové zprávy.",
                                                       ephemeral=True)

    await interaction.response.send_message("📥 **Nové (neodpovězené) zprávy:**", ephemeral=True)

    for uid, user_msgs in list(new_msgs_by_user.items())[:10]:
        uname = user_msgs[0]["from_name"]
        hist_text = "\n".join(f"• {m['text']}" for m in user_msgs[-3:])

        embed = discord.Embed(
            title=f"Nová zpráva od: {uname}",
            description=hist_text,
            color=discord.Color.green(),
            timestamp=datetime.datetime.fromisoformat(user_msgs[-1]["timestamp"])
        )
        view = SingleReplyView(target_id=uid, target_name=uname)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="pripomen", description="Nastaví spolehlivou jednorázovou připomínku (Formát času HH:MM).")
@app_commands.describe(cas="Čas spuštění (např. 15:30)", text="Co ti má bot připomenout")
async def pripomen_slash(interaction: discord.Interaction, cas: str, text: str):
    try:
        h, m = map(int, cas.split(":"))
        ted = datetime.datetime.now()
        cil = ted.replace(hour=h, minute=m, second=0, microsecond=0)
        if cil < ted: cil += datetime.timedelta(days=1)

        pripominky_list.append({
            "user_id": interaction.user.id,
            "cas": cil.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text
        })
        uloz_pripominky()
        await interaction.response.send_message(
            f"⏰ Připomínka bezpečně uložena. Připomenu ti **'{text}'** v **{cas}**.", ephemeral=True)
    except Exception:
        await interaction.response.send_message("⚠️ Špatný formát času! Použij formát `HH:MM` (např. `16:00`).",
                                                ephemeral=True)


@bot.tree.command(name="kalendar",
                  description="Zobrazí přehledný textový kalendář na tento měsíc se zvýrazněným dneškem.")
async def kalendar_slash(interaction: discord.Interaction):
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


@bot.tree.command(name="kalendar_tyden", description="Zašle plně interaktivní týdenní kalendář přímo do tvých DM.")
async def kalendar_tyden_slash(interaction: discord.Interaction):
    start = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
    view = TydenniKalendarView(interaction.user, start)
    try:
        msg = await interaction.user.send(
            embed=discord.Embed(title="📅 Týdenní kalendář", color=discord.Color.blurple()), view=view)
        view.message = msg;
        view._build()
        await interaction.response.send_message("✅ Tým odeslal interaktivní kalendář do tvých DM.", ephemeral=True)
    except Exception:
        await interaction.response.send_message("⚠️ Nelze odeslat zprávu do tvých DM. Povol si soukromé zprávy.",
                                                ephemeral=True)


@bot.tree.command(name="zazvonit", description="Pomyslný zvonek na recepci. Upozorní mě, že na mě čekáš.")
async def zazvonit_slash(interaction: discord.Interaction):
    try:
        owner = await bot.fetch_user(OWNER_ID)
        embed = discord.Embed(
            title="🛎️ Někdo zvoní na recepci!",
            description=f"Uživatel **{interaction.user.mention}** ({interaction.user.display_name}) tě právě shání na serveru.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        await owner.send(embed=embed)
        await interaction.response.send_message("🛎️ *Cink cink!* Zazvonil jsi. Zpráva byla doručena majiteli.",
                                                ephemeral=True)
    except Exception:
        await interaction.response.send_message("❌ Recepční zvonek je momentálně rozbitý (nedoručeno).", ephemeral=True)


@bot.tree.command(name="schuzka", description="Otevře formulář pro sjednání hovoru nebo schůzky.")
async def schuzka_slash(interaction: discord.Interaction):
    await interaction.response.send_modal(SchuzkaModal())


@bot.tree.command(name="vizitka", description="Recepční ti předá mou vizitku s kontakty a užitečnými odkazy.")
async def vizitka_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="🪪 Oficiální Vizitka", color=discord.Color.gold())
    embed.add_field(name="💼 Majitel", value=f"<@{OWNER_ID}>", inline=False)
    embed.add_field(name="🌐 Užitečné odkazy",
                    value="• [Oficiální Web](https://rgliho.cz)\n• [YouTube Kanál](https://rgliho.cz/youtube)",
                    inline=False)
    if interaction.client.user.display_avatar:
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="system", description="Zobrazí rychlost odezvy serveru (ping) a jak dlouho bot běží.")
async def system_slash(interaction: discord.Interaction):
    uptime = datetime.datetime.utcnow() - BOT_START_TIME
    dny, hodiny = uptime.days, uptime.seconds // 3600
    minuty = (uptime.seconds % 3600) // 60

    embed = discord.Embed(title="🖥️ Diagnostika a stav bota", color=discord.Color.dark_magenta())
    embed.add_field(name="📡 Odezva (Ping)", value=f"`{round(bot.latency * 1000)} ms`")
    embed.add_field(name="⏳ Uptime bota", value=f"`{dny}d {hodiny}h {minuty}m`")
    embed.add_field(name="🤖 Architektura",
                    value=f"Python {platform.python_version()} | discord.py {discord.__version__}", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rgliho", description="Zobrazí oficiální komunitní rozcestník, odkazy na web a YouTube.")
async def rgliho_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="🌐 Projekt RGLIHO.cz",
                          description="Vítej v našem komunitním rozcestníku! Zde najdeš všechny důležité odkazy.",
                          color=discord.Color.red())
    embed.add_field(name="💻 Webová stránka", value="[rgliho.cz](https://rgliho.cz)", inline=True)
    embed.add_field(name="📺 YouTube Kanál", value="[rgliho.cz/youtube](https://rgliho.cz/youtube)", inline=True)
    embed.set_footer(text="RGLIHO Bot • Všechna práva vyhrazena")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mc_pozice", description="Uloží souřadnice zajímavých lokací nebo redstone staveb v Minecraftu.")
async def mc_pozice_slash(interaction: discord.Interaction):
    await interaction.response.send_modal(MinecraftCoordsModal())


@bot.tree.command(name="vymaz", description="Promaže zadaný počet starých zpráv bota v DM kanálu.")
@app_commands.describe(pocet="Počet zpráv k vymazání (výchozí 10)")
async def vymaz_slash(interaction: discord.Interaction, pocet: int = 10):
    if isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("🧼 Čistím konverzaci...", ephemeral=True)
        deleted = 0
        async for msg in interaction.channel.history(limit=100):
            if deleted >= pocet: break
            if msg.author == bot.user:
                try:
                    await msg.delete();
                    deleted += 1
                except Exception:
                    pass
    else:
        await interaction.response.send_message("⚠️ Tento příkaz lze použít pouze uvnitř mých přímých zpráv (DM).",
                                                ephemeral=True)


@bot.tree.command(name="help", description="Zobrazí přehlednou nápovědu ke všem Slash příkazům.")
async def help_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="💡 Podrobný přehled moderních / příkazů", color=discord.Color.blurple())
    embed.add_field(name="📚 Správa školních úkolů",
                    value="`/pridej` – Rychlý formulář na úkol\n`/ukoly` – Seznam aktivních úkolů\n`/hotovo` – Označí úkol za splněný\n`/upravit` – Změna hodnot úkolu (formulář)\n`/smaz` a `/smaz_vse` – Smazání a pročištění úkolů\n`/statistiky` – Tvoje školní statistiky úspěšnosti",
                    inline=False)
    embed.add_field(name="📅 Kalendář & Čas",
                    value="`/kalendar` – Přehledný měsíční kalendář v chatu s dneškem\n`/kalendar_tyden` – Interaktivní rozhraní kalendáře do DM\n`/pripomen` – Spolehlivá perzistentní připomínka v čase HH:MM",
                    inline=False)
    embed.add_field(name="🔒 Recepce a profily",
                    value="`/zazvonit` – Virtuální zvonek na recepci (upozorní majitele)\n`/schuzka` – Sjednání schůzky/hovoru přes formulář\n`/vizitka` – Kontaktní údaje majitele bota\n`/offline` – Zapne/vypne automatickou omluvenku\n`/posli` – Odeslání zprávy přes okno (Modal)\n`/inbox` – Správce doručených zpráv (pro majitele)",
                    inline=False)
    embed.add_field(name="📊 Monitoring & Projekty",
                    value="`/workload` – Výpočet vytížení, trendy a graf v PNG\n`/system` – Diagnostika chodu bota a ping\n`/rgliho` a `/sluzby` – Rychlé odkazy na weby, matrix a CAD\n`/mc_pozice` – Rychlé uložení MC souřadnic\n`/party` – Založení chráněné hlasové místnosti",
                    inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="party", description="Založí izolovanou hlasovou místnost a rozešle pozvánky přátelům.")
@app_commands.describe(friend1="První přítel", friend2="Druhý přítel (volitelně)", friend3="Třetí přítel (volitelně)")
async def party(interaction: discord.Interaction, friend1: str, friend2: str = None, friend3: str = None):
    member, guild = interaction.user, interaction.guild
    if not isinstance(member, discord.Member) or not member.voice:
        return await interaction.response.send_message("❌ Pro spuštění lobby musíš fyzicky sedět ve voice kanálu!",
                                                       ephemeral=True)

    def find_member(query: str):
        if query.isdigit():
            m = guild.get_member(int(query))
            if m: return m
        for m in guild.members:
            if m.name.lower() == query.lower() or m.display_name.lower() == query.lower(): return m
        return None

    friends = []
    for q in [friend1, friend2, friend3]:
        if q:
            f = find_member(q)
            if not f: return await interaction.response.send_message(
                f"❌ Uživatel `{q}` nebyl na tomto serveru nalezen.", ephemeral=True)
            friends.append(f)

    v_channel = member.voice.channel
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  member: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)}
    for f in friends: overwrites[f] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

    new_channel = await guild.create_voice_channel(name=f"Party | {member.name}", category=v_channel.category,
                                                   overwrites=overwrites)
    party_channels.add(new_channel.id)
    await member.move_to(new_channel)

    class JoinButtonDM(View):
        def __init__(self, gid, cid):
            super().__init__(timeout=None)
            self.gid, self.cid = gid, cid

        @discord.ui.button(label="🎉 Připojit se do Party", style=discord.ButtonStyle.green)
        async def join(self, inter: discord.Interaction, btn: discord.ui.Button):
            g = bot.get_guild(self.gid);
            c = g.get_channel(self.cid);
            m = g.get_member(inter.user.id)
            if m and m.voice:
                await m.move_to(c);
                await inter.response.send_message(f"✅ Byl jsi přesunut do {c.name}", ephemeral=True)
            else:
                await inter.response.send_message("❌ Musíš být aktivně připojen v libovolném voice kanálu na serveru!",
                                                  ephemeral=True)

    v = JoinButtonDM(guild.id, new_channel.id)
    invited = []
    for f in friends:
        try:
            await f.send(f"🚀 Uživatel **{member.display_name}** tě zve do soukromé herní místnosti!", view=v)
            invited.append(f.mention)
        except Exception:
            pass

    msg = f"✅ Soukromá lobby **{new_channel.name}** úspěšně vytvořena."
    if invited: msg += f"\n📩 Pozvánky odeslány do DM uživatelům: {', '.join(invited)}"
    await interaction.response.send_message(msg)


@bot.event
async def on_voice_state_update(member, before, after):
    if before and before.channel and before.channel.id in party_channels:
        if len(before.channel.members) == 0:
            party_channels.discard(before.channel.id)
            try:
                await before.channel.delete()
            except Exception:
                pass


# ---------- Chytré zpracování DM (Frictionless Receptionist) ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        if not message.content.strip().startswith("/"):
            try:
                async for last_msg in message.channel.history(limit=2):
                    if last_msg.id == message.id:
                        continue

                    if last_msg.author == bot.user:
                        casovy_rozdil = (datetime.datetime.now(datetime.UTC) - last_msg.created_at).total_seconds()
                        if casovy_rozdil < 300:
                            if last_msg.embeds and last_msg.embeds[0].title == "📯 Interaktivní recepce":
                                break
                            else:
                                return
            except Exception:
                pass

            text = message.content.strip()
            if text:
                embed = discord.Embed(
                    title="📯 Interaktivní recepce",
                    description="Detekoval jsem, že chceš odeslat zprávu některému z našich členů.\nZvol kliknutím níže, komu zprávu doručíme:",
                    color=discord.Color.blurple()
                )
                view = DMReceptionView(author=message.author, text=text)
                await message.channel.send(embed=embed, view=view)
                return


# ---------- Spuštění aplikace ----------
if __name__ == "__main__":
    if not TOKEN:
        logger.error("Chybí DISCORD_TOKEN v proměnných prostředí. Ukončuji.")
    else:
        bot.run(TOKEN)