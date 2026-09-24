# DuckDuckGov — AI test calls

This prototype integrates ElevenLabs and Twilio for controlled demonstrations. Every call is routed to `CALL_TEST_NUMBER`, not the business record’s phone number. Use a number you control and participants who know this is a test. DuckDuckGov is not an official municipal service.

## Configuration

Configure a voice-enabled Twilio number and an ElevenLabs conversational agent, then import the Twilio number into ElevenLabs and associate it with the agent. Keep account credentials in the provider dashboards and the ignored local environment file.

```dotenv
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
ELEVENLABS_PHONE_NUMBER_ID=
CALL_TEST_NUMBER=
```

Set `CALL_TEST_NUMBER` locally to your controlled test number in international format. Restart the backend. `GET /api/health` reports `calls_configured: true` when all four settings are present. Leaving the test number empty disables calls.

## Demonstration agent

Use Dutch for the existing interface. Clearly introduce the agent as a demonstration, for example:

> Hallo, dit is een testgesprek van de DuckDuckGov-demo. Ik ben een AI-assistent. We gebruiken fictieve bedrijfsgegevens om de toepassing te testen. Wilt u deelnemen aan deze test?

Use synthetic `business_name`, `address` and `officer_note` values. Ask short questions about the fictional business and stop if the participant declines. Do not claim to represent a municipality. If recording is enabled, inform the participant before recording and obtain any required consent.

The integration expects these analysis fields as strings: `actief`, `sinds_wanneer`, `contactpersoon`, `email`, `telefoon`, `extra_antwoord`, `niet_meer_bellen`. Do not commit real transcripts, recordings or collected contact information.

## API

- `POST /api/businesses/{id}/call` accepts a body such as `{ "note": "Synthetic test" }`. A successful start returns status, conversation ID and destination number. Missing configuration returns `503 CALLS_NOT_CONFIGURED`.
- `GET /api/calls/{conversation_id}` retrieves status, summary, collected fields and transcript.

External calls can incur provider charges. Review access controls and retention before considering use beyond a controlled local demonstration.
