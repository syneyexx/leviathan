# Windows host test — HADES spraak

Fysieke audio is **niet** geverifieerd in de cloud-agentomgeving. Voer dit uit op de Windows-host.

## Voorbereiding

1. Start HADES (`HADES.bat`).
2. Instellingen → Spraak → Installatie / modellen.
3. Bevestig status: ffmpeg OK, ASR ready, TTS ready.

## Scenario’s (acceptatie)

| # | Scenario | Verwacht | Automatiseerbaar zonder hardware |
|---|---|---|---|
| 1 | Dictatie → tekst aanpassen → verzenden | Composer vult; geen auto-send | Deels (contracts + hooks) |
| 2 | Typen + gesproken antwoorden aan | Alleen eindantwoord hoorbaar | Deels (speakable + speak API) |
| 3 | Spraakgesprek ≥3 beurten | Zelfde conversation-id; berichten in chat | Nee (echte mic) |
| 4 | Onderbreken tijdens spreken | Audio stopt ≤250 ms na detectie; correctie als nieuw bericht | Deels (queue stop-ms boekhouding); ≤250 ms host |
| 5 | Stop spreken | Tekstantwoord blijft | Ja (PlaybackQueue/unit) |
| 6 | Opnieuw afspelen | Geen nieuwe modelrun | Ja (force_replay / replay hook) |
| 7 | Gesproken antwoorden uit, dictatie aan | Alleen transcriptie | Deels (contracts) |
| 8 | Stem/tempo wijzigen | Hoorbaar verschil | Deels (settings wiring + TTS speed API) |
| 9 | Microfoon geweigerd | Typen blijft werken | Ja (fake MediaStream NotAllowedError) |
| 10 | Sesssie sluiten | Tracks gestopt (browser-indicator) | Ja (fake stream track.stop) |
| 11 | Tab reconnect | Geen dubbele berichten/oude audio; mic niet stil herstart | Ja (session unit/API) |
| 12 | Airplane mode na install | Gesprek lokaal | Host |
| 13 | Spraak→taak plakpad | Ongewijzigd | Ja |
| 14 | Wake word aan/uit | Herkent “Hades” alleen wanneer aan | Deels (probe API + synthesized keyword) |

## Hardware

- [ ] Hoofdtelefoon (echo/barge-in)
- [ ] Luidsprekers (echo-onderdrukking / false trigger)
- [ ] Apparaatwisseling tijdens sessie
- [ ] CPU-only pad
- [ ] CUDA-pad (indien aanwezig)

## Metingen

Vul `METRICS.md` in. Onbekend = `unknown`.
