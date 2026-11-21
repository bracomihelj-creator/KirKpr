# KIR/KPR → Minimax Studio — Cursor izdaja (v4.0.3)

Program je v mapi `D:\PISARNA\Python\KirKpr` (prej KirKpr_convert_cursor).

## Zagon

1. Dvokliknite `Zaženi_KIRKPR_Minimax_cursor.bat`
2. ali: `py convert_KIrKpr_to_minimax.py`

Odvisnosti (enako kot pri originalu):

```text
py -m pip install -r requirements_KIrKpr_to_minimax.txt
```

## Kaj je dodano v Cursor izdaji

| Izboljšava | Opis |
|---|---|
| Dnevnik | `KIRKPR_studio.log` — API predpreverjanje/oddaja brez gesel |
| Nastavitve poti | Meni **Datoteka → Nastavitve poti…** (EvidencaFirm, TROPS, Minimax settings) |
| Ponovi NAPAKA | Gumb na zavihku API — označi neuspešne vrstice in ponovno odda |
| Povzetek oddaje | JSON v `…\KIRKPR_Minimax\<obdobje>\API_oddaje\` |
| CLI validate | `--validate` preveri podatke in DDV-O kontrolo |
| CLI dry-run | `--dry-run` izvoz v začasno mapo + XSD, brez trajnega zapisa |
| JSON pogled | Lokalni KIR/KPR podatki (samo branje, nič se ne spremeni) |
| Minimax pogled | Uskladi Status/API stanje z živim Minimaxom in pokaže razliko |
| ODDANO sync | Če je osnutek v Minimaxu zbrisan, lokalna sled ODDANO se počisti |
| Listina | Pred ustvarjanjem preveri, da se vezna številka v Minimaxu ne podvoji |
| Filter obdobja | Mesec/leto + datum od/do filtrira tabele, DDV-O, JSON in Minimax |

## CLI primeri

```text
py convert_KIrKpr_to_minimax.py vhod.zip --validate
py convert_KIrKpr_to_minimax.py vhod.zip --validate --summary-json povzetek.json
py convert_KIrKpr_to_minimax.py vhod.zip --dry-run
py convert_KIrKpr_to_minimax.py vhod.zip --output C:\Izhod
```

## Playwright

Vgrajen paket `kirkpr_minimax_pw` (brez odvisnosti od map Fakturiranje*).
Profil Chromium: `%LOCALAPPDATA%\MinimaxBlagajna\PlaywrightProfile`

## Konfiguracija

Lokalna datoteka v tej mapi:

`convert_KIrKpr_to_minimax_config.json`

Gesla in `client_secret` se še vedno berejo iz zunanje datoteke `D:\\PISARNA\\Python\\DavčnaBlagajna_5.1\\blagajna_minimax_settings.json` — tukaj se ne kopirajo.
