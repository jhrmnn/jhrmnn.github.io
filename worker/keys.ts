// Import the actor's RSA private key and remote actors' public keys into
// WebCrypto CryptoKeys. ActivityPub / HTTP Signatures use RSASSA-PKCS1-v1_5
// with SHA-256, which Workers' WebCrypto supports natively — no library needed.

const RSA_PKCS1_SHA256 = {
  name: 'RSASSA-PKCS1-v1_5',
  hash: 'SHA-256',
} as const;

// Decode a base64 (standard, not URL-safe) string to bytes.
function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64.replace(/\s+/g, ''));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// Pull the DER body out of a PEM block (any label), as bytes.
function pemBody(pem: string): Uint8Array {
  const m = pem.match(/-----BEGIN [^-]+-----([\s\S]+?)-----END [^-]+-----/);
  if (!m) throw new Error('not a PEM block');
  return b64ToBytes(m[1]);
}

// The dashboard secret may hold the raw multi-line PEM, or — if multi-line
// paste was awkward — base64 of the whole PEM file. Normalise both to PEM text.
function toPem(secret: string): string {
  const trimmed = secret.trim();
  if (trimmed.includes('-----BEGIN')) return trimmed;
  // base64-of-PEM: decode one layer to recover the PEM text.
  const decoded = atob(trimmed.replace(/\s+/g, ''));
  if (!decoded.includes('-----BEGIN')) {
    throw new Error('AP_PRIVATE_KEY is neither PEM nor base64-of-PEM');
  }
  return decoded;
}

let cachedPrivateKey: Promise<CryptoKey> | null = null;

// The actor's signing key (PKCS#8). Cached per isolate so repeated deliveries
// in one request don't re-import.
export function getPrivateKey(secret: string): Promise<CryptoKey> {
  if (!cachedPrivateKey) {
    const der = pemBody(toPem(secret));
    cachedPrivateKey = crypto.subtle.importKey(
      'pkcs8',
      der as BufferSource,
      RSA_PKCS1_SHA256,
      false,
      ['sign'],
    );
  }
  return cachedPrivateKey;
}

// A remote actor's public key (SPKI PEM from `publicKey.publicKeyPem`).
export function importPublicKey(pem: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'spki',
    pemBody(pem) as BufferSource,
    RSA_PKCS1_SHA256,
    false,
    ['verify'],
  );
}
