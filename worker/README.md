# Self-hosted ActivityPub on Cloudflare Workers

A single-actor ActivityPub server for `jan.hermann.name`, replacing Bridgy Fed.
The Worker serves the static site (Workers Static Assets) and the federation
endpoints from one origin.

## What it does

- **Discoverable** — `/.well-known/webfinger` + `/ap/actor` (a `Person` with the
  RSA public key) make `@jan.hermann.name@jan.hermann.name` resolvable.
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
   `jan.hermann.name` at the Worker. This requires the domain to be a Cloudflare
   zone (Workers custom domains/routes need the zone on Cloudflare). Until then,
   the Worker is live at its `*.workers.dev` URL — set the repo variable
   `AP_BASE_URL` to that origin to test delivery before the cutover.

## Verify

```bash
curl "https://jan.hermann.name/.well-known/webfinger?resource=acct:jan.hermann.name@jan.hermann.name"
curl -H 'accept: application/activity+json' https://jan.hermann.name/ap/actor
```

From a Mastodon account, search `@jan.hermann.name@jan.hermann.name` and Follow;
`wrangler tail` should show the signature verifying and the `Accept` going out,
and `/ap/followers` `totalItems` should increment. Push a test post and confirm it
lands in the follower's timeline and is dereferenceable at `/ap/notes/<slug>`.

## Transition / cutover

The Worker runs **in parallel** with GitHub Pages + Bridgy Fed. Production hosting
only flips when DNS points at the Worker. Once the native actor is verified:

- remove `continue-on-error` from `deploy-worker`,
- delete the `deploy-github`, `deploy-cloudflare`, and Bridgy `federate` jobs,
- remove the Bridgy markup (`rel="webmention"`, `u-bridgy-fed`, the `web.brid.gy`
  `rel="me"` links).

**Followers do not migrate automatically:** existing Fediverse followers follow the
*bridged* actor, not this one. Announce the new handle for a re-follow, or attempt
a `Move`/`alsoKnownAs` migration (separate task). Keep Bridgy running until then.

## Out of MWE scope

Inbound rendering of replies/likes; delivery retries (Queues/Durable Objects);
paged outbox history; D1.
