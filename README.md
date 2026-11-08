# VozKovo Backend

Cloudflare Workers API and speech engine for the VozKovo frontend.

## What it provides

- One central voice catalogue shared by the website and API.
- 10 verified Spanish voices and 37 verified English voices (47 total).
- Deepgram Aura-2 through Cloudflare Workers AI.
- MP3 generation, temporary job status and audio downloads.
- A public JSON catalogue route at `/vozes`, with aliases at `/voices` and `/api/voices`.
- API stays disabled by default until you explicitly enable it.

## Cloudflare setup

1. Install dependencies: `npm install`.
2. Create a Workers KV namespace and replace `REPLACE_WITH_KV_NAMESPACE_ID` in `wrangler.jsonc`.
3. Create an R2 bucket named `vozkovo-audio`.
4. Enable Workers AI for your Cloudflare account.
5. Keep `API_ENABLED` set to `false` while preparing the service.
6. When you decide to make it public, set `API_ENABLED` to `true` in Cloudflare Worker variables and deploy.
7. Set `ALLOWED_ORIGINS` to the exact frontend origin(s), comma-separated. Use `*` only for intentional public access.
8. Deploy with `npm run deploy`.

## API routes

- `GET /api/health` — service status; does not expose the voice catalogue.
- `GET /vozes` — public JSON voice catalogue.
- `GET /voices` and `GET /api/voices` — aliases used by integrations.
- `POST /api/generate` — JSON body: `{ "text": "...", "voice": "es-ES-alvaro" }`.
- `GET /api/jobs/:job_id` — generation status.
- `GET /api/jobs/:job_id/download` — MP3 download.

Example catalogue URL after deployment and activation:

```
https://YOUR-WORKER-DOMAIN/vozes
```

## Voice catalogue

The catalogue is defined once in `src/index.js`; the frontend loads it from `/api/voices` at runtime. Do not maintain a second hard-coded frontend voice list.

The catalogue uses only the speaker names documented by Cloudflare for Aura-2:
- Spanish: Sirio, Néstor, Carina, Celeste, Álvaro, Diana, Aquila, Selena, Estrella and Javier.
- English: Amalthea, Andromeda, Apollo, Arcas, Aries, Asteria, Athena, Atlas, Aurora, Callista, Cora, Cordelia, Delia, Draco, Electra, Harmonia, Helena, Hera, Hermes, Hyperion, Iris, Janus, Juno, Jupiter, Luna, Mars, Minerva, Neptune, Odysseus, Ophelia, Orion, Orpheus, Pandora, Phoebe, Pluto, Saturn, Thalia, Theia, Vesta and Zeus.

## Current limits

- Maximum input is 10,000 characters per generation.
- Pause markers are not supported yet.
- The current model does not accept a speech-rate parameter; the frontend speed control is not applied to generated MP3 files yet.
- Long text is split into model-sized chunks and MP3 byte streams are concatenated. Test long outputs with your target browsers before public launch.
- Aura-2 pricing is listed by Cloudflare at $0.03 per 1,000 characters. This is usage-priced, not unlimited or guaranteed free.
- Configure an R2 lifecycle rule to delete old MP3 objects; job metadata expires after one hour.

## Official model references

- [Aura-2 Spanish](https://developers.cloudflare.com/workers-ai/models/aura-2-es/)
- [Aura-2 English](https://developers.cloudflare.com/workers-ai/models/aura-2-en/)
