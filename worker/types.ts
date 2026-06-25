// Shared types and URL helpers for the ActivityPub Worker.

export interface Env {
  ASSETS: Fetcher;
  FEDI: KVNamespace;
  DOMAIN: string; // e.g. "jan.hermann.name"
  USERNAME: string; // WebFinger local part / preferredUsername, e.g. "jan.hermann.name"
  AP_PUBLIC_KEY: string; // actor RSA public key (SPKI PEM) — public, lives in wrangler.toml
  AP_PRIVATE_KEY: string; // actor RSA private key (PKCS#8 PEM, or base64 of it) — dashboard secret
  AP_ADMIN_TOKEN: string; // bearer token gating /ap/admin/deliver
}

export const AS_CONTEXT = [
  'https://www.w3.org/ns/activitystreams',
  'https://w3id.org/security/v1',
];

export const PUBLIC = 'https://www.w3.org/ns/activitystreams#Public';

// application/activity+json with the AS2 profile; ld+json is also accepted by
// peers, but this is the canonical type Mastodon sends and expects.
export const AP_CONTENT_TYPE = 'application/activity+json';

// Canonical URLs derived from the domain. Keeping them in one place avoids
// drift between the actor object, webfinger, and the id fields on activities.
export function urls(env: Env) {
  const base = `https://${env.DOMAIN}`;
  const actor = `${base}/ap/actor`;
  return {
    base,
    actor,
    keyId: `${actor}#main-key`,
    inbox: `${base}/ap/inbox`,
    outbox: `${base}/ap/outbox`,
    followers: `${base}/ap/followers`,
    note: (slug: string) => `${base}/ap/notes/${slug}`,
    acct: `acct:${env.USERNAME}@${env.DOMAIN}`,
  };
}

// JSON response with the ActivityPub content type.
export function apJson(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { 'content-type': AP_CONTENT_TYPE, ...(init.headers ?? {}) },
  });
}

// A stored follower record.
export interface Follower {
  actor: string; // the remote actor id (also the KV key suffix)
  inbox: string; // where we deliver — prefer sharedInbox
  since: string; // ISO timestamp of the accepted Follow
}

export const FOLLOWER_PREFIX = 'follower:';
export const NOTE_PREFIX = 'note:';
