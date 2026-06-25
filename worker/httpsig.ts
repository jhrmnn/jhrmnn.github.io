// HTTP Signatures (draft-cavage, as used by Mastodon and the wider Fediverse)
// over WebCrypto. We both sign outbound POSTs/GETs with the actor key and verify
// inbound POSTs against the sender's published key.

import { getPrivateKey, importPublicKey } from './keys';
import { AP_CONTENT_TYPE, Env, urls } from './types';

const enc = new TextEncoder();

function bytesToB64(bytes: Uint8Array): string {
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64.replace(/\s+/g, ''));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// `Digest: SHA-256=<base64>` over the exact request body.
export async function digestHeader(body: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', enc.encode(body));
  return 'SHA-256=' + bytesToB64(new Uint8Array(hash));
}

// Build the draft-cavage signing string from an ordered header-name list.
function signingString(
  names: string[],
  values: Record<string, string>,
): string {
  return names.map((n) => `${n}: ${values[n]}`).join('\n');
}

// Sign and send a request as the actor. For POSTs we sign
// `(request-target) host date digest`; for GETs, `(request-target) host date`.
// Note: Host is set by the runtime from the URL (it's a forbidden header to set
// manually), but the value we sign equals url.host, which is what the peer sees.
export async function signedFetch(
  env: Env,
  url: string,
  opts: { method: 'GET' | 'POST'; body?: string; accept?: string },
): Promise<Response> {
  const u = new URL(url);
  const date = new Date().toUTCString();
  const requestTarget = `${opts.method.toLowerCase()} ${u.pathname}${u.search}`;

  const values: Record<string, string> = {
    '(request-target)': requestTarget,
    host: u.host,
    date,
  };
  const names = ['(request-target)', 'host', 'date'];

  const headers: Record<string, string> = { date, accept: opts.accept ?? AP_CONTENT_TYPE };
  if (opts.body !== undefined) {
    const digest = await digestHeader(opts.body);
    values.digest = digest;
    names.push('digest');
    headers.digest = digest;
    headers['content-type'] = AP_CONTENT_TYPE;
  }

  const key = await getPrivateKey(env.AP_PRIVATE_KEY);
  const sig = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    key,
    enc.encode(signingString(names, values)),
  );
  headers.signature =
    `keyId="${urls(env).keyId}",` +
    `algorithm="rsa-sha256",` +
    `headers="${names.join(' ')}",` +
    `signature="${bytesToB64(new Uint8Array(sig))}"`;

  return fetch(url, { method: opts.method, headers, body: opts.body });
}

// Fetch a remote actor object (the fragment in a keyId points at the actor).
// Signed GET so instances in "authorized fetch"/secure mode still answer.
export async function fetchActor(url: string, env: Env): Promise<any> {
  const clean = url.split('#')[0];
  const res = await signedFetch(env, clean, { method: 'GET' });
  if (!res.ok) throw new Error(`fetch actor ${clean} -> ${res.status}`);
  return res.json();
}

function parseSignatureHeader(h: string): Record<string, string> {
  const out: Record<string, string> = {};
  // Quoted values (Mastodon) and bare values (some impls for algorithm) both.
  const re = /(\w+)="([^"]*)"|(\w+)=([^",]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(h))) {
    if (m[1] !== undefined) out[m[1]] = m[2];
    else out[m[3]] = m[4];
  }
  return out;
}

// Verify an inbound request's HTTP signature. Returns the verified sender's
// actor id, or throws. Also checks the body Digest when it is covered.
export async function verifyRequest(
  request: Request,
  rawBody: string,
  env: Env,
): Promise<string> {
  const sigHeader = request.headers.get('signature');
  if (!sigHeader) throw new Error('missing Signature header');
  const params = parseSignatureHeader(sigHeader);
  if (!params.keyId || !params.signature) throw new Error('malformed Signature header');

  const actor = await fetchActor(params.keyId, env);
  const pem: string | undefined = actor?.publicKey?.publicKeyPem;
  if (!pem) throw new Error('sender has no publicKeyPem');

  const u = new URL(request.url);
  const names = (params.headers ?? 'date').split(' ');
  const values: Record<string, string> = {};
  for (const n of names) {
    if (n === '(request-target)') {
      values[n] = `${request.method.toLowerCase()} ${u.pathname}${u.search}`;
    } else if (n === 'host') {
      values[n] = request.headers.get('host') ?? u.host;
    } else {
      values[n] = request.headers.get(n) ?? '';
    }
  }

  const key = await importPublicKey(pem);
  const ok = await crypto.subtle.verify(
    'RSASSA-PKCS1-v1_5',
    key,
    b64ToBytes(params.signature) as BufferSource,
    enc.encode(signingString(names, values)),
  );
  if (!ok) throw new Error('signature verification failed');

  if (names.includes('digest')) {
    const expected = await digestHeader(rawBody);
    if (request.headers.get('digest') !== expected) throw new Error('digest mismatch');
  }

  return (actor.id as string) ?? params.keyId.split('#')[0];
}
