# KIR/KPR → Minimax Studio (KirKpr) 4.0.0

Namizna aplikacija za uvoz evidenc **KIR/KPR**, pregled in pretvorbo v Minimax, obrazec **DDV-O** (XML za eDavke, PDF, virman UPN QR, e-pošta) in oddajo v **Minimax**.

* **Okolje:** Windows 10/11, Python 3.10+, knjižnice iz `requirements_KIrKpr_to_minimax.txt`.
* **Vmesnik:** klasično okno Tkinter (`kirkpr_gui_style.py`).
* **Mapa:** `D:\PISARNA\Python\KirKpr` (prej `KirKpr_convert_cursor`).

## Zagon

1. Dvokliknite `Zaženi_KIRKPR_Minimax_cursor.bat`
2. ali: `py convert_KIrKpr_to_minimax.py`

Odvisnosti:

```text
py -m pip install -r requirements_KIrKpr_to_minimax.txt
```

## CLI primeri

```text
py convert_KIrKpr_to_minimax.py vhod.zip --validate
py convert_KIrKpr_to_minimax.py vhod.zip --validate --summary-json povzetek.json
py convert_KIrKpr_to_minimax.py vhod.zip --dry-run
py convert_KIrKpr_to_minimax.py vhod.zip --output C:\Izhod
```

## Struktura

| Pot | Vsebina |
|---|---|
| `convert_KIrKpr_to_minimax.py` | glavni program in okno |
| `Zaženi_KIRKPR_Minimax_cursor.bat` | priporočeni zagon |
| `kirkpr_minimax_core.py`, `kirkpr_minimax_dataset.py`, `minimax_api_client.py` | jedro pretvorbe in Minimax API |
| `kirkpr_gui_style.py` | slog okna Tkinter |
| `kirkpr_ddvo_*.py`, `ddvo_transforms/` | DDV-O (XML, PDF, virman, e-pošta) |
| `kirkpr_minimax_pw/` | Playwright / CDP za Minimax (brez tujih map) |
| `NAVODILA_convert_KIrKpr_to_minimax.txt` | podrobna navodila programa |
| `FURS_KIR_KPR_primeri/` | primeri evidenc FURS v projektu |
| `.cursor/rules/` | pravila za pomočnika (predlog pred kodo, verzije, P7DS) |

Starejši opis `README_CURSOR.md` ostane kot zgodovina (izdaja v2.48-cursor). Velja ta datoteka.

## Nastavitve in skrivnosti

Lokalna datoteka `convert_KIrKpr_to_minimax_config.json` in baza `kirkpr_sessions.sqlite3` **nista v gitu**. Gesla in `client_secret` se še vedno berejo iz zunanje datoteke Davčne blagajne — tukaj se ne kopirajo.

## Git

Lokalni repozitorij je na veji `main`. Oddaljeni naslov na GitHubu še ni dodan: lastnik bo kasneje ustvaril zasebni repozitorij `bracomihelj-creator/KirKpr`, nato sledi prvi potisk.

## Pravila

Glej `PROMPT.md` in `POROCILO.md`. Vsaka sprememba = svoj git commit. Poslovne logike in izračunov se ne spreminja.
