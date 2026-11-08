# VozKovo Backend

Cloudflare Workers backend for the VozKovo frontend.

## Architecture

- Cloudflare Workers handles the HTTP API.
- Workers AI uses Deepgram Aura-2 Spanish and English TTS models.
- KV stores short-lived job status.
- R2 stores generated MP3 files temporarily.

## Required setup

1. Install dependencies with `npm install`.
2. Create a KV namespace and replace the placeholder ID in `wrangler.jsonc`.
3. Create an R2 bucket named `vozkovo-audio`.
4. Enable Workers AI for the account.
5. Set the frontend origin in CORS before production use (currently permissive for initial testing).
6. Run `npm run dev` or deploy with `npm run deploy`.

## API

- `GET /api/health`
- `GET /api/voices`
- `POST /api/generate` — JSON: `{ "text": "...", "voice": "es-ES-alvaro", "rate": 0 }`
- `GET /api/jobs/:job_id`
- `GET /api/jobs/:job_id/download`

## Current limitations

- This is a Cloudflare-native TTS implementation, not a port of the old Python `edge-tts` backend.
- Spanish and English Aura-2 voices are included.
- Current model input limit is 10,000 characters per request.
- MP3 joining for multi-chunk output and pause-marker audio insertion are not implemented yet.
- Workers AI speech generation is usage-priced; check current account pricing and limits before public launch.
- The current worker performs generation in the request before returning the job ID. For long requests, move synthesis to a Cloudflare Queues consumer and return the job immediately.

## References

- Cloudflare Workers AI Aura-2 Spanish and English model docs.
