# HADES v0.4.1 — Plugin Manager & Runtime

Deze release wijzigt uitsluitend de Plugin Manager/runtime, de Plugins-pagina, de noodzakelijke bot-toolrouter en hun tests/documentatie. De bestaande HADES GUI-stijl, navigatie en overige functionele domeinen zijn behouden.

## Opgelost

- Iedere geregistreerde plugin-tool is vanaf de Plugins-pagina aanklikbaar en handmatig uitvoerbaar.
- JSON Schema-properties worden als invoervelden getoond; het volledige JSON-object blijft direct bewerkbaar.
- Handmatige tool-runs sturen een expliciete, eenmalige gebruikersgoedkeuring mee. Een API-call zonder die goedkeuring krijgt HTTP 428 en wordt persistent vastgelegd.
- Globale `block`-rechten blijven leidend, ook na handmatige goedkeuring. Geblokkeerde calls worden niet uitgevoerd en krijgen HTTP 403 plus een persistent `blocked` toolcall-record.
- Autonome selectie gebruikt alleen enabled, Ready en `autonomous=true` plugins. `ask` wordt niet meer stilzwijgend als goedgekeurd behandeld.
- Autonome toolfouten worden als gestructureerd failed/blocked resultaat teruggegeven aan de bot. De bot kan daarna gecontroleerd antwoorden of een andere tool kiezen.
- Toolresultaten bewaren afzonderlijk stdout, stderr, exitcode, duur, status, fout, start/eindtijd, herkomst (`manual`, `autonomous`, `install`) en approval-status in SQLite.
- De Plugins-pagina toont het actuele resultaat en de persistente toolcallhistorie.
- Pluginnaamregels tonen categorie plus maximaal twee aanvullende labels.

## Echte service-lifecycle

- `start`, `serve` en `dev` worden als service-acties niet-blokkerend gestart.
- Service-stdout en -stderr worden persistent opgeslagen onder de plugin-runtime.
- `start` vereist een expliciete healthcheck en wordt pas succesvol na een bereikbare HTTP-, TCP- of command-check.
- Een gestart of met exitcode 0 afgesloten wrapperproces is op zichzelf nooit bewijs dat de service gezond is.
- Een mislukte start beëindigt een nog lopend beheerd proces en zet health op `unhealthy`.
- `health` en `status` kunnen een manifest-healthcheck uitvoeren zonder apart subprocesscommando.
- `logs` kan zonder commando de persistente servicelogs uitlezen.
- `stop` verifieert dat de healthcheck niet meer bereikbaar is, of vereist bewijs dat HADES zelf het beheerde proces heeft beëindigd.
- Gewone succesvolle CLI-tools krijgen `operational`, niet ten onrechte `healthy`.

## Dependencies en subprocessveiligheid

- Dependency-installatie blijft standaard onderdeel van import/conversie en gebruikt plugin-lokale runtimes.
- Dependency-uitvoer en fouten worden als persistente `__dependencies__` toolcall opgeslagen.
- Een dependency-fout laat de plugin disabled en `needs_review`, met de echte fout in `last_error`.
- Node-projectdetectie registreert alle aanwezige npm-scripts, waaronder `health`, `status`, `logs`, `start`, `stop` en `build` wanneer het project die levert.
- Manifestcommands ondersteunen argv-arrays. Legacy command-strings worden eenmalig geparseerd en altijd met `shell=False` uitgevoerd.
- JSON-input wordt tegen het meegeleverde schema gecontroleerd en placeholders worden uitsluitend naar afzonderlijke argv-waarden uitgebreid.

## Manifestvoorbeeld voor een service

```json
{
  "format": 1,
  "id": "example-service",
  "name": "Example Service",
  "version": "1.0.0",
  "runtime_type": "python",
  "category": "Service",
  "labels": ["local", "api"],
  "permissions": ["subprocess"],
  "autonomous": true,
  "healthcheck": {
    "type": "http",
    "url": "http://127.0.0.1:8765/health",
    "expected_status": [200],
    "timeout_seconds": 20
  },
  "tools": [
    {
      "name": "start",
      "action": "start",
      "mode": "service",
      "command": ["{python}", "service.py"],
      "input_schema": {"type": "object", "properties": {}}
    },
    {"name": "health", "action": "health", "command": "", "input_schema": {"type": "object", "properties": {}}},
    {"name": "logs", "action": "logs", "command": "", "input_schema": {"type": "object", "properties": {}}},
    {"name": "stop", "action": "stop", "command": "", "input_schema": {"type": "object", "properties": {}}}
  ]
}
```

## Verificatie

- TypeScript typecheck: PASS.
- Vite production build: PASS.
- Frontend source/componenttests: 10/10 PASS.
- Backend unittest-suite: 27/27 PASS.
- Python compileall: PASS.
- Extra regressiedekking: handmatige invoke, ontbrekende approval, autonome invoke, autonome toolfailure naar bot, failed healthcheck, volledige service-lifecycle, permission block, dependency failure en shell-injectionpayload.

## Bewuste grens

Pluginpermissions zijn application-level beleid en geen OS-container/sandbox. Een plugin die subprocess-toegang krijgt, draait onder het account waarmee HADES is gestart. Gebruik alleen vertrouwde broncode of voeg later een echte container-/job-sandbox toe.
