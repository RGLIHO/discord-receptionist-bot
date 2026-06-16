# -*- coding: utf-8 -*-
import datetime
import platform
from typing import Literal

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput


class SchuzkaModal(Modal, title='Žádost o schůzku / hovor'):
    tema = TextInput(label='Téma schůzky / hovoru', placeholder='O čem se budeme bavit?', max_length=100)
    termin = TextInput(label='Navrhovaný termín', placeholder='Kdy se ti to hodí? (např. Zítra v 16:00)',
                       max_length=100)
    detail = TextInput(label='Další detaily', style=discord.TextStyle.paragraph, required=False, max_length=1000)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        zprava = f"🤝 **ŽÁDOST O SCHŮZKU**\n• **Téma:** {self.tema.value}\n• **Termín:** {self.termin.value}\n• **Detaily:** {self.detail.value or 'Bez detailů'}"
        owner_id_str = str(self.cog.bot.owner_id_custom)

        await self.cog.bot.db.execute(
            "INSERT INTO inbox (target_id, from_id, from_name, text, timestamp, owner_reply) VALUES (?, ?, ?, ?, ?, 0)",
            (owner_id_str, interaction.user.id, interaction.user.display_name, zprava, now)
        )
        await self.cog.bot.db.commit()

        try:
            owner = await self.cog.bot.fetch_user(self.cog.bot.owner_id_custom)
            await owner.send(
                f"🛎️ **CINK!** Nová žádost o schůzku od {interaction.user.mention}!\nZkontroluj si `/inbox`.")
        except Exception:
            pass

        await interaction.response.send_message("✅ Recepční zapsal tvou žádost o schůzku. Brzy se ti ozveme!",
                                                ephemeral=True)


class ReplyModal(Modal):
    reply_text = TextInput(label='Tvoje odpověď', style=discord.TextStyle.paragraph,
                           placeholder='Napiš svou odpověď sem...', required=True, max_length=2000)

    def __init__(self, cog, target_id: int, target_name: str):
        super().__init__(title=f"Odpověď pro {target_name}")
        self.cog = cog
        self.target_id = target_id
        self.target_name = target_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target = await self.cog.bot.fetch_user(self.target_id)
            await target.send(
                f"✉️ Odpověď od uživatele **{interaction.user.display_name}**:\n\n{self.reply_text.value}")

            owner_id_str = str(self.cog.bot.owner_id_custom)
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            await self.cog.bot.db.execute(
                "UPDATE inbox SET owner_reply = 1, reply_text = ?, reply_timestamp = ? WHERE target_id = ? AND from_id = ? AND owner_reply = 0",
                (self.reply_text.value, now, owner_id_str, self.target_id)
            )
            await self.cog.bot.db.commit()

            await interaction.response.send_message(f"✅ Odpověď úspěšně odeslána uživateli **{self.target_name}**.",
                                                    ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ Nepodařilo se zprávu doručit (uživatel mohl zablokovat bota).",
                                                    ephemeral=True)


