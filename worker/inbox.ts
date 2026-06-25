// POST /ap/inbox — the one mutating inbound endpoint. Verifies the HTTP
// signature, then handles Follow (store + Accept) and Undo Follow (remove).
// Everything else is acknowledged with 202 and ignored, as is fine for a
// single-actor, outbound-only MWE.

import { fetchActor, signedFetch, verifyRequest } from './httpsig';
import { AS_CONTEXT, Env, FOLLOWER_PREFIX, Follower, urls } from './types';

function inboxOf(actor: any): string {
  return actor?.endpoints?.sharedInbox ?? actor?.inbox;
}

async function sendAccept(env: Env, followActivity: any, followerInbox: string): Promise<void> {
  const u = urls(env);
  const accept = {
    '@context': AS_CONTEXT[0],
    id: `${u.base}/ap/activities/${crypto.randomUUID()}`,
    type: 'Accept',
    actor: u.actor,
    object: followActivity,
  };
  const res = await signedFetch(env, followerInbox, {
    method: 'POST',
    body: JSON.stringify(accept),
  });
  if (!res.ok) {
    console.log(`Accept -> ${followerInbox} failed: ${res.status} ${await res.text()}`);
  }
}

export async function inbox(request: Request, env: Env): Promise<Response> {
  const rawBody = await request.text();

  let senderId: string;
  try {
    senderId = await verifyRequest(request, rawBody, env);
  } catch (e) {
    console.log(`inbox: signature rejected: ${(e as Error).message}`);
    return new Response('Unauthorized', { status: 401 });
  }

  let activity: any;
  try {
    activity = JSON.parse(rawBody);
  } catch {
    return new Response('Bad Request', { status: 400 });
  }

  const actorId: string =
    typeof activity.actor === 'string' ? activity.actor : activity.actor?.id;

  switch (activity.type) {
    case 'Follow': {
      // The signer must be the follower they claim to be.
      if (actorId !== senderId) {
        return new Response('Actor mismatch', { status: 401 });
      }
      const remote = await fetchActor(actorId, env);
      const target = inboxOf(remote);
      if (!target) return new Response('No inbox', { status: 422 });
      const follower: Follower = {
        actor: actorId,
        inbox: target,
        since: new Date().toISOString(),
      };
      await env.FEDI.put(`${FOLLOWER_PREFIX}${actorId}`, JSON.stringify(follower));
      await sendAccept(env, activity, target);
      console.log(`inbox: accepted Follow from ${actorId}`);
      return new Response(null, { status: 202 });
    }

    case 'Undo': {
      // Undo of a Follow: drop the follower. (object may be the Follow or its id.)
      const inner = activity.object;
      const innerType = typeof inner === 'object' ? inner.type : undefined;
      if (innerType === 'Follow' || innerType === undefined) {
        await env.FEDI.delete(`${FOLLOWER_PREFIX}${actorId}`);
        console.log(`inbox: removed follower ${actorId}`);
      }
      return new Response(null, { status: 202 });
    }

    default:
      // Like, Announce, Delete, etc. — acknowledged, no-op for the MWE.
      return new Response(null, { status: 202 });
  }
}
