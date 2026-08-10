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

**Oorzaak (serverzijdig bevestigd, reproductie: `null` → 200, `""` → 500, `"null"` → 500):** de server zocht het gesprek nooit op. Validatie werkte en gaf een 422; het *opstellen* van die 422 crashte. `exc.errors()` bevat het oorspronkelijke `ValueError`-object, `JSONResponse` kan dat niet serialiseren, en de resulterende `TypeError` ontsnapte uit de except-tak en werd een generieke 500.

Dit was dus niet specifiek voor `conversation_id`: élke afgekeurde invoer op `/api/chat` gaf 500 "unexpected error" in plaats van te zeggen welk veld fout was.

**Oplossing (PR #256):**
1. De foutdetails worden zonder het contextobject opgebouwd, zodat een afgekeurd veld een echte 422 met bruikbare details geeft.
2. Een leeg of whitespace-`conversation_id` wordt gelezen als "nog geen gesprek" en start een nieuw gesprek — dit was aanbeveling 1 hieronder.

De letterlijke tekst `"null"` geeft nog steeds 422. Daar stilletjes een nieuw gesprek starten zou de draad elke beurt kwijtraken en eruitzien als een model dat vergeet.

**Nog te doen in n8n:** een opslagmechanisme (bijv. workflow static data, een database- of key/value-node) dat `conversation_id` per Discord-kanaal/thread bijhoudt. Het veld mag nu altijd worden meegestuurd, ook leeg.
**Status:** Serverzijdig opgelost. Gesprekscontinuïteit per Discord-kanaal staat nog open aan de n8n-kant.

## Overige observaties
- De HTTP Request node reageerde traag/bleef "wachten op Test URL" wanneer de node los werd uitgevoerd zonder gebruik te maken van "Debug in editor" met bestaande executiedata — geen bug, maar wel een aandachtspunt voor testen.
- Response Format van de HTTP Request node moet op "Text" staan (niet JSON), omdat `/api/chat` een Server-Sent-Events-stream teruggeeft in plaats van een enkel JSON-object.
