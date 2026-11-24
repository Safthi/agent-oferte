#!/usr/bin/env python3
"""
Agent oferte de călătorie
=========================
Verifică site-urile românești de oferte (Călător fără limite, TipTrip, Aventurescu,
Travelator, CityBreak.club, Cestee, Fly4free), păstrează doar ofertele cu plecare din
București (OTP/BBU), Constanța (CND) sau Tulcea (TCE), le dă un scor 0-100 și trimite
notificări pe telefon (ntfy și/sau Telegram).

Rulare:
    python agent_oferte.py                 # o verificare
    python agent_oferte.py --bucla 15      # verifică la fiecare 15 minute, la nesfârșit
    python agent_oferte.py --simulare      # arată ce ar trimite, fără notificări / salvare
    python agent_oferte.py --top 10        # cele mai bune 10 oferte din ultimele zile
    python agent_oferte.py --test          # trimite o notificare de test

Nu are nevoie de pachete externe (doar Python 3.9+).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FISIER_CONFIG = ROOT / "config.json"
FISIER_STARE = ROOT / "stare.json"
FISIER_RAPORT = ROOT / "index.html"  # pagina cu toate ofertele (GitHub Pages o afișează direct)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# --------------------------------------------------------------------------------------
# Configurație implicită (se poate suprascrie din config.json)
# --------------------------------------------------------------------------------------
CONFIG_IMPLICIT = {
    "surse": [
        {"id": "calatorfaralimite", "nume": "Călător fără limite", "tip": "rss",
         "url": "https://calatorfaralimite.ro/feed/", "romanesc": True},
        {"id": "tiptrip", "nume": "TipTrip", "tip": "rss",
         "url": "https://tiptrip.ro/feed/", "romanesc": True},
        {"id": "aventurescu", "nume": "Aventurescu", "tip": "rss",
         "url": "https://aventurescu.ro/feed/", "romanesc": True},
        {"id": "travelator", "nume": "Travelator", "tip": "rss",
         "url": "https://travelator.ro/feed/", "romanesc": True},
        {"id": "citybreak", "nume": "CityBreak.club", "tip": "rss",
         "url": "https://www.citybreak.club/feed/", "romanesc": True},
        {"id": "cestee", "nume": "Cestee", "tip": "cestee",
         "url": "https://www.cestee.ro/oferte", "romanesc": True},
        {"id": "fly4free", "nume": "Fly4free", "tip": "rss",
         "url": "https://www.fly4free.com/feed/", "romanesc": False},
        # Radarul Aventurescu: sute de zboruri ieftine, cu date exacte, pe oraș de plecare
        {"id": "radar_bucuresti", "nume": "Aventurescu Radar", "tip": "aventurescu_radar",
         "url": "https://aventurescu.ro/zboruri-ieftine/din-bucuresti/", "romanesc": True},
        {"id": "radar_constanta", "nume": "Aventurescu Radar", "tip": "aventurescu_radar",
         "url": "https://aventurescu.ro/zboruri-ieftine/din-constanta/", "romanesc": True},
    ],
    # Coduri acceptate: BUH (București OTP/BBU), CND (Constanța), TCE (Tulcea).
    # Opționale: KIV (Chișinău), VAR (Varna), IAS (Iași) - adaugă-le dacă vrei.
    "plecari_acceptate": ["BUH", "CND", "TCE"],
    # Pe site-urile românești, o ofertă fără oraș de plecare e aproape mereu din București.
    "accepta_plecare_neprecizata": True,
    "pret_maxim_eur": None,            # ex. 300 -> ignoră ofertele mai scumpe
    "scor_minim_notificare": 35,       # 0-100
    "scor_super_oferta": 80,
    # Zborurile din Radar sunt multe: te anunță doar cele cu scor mare, și doar la o destinație
    # nouă sau la o scădere de preț de cel puțin 5% față de ultimele 30 de zile.
    "scor_minim_radar": 80,
    # Notificări doar pentru anumite categorii, ex. ["sub100", "departe"]. Gol = toate.
    # Chei: super, sub50, sub100, europa, departe, asia, africa, america_n, america_s,
    #       plaja, citybreak, pachet, allinc, sarbatori, direct
    "categorii_notificare": [],
    "max_notificari_pe_rulare": 8,     # restul vin într-un mesaj-rezumat
    "zile_vechime_maxima": 10,         # articole mai vechi sunt ignorate
    "curs_ron_eur": 5.09,
    "ore_liniste": [23, 7],            # între 23:00 și 07:00 doar super-ofertele
    "destinatii_excluse": [],          # ex. ["londra", "dubai"]
    "destinatii_favorite": [],         # +10 la scor, ex. ["grecia", "bali"]
    "bonus_constanta": 10,             # Constanța e mai aproape de Tulcea
    "bonus_tulcea": 20,
    # Prețuri de referință (EUR, dus-întors / persoană) față de care se calculează scorul
    "referinta_zbor": {"europa": 100, "mediu": 260, "lung": 780},
    "referinta_noapte_cazare": {"europa": 35, "mediu": 45, "lung": 40},
    "referinta_noapte_all_inclusive": 60,
    "notificari": {
        "ntfy_server": "https://ntfy.sh",
        "ntfy_topic": "",              # sau variabila de mediu NTFY_TOPIC
        "telegram_bot_token": "",      # sau TELEGRAM_BOT_TOKEN
        "telegram_chat_id": "",        # sau TELEGRAM_CHAT_ID
        "email_utilizator": "",        # sau EMAIL_UTILIZATOR (adresa Gmail care trimite)
        "email_parola": "",            # sau EMAIL_PAROLA (parola de aplicație Google)
        "email_catre": "",             # sau EMAIL_CATRE (implicit: aceeași adresă)
        "email_smtp_host": "smtp.gmail.com",
        "email_smtp_port": 465,
    },
    "link_raport": "",                 # sau RAPORT_URL (pagina GitHub Pages cu toate ofertele)
    "link_brosura": "",                # pagina „Planificator de vacanță” (broșuri scrise de Claude)
}

# --------------------------------------------------------------------------------------
# Aeroporturi / orașe
# --------------------------------------------------------------------------------------
PLECARI = {
    "BUH": ("București", r"Bucure[sșş]ti|BUCURE[SȘŞ]TI|Bucharest|BUCHAREST|Otopeni|OTOPENI|"
                         r"B[aă]neasa|Henri Coand[aă]|\bOTP\b|\bBBU\b"),
    "CND": ("Constanța", r"Constan[tțţ]a\b|CONSTAN[TȚŢ]A\b|Kog[aă]lniceanu|KOG[AĂ]LNICEANU|\bCND\b"),
    "TCE": ("Tulcea", r"\bTulcea\b|\bTULCEA\b|\bTCE\b"),
    "KIV": ("Chișinău", r"Chi[sșş]in[aă]u|CHI[SȘŞ]IN[AĂ]U|Chisinau|\bKIV\b"),
    "VAR": ("Varna", r"\bVarna\b|\bVARNA\b"),
    "IAS": ("Iași", r"\bIa[sșş]i\b|\bIA[SȘŞ]I\b"),
}

# Orașe care, dacă apar ca loc de plecare, înseamnă că oferta NU e din București/Constanța
ALTE_PLECARI = [
    "cluj-napoca", "cluj", "iasi", "timisoara", "sibiu", "suceava", "craiova", "bacau",
    "oradea", "targu mures", "brasov", "satu mare", "baia mare", "chisinau", "varna",
    "sofia", "budapesta", "budapest", "viena", "vienna", "milano", "milan", "bergamo",
    "roma", "rome", "madrid", "barcelona", "paris", "londra", "london", "atena", "athens",
    "frankfurt", "berlin", "munchen", "munich", "amsterdam", "bruxelles", "brussels",
    "varsovia", "warsaw", "cracovia", "krakow", "praga", "prague", "istanbul", "dublin",
    "lisabona", "lisbon", "zurich", "copenhaga", "copenhagen", "stockholm", "oslo",
    "helsinki", "dusseldorf", "hamburg", "koln", "cologne", "katowice", "gdansk",
    "wroclaw", "bologna", "venetia", "venice", "napoli", "naples", "eindhoven",
    "charleroi", "larnaca", "dubai", "doha", "abu dhabi", "belgrad", "belgrade",
]

# Țări care, în titlu după „din”, indică o plecare din străinătate („Zboruri din Irlanda către ...”)
TARI_PLECARE = [
    "irlanda", "ireland", "germania", "germany", "italia", "italy", "spania", "spain", "franta",
    "france", "anglia", "marea britanie", "uk", "olanda", "belgia", "polonia", "poland",
    "ungaria", "hungary", "austria", "elvetia", "portugalia", "grecia", "bulgaria", "cehia",
    "danemarca", "suedia", "norvegia", "finlanda", "turcia", "serbia", "moldova",
]

DESTINATII_LUNGI = """
thailanda, thailand, bangkok, phuket, krabi, koh samui, chiang mai, bali, indonezia, indonesia,
jakarta, denpasar, lombok, filipine, philippines, manila, boracay, palawan, cebu, japonia, japan,
tokyo, osaka, kyoto, coreea, korea, seoul, seul, china, beijing, shanghai, hong kong, macau,
taiwan, taipei, vietnam, hanoi, ho chi minh, saigon, da nang, malaezia, malaysia, kuala lumpur,
singapore, india, new delhi, delhi, mumbai, goa, sri lanka, colombo, maldive, maldives, nepal,
kathmandu, cambodgia, cambodia, laos, myanmar, australia, sydney, melbourne, noua zeelanda,
new zealand, sua, statele unite, new york, los angeles, miami, chicago, san francisco,
las vegas, canada, toronto, montreal, vancouver, mexic, mexico, cancun, cuba, havana,
dominicana, punta cana, caraibe, caribbean, jamaica, bahamas, barbados, aruba, brazilia,
brazil, rio de janeiro, sao paulo, recife, argentina, buenos aires, peru, chile, columbia,
colombia, bolivia, ecuador, costa rica, panama, kenya, nairobi, tanzania, zanzibar, mauritius,
seychelles, madagascar, africa de sud, south africa, cape town, johannesburg, reunion,
polinezia, tahiti, hawaii, namibia, etiopia, ghana, accra, nigeria, lagos, senegal, dakar,
okinawa, sapporo, busan, guangzhou, chengdu, penang, langkawi, phnom penh, siem reap, bangladesh,
pakistan, mongolia, fiji, auckland, perth, brisbane, honolulu, cartagena, medellin, bogota, quito,
cusco, havana, varadero, santo domingo, montego bay, nassau, curacao, puerto rico, guatemala,
venezuela, uruguay, montevideo, mombasa, dar es salaam, kilimanjaro, windhoek, kigali, uganda,
rwanda, gambia, botswana, zambia, zimbabwe, mozambic, newark, boston, washington, orlando,
seattle, houston, dallas, atlanta, calgary, tulum, puerto vallarta, mexico city
"""
DESTINATII_MEDII = """
egipt, egypt, hurghada, sharm, marsa alam, cairo, dubai, emirate, emiratele, abu dhabi, oman,
muscat, qatar, doha, bahrain, iordania, jordan, amman, aqaba, petra, israel, tel aviv,
arabia saudita, riyadh, jeddah, maroc, morocco, marrakech, agadir, canare, canary, tenerife,
gran canaria, lanzarote, fuerteventura, madeira, islanda, iceland, reykjavik, capul verde,
cape verde, uzbekistan, tashkent, samarkand, kazahstan, almaty, liban, beirut, kuweit, kuwait, tunisia, tunis, djerba, monastir,
enfidha, algeria, alger, sharm el-sheikh, luxor, el gouna, casablanca, fes, salalah, sharjah,
ras al khaimah, arabia, saudi, erbil, irak, iran
"""

# Regiuni (ca pe Aventurescu): Europa e implicită, restul se recunosc după destinație / țară
REGIUNI_TEXT = {
    "asia": """
