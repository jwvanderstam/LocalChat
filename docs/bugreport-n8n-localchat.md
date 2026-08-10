# Bugrapport: n8n LocalChat-Discord integratie

## Samenvatting
Bij het opzetten van de n8n-workflow die Discord-berichten doorstuurt naar de LocalChat API zijn drie problemen gevonden en (deels) opgelost.

## Issue 1 — 401 Authorization failed: "Authentication required"
**Symptoom:** HTTP Request node gaf `Authorization failed - please check your credentials` / `Authentication required`.
**Oorzaak:** Authentication stond op "None" en er werd een overbodige `X-Workspace-ID` header meegestuurd in plaats van een geldige Authorization-header.
**Oplossing:** Authentication ingesteld op Generic Credential Type → Header Auth, met header `Authorization: Bearer <key>`. De `X-Workspace-ID` header verwijderd.
**Status:** Opgelost.

## Issue 2 — 401 Authorization failed: "Invalid or revoked API key"
**Symptoom:** Na het toevoegen van de Header Auth credential veranderde de foutmelding naar "Invalid or revoked API key".
**Oorzaak:** De eerst ingevulde API-key was ongeldig/verlopen.
**Oplossing:** Nieuwe API-key gegenereerd in LocalChat en met het `Bearer `-voorvoegsel opgeslagen in het credential.
**Status:** Opgelost.

## Issue 3 — 500 InternalServerError bij meesturen van conversation_id
**Symptoom:** Zodra de body een `conversation_id`-veld bevatte (bedoeld om `null`/leeg te zijn bij een nieuw gesprek), antwoordde de API met:

    { "success": false, "error": "InternalServerError", "message": "An unexpected error occurred" }

**Oorzaak (vermoeden, niet serverzijdig bevestigd):** De API lijkt een lege string of de letterlijke tekst "null" als `conversation_id` niet netjes af te handelen — mogelijk probeert de server dit als bestaand gesprek op te zoeken en faalt daarop, in plaats van een nieuw gesprek te starten.
**Tijdelijke workaround:** Het `conversation_id`-veld volledig weglaten uit de request body wanneer er nog geen eerder gesprek is. De node stuurt nu alleen `message` en `use_rag`.
**Aanbevolen structurele oplossing (nog niet geïmplementeerd):**
1. Valideer serverzijdig dat een ontbrekende/lege/`null` `conversation_id` altijd een nieuw gesprek start zonder 500-fout.
2. Implementeer in n8n een opslagmechanisme (bijv. workflow static data, een database- of key/value-node) dat `conversation_id` per Discord-kanaal/thread bijhoudt, en stuur het veld alleen mee wanneer er al een waarde bekend is.
**Status:** Open — workaround actief, structurele fix nodig voor gesprekscontinuïteit (geheugen) per Discord-kanaal.

## Overige observaties
- De HTTP Request node reageerde traag/bleef "wachten op Test URL" wanneer de node los werd uitgevoerd zonder gebruik te maken van "Debug in editor" met bestaande executiedata — geen bug, maar wel een aandachtspunt voor testen.
- Response Format van de HTTP Request node moet op "Text" staan (niet JSON), omdat `/api/chat` een Server-Sent-Events-stream teruggeeft in plaats van een enkel JSON-object.
