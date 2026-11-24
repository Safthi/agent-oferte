# Agent oferte de călătorie (București / Constanța)

Agentul verifică automat site-urile românești de oferte și îți trimite pe telefon fiecare
ofertă nouă cu **plecare din București (Otopeni/Băneasa), Constanța sau Tulcea**, ordonată după
cât de bună e (scor 0–100). **Nu trebuie instalat nimic pe telefon sau pe calculator**:
rulează gratuit pe GitHub, iar tu primești notificări în browser sau pe email.

## Ce site-uri urmărește

| Site | Ce publică |
|---|---|
| [calatorfaralimite.ro](https://calatorfaralimite.ro) | vacanțe zbor + cazare, zboruri ieftine |
| [tiptrip.ro](https://tiptrip.ro) | zboruri și pachete din București |
| [aventurescu.ro](https://aventurescu.ro) | zboruri ieftine, promoții ale companiilor |
| [travelator.ro](https://travelator.ro) | zboruri lungi, vacanțe DIY |
| [citybreak.club](https://www.citybreak.club) | city break-uri cu zbor direct + cazare |
| [cestee.ro](https://www.cestee.ro/oferte) | reduceri ale companiilor aeriene (în lei) |
| [fly4free.com](https://www.fly4free.com) | oferte europene, doar cele din București |

## Ce face, pas cu pas

1. Citește ultimele articole de pe fiecare site (feed RSS sau pagina de oferte).
2. Păstrează doar ofertele cu preț și cu plecare din București / Constanța / Tulcea.
   Ofertele din Cluj, Timișoara, Milano, Paris etc. sunt eliminate.
3. Calculează un **scor 0–100** comparând prețul cu un preț „normal”:
   - zbor dus-întors: ~100€ Europa, ~260€ Egipt/Dubai/Canare, ~780€ Asia/America;
   - zbor + cazare: prețul zborului + ~35€/noapte (60€/noapte la all inclusive);
   - bonus: plecare din Constanța (+10), din Tulcea (+20), destinație favorită (+10),
     cel mai mic preț văzut pentru acea destinație (+10).
4. Elimină dublurile: aceeași ofertă publicată pe două site-uri vine o singură dată.
5. Trimite notificarea: 🔥 **SUPER OFERTĂ** (scor ≥ 80) sau 👍 ofertă bună.
   Între 23:00 și 07:00 vin doar super-ofertele.
6. Actualizează pagina `index.html` cu toate ofertele din ultimele 14 zile, cea mai bună sus.

---

## Instalare doar din telefon (fără aplicații)

Totul se face din browserul telefonului (Chrome pe Android, Safari pe iPhone).
Dacă un buton de pe GitHub nu apare, activează **Site pentru desktop**
(Chrome: meniul ⋮ → „Site pentru desktop”; Safari: „aA” → „Solicită site-ul desktop”).

### Pasul 1: cont GitHub și repository
1. Intră pe **github.com** → **Sign up** → email, parolă, nume de utilizator → confirmă codul primit pe email.
2. Intră pe **github.com/new**:
   - Repository name: `agent-oferte`
   - bifează **Public** (minute de rulare nelimitate și gratuite)
   - **nu** bifa „Add a README file”
   - **Create repository**.

### Pasul 2: urcă fișierele
**Varianta ușoară:** conectează GitHub la Claude (claude.ai/connect-github), dă acces la
repository-ul `agent-oferte` și cere-i lui Claude să urce codul.

**Varianta manuală:**
1. Descarcă arhiva `agent-oferte.zip` și dezarhiveaz-o (aplicația de fișiere a telefonului: apasă pe arhivă → „Extrage”).
2. În repository: **Add file → Upload files** → alege `agent_oferte.py`, `config.json`, `README.md` → **Commit changes**.
3. **Add file → Create new file** → la nume scrie exact `.github/workflows/oferte.yml` →
   lipește conținutul fișierului `oferte.yml` din arhivă → **Commit changes**.

### Pasul 3: unde primești notificările (alege una sau ambele)

**A. Notificări în browser cu ntfy (fără cont, fără aplicație)**
- *Android (Chrome):* deschide **ntfy.sh/app** → **Subscribe to topic** → scrie numele canalului tău
  (ex. `oferte-tulcea-q4nq7uv0`, ceva greu de ghicit) → **Subscribe** → **Permite** notificările.
  În ⚙️ Settings activează notificările în fundal (Web Push), dacă ți se cere.
- *iPhone (iOS 16.4+, Safari):* deschide **ntfy.sh/app** → butonul **Partajează** →
  **Adaugă pe ecranul principal** → deschide ntfy din iconița nouă → abonează-te la canal →
  **Permite** notificările. (Pe iPhone notificările web merg doar așa, din iconiță.)
- Numele canalului îl pui la pasul 4 ca secret `NTFY_TOPIC`.

**B. Email (Gmail)**
1. Ai nevoie de verificarea în doi pași activă: **myaccount.google.com/security** → „Verificare în doi pași”.
2. Intră pe **myaccount.google.com/apppasswords** → nume: `agent oferte` → **Creează** →
   copiază codul de 16 litere (asta e `EMAIL_PAROLA`; nu e parola ta obișnuită).
3. Emailurile vin de la adresa ta Gmail către tine. Pentru notificare cu sunet,
   activează notificările aplicației de email deja instalate pe telefon.

### Pasul 4: secretele (setările private)
În repository: **Settings → Secrets and variables → Actions → New repository secret**.
Adaugă doar ce folosești:

| Name | Value |
|---|---|
| `NTFY_TOPIC` | numele canalului ntfy |
| `EMAIL_UTILIZATOR` | adresa ta Gmail |
| `EMAIL_PAROLA` | codul de 16 litere de la Google |
| `EMAIL_CATRE` | opțional: altă adresă pe care să primești emailurile |

### Pasul 5: pagina cu toate ofertele
**Settings → Pages** → Source: **Deploy from a branch** → Branch: **main**, folder **/ (root)** → **Save**.
După câteva minute, pagina e la `https://<utilizatorul-tău>.github.io/agent-oferte/`.
Adaug-o la favorite în browser: acolo vezi oricând cea mai bună ofertă de moment.

### Pasul 6: pornește agentul
**Actions** → dacă ți se cere, **I understand my workflows, go ahead and enable them** →
„Agent oferte calatorii” → **Run workflow** → **Run workflow**.
În 1–2 minute primești „✅ Agentul de oferte a pornit” cu topul ofertelor de acum.
De acum rulează singur la fiecare 15 minute (GitHub poate întârzia uneori câteva minute).

---

## Alte variante

- **Telegram** (dacă îl ai deja): scrie-i lui **@BotFather** → `/newbot` → primești un token
  (`TELEGRAM_BOT_TOKEN`). Trimite un mesaj botului, apoi deschide
  `https://api.telegram.org/bot<TOKEN>/getUpdates` și copiază `"chat":{"id": ...}` (`TELEGRAM_CHAT_ID`).
- **Pe calculator** (dacă ai voie să instalezi Python 3.9+):
  - Windows: editează `porneste_windows.bat`, apoi dublu-click.
  - Linux / macOS: `NTFY_TOPIC=canalul-tau python3 agent_oferte.py --bucla 15`

## Comenzi utile (când rulezi pe calculator)

```bash
python agent_oferte.py              # o verificare
python agent_oferte.py --bucla 15   # verifică la fiecare 15 minute
python agent_oferte.py --simulare   # arată ce ar trimite, fără să trimită nimic
python agent_oferte.py --top 10     # cele mai bune 10 oferte din ultima săptămână
python agent_oferte.py --test       # notificare de test
python agent_oferte.py --reset      # șterge istoricul
```

## Setări (`config.json`, se poate edita direct pe GitHub cu ✏️)

| Cheie | Ce face |
|---|---|
| `plecari_acceptate` | `BUH` București, `CND` Constanța, `TCE` Tulcea; opțional `KIV` Chișinău, `VAR` Varna, `IAS` Iași |
| `pret_maxim_eur` | ex. `300`: ignoră ofertele mai scumpe |
| `scor_minim_notificare` | sub acest scor nu primești notificare (implicit 35) |
| `scor_super_oferta` | de la acest scor notificarea e „SUPER” (implicit 80) |
| `destinatii_favorite` | ex. `["grecia", "bali"]`: +10 la scor |
| `destinatii_excluse` | ex. `["londra"]`: nu mai apar |
| `ore_liniste` | `[23, 7]`: noaptea doar super-oferte; `[]` dezactivează |
| `accepta_plecare_neprecizata` | ofertele fără oraș de plecare de pe site-urile românești sunt considerate „București (probabil)” |

## Limitări
- Zborurile din **Constanța** sunt puține (mai ales Wizz Air spre Londra și câteva sezoniere),
  așa că majoritatea ofertelor vor fi din București.
- Prețurile de pe bloguri se schimbă repede. Verifică pe site-ul companiei înainte să plătești.
- secretflying.com blochează roboții, de aceea nu e inclus.
- Nu pune parole sau tokenuri în `config.json`: repository-ul e public. Folosește doar Secrets.