thailanda, thailand, bangkok, phuket, krabi, koh samui, chiang mai, pattaya, bali, denpasar,
indonezia, indonesia, jakarta, lombok, filipine, philippines, manila, cebu, boracay, palawan,
japonia, japan, tokyo, osaka, kyoto, okinawa, sapporo, coreea, korea, seul, seoul, busan, china,
beijing, shanghai, guangzhou, chengdu, hong kong, macau, taiwan, taipei, vietnam, hanoi,
ho chi minh, saigon, da nang, malaezia, malaysia, kuala lumpur, penang, langkawi, singapore,
india, delhi, new delhi, mumbai, goa, sri lanka, colombo, maldive, maldives, nepal, kathmandu,
cambodgia, cambodia, phnom penh, siem reap, laos, myanmar, bangladesh, pakistan, uzbekistan,
tashkent, samarkand, kazahstan, kazakhstan, almaty, astana, kirghizstan, kargazstan, kirgizstan,
kyrgyzstan, bishkek, biskek, turkmenistan, asgabat, ashgabat, tadjikistan, dusanbe, mongolia,
dubai, emirate, emiratele arabe unite, abu dhabi, sharjah, ras al khaimah, oman, muscat,
salalah, qatar, doha, bahrain, kuweit, kuwait, iordania, jordan, amman, aqaba, petra, israel,
tel aviv, ierusalim, arabia saudita, saudi, riyadh, jeddah, liban, beirut, iran, teheran, irak,
baghdad, erbil, australia, sydney, melbourne, perth, brisbane, noua zeelanda, new zealand,
auckland, fiji, polinezia, tahiti
""",
    "africa": """
egipt, egypt, hurghada, sharm, marsa alam, cairo, luxor, el gouna, maroc, morocco, marrakech,
agadir, casablanca, fes, rabat, tanger, tunisia, tunis, djerba, monastir, enfidha, algeria,
alger, kenya, nairobi, mombasa, tanzania, zanzibar, dar es salaam, kilimanjaro, mauritius,
seychelles, madagascar, africa de sud, south africa, cape town, johannesburg, namibia, windhoek,
etiopia, ethiopia, addis abeba, capul verde, cape verde, senegal, dakar, ghana, accra, nigeria,
lagos, reunion, uganda, rwanda, kigali, gambia, banjul, botswana, zambia, zimbabwe, mozambic
""",
    "america_n": """
sua, statele unite, new york, newark, boston, washington, miami, orlando, los angeles,
san francisco, las vegas, chicago, seattle, houston, dallas, atlanta, hawaii, honolulu, canada,
toronto, montreal, vancouver, calgary, mexic, mexico, cancun, mexico city, ciudad de mexico,
puerto vallarta, tulum
""",
    "america_s": """
