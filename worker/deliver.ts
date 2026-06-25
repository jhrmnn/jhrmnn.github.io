// POST /ap/admin/deliver — called by the GitHub Action's `federate` job (Bearer
// AP_ADMIN_TOKEN) after a push to main. For each changed post it stores the Note
// (so /ap/notes/<slug> is dereferenceable) and fans a signed Create (or Update,
// for an edit) out to every follower's inbox.

import { buildNote, listFollowers } from './activitypub';
import { signedFetch } from './httpsig';
import { AS_CONTEXT, Env, NOTE_PREFIX, PUBLIC, urls } from './types';

interface PostInput {
  slug: string;
  url: string;
  contentHtml: string;
  published: string;
  updated?: string;
}

export async function deliver(request: Request, env: Env): Promise<Response> {
  const auth = request.headers.get('authorization') ?? '';
  if (auth !== `Bearer ${env.AP_ADMIN_TOKEN}`) {
    return new Response('Unauthorized', { status: 401 });
  }

  let body: { posts?: PostInput[] };
  try {
    body = await request.json();
  } catch {
    return new Response('Bad Request', { status: 400 });
  }
  const posts = body.posts ?? [];
  if (posts.length === 0) return Response.json({ ok: true, delivered: 0, note: 'no posts' });

  const u = urls(env);
  const followers = await listFollowers(env);
  // One delivery per distinct inbox (shared inboxes dedupe many followers).
  const inboxes = [...new Set(followers.map((f) => f.inbox))];

  const results: Array<{ slug: string; type: string; sent: number; failed: number }> = [];

  for (const post of posts) {
    const noteObj = buildNote(env, post);
    await env.FEDI.put(`${NOTE_PREFIX}${post.slug}`, JSON.stringify(noteObj));

    const isUpdate = Boolean(post.updated && post.updated !== post.published);
    const activity = {
      '@context': AS_CONTEXT[0],
      id: `${u.note(post.slug)}#${isUpdate ? 'update' : 'create'}`,
      type: isUpdate ? 'Update' : 'Create',
      actor: u.actor,
      published: post.updated ?? post.published,
      to: [PUBLIC],
      cc: [u.followers],
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
          console.log(`deliver ${post.slug} -> ${inbox}: ${res.status}`);
        }
      } catch (e) {
        failed++;
        console.log(`deliver ${post.slug} -> ${inbox}: ${(e as Error).message}`);
      }
    }
    results.push({ slug: post.slug, type: activity.type, sent, failed });
  }

  return Response.json({ ok: true, followers: inboxes.length, results });
}
