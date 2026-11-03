# Shopping image search and voice input

Both bonuses reuse `GEMINI_API_KEY` and `GEMINI_MODEL`. No extra API key, service,
training or required local `.env` file is needed. Set the existing key through
Render Environment Variables. BuyWhere must be the configured Shopping provider
(`auto` or `buywhere`) for visual search. No deployment is performed by this change.

Use the image icon in the composer to upload JPEG, PNG or WebP (maximum 4 MiB).
Gemini returns a proposed keyword query, visible attributes and an estimated
confidence. Review/edit the query and click **Search products**. The existing chat
router, BuyWhere service, filters, history and carousel handle the search. Low
confidence and non-product images ask for confirmation or a product name. Matches
are similar offers; exact identity, inventory and availability remain unverified.

Use the microphone icon over HTTPS (localhost also works). MediaRecorder captures
audio; Web Audio measures RMS energy and stops after 1.5 seconds of silence after
speech, 7 seconds without speech, or 30 seconds total. The button can stop manually;
Cancel discards recording. Tracks are stopped when processing, cancelling or leaving
the page. These are lightweight energy-based VAD thresholds, not a trained model;
background noise can affect detection. Silence does not call Gemini.

Gemini transcribes AZ/EN/RU and mixed speech without translating. Recognized text is
inserted into the message box for editing; it is never sent as a chat message until
the user presses Send. It then uses existing language detection, routing and state.
WebM/Ogg capture is sent inline; browsers recording MP4 use Web Audio to convert to
16 kHz mono WAV locally. No server-side transcoder is required.

The raw-byte endpoints are `/api/shopping/visual` and `/api/media/transcribe`, with
optional `session_id` query parameter and an accurate Content-Type. Size/signature
checks, same-origin checks, existing browser rate limits and session ownership apply.
Audio uploads are limited to 6 MiB; four media requests may run concurrently. Upload
reads time out after 10 seconds, Gemini uses a maximum 20-second SDK timeout and a
25-second response wait, and browser requests time out after 30 seconds. SDK retries
are disabled to avoid duplicate media inference. Errors and quota failures are
sanitized. Uploads are not written to disk or chat history; submitted text still uses
normal conversation history. Existing Gemini usage/quota applies.

The implementation uses Google's official
[image understanding](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding)
and [audio understanding](https://ai.google.dev/gemini-api/docs/generate-content/audio)
interfaces with inline bytes and structured JSON, through the installed SDK.

Focused checks: `python -m pytest tests/test_media_bonuses.py -q` and
`node --test tests/media_bonuses.test.cjs`. Endpoint/UI checks use controlled Gemini
responses and provider fixtures. Actual Gemini inference and physical microphone
permissions must also be checked in a keyed HTTPS environment; the current local
workspace has no Gemini API key. These checks do not start a browser.
