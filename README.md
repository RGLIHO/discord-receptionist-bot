<div align="center">
  <img width="200" height="200" alt="logo" src="https://github.com/user-attachments/assets/8a6a8dd8-0df9-46bc-88b2-6f8a85eeb086" />

  # 🛎️ Discord Receptionist & Task Manager Bot
</div>

Komplexní, česky komunikující Discord bot navržený pro osobní produktivitu, správu školních úkolů a automatickou recepci na tvém serveru. Nyní poháněn asynchronní **SQLite databází** pro maximální spolehlivost.

---

## ✨ Hlavní funkce

* **📚 Správa úkolů a vytížení:** Přidávání úkolů, generování grafů zátěže (workload) a matematická predikce stresových dní.
* **🛎️ Chytrá Recepce:** Pokud ti někdo napíše do DM (Direct Messages), bot automaticky nabídne doručení zprávy tobě, aniž by tě uživatel musel rušit.
* **📅 Interaktivní kalendáře:** Výpisy dnů a vizualizace termínů přímo v chatu.
* **🎉 Party Systém:** Možnost zakládat dočasné soukromé voice kanály na jedno kliknutí.
* **🌍 Minecraft Souřadnice:** Ukládání zajímavých lokací přímo do SQL databáze.
* **💾 Perzistentní úložiště:** Využívá `aiosqlite` pro bezpečné a rychlé ukládání dat.

---

## 📜 Seznam Slash příkazů (Slash Commands)

Bot kompletně využívá moderní Discord Slash příkazy.

### 📚 Správa školních úkolů
* `/pridej` – Otevře rychlý formulář pro přidání nového školního úkolu.
* `/ukoly` – Vypíše přehledný seznam všech aktuálně aktivních školních úkolů do DM.
* `/hotovo` – Zobrazí výběr aktivních úkolů a označí vybraný úkol za dokončený.
* `/upravit` – Umožní upravit parametry existujícího úkolu přes čistý formulář.
* `/smaz` – Kompletně odstraní vybraný úkol z databáze.
* `/smaz_vse` – Pročistí databázi od starých, vypršelých nebo dokončených úkolů.
* `/statistiky` – Ukáže tvou úspěšnost a rozpad plnění úkolů podle jednotlivých předmětů.

### 📊 Monitoring, Analýzy & Projekty
* `/workload` – Zobrazí podrobnou matematickou analýzu vytížení, budoucí trendy a vygeneruje vizuální graf v PNG.
* `/system` – Diagnostika chodu bota (ping, uptime, verze knihoven a stav databáze).
* `/rgliho` – Zobrazí oficiální komunitní rozcestník.
* `/mc_pozice` – Otevře formulář pro rychlé uložení souřadnic zajímavých lokací v Minecraftu.

### 📅 Kalendář & Čas
* `/kalendar` – Zobrazí přehledný textový kalendář na tento měsíc.
* `/kalendar_tyden` – Zašle interaktivní týdenní kalendář přímo do tvých DM.
* `/pripomen [cas] [text]` – Nastaví spolehlivou jednorázovou připomínku.

### 🔒 Recepce a profily
* `/zazvonit` – Virtuální zvonek na recepci (upozorní majitele).
* `/schuzka` – Otevře formulář pro sjednání hovoru.
* `/posli` – Odeslání zprávy přes recepční formulář.
* `/inbox` – *(Pouze majitel)* Správce doručených zpráv.
* `/tlum [on/off]` – Ztlumí večerní přehled úkolů.
* `/offline [on/off]` – Automatická omluvenka v DM.

### 🛠️ Ostatní příkazy
* `/party [friend1]...` – Založí izolovanou hlasovou místnost s pozvánkami.
* `/vymaz (pocet)` – Promaže zprávy v DM.
* `/vizitka` – Digitální vizitka majitele.
* `/help` – Přehledná nápověda.

---

## 🚀 Rychlý start

### 1. Naklonování repozitáře
```bash
git clone https://github.com/RGLIHO/discord-receptionist-bot.git
cd discord-receptionist-bot\receptionist-bot

```

### 2. Instalace závislostí

```bash
pip install -r requirements.txt

```

### 3. Konfigurace

Přejmenuj soubor `.env.example` na `.env` a doplň svůj **Discord token** a **Owner ID** a **Owner Name**.

### 4. Spuštění

```bash
python bot.py

```

*(Poznámka: Při prvním spuštění si bot automaticky vytvoří soubor `school_data.db` a `bot.db`)*
