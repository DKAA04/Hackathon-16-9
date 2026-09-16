# DuckDuckGov · AI phone call (ElevenLabs + Twilio)

Every call goes to `CALL_TEST_NUMBER` (+32489816582), never to the business.

## 1. Twilio
1. Create an account and buy a voice number (US numbers are instant; Belgian numbers need a regulatory bundle).
2. Trial account: add +32489816582 under *Phone Numbers → Verified Caller IDs*.
3. *Voice → Settings → Geographic permissions*: allow Belgium.

## 2. ElevenLabs agent (Agents → Create agent, blank)
- Language: Dutch. Pick a Flemish-sounding voice.
- **First message:**
  > Goeiedag, u spreekt met de digitale assistent van de dienst lokale economie van Schoten. Ik ben een AI-assistent en dit gesprek wordt opgenomen om onze gegevens te controleren. Spreek ik met {{business_name}}?
- **System prompt:**
  > Je belt namens de dienst lokale economie van Schoten om registergegevens te controleren van {{business_name}}, geregistreerd op {{address}}. Wees beleefd en kort, spreek Nederlands (Vlaams).
  > Vraag, één voor één:
  > 1. Is de zaak nog actief op dit adres? Zo niet, sinds wanneer?
  > 2. Wie is de beste contactpersoon voor de gemeente?
  > 3. Op welk e-mailadres en telefoonnummer mogen we de zaak bereiken? Herhaal het e-mailadres letter per letter ter controle.
  > 4. Extra vraag van de medewerker: {{officer_note}} (sla over als dit "geen extra vraag" is).
  > Geef nooit advies over regels of vergunningen: zeg dat een medewerker terugbelt. Wil de persoon niet meer gebeld worden, noteer dat en rond af.
  > Sluit af met: "Dank u. Een medewerker controleert dit voordat er iets wordt aangepast."
- **Analysis → Data collection** (all strings): `actief` (ja/nee/onduidelijk), `sinds_wanneer`, `contactpersoon`, `email`, `telefoon`, `extra_antwoord`, `niet_meer_bellen` (ja/nee).
- **Phone Numbers → Import from Twilio** (Account SID + Auth Token): assign this agent and copy the phone number ID.
- **API keys:** create a key with access to agents (ElevenAgents / Conversational AI).

## 3. backend/.env
```
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_PHONE_NUMBER_ID=...
CALL_TEST_NUMBER=+32489816582
```
Restart the backend. `GET /api/health` then shows `"calls_configured": true`.

## API
- `POST /api/businesses/{id}/call`, body `{"note": "..."}` → `{"status": "started", "conversation_id", "to_number"}`. Returns 503 `CALLS_NOT_CONFIGURED` when the settings above are missing.
- `GET /api/calls/{conversation_id}` → `{"status": "initiated|in-progress|processing|done|failed", "summary", "collected": {...}, "transcript": [...]}`.
