// Entry point. Routes the ActivityPub paths to their handlers and forwards
// everything else to the static site (Workers Static Assets, env.ASSETS).

import {
  actor,
  followersCollection,
  note,
  outboxCollection,
  webfinger,
} from './activitypub';
import { deliver } from './deliver';
import { inbox } from './inbox';
import { Env } from './types';

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    try {
      if (path === '/.well-known/webfinger') return webfinger(request, env);
      if (path === '/ap/actor') return actor(env);
      if (path === '/ap/followers') return await followersCollection(env);
      if (path === '/ap/outbox') return await outboxCollection(env);
      if (path.startsWith('/ap/notes/')) {
        return await note(decodeURIComponent(path.slice('/ap/notes/'.length)), env);
      }
      if (path === '/ap/inbox') {
        if (request.method !== 'POST') return new Response('Method Not Allowed', { status: 405 });
        return await inbox(request, env);
      }
      if (path === '/ap/admin/deliver') {
        if (request.method !== 'POST') return new Response('Method Not Allowed', { status: 405 });
        return await deliver(request, env);
      }
    } catch (e) {
      console.log(`error handling ${path}: ${(e as Error).message}`);
      return new Response('Internal Server Error', { status: 500 });
    }

    // Not an ActivityPub route: serve the static site.
    return env.ASSETS.fetch(request);
  },
};