brazilia, brazil, rio de janeiro, sao paulo, recife, salvador, argentina, buenos aires, peru,
lima, cusco, chile, santiago de chile, columbia, colombia, bogota, cartagena, medellin, ecuador,
quito, bolivia, venezuela, uruguay, montevideo, paraguay, costa rica, panama, guatemala, cuba,
havana, varadero, republica dominicana, dominicana, punta cana, santo domingo, jamaica,
montego bay, bahamas, nassau, barbados, aruba, curacao, guadelupa, guadeloupe, martinica,
martinique, puerto rico, trinidad, caraibe, caribbean
""",
}
PLAJA_TEXT = """
egipt, hurghada, sharm, marsa alam, el gouna, dubai, abu dhabi, ras al khaimah, canare, tenerife,
gran canaria, lanzarote, fuerteventura, la palma, madeira, funchal, cipru, larnaca, paphos,
ayia napa, limassol, malta, creta, heraklion, chania, rodos, rhodes, corfu, zakynthos, kefalonia,
santorini, mykonos, skiathos, thassos, kos, lefkada, preveza, halkidiki, kalamata, mallorca,
palma de mallorca, ibiza, menorca, malaga, alicante, almeria, faro, algarve, sicilia, catania,
palermo, trapani, comiso, sardinia, cagliari, olbia, alghero, split, dubrovnik, zadar, antalya,
bodrum, dalaman, tunisia, djerba, monastir, enfidha, agadir, thailanda, phuket, krabi, koh samui,
pattaya, bali, lombok, maldive, mauritius, seychelles, zanzibar, cancun, punta cana, dominicana,
cuba, varadero, jamaica, bahamas, barbados, aruba, curacao, sri lanka, goa, langkawi, boracay,
palawan, capul verde, nisa, tivat, budva, burgas, all inclusive, plaja, la caldura, okinawa,
hawaii, miami, rio de janeiro, mombasa
"""

COMPANII = ["Wizz Air", "Ryanair", "TAROM", "Etihad", "Turkish Airlines", "Pegasus",
            "Lufthansa", "Air France", "KLM", "Qatar Airways", "Emirates", "flydubai",
            "AnimaWings", "HiSky", "Aegean", "LOT", "Air China", "Norwegian", "Austrian",
            "British Airways", "Air Serbia", "Oman Air", "Ethiopian", "China Southern",
            "Swiss", "ITA Airways", "easyJet", "Air Arabia", "Saudia", "Air Astana"]

LUNI = ("ianuarie februarie martie aprilie mai iunie iulie august septembrie octombrie "
        "noiembrie decembrie").split()
LUNI_SCURT = r"(?:Ian|Feb|Mar|Apr|Mai|Iun|Iul|Aug|Sep|Oct|Noi|Nov|Dec)[a-zăâîșț]*\.?"

CUVINTE_CAPS_IGNORATE = {
    "ALL", "INCLUSIVE", "VARA", "VARĂ", "IARNA", "IARNĂ", "SUPEROFERTĂ", "SUPEROFERTA",
    "VÂRF", "VARF", "DE", "SEZON", "URGENT", "WOW", "MEGA", "PROMOTIE", "PROMOȚIE",
    "ETIHAD", "DIRECTE", "TAROM", "EURO", "BONUS", "POMANA", "BLACK", "FRIDAY", "NU",
    "GREAT", "DEAL", "HIGH", "SEASON", "SUMMER", "LAST", "MINUTE", "CITY", "BREAK", "AI",
    "REVELION", "PASTE", "PAȘTE", "CRACIUN", "CRĂCIUN", "LISTA", "LISTĂ", "TOP", "NOU",
    "RAPID", "ATENTIE", "ATENȚIE", "EUR", "RON", "LEI", "SI", "ȘI", "IN", "ÎN", "LA",
}


# --------------------------------------------------------------------------------------
# Utilitare
# --------------------------------------------------------------------------------------
def norm(text: str) -> str:
    """Fără diacritice, litere mici, spații simple."""
    t = (text or "").translate({0x2013: "-", 0x2014: "-", 0x2212: "-", 0x2192: "->"})
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


def text_simplu(fragment_html: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment_html or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def acum() -> datetime:
    return datetime.now(timezone.utc)


def ora_locala() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Bucharest"))
    except Exception:  # Windows fără tzdata: aproximare UTC+2
        return datetime.now(timezone(timedelta(hours=2)))


def log(msg: str) -> None:
    print(f"[{ora_locala():%Y-%m-%d %H:%M}] {msg}", flush=True)


def descarca(url: str, incercari: int = 3, timeout: int = 25) -> bytes:
    ultima = None
    for i in range(incercari):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.7",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            ultima = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"nu am putut descărca {url}: {ultima}")


def id_oferta(url: str) -> str:
    p = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith("utm")]
    curat = urllib.parse.urlunsplit((p.scheme, p.netloc.lower().removeprefix("www."),
                                     p.path.rstrip("/"), urllib.parse.urlencode(q), ""))
    return hashlib.sha1(curat.encode()).hexdigest()[:16]


def incarca_config() -> dict:
    cfg = json.loads(json.dumps(CONFIG_IMPLICIT))
    if FISIER_CONFIG.exists():
        try:
            utilizator = json.loads(FISIER_CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"config.json are o eroare de sintaxă: {e}")
        for k, v in utilizator.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    n = cfg["notificari"]
    n["ntfy_topic"] = os.environ.get("NTFY_TOPIC") or n.get("ntfy_topic", "")
    n["ntfy_server"] = os.environ.get("NTFY_SERVER") or n.get("ntfy_server") or "https://ntfy.sh"
    n["ntfy_token"] = os.environ.get("NTFY_TOKEN") or n.get("ntfy_token", "")
    n["telegram_bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN") or n.get("telegram_bot_token", "")
    n["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID") or n.get("telegram_chat_id", "")
    n["email_utilizator"] = os.environ.get("EMAIL_UTILIZATOR") or n.get("email_utilizator", "")
    n["email_parola"] = os.environ.get("EMAIL_PAROLA") or n.get("email_parola", "")
    n["email_catre"] = (os.environ.get("EMAIL_CATRE") or n.get("email_catre")
                        or n["email_utilizator"])
    n["email_smtp_host"] = os.environ.get("EMAIL_SMTP_HOST") or n.get("email_smtp_host") or "smtp.gmail.com"
    n["email_smtp_port"] = int(os.environ.get("EMAIL_SMTP_PORT") or n.get("email_smtp_port") or 465)
    cfg["link_raport"] = os.environ.get("RAPORT_URL") or cfg.get("link_raport", "")
    return cfg


def incarca_stare() -> dict:
    if FISIER_STARE.exists():
        try:
            return json.loads(FISIER_STARE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("stare.json corupt - pornesc de la zero")
    return {"versiune": 1, "oferte": {}, "minime": {}}


def salveaza_stare(stare: dict) -> None:
    limita = (acum() - timedelta(days=45)).isoformat()
    stare["oferte"] = {k: v for k, v in stare["oferte"].items() if v.get("vazut", "") >= limita}
    stare["minime"] = {k: v for k, v in stare.get("minime", {}).items()
                       if isinstance(v, dict) and v.get("ts", "") >= limita}
    tmp = FISIER_STARE.with_suffix(".tmp")
    tmp.write_text(json.dumps(stare, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FISIER_STARE)


# --------------------------------------------------------------------------------------
# Citirea surselor
# --------------------------------------------------------------------------------------
NS = {"content": "http://purl.org/rss/1.0/modules/content/",
      "atom": "http://www.w3.org/2005/Atom"}


def data_din_text(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def citeste_rss(sursa: dict) -> list[dict]:
    brut = descarca(sursa["url"])
    articole = []
    try:
        radacina = ET.fromstring(brut)
        noduri = radacina.findall(".//item") or radacina.findall(".//atom:entry", NS)
        for it in noduri:
            titlu = it.findtext("title") or it.findtext("atom:title", namespaces=NS) or ""
            link = it.findtext("link") or ""
            if not link.strip():
                el = it.find("atom:link", NS)
                link = el.get("href", "") if el is not None else ""
            continut = (it.findtext("content:encoded", namespaces=NS)
                        or it.findtext("description")
                        or it.findtext("atom:content", namespaces=NS)
                        or it.findtext("atom:summary", namespaces=NS) or "")
            data = (it.findtext("pubDate") or it.findtext("atom:published", namespaces=NS)
                    or it.findtext("atom:updated", namespaces=NS))
            cat = [c.text or "" for c in it.findall("category")]
            articole.append({"titlu": html.unescape(titlu).strip(), "url": link.strip(),
                             "text": text_simplu(continut), "data": data_din_text(data),
                             "categorii": cat})
    except ET.ParseError:
        # XML invalid - extragere grosieră cu regex
        s = brut.decode("utf-8", "replace")
        for bloc in re.findall(r"(?s)<item\b.*?</item>", s):
            def tag(nume):
                m = re.search(rf"(?s)<{nume}[^>]*>(.*?)</{nume}>", bloc)
                v = m.group(1) if m else ""
                return re.sub(r"(?s)^<!\[CDATA\[(.*)\]\]>$", r"\1", v.strip())
            articole.append({"titlu": html.unescape(tag("title")).strip(), "url": tag("link"),
                             "text": text_simplu(tag("content:encoded") or tag("description")),
                             "data": data_din_text(tag("pubDate")), "categorii": []})
    return articole


def citeste_cestee(sursa: dict) -> list[dict]:
    s = descarca(sursa["url"]).decode("utf-8", "replace")
    baza = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(sursa["url"]))
    articole = []
    for bloc in re.findall(r'(?s)<article class="deal-card.*?</article>', s):
        href = re.search(r'href="([^"]+)"', bloc)
        titlu = re.search(r'(?s)<h3[^>]*>(.*?)</h3>', bloc)
        if not (href and titlu):
            continue
        pret = re.search(r'<data value="([^"]+)"', bloc)
        tara = re.search(r'(?s)deal-card__meta-txt">(.*?)</span>', bloc)
        data = re.search(r'<time datetime="([^"]+)"', bloc)
        reducere = re.search(r'deal-card__badge[^>]*>\s*-?(\d+)\s*%', bloc)
        t = text_simplu(titlu.group(1))
        p = text_simplu(pret.group(1)) if pret else ""
        articole.append({
            "titlu": f"{t} – {p}" if p else t,
            "url": urllib.parse.urljoin(baza, href.group(1)),
            "text": text_simplu(tara.group(1)) if tara else "",
            "tara": text_simplu(tara.group(1)) if tara else "",
            "data": data_din_text(data.group(1)) if data else None,
            "categorii": [],
            "reducere": int(reducere.group(1)) if reducere else None,
        })
    return articole


IATA_PLECARE = {"OTP": "BUH", "BBU": "BUH", "CND": "CND", "TCE": "TCE",
                "KIV": "KIV", "VAR": "VAR", "IAS": "IAS"}
NUME_AEROPORT = {"OTP": "Otopeni", "BBU": "Băneasa"}
LUNI_SCURTE = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.",
               "nov.", "dec."]


def interval_ro(d1: date, d2: date | None) -> str:
    """2027-01-20, 2027-01-22 -> „20–22 ian. 2027”"""
    L = LUNI_SCURTE
    if not d2:
        return f"{d1.day} {L[d1.month - 1]} {d1.year} (dus)"
    if (d1.year, d1.month) == (d2.year, d2.month):
        return f"{d1.day}–{d2.day} {L[d2.month - 1]} {d2.year}"
    if d1.year == d2.year:
        return f"{d1.day} {L[d1.month - 1]} – {d2.day} {L[d2.month - 1]} {d2.year}"
    return f"{d1.day} {L[d1.month - 1]} {d1.year} – {d2.day} {L[d2.month - 1]} {d2.year}"


def citeste_aventurescu_radar(sursa: dict) -> list[dict]:
    """Pagina „Aventurescu Radar” pentru un oraș: zboruri cu rută, date, preț și companie."""
    s = descarca(sursa["url"]).decode("utf-8", "replace")
    blocuri = re.findall(r'(?s)<li class="aro-lc[^"]*"(.*?)</li>', s)
    # țara pentru cardurile care nu o afișează (le completăm din celelalte carduri)
    tari = {}
    for b in blocuri:
        r = re.search(r"/flight-search/[A-Z]{3}-([A-Z]{3})/", b)
        t = re.search(r'(?s)class="aro-lc-ctry">(.*?)</span>', b)
        if r and t:
            tari[r.group(1)] = text_simplu(t.group(1))
    articole, vazute = [], set()
    for b in blocuri:
        href = re.search(r'href="([^"]+)"', b)
        if not href:
            continue
        url = html.unescape(href.group(1))
        rt = re.search(r"/flight-search/([A-Z]{3})-([A-Z]{3})/(\d{4}-\d{2}-\d{2})"
                       r"(?:/(\d{4}-\d{2}-\d{2}))?", url)
        if not rt or rt.groups() in vazute:
            continue
        vazute.add(rt.groups())
        orig, dest_iata, d1s, d2s = rt.groups()
        atr = dict(re.findall(r'data-(k|p)="([^"]*)"', b[:600]))
        oras = re.search(r'(?s)class="aro-lc-d">(.*?)</span>', b)
        oras = text_simplu(oras.group(1)) if oras else dest_iata
        tara = tari.get(dest_iata, "")
        meta = ""
        i = b.find('class="aro-lc-m')
        if i >= 0:
            j = b.find('class="aro-lc-dt"', i)
            j = b.rfind("<span", i, j) if j > 0 else i + 400
            meta = b[i:j]
        companie = text_simplu(re.sub(r'(?s)<span class="aro-chip.*?</span>', " ", meta.split(">", 1)[-1]))
        companie = re.sub(r"^din [^·]*·\s*", "", companie).strip(" ·<\"")
        try:
            pret = float(atr.get("p") or re.search(r'aro-price">(\d+)', b).group(1))
            d1 = date.fromisoformat(d1s)
            d2 = date.fromisoformat(d2s) if d2s else None
        except (AttributeError, ValueError):
            continue
        gasit = re.search(r'<time datetime="([^"]+)"', b)
        destinatie = f"{oras}, {tara}" if tara and norm(tara) != norm(oras) else oras
        articole.append({
            "titlu": f"{destinatie} – {int(pret)}€ {'dus-întors' if d2 else 'dus'}",
            "url": url, "text": "", "categorii": [],
            "data": data_din_text(gasit.group(1)) if gasit else None,
            "radar": {"orig": orig, "dest": dest_iata, "oras": oras, "tara": tara,
                      "destinatie": destinatie, "pret": pret, "d1": d1, "d2": d2,
                      "companie": companie[:40], "direct": "aro-chip-dir" in meta,
                      "k": atr.get("k", "")},
        })
    return articole


CITITORI = {"rss": citeste_rss, "cestee": citeste_cestee,
            "aventurescu_radar": citeste_aventurescu_radar}


# --------------------------------------------------------------------------------------
# Analiza unei oferte
# --------------------------------------------------------------------------------------
RE_PRET = re.compile(
    r"(?:€\s*(\d{1,3}(?:[ .,]\d{3})+(?!\d)|\d+))"                             # €380
    r"|(?:(?<![\d.,])(\d{1,3}(?:[ .,]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*"
    r"(€|euro|eur\b|lei\b|ron\b))",
    re.IGNORECASE)


def extrage_pret(text: str, curs: float) -> tuple[float | None, str]:
    for m in RE_PRET.finditer(text):
        valoare = m.group(1) or m.group(2)
        moneda = (m.group(3) or "€").lower()
        try:
            v = float(re.sub(r"[ .,]", "", valoare))
        except ValueError:
            continue
        if v <= 0:
            continue
        if moneda in ("lei", "ron"):
            return round(v / curs), f"{int(v)} lei"
        return v, f"{int(v)}€"
    return None, ""


def gaseste_plecari(titlu: str, text: str, coduri: list[str]) -> set[str]:
    gasite = set()
    for cod in coduri:
        if cod in PLECARI and re.search(PLECARI[cod][1], f"{titlu} \n {text}"):
            gasite.add(cod)
    return gasite


_ALTE = "|".join(sorted((re.escape(c) for c in ALTE_PLECARI), key=len, reverse=True))
_ALTE_SI_TARI = "|".join(sorted((re.escape(c) for c in ALTE_PLECARI + TARI_PLECARE),
                                key=len, reverse=True))
RE_ALTA_DIN_TITLU = re.compile(rf"\b(?:din|from|de la)\s+(?:orasul\s+)?({_ALTE_SI_TARI})\b")
RE_ALTA_RUTA_TITLU = re.compile(rf"(?:^|\s)(?<!catre )(?<!spre )(?<!in )(?<!la )(?<!to )"
                                rf"({_ALTE})\s*[-–—]\s*(?=[a-z])")
RE_ALTA_DIN_TEXT = re.compile(
    rf"\b(?:zbor\w*|plecar\w*|flights?|departures?)\s+(?:\w+\s+){{0,2}}(?:din|de la|from)\s+({_ALTE})\b")


def gaseste_alte_plecari(titlu_brut: str, text: str) -> set[str]:
    titlu = norm(titlu_brut)
    alte = set(RE_ALTA_DIN_TITLU.findall(titlu))
    # "Zboruri ieftine Milano – Zanzibar": orașul de dinaintea liniuței e plecarea,
    # dar doar dacă după liniuță urmează un nume (nu "– de la 41 euro")
    for m in RE_ALTA_RUTA_TITLU.finditer(titlu):
        dupa = titlu[m.end():m.end() + 6]
        if not re.match(r"(de la|doar|\d)", dupa):
            alte.add(m.group(1))
    alte |= set(RE_ALTA_DIN_TEXT.findall(norm(text[:3000])))
    return alte


RE_HOME_ORICARE = re.compile("|".join(v[1] for v in PLECARI.values()))
_MAJ = r"[A-ZĂÂÎȘȚŞŢ][\wĂÂÎȘȚŞŢăâîșțşţ'’.\-]*"


def destinatie_din_text(text: str) -> str:
    """Fallback: „Am găsit zboruri ieftine spre Milano...” în primele rânduri din articol."""
    m = re.search(rf"\b(?:spre|către|catre|to)\s+({_MAJ}(?:\s+{_MAJ}){{0,2}})", text[:300])
    if m and not RE_HOME_ORICARE.search(m.group(1)):
        if not any(norm(c) in norm(m.group(1)) for c in COMPANII):
            return frumos(m.group(1).strip(" .-’'"))
    return ""


def extrage_destinatie(titlu: str) -> str:
    home = RE_HOME_ORICARE
    # 0) „Malta din București ...”, „Kuala Lumpur din București ...”
    m = re.match(rf"\s*({_MAJ}(?:\s+{_MAJ})?)\s+din\s+(?:{PLECARI['BUH'][1]}|{PLECARI['CND'][1]})", titlu)
    if m and not home.search(m.group(1)):
        return frumos(m.group(1))
    # 1) după o prepoziție, cuvinte cu majusculă: "în PAPHOS", "spre Alghero", "to Bali"
    for m in re.finditer(r"(?:^|\s)(?:în|in|spre|către|catre|la|to|City Break)\s+"
                         r"([A-ZĂÂÎȘȚŞŢ][\wĂÂÎȘȚŞŢăâîșțşţ'’.\-]*"
                         r"(?:\s+(?:de\s+)?[A-ZĂÂÎȘȚŞŢ][\wĂÂÎȘȚŞŢăâîșțşţ'’.\-]*){0,3}"
                         r"(?:,\s*[A-ZĂÂÎȘȚŞŢ]{3,}(?:\s+[A-ZĂÂÎȘȚŞŢ]{2,})*)?)", titlu):
        cand = m.group(1).strip(" .-’'")
        if (home.search(cand) or cand.upper() in CUVINTE_CAPS_IGNORATE
                or any(norm(c) in norm(cand) for c in COMPANII)):
            continue
        return frumos(re.sub(r"\s+de$", "", cand))
    # 2) primul grup de cuvinte scrise numai cu majuscule
    for m in re.finditer(r"\b([A-ZĂÂÎȘȚŞŢ]{3,}(?:[ ,]+[A-ZĂÂÎȘȚŞŢ]{2,})*)\b", titlu):
        cuvinte = [c for c in re.split(r"[ ,]+", m.group(1)) if c not in CUVINTE_CAPS_IGNORATE]
        if cuvinte and not home.search(" ".join(cuvinte)):
            return frumos(" ".join(cuvinte))
    return ""


def frumos(nume: str) -> str:
    """SEOUL, COREEA DE SUD -> Seoul, Coreea de Sud"""
    if nume.upper() != nume:
        return nume
    mici = {"de", "si", "și", "la", "din"}
    return " ".join(c.lower() if c.lower() in mici else c.capitalize() for c in nume.split(" "))


def _regex_lista(lista: str) -> re.Pattern:
    termeni = [t.strip() for t in lista.replace("\n", " ").split(",") if t.strip()]
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in termeni) + r")\b")


RE_LUNGI, RE_MEDII = _regex_lista(DESTINATII_LUNGI), _regex_lista(DESTINATII_MEDII)
RE_REGIUNI = {k: _regex_lista(v) for k, v in REGIUNI_TEXT.items()}
RE_PLAJA = _regex_lista(PLAJA_TEXT)


def regiune(text_norm: str) -> str:
    """europa / asia (și Orientul Mijlociu) / africa / america_n / america_s"""
    scoruri = {k: len(rx.findall(text_norm)) for k, rx in RE_REGIUNI.items()}
    cel_mai_bun = max(scoruri, key=lambda k: scoruri[k])
    return cel_mai_bun if scoruri[cel_mai_bun] else "europa"


def clasa_distanta(text_norm: str, reg: str | None = None) -> str:
    """Pentru prețul de referință: europa (zbor scurt) / mediu (4-6 ore) / lung."""
    if RE_LUNGI.search(text_norm):
        return "lung"
    if RE_MEDII.search(text_norm):
        return "mediu"
    if reg and reg != "europa":
        return "lung"
    return "europa"


def extrage_nopti(text: str, doar_nopti: bool = False) -> int | None:
    m = re.search(r"(\d{1,2})\s*(?:nop[tț]i|nights?|-night)", text, re.I)
    if m:
        return int(m.group(1))
    if doar_nopti:
        return None
    m = re.search(r"(\d{1,2})\s*zile", text, re.I)
    if m:
        return max(1, int(m.group(1)) - 1)
    return None


def extrage_perioada(text: str, categorii: list[str]) -> str:
    m = re.search(r"Perioad[aă] de c[aă]l[aă]torie:?\s*([^.;]{3,60})", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(rf"\b\d{{1,2}}(?:\s*{LUNI_SCURT})?\s*[-–]\s*\d{{1,2}}\s+{LUNI_SCURT}\s+20\d\d", text)
    if m:
        return m.group(0)
    m = re.search(rf"\b({'|'.join(LUNI)})(?:\s*[-–]\s*({'|'.join(LUNI)}))?\s+20\d\d", text, re.I)
    if m:
        return m.group(0)
    luni = [c for c in categorii if norm(c) in LUNI]
    if luni:
        return ", ".join(luni[:4])
    return ""


def analizeaza(art: dict, sursa: dict, cfg: dict) -> dict | None:
    """Întoarce oferta analizată sau None dacă nu e o ofertă potrivită."""
    if art.get("radar"):
        return analizeaza_radar(art, sursa, cfg)
    titlu, text = art["titlu"], art["text"]
    if not titlu or not art["url"]:
        return None
    tn, xn = norm(titlu), norm(text)

    pret, pret_afisat = extrage_pret(titlu, cfg["curs_ron_eur"])
    if pret is None:
        return None  # știri, ghiduri, articole fără preț în titlu

    acceptate = cfg["plecari_acceptate"]
    plecari = gaseste_plecari(titlu, text, acceptate)
    alte = gaseste_alte_plecari(titlu, text)
    if plecari:
        plecare_sigura = True
    elif alte:
        return None
    elif sursa.get("romanesc") and cfg["accepta_plecare_neprecizata"] and "BUH" in acceptate:
        plecari, plecare_sigura = {"BUH"}, False
    else:
        return None

    destinatie = (extrage_destinatie(titlu) or destinatie_din_text(text)
                  or art.get("tara") or "Diverse destinații")
    generic = destinatie == "Diverse destinații"
    dn = norm(destinatie)
    if any(norm(e) in tn or norm(e) == dn for e in cfg["destinatii_excluse"]):
        return None
    if cfg["pret_maxim_eur"] and pret > float(cfg["pret_maxim_eur"]):
        return None

    all_inclusive = "all inclusive" in tn or "all inclusive" in xn[:600]
    pachet = bool(re.search(r"cazare|nopti|hotel|\bstay\b|all inclusive|sejur|pachet|"
                            r"package|city break|holiday", tn))
    nopti = None
    if pachet:
        nopti = (extrage_nopti(titlu, doar_nopti=True) or extrage_nopti(text[:800], doar_nopti=True)
                 or extrage_nopti(titlu) or (3 if "city break" in tn else 4))
    text_dest = f"{tn} {dn}" + (f" {xn[:400]}" if generic else "")
    reg = regiune(text_dest)
    distanta = clasa_distanta(text_dest, reg)

    ref = float(cfg["referinta_zbor"][distanta])
    if pachet:
        pe_noapte = (cfg["referinta_noapte_all_inclusive"] if all_inclusive
                     else cfg["referinta_noapte_cazare"][distanta])
        ref += nopti * float(pe_noapte)
    raport = pret / ref
    scor = 100 * (1.2 - raport) / 0.9
    motive = []

    if "CND" in plecari:
        scor += cfg["bonus_constanta"]; motive.append("plecare din Constanța")
    if "TCE" in plecari:
        scor += cfg["bonus_tulcea"]; motive.append("plecare din Tulcea")
    if any(norm(f) in tn for f in cfg["destinatii_favorite"]):
        scor += 10; motive.append("destinație favorită")
    if art.get("reducere") and art["reducere"] >= 50:
        scor += 8; motive.append(f"reducere {art['reducere']}%")
    if re.search(r"eroare de pre|error fare|tarif de eroare", tn):
        scor += 12; motive.append("posibilă eroare de preț")
    if re.search(r"\bdirect", tn):
        scor += 3
    if not plecare_sigura:
        scor -= 5
    if generic and scor > 70:
        scor = 70  # listele „zboruri de la 27€” apar zilnic; nu le tratăm ca super-oferte
        motive.append("listă cu mai multe destinații")

    companii = [c for c in COMPANII if re.search(rf"\b{re.escape(c)}\b", f"{titlu} {text[:2500]}", re.I)]
    data = art["data"] or acum()

    return {
        "id": id_oferta(art["url"]),
        "url": art["url"],
        "titlu": titlu,
        "sursa": sursa["nume"],
        "sursa_id": sursa["id"],
        "publicat": data.astimezone(timezone.utc).isoformat(),
        "pret": pret,
        "pret_afisat": pret_afisat,
        "destinatie": destinatie,
        "tip": "pachet" if pachet else "zbor",
        "nopti": nopti,
        "all_inclusive": all_inclusive,
        "distanta": distanta,
        "regiune": reg,
        "direct": bool(re.search(r"\bdirect", tn)),
        "plecari": sorted(plecari),
        "plecare_sigura": plecare_sigura,
        "companii": companii[:3],
        "perioada": extrage_perioada(text, art.get("categorii", [])),
        "scor": int(max(0, min(100, round(scor)))),
        "motive": motive,
    }


def analizeaza_radar(art: dict, sursa: dict, cfg: dict) -> dict | None:
    r = art["radar"]
    plecare = IATA_PLECARE.get(r["orig"])
    if not plecare or plecare not in cfg["plecari_acceptate"]:
        return None
    if r["d1"] < ora_locala().date():
        return None  # zborul a plecat deja
    destinatie, pret = r["destinatie"], r["pret"]
    dn = norm(destinatie)
    if any(norm(e) in dn for e in cfg["destinatii_excluse"]):
        return None
    if cfg["pret_maxim_eur"] and pret > float(cfg["pret_maxim_eur"]):
        return None
    reg = regiune(dn)
    if reg == "europa" and "departe" in r["k"]:
        reg = "alte"  # Aventurescu o pune la „Departe”, dar nu-i știm regiunea
    distanta = clasa_distanta(dn, reg)
    scor = 100 * (1.2 - pret / float(cfg["referinta_zbor"][distanta])) / 0.9
    motive = []
    if plecare == "CND":
        scor += cfg["bonus_constanta"]; motive.append("plecare din Constanța")
    if plecare == "TCE":
        scor += cfg["bonus_tulcea"]; motive.append("plecare din Tulcea")
    if any(norm(f) in dn for f in cfg["destinatii_favorite"]):
        scor += 10; motive.append("destinație favorită")
    if r["direct"]:
        scor += 3
    data = art["data"] or acum()
    return {
        "id": id_oferta(art["url"]),
        "url": art["url"],
        "titlu": art["titlu"],
        "sursa": sursa["nume"],
        "sursa_id": sursa["id"],
        "publicat": data.astimezone(timezone.utc).isoformat(),
        "pret": pret,
        "pret_afisat": f"{int(pret)}€",
        "destinatie": destinatie,
        "tip": "zbor",
        "nopti": (r["d2"] - r["d1"]).days if r["d2"] else None,
        "all_inclusive": False,
        "distanta": distanta,
        "regiune": reg,
        "direct": r["direct"],
        "plecari": [plecare],
        "plecare_sigura": True,
        "aeroport": r["orig"],
        "companii": [r["companie"]] if r["companie"] else [],
        "perioada": interval_ro(r["d1"], r["d2"]),
        "data_plecare": r["d1"].isoformat(),
        "data_intoarcere": r["d2"].isoformat() if r["d2"] else None,
        "radar": True,
        "scor": int(max(0, min(100, round(scor)))),
        "motive": motive,
    }


# --------------------------------------------------------------------------------------
# Categorii (ca pe Aventurescu)
# --------------------------------------------------------------------------------------
CATEGORII = [
    ("super", "🔥 Super oferte"), ("sub50", "💸 Sub 50€"), ("sub100", "💶 Sub 100€"),
    ("europa", "🇪🇺 Europa"), ("departe", "🌍 Destinații îndepărtate"),
    ("asia", "🕌 Asia și Orientul Mijlociu"), ("africa", "🐪 Africa"),
    ("america_n", "🗽 America de Nord"), ("america_s", "🌴 America de Sud și Caraibe"),
    ("plaja", "🏖️ Plajă și soare"), ("citybreak", "🏙️ City break și weekend"),
    ("pachet", "🏨 Zbor + cazare"), ("allinc", "🍹 All inclusive"),
    ("sarbatori", "🎄 Sărbători"), ("direct", "✈️ Zboruri directe"),
]
NUME_CATEGORIE = dict(CATEGORII)
LUNI_NUME = ["Ianuarie", "Februarie", "Martie", "Aprilie", "Mai", "Iunie", "Iulie", "August",
             "Septembrie", "Octombrie", "Noiembrie", "Decembrie"]


def paste_ortodox(an: int) -> date:
    a, b, c = an % 4, an % 7, an % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    luna, zi = divmod(d + e + 114, 31)
    return date(an, luna, zi + 1) + timedelta(days=13)


def e_in_sarbatori(d1: date, d2: date | None) -> bool:
    d2 = d2 or d1
    for an in {d1.year, d2.year}:
        paste = paste_ortodox(an)
        ferestre = [
            (date(an, 12, 20), date(an + 1, 1, 6)),                    # Crăciun și Revelion
            (date(an - 1, 12, 20), date(an, 1, 6)),
            (paste - timedelta(days=3), paste + timedelta(days=2)),   # Paște
            (date(an, 4, 29), date(an, 5, 3)),                         # 1 Mai
            (paste + timedelta(days=47), paste + timedelta(days=50)),  # Rusalii
            (date(an, 11, 28), date(an, 12, 1)),                       # 1 Decembrie
        ]
        if any(d1 <= sf and d2 >= st for st, sf in ferestre):
            return True
    return False


def luna_oferta(o: dict) -> str:
    """„2027-01” pentru filtrul pe luni (din data zborului sau din perioada scrisă)."""
    if o.get("data_plecare"):
        return o["data_plecare"][:7]
    t = norm(o.get("perioada", ""))
    m = re.search(r"\b(ian|feb|mar|apr|mai|iun|iul|aug|sep|oct|noi|nov|dec)[a-z]*\.?"
                  r"(?:\s*-\s*[a-z]+\.?)?\s*(20\d\d)?", t)
    if not m:
        return ""
    luna = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi",
            "dec"].index("noi" if m.group(1) == "nov" else m.group(1)) + 1
    azi = ora_locala().date()
    an = int(m.group(2)) if m.group(2) else (azi.year if luna >= azi.month else azi.year + 1)
    return f"{an}-{luna:02d}"


def categorii_oferta(o: dict, cfg: dict) -> list[str]:
    tn = norm(f"{o['titlu']} {o['destinatie']}")
    reg = o.get("regiune") or regiune(tn)
    cat = []
    if o["scor"] >= cfg["scor_super_oferta"]:
        cat.append("super")
    if o["pret"] <= 50:
        cat.append("sub50")
    if o["pret"] <= 100:
        cat.append("sub100")
    if reg == "europa":
        cat.append("europa")
    else:
        cat.append("departe")
        if reg in NUME_CATEGORIE:
            cat.append(reg)
    if RE_PLAJA.search(tn) or o.get("all_inclusive"):
        cat.append("plaja")
    scurt = o.get("nopti") is not None and o["nopti"] <= 4
    if reg == "europa" and (scurt or re.search(r"city break|weekend", tn)):
        cat.append("citybreak")
    if o["tip"] == "pachet":
        cat.append("pachet")
    if o.get("all_inclusive"):
        cat.append("allinc")
    sarbatoare = re.search(r"revelion|craciun|sarbator|\bpaste\b|1 mai|rusalii|anul nou|"
                           r"christmas|new year|easter", norm(f"{tn} {o.get('perioada', '')}"))
    if sarbatoare or (o.get("data_plecare") and e_in_sarbatori(
            date.fromisoformat(o["data_plecare"]),
            date.fromisoformat(o["data_intoarcere"]) if o.get("data_intoarcere") else None)):
        cat.append("sarbatori")
    if o.get("direct"):
        cat.append("direct")
    return cat


def referinta(o: dict, cfg: dict, distanta: str) -> float:
    ref = float(cfg["referinta_zbor"][distanta])
    if o["tip"] == "pachet":
        pe_noapte = (cfg["referinta_noapte_all_inclusive"] if o.get("all_inclusive")
                     else cfg["referinta_noapte_cazare"][distanta])
        ref += (o.get("nopti") or 4) * float(pe_noapte)
    return ref


def migreaza_oferta(o: dict, cfg: dict) -> None:
    """Ofertele salvate de versiunea veche nu au regiune: o adăugăm și corectăm scorul."""
    if "regiune" in o:
        return
    text = norm(f"{o['titlu']} {o['destinatie']}")
    o["regiune"] = regiune(text)
    nou = clasa_distanta(text, o["regiune"])
    vechi = o.get("distanta", nou)
    if nou != vechi:
        baza_veche = 100 * (1.2 - o["pret"] / referinta(o, cfg, vechi)) / 0.9
        baza_noua = 100 * (1.2 - o["pret"] / referinta(o, cfg, nou)) / 0.9
        bonus = 0 if o["scor"] in (0, 100) else o["scor"] - baza_veche  # scorul vechi era tăiat la 0/100
        o["scor"] = int(max(0, min(100, round(baza_noua + bonus))))
        o["distanta"] = nou


def cheie_minim(o: dict) -> str:
    plecare = o["plecari"][0] if o.get("plecari") else ""
    return f"{norm(o['destinatie']).split(',')[0]}|{o['tip']}|{plecare}"


def actualizeaza_minim(stare: dict, o: dict) -> float | None:
    """Întoarce cel mai mic preț din ultimele 30 de zile pentru destinație (înainte de asta)."""
    if o["destinatie"] == "Diverse destinații":
        return None
    cheie = cheie_minim(o)
    v = stare["minime"].get(cheie)
    anterior = None
    if isinstance(v, dict) and v.get("ts", "") >= (acum() - timedelta(days=30)).isoformat():
        anterior = float(v["pret"])
    if anterior is None or o["pret"] < anterior:
        stare["minime"][cheie] = {"pret": o["pret"], "ts": acum().isoformat()}
    return anterior


def merita_notificare(o: dict, cfg: dict, liniste: bool) -> bool:
    prag = cfg["scor_minim_radar"] if o.get("radar") else cfg["scor_minim_notificare"]
    if o["scor"] < prag or (o.get("radar") and not o.get("notifica", True)):
        return False
    if liniste and o["scor"] < cfg["scor_super_oferta"]:
        return False
    dorite = cfg.get("categorii_notificare") or []
    return not dorite or bool(set(dorite) & set(categorii_oferta(o, cfg)))


def cheie_duplicat(o: dict) -> str:
    dest = norm(o["destinatie"]).split(",")[0].split(" ")[0]
    if dest == "diverse":
        return o["id"]
    return f"{dest}|{o['tip']}|{round(o['pret'] / 5)}"


# --------------------------------------------------------------------------------------
# Notificări
# --------------------------------------------------------------------------------------
def eticheta(scor: int, cfg: dict) -> str:
    if scor >= cfg["scor_super_oferta"]:
        return "🔥 SUPER OFERTĂ"
    if scor >= 60:
        return "👍 Ofertă bună"
    return "✈️ Ofertă"


def descriere_tip(o: dict) -> str:
    if o["tip"] == "zbor":
        t = "zbor dus" if o.get("data_plecare") and not o.get("data_intoarcere") else "zbor dus-întors"
        if o.get("nopti"):
            t += f" · {o['nopti']} {'noapte' if o['nopti'] == 1 else 'nopți'}"
        return t + (" · direct" if o.get("direct") else "")
    s = f"zbor + {o['nopti']} nopți cazare" if o.get("nopti") else "zbor + cazare"
    return s + (" ALL INCLUSIVE" if o.get("all_inclusive") else "")


def nume_plecari(o: dict) -> str:
    nume = ", ".join(PLECARI[c][0] for c in o["plecari"] if c in PLECARI)
    if o.get("aeroport") in NUME_AEROPORT:
        nume += f" ({NUME_AEROPORT[o['aeroport']]})"
    return nume if o["plecare_sigura"] else f"{nume} (probabil)"


def link_brosura(o: dict, cfg: dict) -> str:
    """Link spre planificator, cu biletul completat: #oferta--oras--tara--4n--20270120--20270124--buh--fco"""
    baza = cfg.get("link_brosura") or ""
    if not baza or o["destinatie"] == "Diverse destinații":
        return ""
    s = lambda t: re.sub(r"[^a-z0-9]+", "-", norm(t)).strip("-") or "x"
    oras, _, tara = o["destinatie"].partition(",")
    iata = re.search(r"/flight-search/[A-Z]{3}-([A-Z]{3})/", o.get("url", ""))
    parti = [s(oras), s(tara), f"{o.get('nopti') or 'x'}n",
             (o.get("data_plecare") or "x").replace("-", ""),
             (o.get("data_intoarcere") or "x").replace("-", ""),
             (o["plecari"][0] if o.get("plecari") else "BUH").lower(),
             iata.group(1).lower() if iata else "x"]
    return baza.split("#")[0] + "#oferta--" + "--".join(parti)


