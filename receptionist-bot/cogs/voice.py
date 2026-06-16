# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View

class JoinButtonDM(View):
    def __init__(self, bot, gid, cid):
        super().__init__(timeout=None)
        self.bot = bot
        self.gid = gid
        self.cid = cid

    @discord.ui.button(label="🎉 Připojit se do Party", style=discord.ButtonStyle.green)
    async def join(self, inter: discord.Interaction, btn: discord.ui.Button):
        g = self.bot.get_guild(self.gid)
        c = g.get_channel(self.cid)
        m = g.get_member(inter.user.id)
        if m and m.voice:
            await m.move_to(c)
            await inter.response.send_message(f"✅ Byl jsi přesunut do {c.name}", ephemeral=True)
        else:
            await inter.response.send_message("❌ Musíš být aktivně připojen v libovolném voice kanálu na serveru!", ephemeral=True)

class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="party", description="Založí izolovanou hlasovou místnost a rozešle pozvánky přátelům.")
    @app_commands.describe(friend1="První přítel", friend2="Druhý přítel (volitelně)", friend3="Třetí přítel (volitelně)")
    async def party(self, interaction: discord.Interaction, friend1: str, friend2: str = None, friend3: str = None):
        member = interaction.user
        guild = interaction.guild
        if not isinstance(member, discord.Member) or not member.voice:
            return await interaction.response.send_message("❌ Pro spuštění lobby musíš fyzicky sedět ve voice kanálu!", ephemeral=True)

        def find_member(query: str):
            if query.isdigit():
                m = guild.get_member(int(query))
                if m: return m
            for m in guild.members:
                if m.name.lower() == query.lower() or m.display_name.lower() == query.lower():
                    return m
            return None

        friends = []
        for q in [friend1, friend2, friend3]:
            if q:
                f = find_member(q)
                if not f:
                    return await interaction.response.send_message(f"❌ Uživatel `{q}` nebyl na tomto serveru nalezen.", ephemeral=True)
                friends.append(f)

        v_channel = member.voice.channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        }
        for f in friends:
            overwrites[f] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

        new_channel = await guild.create_voice_channel(name=f"Party | {member.name}", category=v_channel.category, overwrites=overwrites)
        self.bot.party_channels.add(new_channel.id)
        await member.move_to(new_channel)

        v = JoinButtonDM(self.bot, guild.id, new_channel.id)
        invited = []
        for f in friends:
            try:
                await f.send(f"🚀 Uživatel **{member.display_name}** tě zve do soukromé herní místnosti!", view=v)
                invited.append(f.mention)
            except Exception:
                pass

        msg = f"✅ Soukromá lobby **{new_channel.name}** úspěšně vytvořena."
        if invited:
            msg += f"\n📩 Pozvánky odeslány do DM uživatelům: {', '.join(invited)}"
        await interaction.response.send_message(msg)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before and before.channel and before.channel.id in self.bot.party_channels:
            if len(before.channel.members) == 0:
                self.bot.party_channels.discard(before.channel.id)
                try:
                    await before.channel.delete()
                except Exception:
                    pass

async def setup(bot):
    await bot.add_cog(VoiceCog(bot))