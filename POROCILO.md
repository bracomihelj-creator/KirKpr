# POROČILO — KirKpr (ureditev mape in lokalni git)

**Datum:** 21. 11. 2026 (Europe/Warsaw) · **Mapa:** `D:\PISARNA\Python\KirKpr` (preimenovana iz `KirKpr_convert_cursor`)
**Verzija programa:** 3.0.191 · **Vmesnik:** Tkinter

## 1. Kaj je bilo narejeno

1. Šest starih datotek iz julija 2026 v korenu `D:\PISARNA\Python` je bilo zapakirano, preverjeno in nato izbrisano. Trenutni program ni bil v tem arhivu.
2. Mapa `KirKpr_convert_cursor` je preimenovana v `KirKpr`.
3. Dodan je `.gitignore`. Uveden je lokalni git (veja `main`), začetni commit vsebuje trenutno drevo programa.
4. V ločenih commitih so dodani `PROMPT.md`, `README.md` in ta `POROCILO.md`.
5. Oddaljeni repozitorij **ni** nastavljen in na GitHub **ni** bilo potisnjeno. To ostane za kasneje, ko lastnik ustvari prazen zasebni repozitorij `bracomihelj-creator/KirKpr`.

Poslovne logike, izračunov in podatkovnih datotek v mapi programa se ta korak ni dotaknil.

## 2. Arhiv starih datotek v korenu

Arhiv: `D:\PISARNA\Python\KirKpr_stari_koren_20261121.zip` in kopija `F:\Arhiv_KirKpr\KirKpr_stari_koren_20261121.zip`.

- Velikost ZIP: 182.128 bajtov (178 KiB), obe kopiji sta enaki.
- V arhivu je 6 datotek, nezgoščeno 229.446 bajtov.
- 7-Zip (`7z t`) je obe kopiji preveril z rezultatom *Everything is Ok*, šele nato so bili izvirniki izbrisani.

Izbrisane datoteke (samo te, vse iz `D:\PISARNA\Python`):

| Datoteka | Opomba |
|---|---|
| `convert_KIrKpr_to_minimax.py` | stara skripta, 17. 7. 2026 |
| `kirkpr_minimax_core.py` | stara skripta, 17. 7. 2026 |
| `convert_KIrKpr_to_minimax_config.json` | stare nastavitve, 17. 7. 2026 |
| `requirements_KIrKpr_to_minimax.txt` | star seznam, 17. 7. 2026 |
| `convert_KIrKpr_to_minimax_program.zip` | star arhiv, 17. 7. 2026 |
| `KirKpr_convert_ChatGPT_za_pregled.zip` | star arhiv, 19. 7. 2026 |

Referenčni dokumenti FURS za KIR/KPR v `D:\PISARNA\Python` (shema, primeri, tehnična navodila) **niso** bili arhivirani niti izbrisani.

## 3. Git

- `.gitignore` izključuje dnevnike, `convert_KIrKpr_to_minimax_config.json`, `kirkpr_sessions.sqlite3`, `upn_qr_cache/`, `__pycache__/` in preizkusni `_roundtrip_out.html`.
- Začetni commit: `4e2b132` — 54 datotek, avtor `braco <braco@localhost>`, 21. 11. 2026 ob 21:39 (Europe/Warsaw).
- `git remote` je prazen. Potisk na GitHub je v čakanju.

## 4. eNDM

KirKpr **nima** aktivne odvisnosti od `QUICK_eNDM` in napake `browser_bridge` v dnevnikih ni. Posega v kodo zaradi eNDM ni bilo.

## 5. Kaj še ni narejeno

- Potisk na GitHub (čaka na ročno ustvarjen repozitorij).
- Preobleka vmesnika po možnosti A (barve, pisava in gostota iz Trops Studio v5 v obstoječe okno Tkinter). Kode za videz v tem koraku ni bilo spremenjene.
- Selitev podatkov v mapo `data/` — šele po posebnem predlogu.