def etichete_categorii(o: dict, cfg: dict) -> str:
    return " · ".join(NUME_CATEGORIE[c] for c in categorii_oferta(o, cfg) if c != "super")


def text_notificare(o: dict, cfg: dict) -> tuple[str, str]:
    titlu = f"{eticheta(o['scor'], cfg)} · {o['pret_afisat']} · {o['destinatie']}"
    linii = [
        o["titlu"],
        "",
        f"💶 {o['pret_afisat']} / pers · {descriere_tip(o)}",
        f"🛫 Plecare: {nume_plecari(o)}",
    ]
    if o.get("perioada"):
        linii.append(f"📅 Perioadă: {o['perioada']}")
    if o.get("companii"):
        linii.append(f"🏷️ {', '.join(o['companii'])}")
    if etichete_categorii(o, cfg):
        linii.append(f"🗂️ {etichete_categorii(o, cfg)}")
    linii.append(f"⭐ Scor {o['scor']}/100" + (f" ({'; '.join(o['motive'])})" if o["motive"] else ""))
    sursa = o["sursa"] + (f" (și pe {', '.join(o['si_pe'])})" if o.get("si_pe") else "")
    linii.append(f"📰 {sursa}")
    linii.append(o["url"])
    if link_brosura(o, cfg):
        linii.append(f"\n📖 Broșură de călătorie: {link_brosura(o, cfg)}")
    if cfg.get("link_raport"):
        linii.append(f"\n🗂️ Toate ofertele: {cfg['link_raport']}")
    return titlu, "\n".join(linii)


