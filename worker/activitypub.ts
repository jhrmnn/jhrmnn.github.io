// The "document" side of the actor: WebFinger, the actor (Person) object, the
// followers/outbox collections, and dereferenceable Notes. All read-only GETs.

import {
  AP_CONTENT_TYPE,
  AS_CONTEXT,
  Env,
  FOLLOWER_PREFIX,
  Follower,
  NOTE_PREFIX,
  PUBLIC,
  apJson,
  urls,
} from './types';

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

// GET /ap/outbox — MWE: advertise the collection; items are not paged.
export async function outboxCollection(env: Env): Promise<Response> {
  const u = urls(env);
  return apJson({
    '@context': AS_CONTEXT[0],
    id: u.outbox,
    type: 'OrderedCollection',
    totalItems: 0,
    orderedItems: [],
  });
}

// GET /ap/notes/<slug> — return the stored Note so delivered posts are
// dereferenceable by remote servers that re-fetch them.
export async function note(slug: string, env: Env): Promise<Response> {
  const stored = await env.FEDI.get(`${NOTE_PREFIX}${slug}`, 'json');
  if (!stored) return new Response('Not found', { status: 404 });
  return apJson({ '@context': AS_CONTEXT[0], ...(stored as object) });
}

// Build the Note object for a published post. Stored in KV (so /ap/notes/<slug>
// can serve it) and wrapped in a Create/Update for delivery.
export function buildNote(
  env: Env,
  post: { slug: string; url: string; contentHtml: string; published: string; updated?: string },
): Record<string, unknown> {
  const u = urls(env);
  return {
    id: u.note(post.slug),
    type: 'Note',
    attributedTo: u.actor,
    content: post.contentHtml,
    url: post.url,
    published: post.published,
    ...(post.updated ? { updated: post.updated } : {}),
    to: [PUBLIC],
    cc: [u.followers],
  };
}