class SingleReplyView(View):
    def __init__(self, cog, target_id: int, target_name: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.target_id = target_id
        self.target_name = target_name

    @discord.ui.button(label="Odpovědět", style=discord.ButtonStyle.success, emoji="✉️")
    async def reply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cog.bot.owner_id_custom:
            return await interaction.response.send_message("❌ Nemáš oprávnění.", ephemeral=True)

        await interaction.response.send_modal(ReplyModal(self.cog, self.target_id, self.target_name))
        button.disabled = True
        button.label = "Odpovídáš..."
        button.style = discord.ButtonStyle.secondary
        await interaction.edit_original_response(view=self)


class DMReceptionView(View):
    def __init__(self, cog, author: discord.User, text: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.author = author
        self.text = text

        for name, uid in self.cog.bot.recipients_custom.items():
            btn = Button(label=f"Poslat uživateli {name}", style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(uid, name)
            self.add_item(btn)

    def make_callback(self, uid, name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            target_user = await self.cog.bot.fetch_user(uid)
            try:
                embed = discord.Embed(title="📩 Nová zpráva z recepce", description=self.text,
                                      color=discord.Color.blue())
                embed.set_author(name=self.author.display_name,
                                 icon_url=self.author.display_avatar.url if self.author.display_avatar else None)
                await target_user.send(embed=embed)
                await interaction.followup.send(f"✅ Tvoje zpráva byla bezpečně předána uživateli **{name}**.",
                                                ephemeral=True)

                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                target_key = str(uid)

                await self.cog.bot.db.execute(
                    "INSERT INTO inbox (target_id, from_id, from_name, text, timestamp, owner_reply) VALUES (?, ?, ?, ?, ?, 0)",
                    (target_key, self.author.id, self.author.display_name, self.text, now)
                )
                await self.cog.bot.db.commit()

                async with self.cog.bot.db.execute("SELECT is_offline FROM offline_status WHERE user_id = ?",
                                                   (target_key,)) as cursor:
                    row = await cursor.fetchone()
                    is_offline = bool(row[0]) if row else False

                if is_offline:
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


class PoslatZpravuModal(Modal):
    def __init__(self, cog, target_id: int, target_name: str):
        super().__init__(title=f"📩 Zpráva pro {target_name}")
        self.cog = cog
        self.target_id = target_id
        self.target_name = target_name
        self.text = TextInput(label='Text zprávy', style=discord.TextStyle.paragraph, placeholder='Co chceš vyřídit?',
                              required=True)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        target = await self.cog.bot.fetch_user(self.target_id)
        try:
            await target.send(f"📩 Přeposlaná zpráva od **{interaction.user.display_name}**:\n{self.text.value}")
            uid_str = str(self.target_id)

            await self.cog.bot.db.execute(
                "INSERT INTO inbox (target_id, from_id, from_name, text, timestamp, owner_reply) VALUES (?, ?, ?, ?, ?, 0)",
                (uid_str, interaction.user.id, interaction.user.display_name, self.text.value,
                 datetime.datetime.now(datetime.timezone.utc).isoformat())
            )
            await self.cog.bot.db.commit()

            await interaction.response.send_message(f"✅ Zpráva pro uživatele {self.target_name} byla doručena.",
                                                    ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ Nepodařilo se doručit zprávu.", ephemeral=True)


class ReceptionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.kontrola_pripominek.start()

    def cog_unload(self):
        self.kontrola_pripominek.cancel()

    def parsuj_cas(self, cas_str: str) -> datetime.datetime:
        now = datetime.datetime.now(datetime.timezone.utc)
        cas_str = cas_str.strip()

        try:
            t = datetime.datetime.strptime(cas_str, "%H:%M")
            cil = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if cil < now:
                cil += datetime.timedelta(days=1)
            return cil
        except ValueError:
            pass

        try:
            dt = datetime.datetime.strptime(cas_str, "%d.%m.%Y %H:%M")
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass

        try:
            dt = datetime.datetime.strptime(f"{cas_str} {now.year}", "%d.%m. %H:%M %Y")
            cil = dt.replace(tzinfo=datetime.timezone.utc)
            if cil < now:
                cil = cil.replace(year=now.year + 1)
            return cil
        except ValueError:
            pass

        try:
            dt = datetime.datetime.strptime(cas_str, "%Y-%m-%d %H:%M")
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass

        raise ValueError("Nepodporovaný formát data a času")

    @tasks.loop(seconds=30)
    async def kontrola_pripominek(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        async with self.bot.db.execute("SELECT id, user_id, cas, text FROM pripominky") as cursor:
            rows = await cursor.fetchall()

        for db_id, user_id, cas_str, text in rows:
            try:
                cas_obj = datetime.datetime.strptime(cas_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
                if now >= cas_obj:
                    user = await self.bot.fetch_user(user_id)
                    if user:
                        embed = discord.Embed(title="🔔 Připomínka!", description=text, color=discord.Color.gold(),
                                              timestamp=now)
                        await user.send(embed=embed)
                    await self.bot.db.execute("DELETE FROM pripominky WHERE id = ?", (db_id,))
                    await self.bot.db.commit()
            except Exception:
                await self.bot.db.execute("DELETE FROM pripominky WHERE id = ?", (db_id,))
                await self.bot.db.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            if not message.content.strip().startswith("/"):
                try:
                    async for last_msg in message.channel.history(limit=2):
                        if last_msg.id == message.id:
                            continue

                        if last_msg.author == self.bot.user:
                            casovy_rozdil = (datetime.datetime.now(
                                datetime.timezone.utc) - last_msg.created_at).total_seconds()
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
                    view = DMReceptionView(self, author=message.author, text=text)
                    await message.channel.send(embed=embed, view=view)

    @app_commands.command(name="offline",
                          description="Přepne tvůj status bota do offline režimu s automatickou omluvou.")
    async def offline_slash(self, interaction: discord.Interaction, stav: Literal["on", "off"]):
        uid = str(interaction.user.id)
        stav_int = 1 if stav == "on" else 0

        await self.bot.db.execute(
            "INSERT INTO offline_status (user_id, is_offline) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET is_offline=excluded.is_offline",
            (uid, stav_int)
        )
        await self.bot.db.commit()

        if stav == "on":
            await interaction.response.send_message("🔕 Tvůj **offline režim** byl aktivován.", ephemeral=True)
        else:
            await interaction.response.send_message("🔔 Tvůj **offline režim** byl vypnut.", ephemeral=True)

    @app_commands.command(name="posli", description="Odešle zprávu vybranému uživateli přes recepční formulář.")
    async def posli_slash(self, interaction: discord.Interaction):
        options = [discord.SelectOption(label=name, value=str(uid)) for name, uid in self.bot.recipients_custom.items()]
        select = Select(placeholder="Komu chceš napsat?", options=options)

        async def cb(inter: discord.Interaction):
            if inter.user.id != interaction.user.id: return
            target_uid = int(select.values[0])
            name = next(n for n, u in self.bot.recipients_custom.items() if u == target_uid)
            await inter.response.send_modal(PoslatZpravuModal(self, target_uid, name))

        select.callback = cb
        v = View()
        v.add_item(select)
        await interaction.response.send_message("Vyber příjemce zprávy:", view=v, ephemeral=True)

    @app_commands.command(name="inbox", description="Zobrazí nové doručené zprávy v recepci a umožní na ně odpovědět.")
    async def inbox_slash(self, interaction: discord.Interaction):
        if interaction.user.id != self.bot.owner_id_custom:
            return await interaction.response.send_message("❌ Nemáš oprávnění k tomuto příkazu.", ephemeral=True)

        owner_key = str(self.bot.owner_id_custom)

        async with self.bot.db.execute(
                "SELECT from_id, from_name, text, timestamp FROM inbox WHERE target_id = ? AND owner_reply = 0",
                (owner_key,)) as cursor:
            rows = await cursor.fetchall()

        new_msgs_by_user = {}
        for from_id, from_name, text, timestamp in rows:
            if from_id not in new_msgs_by_user:
                new_msgs_by_user[from_id] = []
            new_msgs_by_user[from_id].append({"from_name": from_name, "text": text, "timestamp": timestamp})

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
            view = SingleReplyView(self, target_id=uid, target_name=uname)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="pripomen",
                          description="Nastaví jednorázovou připomínku (Formáty: HH:MM, DD.MM. HH:MM, YYYY-MM-DD HH:MM).")
    @app_commands.describe(cas="Čas spuštění (např. 15:30 nebo 24.12. 18:00)", text="Co ti má bot připomenout")
    async def pripomen_slash(self, interaction: discord.Interaction, cas: str, text: str):
        try:
            cil = self.parsuj_cas(cas)
            cas_str = cil.strftime("%Y-%m-%d %H:%M:%S")

            await self.bot.db.execute("INSERT INTO pripominky (user_id, cas, text) VALUES (?, ?, ?)",
                                      (interaction.user.id, cas_str, text))
            await self.bot.db.commit()

            krasny_cas = cil.strftime("%d.%m.%Y v %H:%M")
            await interaction.response.send_message(
                f"⏰ Připomínka bezpečně uložena. Připomenu ti **'{text}'** dne **{krasny_cas}** (UTC).", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(
                f"⚠️ {str(e)}! Použij formáty `HH:MM`, `DD.MM. HH:MM` nebo `YYYY-MM-DD HH:MM`.", ephemeral=True)

    @app_commands.command(name="zazvonit", description="Pomyslný zvonek na recepci. Vyber si, na koho chceš zazvonit.")
    async def zazvonit_slash(self, interaction: discord.Interaction):
        options = [discord.SelectOption(label=name, value=str(uid)) for name, uid in self.bot.recipients_custom.items()]
        options.append(
            discord.SelectOption(label="Rick Astley", value="rickroll", description="Zazvonit na legendu popu",
                                 emoji="🎵"))

        select = discord.ui.Select(placeholder="Na koho chceš zazvonit?", options=options)

        async def cb(inter: discord.Interaction):
            if inter.user.id != interaction.user.id:
                await inter.response.send_message("Tento výběr není pro tebe!", ephemeral=True)
                return

            await inter.response.defer()
            vybrana_hodnota = select.values[0]

            if vybrana_hodnota == "rickroll":
                await interaction.edit_original_response(
                    content="🎵 **Never gonna give you up, never gonna let you down...** 🎵\nPrávě jsi chytil recepční Rickroll! 🛎️🕺\nhttps://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    view=None
                )
                return

            target_uid = int(vybrana_hodnota)
            name = next(n for n, u in self.bot.recipients_custom.items() if u == target_uid)

            try:
                target_user = await self.bot.fetch_user(target_uid)
                embed = discord.Embed(
                    title="🛎️ Někdo zvoní na recepci!",
                    description=f"Uživatel **{interaction.user.mention}** ({interaction.user.display_name}) tě právě shání na serveru.",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                await target_user.send(embed=embed)
                await interaction.edit_original_response(
                    content=f"🛎️ *Cink cink!* Zazvonil jsi na uživatele **{name}**. Zpráva byla doručena.", view=None)
            except Exception:
                await interaction.edit_original_response(
                    content=f"❌ Recepční zvonek pro uživatele **{name}** je momentálně rozbitý (nedoručeno).",
                    view=None)

        select.callback = cb
        v = discord.ui.View()
        v.add_item(select)
        await interaction.response.send_message("Vyber, na koho chceš zazvonit:", view=v, ephemeral=True)

    @app_commands.command(name="schuzka", description="Otevře formulář pro sjednání hovoru nebo schůzky.")
    async def schuzka_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SchuzkaModal(self))

    @app_commands.command(name="vizitka", description="Recepční ti předá mou vizitku s kontakty a užitečnými odkazy.")
    async def vizitka_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🪪 Oficiální Vizitka", color=discord.Color.gold())
        embed.add_field(name="💼 Majitel", value=f"<@{self.bot.owner_id_custom}>", inline=False)
        embed.add_field(name="🌐 Užitečné odkazy",
                        value="• [Oficiální Web](https://rgliho.cz)\n• [YouTube Kanál](https://rgliho.cz/youtube)",
                        inline=False)
        if interaction.client.user.display_avatar:
            embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="system", description="Zobrazí rychlost odezvy serveru (ping) a jak dlouho bot běží.")
    async def system_slash(self, interaction: discord.Interaction):
        uptime = datetime.datetime.now(datetime.timezone.utc) - self.bot.start_time_custom
        dny, hodiny = uptime.days, uptime.seconds // 3600
        minuty = (uptime.seconds % 3600) // 60

        embed = discord.Embed(title="🖥️ Diagnostika a stav bota", color=discord.Color.dark_magenta())
        embed.add_field(name="📡 Odezva (Ping)", value=f"`{round(self.bot.latency * 1000)} ms`")
        embed.add_field(name="⏳ Uptime bota", value=f"`{dny}d {hodiny}h {minuty}m`")
        embed.add_field(name="🤖 Architektura",
                        value=f"Python {platform.python_version()} | discord.py {discord.__version__}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rgliho", description="Zobrazí oficiální komunitní rozcestník, odkazy na web a YouTube.")
    async def rgliho_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🌐 Projekt RGLIHO.cz",
                              description="Vítej v našem komunitním rozcestníku! Zde najdeš všechny důležité odkazy.",
                              color=discord.Color.red())
        embed.add_field(name="💻 Webová stránka", value="[rgliho.cz](https://rgliho.cz)", inline=True)
        embed.add_field(name="📺 YouTube Kanál", value="[rgliho.cz/youtube](https://rgliho.cz/youtube)", inline=True)
        embed.set_footer(text="RGLIHO Bot • Všechna práva vyhrazena")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="vymaz", description="Promaže zadaný počet starých zpráv bota v DM kanálu.")
    @app_commands.describe(pocet="Počet zpráv k vymazání (výchozí 10)")
    async def vymaz_slash(self, interaction: discord.Interaction, pocet: int = 10):
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message("🧼 Čistím konverzaci...", ephemeral=True)
            deleted = 0
            async for msg in interaction.channel.history(limit=100):
                if deleted >= pocet: break
                if msg.author == self.bot.user:
                    try:
                        await msg.delete()
                        deleted += 1
                    except Exception:
                        pass
        else:
            await interaction.response.send_message("⚠️ Tento příkaz lze použít pouze uvnitř mých přímých zpráv (DM).",
                                                    ephemeral=True)

    @app_commands.command(name="help", description="Zobrazí přehlednou nápovědu ke všem Slash příkazům.")
    async def help_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="💡 Podrobný přehled moderních / příkazů", color=discord.Color.blurple())
        embed.add_field(name="📚 Správa školních úkolů",
                        value="`/pridej` – Rychlý formulář na úkol\n`/ukoly` – Seznam aktivních úkolů\n`/hotovo` – Označí úkol za splněný\n`/upravit` – Změna hodnot úkolu (formulář)\n`/smaz` a `/smaz_vse` – Smazání a pročištění úkolů\n`/statistiky` – Tvoje školní statistiky úspěšnosti",
                        inline=False)
        embed.add_field(name="📅 Kalendář & Čas",
                        value="`/kalendar` – Přehledný měsíční kalendář v chatu s dneškem\n`/kalendar_tyden` – Interaktivní rozhraní kalendáře do DM\n`/pripomen` – Spolehlivá perzistentní připomínka s flexibilním datem",
                        inline=False)
        embed.add_field(name="🔒 Recepce a profily",
                        value="`/zazvonit` – Virtuální zvonek na recepci (upozorní majitele)\n`/schuzka` – Sjednání schůzky/hovoru přes formulář\n`/vizitka` – Kontaktní údaje majitele bota\n`/offline` – Zapne/vypne automatickou omluvenku\n`/posli` – Odeslání zprávy přes okno (Modal)\n`/inbox` – Správce doručených zpráv (pro majitele)",
                        inline=False)
        embed.add_field(name="📊 Monitoring & Projekty",
                        value="`/workload` – Výpočet vytížení, trendy a graf v PNG\n`/system` – Diagnostika chodu bota a ping\n`/rgliho` – Rychlé odkazy na weby\n`/mc_pozice` a `/mc_seznam` – Správa MC souřadnic\n`/party` – Založení chráněné hlasové místnosti",
                        inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ReceptionCog(bot))