def trimite_ntfy(cfg: dict, titlu: str, mesaj: str, prioritate: int = 3,
                 etichete: list[str] | None = None, link: str | None = None,
                 brosura: str | None = None) -> bool:
    n = cfg["notificari"]
    if not n.get("ntfy_topic"):
        return False
    corp = {"topic": n["ntfy_topic"], "title": titlu, "message": mesaj,
            "priority": prioritate, "tags": etichete or ["airplane"]}
    actiuni = []
    if link:
        corp["click"] = link
        actiuni.append({"action": "view", "label": "Vezi oferta", "url": link})
    if brosura:
        actiuni.append({"action": "view", "label": "Broșură", "url": brosura})
    if cfg.get("link_raport"):
        actiuni.append({"action": "view", "label": "Toate ofertele", "url": cfg["link_raport"]})
    if actiuni:
        corp["actions"] = actiuni
    antete = {"Content-Type": "application/json", "User-Agent": "agent-oferte"}
    if n.get("ntfy_token"):
        antete["Authorization"] = f"Bearer {n['ntfy_token']}"
    req = urllib.request.Request(n["ntfy_server"].rstrip("/"), method="POST", headers=antete,
                                 data=json.dumps(corp).encode())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        log(f"ntfy: eroare {e}")
        return False


