# HADES Spraakmodus — eerste gesprek

Lokale microfoon-ASR (faster-whisper) en stemuitvoer (Piper), geïntegreerd in Chat.  
**Blijft apart van** Spraak→taak (plak/`/voice`), `local-stt-paste` en VoiceStudio.

Transcripties zijn **final-only** (complete utterance na VAD/PTT); geen streaming partial MediaRecorder-chunks.

## Eerste keer

1. Open **Instellingen → Spraak**.
2. Klik **Installatie / modellen** (downloadt Python-deps, Whisper-model, Nederlandse Piper-stem). Vereist netwerk alleen tijdens installatie.
3. **Test microfoon** en **Test stem**.
4. Optioneel: doorloop de setup-wizard.
5. Ga naar **Chat**.

## Drie gebruiksvormen

| Modus | Hoe |
|---|---|
| **Dicteren** | Knop **Dictatie** (of ingedrukt houden). Transcriptie verschijnt in het tekstvak; pas aan en verstuur zelf. |
| **Gesproken antwoorden** | Zet de schakelaar aan. Typ of dicteer; het **definitieve** antwoord wordt voorgelezen (niet de voorlopige streamtekst). |
| **Spraakgesprek** | Start **Spraakgesprek**. Spreek beurten; HADES antwoordt in dezelfde chat. **Stop spreken** / onderbreken stopt audio snel. |

## Belangrijk

- Microfoon start alleen na een bewuste klik.
- Gesproken antwoorden en dicteren zijn onafhankelijk in te stellen.
- Zonder microfoontoestemming blijft tekstchat werken.
- Na modelinstallatie werkt de lokale route offline.
- Activatiewoord “Hades” staat standaard **uit** (Instellingen → Spraak).

Zie ook `HOST_TEST.md` voor Windows-hardwareverificatie.
