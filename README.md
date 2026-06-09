<div align="center">
  <img width="200" height="200" alt="logo" src="https://github.com/user-attachments/assets/8a6a8dd8-0df9-46bc-88b2-6f8a85eeb086" />

  # 🛎️ Discord Receptionist & Task Manager Bot
</div>

Komplexní, česky komunikující Discord bot navržený pro osobní produktivitu, správu školních úkolů a automatickou recepci na tvém serveru.

---

## ✨ Hlavní funkce

* **📚 Správa úkolů a vytížení:** Přidávání úkolů, generování grafů zátěže (workload) a matematická predikce stresových dní.
* **🛎️ Chytrá Recepce:** Pokud ti někdo napíše do DM (Direct Messages), bot automaticky nabídne doručení zprávy tobě, aniž by tě uživatel musel rušit.
* **📅 Interaktivní kalendáře:** Výpisy dnů a vizualizace termínů přímo v chatu.
* **🎉 Party Systém:** Možnost zakládat dočasné soukromé voice kanály na jedno kliknutí.
* **🌍 Minecraft Souřadnice:** Ukládání zajímavých lokací přímo do botovy databáze.

---

## 📜 Seznam Slash příkazů (Slash Commands)

Bot kompletně využívá moderní Discord Slash příkazy. Zde je jejich kompletní přehled rozdělený podle kategorií:

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
* `/system` – Diagnostika chodu bota (rychlost odezvy/ping, uptime serveru, verze knihoven).
* `/rgliho` – Zobrazí oficiální komunitní rozcestník, odkazy na web a YouTube kanál.
* `/mc_pozice` – Otevře formulář pro rychlé uložení souřadnic zajímavých lokací nebo redstone staveb v Minecraftu.

### 📅 Kalendář & Čas
* `/kalendar` – Zobrazí přehledný textový kalendář na tento měsíc se zvýrazněným dnešním dnem.
* `/kalendar_tyden` – Zašle plně interaktivní tlačítkový týdenní kalendář přímo do tvých DM.
* `/pripomen [cas] [text]` – Nastaví spolehlivou jednorázovou připomínku (Formát času `HH:MM`, např. `15:30`).

### 🔒 Recepce a profily
* `/zazvonit` – Virtuální zvonek na recepci. Upozorní majitele bota v DM, že na něj někdo čeká.
* `/schuzka` – Otevře formulář pro sjednání hovoru nebo schůzky s detaily a termínem.
* `/posli` – Umožní vybrat příjemce a odeslat mu zprávu přes recepční formulář.
* `/inbox` – *(Pouze pro majitele)* Správce doručených zpráv. Zobrazí nové zprávy z recepce a umožní na ně odpovědět.
* `/tlum [on/off]` – Ztlumí nebo aktivuje automatické večerní zasílání přehledu úkolů (každý den v 18:00).
* `/offline [on/off]` – Přepne tvůj status bota do offline režimu s automatickou omluvou pro lidi, co ti píší.

### 🛠️ Ostatní příkazy
* `/party [friend1] (friend2) (friend3)` – Založí izolovanou hlasovou místnost, nastaví práva a rozešle pozvánky s tlačítkem pro připojení vybraným přátelům do DM.
* `/vymaz (pocet)` – Promaže zadaný počet starých zpráv bota v DM kanálu (výchozí hodnota je 10).
* `/vizitka` – Recepční ti předá digitální vizitku majitele s kontakty a užitečnými odkazy.
* `/help` – Zobrazí přehlednou nápovědu ke všem Slash příkazům přímo v Discordu.

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
Přejmenuj soubor `.env.example` na `.env` a doplň svůj Discord token a Owner ID.

### 4. Spuštění
```bash
python bot.py
```