def trimite_telegram(cfg: dict, titlu: str, mesaj: str, silentios: bool = False) -> bool:
    n = cfg["notificari"]
    if not (n.get("telegram_bot_token") and n.get("telegram_chat_id")):
        return False
    text = f"<b>{html.escape(titlu)}</b>\n\n{html.escape(mesaj)}"
    date = urllib.parse.urlencode({
        "chat_id": n["telegram_chat_id"], "text": text[:4000], "parse_mode": "HTML",
        "disable_notification": "true" if silentios else "false",
    }).encode()
    baza = os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
    url = f"{baza}/bot{n['telegram_bot_token']}/sendMessage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=date), timeout=20) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        log(f"Telegram: eroare {e.code} {e.read()[:200]!r}")
    except Exception as e:  # noqa: BLE001
        log(f"Telegram: eroare {e}")
    return False


def email_configurat(cfg: dict) -> bool:
    n = cfg["notificari"]
    return bool(n.get("email_utilizator") and n.get("email_parola"))


def trimite_email(cfg: dict, subiect: str, text: str, corp_html: str | None = None) -> bool:
    """Trimite un email prin SMTP (implicit Gmail cu „parolă de aplicație”)."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    if not email_configurat(cfg):
        return False
    n = cfg["notificari"]
    msg = EmailMessage()
    msg["Subject"] = subiect
    msg["From"] = f"Agent oferte <{n['email_utilizator']}>"
    msg["To"] = n["email_catre"]
    msg.set_content(text)
    if corp_html:
        msg.add_alternative(corp_html, subtype="html")
    parola = n["email_parola"].replace(" ", "")  # Gmail o afișează în grupuri de câte 4
    host, port = n["email_smtp_host"], int(n["email_smtp_port"])
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
                s.login(n["email_utilizator"], parola)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if s.has_extn("starttls"):
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if s.has_extn("auth"):
                    s.login(n["email_utilizator"], parola)
                s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"Email: eroare {e}")
        return False


def email_oferte(cfg: dict, oferte: list[dict], introducere: str = "") -> tuple[str, str]:
    """Un singur email cu toate ofertele noi dintr-o rulare: (text simplu, HTML)."""
    e = html.escape
    texte, carduri = [], []
    for o in oferte:
        t, m = text_notificare(o, {**cfg, "link_raport": ""})
        texte.append(f"{t}\n{m}")
        culoare = ("#c2410c" if o["scor"] >= cfg["scor_super_oferta"]
                   else "#15803d" if o["scor"] >= 60 else "#5d6672")
        detalii = " · ".join(x for x in [descriere_tip(o), "Plecare: " + nume_plecari(o),
                                          ("Perioadă: " + o["perioada"]) if o.get("perioada") else "",
                                          ", ".join(o.get("companii", []))] if x)
        carduri.append(
            f'<div style="border:1px solid #e3e6ea;border-radius:10px;padding:12px 14px;margin:0 0 10px">'
            f'<div style="font-size:13px;color:{culoare};font-weight:700">{e(eticheta(o["scor"], cfg))}'
            f' · scor {o["scor"]}/100</div>'
            f'<div style="font-size:18px;font-weight:700;margin:2px 0">{e(o["pret_afisat"])} · '
            f'{e(o["destinatie"])}</div>'
            f'<div style="margin:2px 0">{e(o["titlu"])}</div>'
            f'<div style="font-size:13px;color:#5d6672">{e(detalii)}</div>'
            f'<div style="font-size:13px;color:#5d6672">{e(etichete_categorii(o, cfg))}</div>'
            f'<div style="font-size:13px;color:#5d6672">{e(o["sursa"])}</div>'
            f'<a href="{e(o["url"])}" style="display:inline-block;margin-top:8px;padding:8px 14px;'
            f'background:#0b6bcb;color:#fff;border-radius:8px;text-decoration:none">Vezi oferta</a>'
            + (f' <a href="{e(link_brosura(o, cfg))}" style="display:inline-block;margin-top:8px;padding:8px 14px;'
               f'border:1px solid #0b6bcb;color:#0b6bcb;border-radius:8px;text-decoration:none">📖 Broșură</a>'
               if link_brosura(o, cfg) else "") + '</div>')
    raport = cfg.get("link_raport")
    text = (introducere + "\n\n" if introducere else "") + "\n\n————\n\n".join(texte)
    if raport:
        text += f"\n\nToate ofertele, ordonate după scor: {raport}"
    corp_html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#1b1f24;max-width:600px">'
        + (f"<p>{e(introducere)}</p>" if introducere else "") + "".join(carduri)
        + (f'<p><a href="{e(raport)}">Toate ofertele, ordonate după scor</a></p>' if raport else "")
        + "</div>")
    return text, corp_html


def notifica(cfg: dict, titlu: str, mesaj: str, prioritate: int = 3,
             etichete: list[str] | None = None, link: str | None = None,
             brosura: str | None = None) -> bool:
    ok1 = trimite_ntfy(cfg, titlu, mesaj, prioritate, etichete, link, brosura)
    ok2 = trimite_telegram(cfg, titlu, mesaj, silentios=prioritate <= 2)
    return ok1 or ok2


def are_canal(cfg: dict) -> bool:
    n = cfg["notificari"]
    return bool(n.get("ntfy_topic") or (n.get("telegram_bot_token") and n.get("telegram_chat_id"))
                or email_configurat(cfg))


def e_ora_de_liniste(cfg: dict) -> bool:
    if not cfg.get("ore_liniste"):
        return False
    start, stop = cfg["ore_liniste"]
    h = ora_locala().hour
    return (h >= start or h < stop) if start > stop else (start <= h < stop)


# --------------------------------------------------------------------------------------
# Raport HTML (cea mai bună ofertă în orice moment)
# --------------------------------------------------------------------------------------
def scrie_raport(stare: dict, cfg: dict) -> None:
    """Pagina cu toate ofertele, pe categorii (ca pe Aventurescu), cu filtre și sortare."""
    limita = (acum() - timedelta(days=14)).isoformat()
    azi = ora_locala().date().isoformat()
    oferte = [o for o in stare["oferte"].values()
              if o.get("publicat", "") >= limita and not o.get("duplicat_al")
              and (not o.get("data_plecare") or o["data_plecare"] >= azi)]
    oferte.sort(key=lambda o: (-o["scor"], o["pret"]))
    date_json = []
    for o in oferte:
        try:
            ts = int(datetime.fromisoformat(o["publicat"]).timestamp())
        except (KeyError, ValueError):
            ts = 0
        sursa = o["sursa"] + (f" + {', '.join(o['si_pe'])}" if o.get("si_pe") else "")
        date_json.append({
            "u": o["url"], "t": o["titlu"], "d": o["destinatie"], "p": o["pret"],
            "pa": o["pret_afisat"], "s": o["scor"], "c": categorii_oferta(o, cfg),
            "l": luna_oferta(o), "pl": o.get("plecari", []), "dep": nume_plecari(o),
            "tip": descriere_tip(o), "per": o.get("perioada", ""),
            "co": ", ".join(o.get("companii", [])), "src": sursa, "ts": ts,
            "r": bool(o.get("radar")), "h": link_brosura(o, cfg),
        })
    luni = sorted({x["l"] for x in date_json if x["l"]})
    optiuni_luni = "".join(
        f'<option value="{l}">{LUNI_NUME[int(l[5:]) - 1]} {l[:4]}</option>' for l in luni)
    categorii_js = json.dumps([["toate", "Toate"]] + [list(c) for c in CATEGORII], ensure_ascii=False)
    date_js = json.dumps(date_json, ensure_ascii=False).replace("</", "<\\/")
    prag_super = cfg["scor_super_oferta"]
    pagina = f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oferte călătorii</title>
<style>
:root{{--bg:#f4f5f7;--card:#fff;--txt:#1b1f24;--mut:#5d6672;--lin:#e1e4e8;--acc:#0b6bcb;--acc-bg:#e8f1fb;
--sup:#c2410c;--bun:#15803d;--tag:#eef0f3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--card:#1b2027;--txt:#e8eaed;--mut:#9aa3ad;--lin:#2b323b;
--acc:#6aa9ff;--acc-bg:#1a2a3d;--sup:#fb923c;--bun:#4ade80;--tag:#252b33}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--txt);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:20px 16px 48px}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{color:var(--mut);margin:0 0 16px}}
.ctrl{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:12px}}
.ctrl label{{display:flex;flex-direction:column;font-size:12px;color:var(--mut);gap:4px}}
select,input{{font:inherit;color:var(--txt);background:var(--card);border:1px solid var(--lin);border-radius:8px;
padding:8px 10px;width:100%}}
.chips{{display:flex;gap:8px;overflow-x:auto;padding:2px 0 10px;margin-bottom:8px;scrollbar-width:thin}}
.chip{{flex:0 0 auto;border:1px solid var(--lin);background:var(--card);color:var(--txt);border-radius:999px;
padding:7px 12px;cursor:pointer;font:inherit;font-size:14px;white-space:nowrap}}
.chip b{{font-weight:600;color:var(--mut);margin-left:6px}}
.chip[aria-pressed="true"]{{border-color:var(--acc);background:var(--acc-bg);color:var(--acc)}}
.chip[aria-pressed="true"] b{{color:var(--acc)}}
.lista{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
.card{{display:flex;flex-direction:column;gap:3px;background:var(--card);border:1px solid var(--lin);
border-radius:12px;padding:14px;color:inherit;min-width:0}}
.card:hover{{border-color:var(--acc)}}
.card a{{text-decoration:none}}.card a.dest{{color:inherit}}.card a.dest:hover{{color:var(--acc)}}
.linkuri{{display:flex;gap:14px;flex-wrap:wrap;justify-content:flex-end}}
.sus{{display:flex;justify-content:space-between;align-items:center;gap:8px}}
.pret{{font-weight:700;font-size:22px}}.pret small{{font-size:13px;font-weight:400;color:var(--mut)}}
.scor{{min-width:38px;height:30px;padding:0 8px;border-radius:8px;display:grid;place-items:center;font-weight:700;
background:var(--tag);font-size:14px}}
.super .scor{{background:var(--sup);color:#fff}}.bun .scor{{background:var(--bun);color:#fff}}
.dest{{font-weight:700;font-size:16px;overflow-wrap:anywhere}}
.titlu{{font-size:14px;overflow-wrap:anywhere}}.mut{{color:var(--mut);font-size:13px;overflow-wrap:anywhere}}
.tags{{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}}
.tags span{{background:var(--tag);border-radius:6px;padding:2px 7px;font-size:12px;color:var(--mut)}}
.jos{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap}}
.go{{color:var(--acc);font-weight:600;font-size:14px;white-space:nowrap}}
.gol{{color:var(--mut);padding:24px 0}}
#mai{{display:block;margin:16px auto 0;border:1px solid var(--lin);background:var(--card);color:var(--txt);
border-radius:999px;padding:9px 18px;font:inherit;cursor:pointer}}
</style></head><body><main>
<h1>Oferte de călătorie din București / Constanța</h1>
<p class="sub">Actualizat {ora_locala():%d.%m.%Y %H:%M} · {len(date_json)} oferte din ultimele 14 zile</p>
<div class="ctrl">
<label>Pleci din<select id="din"><option value="toate">Toate orașele</option>
<option value="BUH">București</option><option value="CND">Constanța</option><option value="TCE">Tulcea</option></select></label>
<label>Luna plecării<select id="luna"><option value="toate">Toate lunile</option>{optiuni_luni}</select></label>
<label>Sortează<select id="sort"><option value="scor">Cele mai bune</option>
<option value="pret">Cele mai ieftine</option><option value="noi">Cele mai noi</option></select></label>
<label>Caută destinația<input id="q" type="search" placeholder="ex. Roma, Bali, Egipt"></label>
</div>
<div class="chips" id="chips" role="group" aria-label="Categorii"></div>
<div class="lista" id="lista"></div>
<button id="mai" type="button" hidden>Arată mai multe</button>
</main>
<script id="date" type="application/json">{date_js}</script>
<script>
const D=JSON.parse(document.getElementById('date').textContent);
const CAT={categorii_js};
const NUME=Object.fromEntries(CAT);
const SUPER={prag_super};
const st={{cat:(location.hash||'#toate').slice(1),din:'toate',luna:'toate',sort:'scor',q:'',n:60}};
if(!NUME[st.cat])st.cat='toate';
const norm=s=>(s||'').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
const el=(tag,cls,txt)=>{{const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}};
function cand(ts){{if(!ts)return'';const m=Math.round((Date.now()/1000-ts)/60);
if(m<60)return'acum '+Math.max(1,m)+' min';const h=Math.round(m/60);if(h<24)return'acum '+h+(h===1?' oră':' ore');
const z=Math.round(h/24);return'acum '+z+(z===1?' zi':' zile');}}
function trece(o,faraCat){{
if(st.din!=='toate'&&!o.pl.includes(st.din))return false;
if(st.luna!=='toate'&&o.l!==st.luna)return false;
if(st.q&&!norm(o.d+' '+o.t).includes(st.q))return false;
return faraCat||st.cat==='toate'||o.c.includes(st.cat);}}
function card(o){{
const a=el('div','card'+(o.s>=SUPER?' super':o.s>=60?' bun':''));
const lnk=(cls,t,u)=>{{const x=el('a',cls,t);x.href=u;x.target='_blank';x.rel='noopener';return x;}};
const sus=el('div','sus');const p=el('span','pret',o.pa+' ');p.appendChild(el('small',null,'/ pers'));
sus.append(p,el('span','scor',String(o.s)));sus.lastChild.title='Scor '+o.s+'/100';a.append(sus,lnk('dest',o.d,o.u));
if(!o.r)a.append(el('div','titlu',o.t));
a.append(el('div','mut',o.tip));
a.append(el('div','mut','din '+o.dep+(o.co?' · '+o.co:'')));
if(o.per)a.append(el('div','mut','📅 '+o.per));
const tg=el('div','tags');o.c.filter(c=>c!=='super').forEach(c=>tg.append(el('span',null,NUME[c]||c)));a.append(tg);
const jos=el('div','jos');const lk=el('span','linkuri');
if(o.h)lk.append(lnk('go','📖 Broșură',o.h));lk.append(lnk('go','Vezi oferta ↗',o.u));
jos.append(el('span','mut',o.src+(o.ts?' · '+cand(o.ts):'')),lk);
a.append(jos);return a;}}
function render(){{
const baza=D.filter(o=>trece(o,true));
const nr={{toate:baza.length}};baza.forEach(o=>o.c.forEach(c=>nr[c]=(nr[c]||0)+1));
const ch=document.getElementById('chips');ch.textContent='';
CAT.forEach(([k,n])=>{{if(k!=='toate'&&!nr[k]&&st.cat!==k)return;
const b=el('button','chip',n);b.type='button';b.setAttribute('aria-pressed',String(st.cat===k));
b.append(el('b',null,String(nr[k]||0)));b.onclick=()=>{{st.cat=k;st.n=60;history.replaceState(null,'','#'+k);render();}};ch.append(b);}});
const act=ch.querySelector('[aria-pressed="true"]');if(act&&act.offsetLeft+act.offsetWidth>ch.scrollLeft+ch.clientWidth)ch.scrollLeft=act.offsetLeft-ch.offsetLeft-16;
let l=baza.filter(o=>trece(o,false));
if(st.sort==='pret')l.sort((a,b)=>a.p-b.p||b.s-a.s);else if(st.sort==='noi')l.sort((a,b)=>b.ts-a.ts);
else l.sort((a,b)=>b.s-a.s||a.p-b.p);
const li=document.getElementById('lista');li.textContent='';
if(!l.length)li.append(el('p','gol','Nicio ofertă pentru filtrele alese.'));
l.slice(0,st.n).forEach(o=>li.append(card(o)));
const m=document.getElementById('mai');m.hidden=l.length<=st.n;m.textContent='Arată mai multe ('+(l.length-st.n)+')';}}
document.getElementById('mai').onclick=()=>{{st.n+=60;render();}};
['din','luna','sort'].forEach(id=>document.getElementById(id).onchange=e=>{{st[id]=e.target.value;st.n=60;render();}});
document.getElementById('q').oninput=e=>{{st.q=norm(e.target.value.trim());st.n=60;render();}};
render();
</script></body></html>"""
    # rescrie pagina doar dacă s-au schimbat ofertele (nu doar ora), ca să nu facă commit degeaba
    def fara_ora(t: str) -> str:
        return re.sub(r'<p class="sub">Actualizat [^·]*·', "", t)
    if FISIER_RAPORT.exists() and fara_ora(FISIER_RAPORT.read_text(encoding="utf-8")) == fara_ora(pagina):
        return
    FISIER_RAPORT.write_text(pagina, encoding="utf-8")


