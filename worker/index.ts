// Entry point. Routes the ActivityPub paths to their handlers and forwards
// everything else to the static site (Workers Static Assets, env.ASSETS).
//
// A post page and its Note share one URL (/notes/<slug>/): browsers get the HTML
// page, clients that ask for ActivityPub get the Note. run_worker_first in
// wrangler.toml ensures the Worker sees /notes/* before the static asset does.

import {
  actor,
  followersCollection,
  noteFromAssets,
  outboxCollection,
  webfinger,
} from './activitypub';
import { deliver } from './deliver';
import { inbox } from './inbox';
import { Env } from './types';

const NOTE_PAGE = /^\/notes\/[^/]+\/?$/;

function wantsActivityPub(request: Request): boolean {
  const accept = request.headers.get('accept') ?? '';
  return accept.includes('application/activity+json') || accept.includes('application/ld+json');
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    try {
      if (path === '/.well-known/webfinger') return webfinger(request, env);
      if (path === '/ap/actor') return actor(env);
      if (path === '/ap/followers') return await followersCollection(env);
      if (path === '/ap/outbox') return await outboxCollection(request, env);
      if (path === '/ap/inbox') {
        if (request.method !== 'POST') return new Response('Method Not Allowed', { status: 405 });
        return await inbox(request, env);
      }
      if (path === '/ap/admin/deliver') {
        if (request.method !== 'POST') return new Response('Method Not Allowed', { status: 405 });
        return await deliver(request, env);
      }
      // Legacy machine URL from the initial MWE: redirect to the canonical page.
      if (path.startsWith('/ap/notes/')) {
        const slug = decodeURIComponent(path.slice('/ap/notes/'.length)).replace(/\/$/, '');
        return Response.redirect(`${url.origin}/notes/${slug}/`, 301);
      }
      // Content negotiation: a post page requested as ActivityPub returns its Note.
      if (NOTE_PAGE.test(path) && wantsActivityPub(request)) {
        return await noteFromAssets(request, env);
      }
    } catch (e) {
      console.log(`error handling ${path}: ${(e as Error).message}`);
      return new Response('Internal Server Error', { status: 500 });
    }

    // Not an ActivityPub route: serve the static site.
    return env.ASSETS.fetch(request);
  },
};
