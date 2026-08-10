# n8n → LocalChat → Discord: werkende opzet

## Doel
Discord-berichten via een n8n-webhook doorsturen naar de LocalChat API (`/api/chat`), de streaming-SSE-respons parsen, en het antwoord terugsturen naar Discord.

## Workflow-opbouw
Webhook (Discord) → HTTP Request (LocalChat API) → Code (JavaScript, SSE-parser) → Send a message (Discord)

## Belangrijk inzicht: de respons is SSE, geen JSON
`/api/chat` streamt tekstregels in het formaat:

    data: {"content": "..."}
    data: {"done": true, "conversation_id": "...", "message_id": ..., "sources": [...]}

Als de HTTP Request node op JSON-respons staat, crasht de node. Oplossing: zet in de node onder **Options → Response → Response Format** de waarde op **Text**, met **Put Output in Field** op `data`.

## Stap 1 — Credential (Header Auth)
In n8n: Credentials → New → Header Auth
- Name (header): `Authorization`
- Value: `Bearer <jouw-lcw_-key>` (met het woord "Bearer" ervoor)

Alternatief is de header `X-API-Key` met alleen de key als waarde.

## Stap 2 — HTTP Request node
- Method: POST
- URL: interne LocalChat-URL (bijv. `http://localchat-app-1:5000/api/chat`)
- Authentication: Generic Credential Type → Header Auth → bovenstaand credential
- Send Body: aan, JSON:

    {
      "message": "={{ $json.body.content }}",
      "use_rag": true
    }

- Options → Response → Response Format: Text
- Options → Response → Put Output in Field: data
- Options → Timeout: 120000 (eerste antwoord kan traag zijn doordat het model moet laden)

**Let op:** stuur geen `X-Workspace-ID` header mee. De API-key legt zijn eigen workspace al vast en dat wint sowieso — de header zorgde in onze opzet voor conflicten.

**Let op 2:** `conversation_id` in de body gaf eerder een 500-fout zodra de waarde leeg/null was. Dat is serverzijdig opgelost (zie bugrapport); een leeg veld start nu gewoon een nieuw gesprek. Je mag het dus altijd meesturen:

    {
      "message": "={{ $json.body.content }}",
      "use_rag": true,
      "conversation_id": "={{ $json.conversation_id }}"
    }

## Stap 3 — Code-node om de SSE-stream te parsen

    const raw = $input.first().json.data;
    let answer = '';
    let done = null;
    for (const line of raw.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      const p = JSON.parse(line.slice(6));
      if (p.error) throw new Error(p.message);
      if (p.content) answer += p.content;
      if (p.done) done = p;
    }
    return [{ json: {
      answer,
      conversation_id: done?.conversation_id,
      sources: (done?.sources || []).map(s => s.filename),
    }}];

## Stap 4 — Terug naar Discord
Stuur `answer` terug naar het kanaal. Let op de Discord-limiet van 2000 tekens (knip/kort in indien nodig). `sources` kan als voetnoot met bestandsnamen worden meegestuurd.

## Veelvoorkomende valkuilen
- `localhost` werkt niet als n8n in een Docker-container draait — dat verwijst dan naar de n8n-container zelf, niet naar de LocalChat-app. Gebruik `http://host.docker.internal:5000` of het interne compose-netwerkadres (bijv. `http://app:5000` of `http://localchat-app-1:5000`).
- Geheugen per gesprek werkt serverzijdig, maar n8n moet de `conversation_id` uit het antwoord zelf bewaren per Discord-kanaal/thread en de volgende keer meesturen — zie bugrapport.
- Test HTTP Request/Code-nodes met "Debug in editor" op een bestaande (gefaalde) executie om snel te itereren zonder een echt Discord-bericht te hoeven sturen.