# --------------------------------------------------------------------------------------
# Rularea propriu-zisă
# --------------------------------------------------------------------------------------
def ruleaza(cfg: dict, simulare: bool = False) -> list[dict]:
    stare = incarca_stare()
    prima_rulare = not stare["oferte"]
    if "surse_vazute" not in stare:
        stare["surse_vazute"] = sorted({o.get("sursa_id", "") for o in stare["oferte"].values()})
    for o in stare["oferte"].values():
        migreaza_oferta(o, cfg)
    limita_vechime = acum() - timedelta(days=cfg["zile_vechime_maxima"])
    noi: list[dict] = []
    recente = {}
    for o in stare["oferte"].values():
        if o.get("publicat", "") >= (acum() - timedelta(days=4)).isoformat() and not o.get("duplicat_al"):
            recente.setdefault(cheie_duplicat(o), o)

    for sursa in cfg["surse"]:
        if sursa.get("activ") is False:
            continue
        cititor = CITITORI.get(sursa.get("tip", "rss"))
        if not cititor:
            log(f"{sursa['nume']}: tip de sursă necunoscut „{sursa.get('tip')}”")
            continue
        try:
            articole = cititor(sursa)
        except Exception as e:  # noqa: BLE001
            log(f"{sursa['nume']} [{sursa['id']}]: {e}")
            continue
        # o sursă adăugată acum: ofertele ei existente se salvează fără notificări (fără spam)
        sursa_noua = not prima_rulare and sursa["id"] not in stare["surse_vazute"]
        potrivite = 0
        for art in articole:
            if art["data"] and art["data"] < limita_vechime:
                continue
            o = analizeaza(art, sursa, cfg)
            if not o:
                continue
            potrivite += 1
            if o["id"] in stare["oferte"]:
                continue
            o["vazut"] = acum().isoformat()
            if sursa_noua:
                o["initial"] = True
                actualizeaza_minim(stare, o)
                stare["oferte"][o["id"]] = o
                continue
            k = cheie_duplicat(o)
            if k in recente and recente[k]["sursa_id"] != o["sursa_id"]:
                orig = recente[k]
                orig.setdefault("si_pe", [])
                if o["sursa"] not in orig["si_pe"]:
                    orig["si_pe"].append(o["sursa"])
                o["duplicat_al"] = orig["id"]
            else:
                recente[k] = o
                noi.append(o)
            stare["oferte"][o["id"]] = o
        if sursa["id"] not in stare["surse_vazute"]:
            stare["surse_vazute"].append(sursa["id"])
        log(f"{sursa['nume']} [{sursa['id']}]: {len(articole)} articole, {potrivite} oferte potrivite"
            + (" (sursă nouă: salvate fără notificări)" if sursa_noua else ""))

    # cel mai mic preț din ultimele 30 de zile pentru destinație -> bonus / notificare (Radar)
    noi.sort(key=lambda o: o["pret"])
    for o in noi:
        anterior = actualizeaza_minim(stare, o)
        scazut = anterior is not None and o["pret"] <= 0.95 * anterior
        if o.get("radar"):
            o["notifica"] = anterior is None or scazut
        if scazut:
            o["scor"] = min(100, o["scor"] + 10)
            o["motive"].append(f"preț mai mic decât în ultimele 30 de zile (înainte {int(anterior)}€)")

    noi.sort(key=lambda o: (-o["scor"], o["pret"]))
    log(f"Oferte noi: {len(noi)}" + (" (prima rulare)" if prima_rulare else ""))

    if simulare:
        for o in noi[:25]:
            t, m = text_notificare(o, cfg)
            print("\n" + "=" * 70 + f"\n{t}\n{m}")
        return noi

    if not are_canal(cfg):
        log("Atenție: niciun canal de notificare configurat (NTFY_TOPIC, TELEGRAM_* sau EMAIL_*). "
            "Nu salvez istoricul, ca prima rulare cu notificări să-ți trimită topul ofertelor.")
        scrie_raport(stare, cfg)
        return noi

    trimise = 0
    if prima_rulare:
        top = [o for o in noi if o["scor"] >= cfg["scor_minim_notificare"]][:5]
        corp = "\n\n".join(f"{i}. {o['pret_afisat']} · {o['destinatie']} ({descriere_tip(o)}), "
                           f"scor {o['scor']}\n{o['url']}" for i, o in enumerate(top, 1))
        intro = "De acum primești aici fiecare ofertă nouă din București/Constanța."
        notifica(cfg, "✅ Agentul de oferte a pornit",
                 intro + "\n\nCele mai bune oferte de acum:\n\n" + (corp or "(nicio ofertă momentan)")
                 + (f"\n\n🗂️ Toate ofertele: {cfg['link_raport']}" if cfg.get("link_raport") else ""),
                 prioritate=3, etichete=["white_check_mark"])
        if email_configurat(cfg):
            text, corp_html = email_oferte(cfg, top, intro + " Cele mai bune oferte de acum:")
            trimite_email(cfg, "✅ Agentul de oferte a pornit", text, corp_html)
    else:
        liniste = e_ora_de_liniste(cfg)
        eligibile = [o for o in noi if merita_notificare(o, cfg, liniste)]
        for o in eligibile[:cfg["max_notificari_pe_rulare"]]:
            t, m = text_notificare(o, cfg)
            sup = o["scor"] >= cfg["scor_super_oferta"]
            if notifica(cfg, t, m, prioritate=4 if sup else 3,
                        etichete=["fire"] if sup else ["airplane"], link=o["url"],
                        brosura=link_brosura(o, cfg) or None):
                o["notificat"] = True
                trimise += 1
        rest = eligibile[cfg["max_notificari_pe_rulare"]:]
        if rest:
            corp = "\n".join(f"• {o['pret_afisat']} {o['destinatie']} (scor {o['scor']}) {o['url']}"
                             for o in rest[:15])
            notifica(cfg, f"➕ Încă {len(rest)} oferte noi", corp, prioritate=2)
        # pe email: un singur mesaj pe rulare, cu toate ofertele noi (cea mai bună sus)
        if eligibile and email_configurat(cfg):
            prima = eligibile[0]
            subiect = f"{eticheta(prima['scor'], cfg)}: {prima['pret_afisat']} {prima['destinatie']}"
            if len(eligibile) > 1:
                subiect += f" + încă {len(eligibile) - 1} oferte"
            text, corp_html = email_oferte(cfg, eligibile[:20])
            if trimite_email(cfg, subiect, text, corp_html):
                log(f"Email trimis cu {min(len(eligibile), 20)} oferte")
    log(f"Notificări trimise: {trimise}")

    salveaza_stare(stare)
    scrie_raport(stare, cfg)
    return noi


