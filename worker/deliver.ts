// POST /ap/admin/deliver — called by the `federate-native` CI job (Bearer
// AP_ADMIN_TOKEN) after a push to main, with a list of changed slugs. For each,
// read the canonical Note straight from the deployed static assets
// (notes/<slug>/note.json), wrap it in a signed Create (or Update, when the Note
// carries an `updated`), and fan out to every follower's inbox.

import { listFollowers } from './activitypub';
import { signedFetch } from './httpsig';
import { AS_CONTEXT, Env, urls } from './types';

export async function deliver(request: Request, env: Env): Promise<Response> {
  const auth = request.headers.get('authorization') ?? '';
  if (auth !== `Bearer ${env.AP_ADMIN_TOKEN}`) {
    return new Response('Unauthorized', { status: 401 });
  }

  let body: { slugs?: string[] };
  try {
    body = await request.json();
  } catch {
    return new Response('Bad Request', { status: 400 });
  }
  const slugs = body.slugs ?? [];
  if (slugs.length === 0) return Response.json({ ok: true, delivered: 0, note: 'no slugs' });

  const u = urls(env);
  const origin = new URL(request.url).origin;
  const followers = await listFollowers(env);
  // One delivery per distinct inbox (shared inboxes dedupe many followers).
  const inboxes = [...new Set(followers.map((f) => f.inbox))];

  const results: Array<{ slug: string; type?: string; sent?: number; failed?: number; error?: string }> = [];

  for (const slug of slugs) {
    const noteUrl = new URL(`/notes/${slug}/note.json`, origin);
    const noteRes = await env.ASSETS.fetch(
      new Request(noteUrl.toString(), { headers: { accept: 'application/json' } }),
    );
    if (!noteRes.ok) {
      results.push({ slug, error: `note.json ${noteRes.status}` });
      continue;
    }
    const noteObj = (await noteRes.json()) as any;

    // An edit re-delivers as an Update (mirrors the dt-updated behaviour).
    const isUpdate = Boolean(noteObj.updated && noteObj.updated !== noteObj.published);
    const activity = {
      '@context': AS_CONTEXT[0],
      id: `${noteObj.id}#${isUpdate ? 'update' : 'create'}`,
      type: isUpdate ? 'Update' : 'Create',
      actor: u.actor,
      published: noteObj.updated ?? noteObj.published,
      to: noteObj.to,
      cc: noteObj.cc,
      object: noteObj,
    };
    const payload = JSON.stringify(activity);

    let sent = 0;
    let failed = 0;
    for (const inbox of inboxes) {
      try {
        const res = await signedFetch(env, inbox, { method: 'POST', body: payload });
        if (res.ok) sent++;
        else {
          failed++;
          console.log(`deliver ${slug} -> ${inbox}: ${res.status}`);
        }
      } catch (e) {
        failed++;
        console.log(`deliver ${slug} -> ${inbox}: ${(e as Error).message}`);
      }
    }
    results.push({ slug, type: activity.type, sent, failed });
  }

  return Response.json({ ok: true, followers: inboxes.length, results });
}
