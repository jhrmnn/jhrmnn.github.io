# Self-hosted ActivityPub on Cloudflare Workers

A single-actor ActivityPub server for `hrmnn.net`. The site owns its Fediverse
presence directly — it is not bridged via Bridgy Fed. The Worker serves the
static site (Workers Static Assets) and the federation endpoints from one origin.

## What it does

- **Discoverable** — `/.well-known/webfinger` + `/ap/actor` (a `Person` with the
  RSA public key) make `@hrmnn.net@hrmnn.net` resolvable.
- **Followable** — `POST /ap/inbox` verifies the HTTP signature, stores the
  follower in KV, and returns a signed `Accept`. `Undo` removes them.
- **Delivers posts** — `POST /ap/admin/deliver` (called by the `federate-native`
  CI job) stores each Note and fans a signed `Create`/`Update` out to followers.

Files: `index.ts` (router), `activitypub.ts` (webfinger/actor/collections/notes),
`inbox.ts` (Follow/Undo + Accept), `deliver.ts` (admin fan-out),
`httpsig.ts` + `keys.ts` (HTTP Signatures over WebCrypto, no external library).

## One-time setup (owner)

1. **Keypair** (already generated; never commit `ap_private.pem`):
   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out ap_private.pem
   openssl rsa -in ap_private.pem -pubout -out ap_public.pem
   openssl rand -hex 32   # AP_ADMIN_TOKEN
   ```
2. **Public key** → paste `ap_public.pem` contents into `AP_PUBLIC_KEY` in
   `wrangler.toml` (it is public; committed on purpose).
3. **KV namespace** → create one (dashboard, or `wrangler kv namespace create FEDI`)
   and put its id into `wrangler.toml` (`kv_namespaces[0].id`).
4. **Deploy** → merge to `main`; the `deploy-worker` CI job runs `wrangler deploy`.
   Needs the existing `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` repo secrets.
5. **Secrets** (after the Worker exists) → dashboard → Workers & Pages → the
   Worker → Settings → Variables and Secrets → Add → type **Secret**:
   - `AP_PRIVATE_KEY` — paste `ap_private.pem` (multi-line ok; base64 of it also
     works — the loader accepts both).
   - `AP_ADMIN_TOKEN` — the hex from step 1. Add the **same value** as a GitHub
     repo secret `AP_ADMIN_TOKEN` so `federate-native` can call the endpoint.
6. **Custom domain / DNS** (owner, on Fastmail/Cloudflare) → point
   `hrmnn.net` at the Worker. This requires the domain to be a Cloudflare
   zone (Workers custom domains/routes need the zone on Cloudflare). Until then,
   the Worker is live at its `*.workers.dev` URL — set the repo variable
   `AP_BASE_URL` to that origin to test delivery before the cutover.

## Verify

```bash
curl "https://hrmnn.net/.well-known/webfinger?resource=acct:hrmnn.net@hrmnn.net"
curl -H 'accept: application/activity+json' https://hrmnn.net/ap/actor
```

From a Mastodon account, search `@hrmnn.net@hrmnn.net` and Follow;
`wrangler tail` should show the signature verifying and the `Accept` going out,
and `/ap/followers` `totalItems` should increment. Push a test post and confirm it
lands in the follower's timeline and is dereferenceable at `/ap/notes/<slug>`.

## Transition / cutover

Only the **hosting** is transitional: the Worker deploys alongside the existing
GitHub Pages deploy, and production flips when DNS points `hrmnn.net` at the
Worker. Once the native actor is verified and DNS is cut over:

- remove `continue-on-error` from `deploy-worker`,
- delete the `deploy-github` and `deploy-cloudflare` (Pages preview) jobs.

Federation itself has no parallel path to unwind: the site was migrated to
`hrmnn.net` and never bridged via Bridgy Fed, so there are no bridged followers to
migrate — the self-hosted actor is the only Fediverse identity from the start.

## Out of MWE scope

Inbound rendering of replies/likes; delivery retries (Queues/Durable Objects);
paged outbox history; D1.