def afiseaza_top(cfg: dict, n: int) -> None:
    stare = incarca_stare()
    limita = (acum() - timedelta(days=7)).isoformat()
    oferte = sorted((o for o in stare["oferte"].values()
                     if o.get("publicat", "") >= limita and not o.get("duplicat_al")),
                    key=lambda o: (-o["scor"], o["pret"]))
    if not oferte:
        print("Nicio ofertă salvată încă. Rulează întâi: python agent_oferte.py")
    for i, o in enumerate(oferte[:n], 1):
        print(f"{i:2}. [{o['scor']:3}] {o['pret_afisat']:>9} {o['destinatie'][:28]:28} "
              f"{descriere_tip(o):32} {nume_plecari(o):22} {o['sursa']}\n    {o['url']}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Agent oferte de călătorie (București / Constanța)")
    ap.add_argument("--bucla", type=int, metavar="MINUTE", help="rulează la nesfârșit, la fiecare N minute")
    ap.add_argument("--simulare", action="store_true", help="nu trimite notificări și nu salvează nimic")
    ap.add_argument("--top", type=int, metavar="N", help="afișează cele mai bune N oferte salvate")
    ap.add_argument("--test", action="store_true", help="trimite o notificare de test")
    ap.add_argument("--reset", action="store_true", help="șterge istoricul (stare.json)")
    a = ap.parse_args()
    cfg = incarca_config()

    if a.reset:
        FISIER_STARE.unlink(missing_ok=True)
        print("Istoric șters.")
        return
    if a.test:
        if not are_canal(cfg):
            sys.exit("Niciun canal configurat. Setează NTFY_TOPIC, TELEGRAM_BOT_TOKEN + "
                     "TELEGRAM_CHAT_ID sau EMAIL_UTILIZATOR + EMAIL_PAROLA.")
        ok = notifica(cfg, "🧪 Test agent oferte", "Dacă vezi mesajul ăsta, notificările merg.",
                      etichete=["test_tube"])
        if email_configurat(cfg):
            ok = trimite_email(cfg, "🧪 Test agent oferte",
                               "Dacă vezi mesajul ăsta, notificările pe email merg.") or ok
        print("Trimis ✅" if ok else "Nu s-a putut trimite ❌")
        return
    if a.top:
        afiseaza_top(cfg, a.top)
        return
    if a.bucla:
        log(f"Pornit în buclă: verific la fiecare {a.bucla} minute (Ctrl+C pentru oprire)")
        while True:
            try:
                ruleaza(cfg)
            except Exception as e:  # noqa: BLE001
                log(f"Eroare la rulare: {e}")
            time.sleep(max(1, a.bucla) * 60)
    ruleaza(cfg, simulare=a.simulare)


if __name__ == "__main__":
    main()
