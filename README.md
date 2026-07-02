# Afslutning af borgere i genoptræning (SUL § 140)

Robotten afslutter borgeres genoptræningsforløb i KMD Nexus under SUL § 140, når fagpersoner har registreret en afslutning via en aktivitetsliste.

## Hvad gør robotten?

1. Henter aktivitetslisten "Robot - afslut genoptræningsforløb SUL § 140" fra KMD Nexus og filtrerer aktive poster fra de seneste 7 dage.
2. Tilføjer nye aktiviteter til arbejdskøen og springer allerede køede poster og poster tilhørende "Myndighed genoptræning" over.
3. Slår borgeren op i Nexus via CPR-nummer.
4. Kontrollerer om borgeren er udenbys borger — er det tilfældet, oprettes en opgave i Nexus og borgeren springes over.
5. Kontrollerer om der er flere aktive genoptræningshenvisningsskemaer — er det tilfældet, oprettes en opgave til leverandøren og borgeren springes over.
6. Kontrollerer om der er aktive hjælpemidler og opretter i så fald opfølgningsopgaver til leverandøren.
7. Fjerner relationer og deaktiverer genoptræningsrelaterede tilstande (Tilstandsgruppe.GENOPTRÆNING).
8. Lukker aktive indsatser i genoptræningsforløbet.
9. Lukker aktive skemaer og sletter tilknyttede aktiviteter.
10. Fjerner tildelte medarbejdere fra genoptræningsforløbet.
11. Lukker genoptræningsforløbet i Nexus.
12. Lukker forløbsindplacering, hvis borgeren ikke har andre aktive hovedforløb (f.eks. Helhedspleje, Pleje/omsorg/træning, Sygepleje, Dagcenter, Kommunal tandpleje eller Plejebolig/Ældrebolig).
13. Fjerner organisationstilknytningen mellem borgeren og leverandøren.
14. Lukker Nexus-opgaven og registrerer gennemførelse i Odense SQL Server.

## Forudsætninger

- Python ≥ 3.13
- [`uv`](https://docs.astral.sh/uv/) til pakkehåndtering
- Adgang til **Automation Server** (arbejdskø)
- Adgang til **KMD Nexus** (produktion)
- Adgang til **Odense SQL Server**

## Installation

```sh
uv sync
```

## Konfiguration

Credentials registreres i Automation Server:
- `KMD Nexus - produktion`
- `Odense SQL Server`

| Miljøvariabel | Beskrivelse |
|---|---|
| `ATS_URL` | URL til Automation Server API |
| `ATS_TOKEN` | Bearer token til Automation Server |
| `ATS_WORKQUEUE_OVERRIDE` | Tilsidesæt arbejdskø-ID (valgfrit) |

## Kørsel

```sh
uv run python main.py --queue   # Fyld arbejdskøen
uv run python main.py           # Behandl arbejdskøen
```

## Afhængigheder

| Pakke | Formål |
|---|---|
| `automation-server-client` | Klient til Odense RPA Automation Server (arbejdskøer, credentials) |
| `odk-tools` | Fejlrapportering og registrering af gennemførelse i Odense SQL Server |
| `kmd-nexus-client` | Læsning og opdatering af borgersager i KMD Nexus |
| `openpyxl` | Excel-filhåndtering |
| `ruff` | Python-linter til kodekvalitet |

## GDPR og sikkerhed

Processen behandler borgernes CPR-numre for at slå dem op og opdatere deres sundhedsdata i KMD Nexus. Det omfatter genoptræningsplaner, indsatser, tilstande, hjælpemidler og organisationstilknytninger. Ingen personoplysninger gemmes uden for KMD Nexus og Odense SQL Server. Adgang til fejlrapporter og logning bør begrænses til relevante medarbejdere.
