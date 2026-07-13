// The "document" side of the actor: WebFinger, the actor (Person) object, the
// followers collection, and content negotiation for Notes and the outbox.
//
// Notes and the outbox are static build artifacts (posts.py writes
// notes/<slug>/note.json and ap/outbox.json). The Worker reads them from its own
// deployed assets and re-serves them with the ActivityPub content type — the post
// record is the single source of truth, so there is no KV Note store and no HTML
// re-parsing. KV holds followers only.

import {
  AP_CONTENT_TYPE,
  AS_CONTEXT,
  Env,
  FOLLOWER_PREFIX,
  Follower,
  apJson,
  urls,
} from './types';

// Fetch a JSON asset from the deployed static site (bypasses Worker routing).
async function fetchAsset(request: Request, path: string, env: Env): Promise<Response> {
  const assetUrl = new URL(path, new URL(request.url).origin);
  return env.ASSETS.fetch(new Request(assetUrl.toString(), { headers: { accept: 'application/json' } }));
}

// GET /.well-known/webfinger?resource=acct:<user>@<domain>
export function webfinger(request: Request, env: Env): Response {
  const u = urls(env);
  const resource = new URL(request.url).searchParams.get('resource') ?? '';
  if (resource.toLowerCase() !== u.acct.toLowerCase()) {
    return new Response('Not found', { status: 404 });
  }
  return apJson(
    {
      subject: u.acct,
      aliases: [u.actor],
      links: [
        { rel: 'self', type: AP_CONTENT_TYPE, href: u.actor },
        { rel: 'http://webfinger.net/rel/profile-page', type: 'text/html', href: u.base },
      ],
    },
    { headers: { 'content-type': 'application/jrd+json' } },
  );
}

// GET /ap/actor — the Person object Mastodon follows.
export function actor(env: Env): Response {
  const u = urls(env);
  return apJson({
    '@context': AS_CONTEXT,
    id: u.actor,
    type: 'Person',
    preferredUsername: env.USERNAME,
    name: 'Jan Hermann',
    summary: 'Personal site of Jan Hermann — notes and writing.',
    url: u.base,
    inbox: u.inbox,
    outbox: u.outbox,
    followers: u.followers,
    manuallyApprovesFollowers: false,
    discoverable: true,
    icon: {
      type: 'Image',
      mediaType: 'image/jpeg',
      url: `${u.base}/profile-pic-web.jpeg`,
    },
    publicKey: {
      id: u.keyId,
      owner: u.actor,
      publicKeyPem: env.AP_PUBLIC_KEY,
    },
  });
}

export async function listFollowers(env: Env): Promise<Follower[]> {
  const out: Follower[] = [];
  let cursor: string | undefined;
  do {
    const page = await env.FEDI.list({ prefix: FOLLOWER_PREFIX, cursor });
    for (const k of page.keys) {
      const v = await env.FEDI.get<Follower>(k.name, 'json');
      if (v) out.push(v);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

// GET /ap/followers
export async function followersCollection(env: Env): Promise<Response> {
  const u = urls(env);
  const followers = await listFollowers(env);
  return apJson({
    '@context': AS_CONTEXT[0],
    id: u.followers,
    type: 'OrderedCollection',
    totalItems: followers.length,
    orderedItems: followers.map((f) => f.actor),
  });
}

// GET /ap/outbox — re-serve the static ap/outbox.json with the AP content type.
export async function outboxCollection(request: Request, env: Env): Promise<Response> {
  const res = await fetchAsset(request, '/ap/outbox.json', env);
  if (res.ok) {
    return new Response(await res.text(), { headers: { 'content-type': AP_CONTENT_TYPE } });
  }
  // Fallback: empty collection if the build hasn't produced one yet.
  const u = urls(env);
  return apJson({
    '@context': AS_CONTEXT[0],
    id: u.outbox,
    type: 'OrderedCollection',
    totalItems: 0,
    orderedItems: [],
  });
}

// A post page (/notes/<slug>/) requested as ActivityPub: return its static Note,
// re-served with the AP content type. `Vary: Accept` so caches key HTML and AS2
// separately for the same URL.
export async function noteFromAssets(request: Request, env: Env): Promise<Response> {
  const pagePath = new URL(request.url).pathname.replace(/\/?$/, '/');
  const res = await fetchAsset(request, `${pagePath}note.json`, env);
  if (!res.ok) return new Response('Not found', { status: 404 });
  return new Response(await res.text(), {
    headers: { 'content-type': AP_CONTENT_TYPE, vary: 'Accept' },
  });
}
