/**
 * Cloudflare Worker — SUDV11 : état du live Mixcloud (M_GO) + relais HLS.
 *
 * Deux rôles :
 *  1. GET /            -> { live, status, src }
 *       live   : true si le stream est en cours (streamStatus != "ENDED")
 *       src    : URL (proxifiée par ce Worker) du flux AUDIO HLS à jouer,
 *                ou null si offline. À passer à un <audio>/hls.js côté site.
 *  2. GET /hls?u=<url> -> proxifie le manifeste/segments HLS de Mixcloud en
 *       ajoutant les en-têtes CORS (Mixcloud ne les fournit pas, donc un site
 *       tiers ne peut pas lire le flux directement hors Safari). Les URIs des
 *       manifestes .m3u8 sont réécrites pour repasser par ce même endpoint.
 *
 * Déploiement : coller ce fichier dans le Worker et Deploy.
 */

const USER = "M_GO";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,HEAD,OPTIONS",
  "access-control-allow-headers": "Range,Content-Type,Cache-Control",
  "access-control-expose-headers": "Content-Length,Content-Range,Date,Accept-Ranges",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (url.pathname === "/hls") {
      return proxyHls(url, request);
    }

    return status(url);
  },
};

/* ---------- Statut + résolution du flux audio ---------- */
async function status(url) {
  const q =
    `{ userLookup(lookup:{username:"${USER}"}){ liveStream { streamStatus hlsUrl } } }`;
  let streamStatus = null;
  let hlsUrl = null;
  try {
    const r = await fetch(
      "https://app.mixcloud.com/graphql?query=" + encodeURIComponent(q),
      { headers: { "User-Agent": "Mozilla/5.0", Accept: "application/json" }, cf: { cacheTtl: 0 } }
    );
    const j = await r.json();
    const ls = j && j.data && j.data.userLookup && j.data.userLookup.liveStream;
    streamStatus = (ls && ls.streamStatus) || null;
    hlsUrl = (ls && ls.hlsUrl) || null;
  } catch (e) { /* ignore */ }

  const live = !!streamStatus && streamStatus !== "ENDED";

  // Extrait le sous-flux AUDIO du master pour ne pas tirer la vidéo.
  let audioUrl = hlsUrl;
  if (live && hlsUrl) {
    try {
      const m = await fetch(hlsUrl, { headers: { "User-Agent": "Mozilla/5.0" }, cf: { cacheTtl: 0 } });
      const txt = await m.text();
      const match = txt.match(/#EXT-X-MEDIA:[^\n]*TYPE=AUDIO[^\n]*URI="([^"]+)"/);
      if (match) audioUrl = resolve(hlsUrl, match[1]);
    } catch (e) { /* on garde le master */ }
  }

  const src = live && audioUrl
    ? url.origin + "/hls?u=" + encodeURIComponent(audioUrl)
    : null;

  return new Response(JSON.stringify({ live, status: streamStatus, src }), {
    headers: Object.assign({}, CORS, {
      "content-type": "application/json",
      "cache-control": "no-store",
    }),
  });
}

/* ---------- Proxy HLS ---------- */
async function proxyHls(url, request) {
  const target = url.searchParams.get("u");
  if (!target) return new Response("missing u", { status: 400, headers: CORS });
  const t = decodeURIComponent(target);
  if (!/^https:\/\/[a-z0-9.-]*mixcloud\.com\//i.test(t)) {
    return new Response("blocked", { status: 403, headers: CORS });
  }

  const range = request.headers.get("Range");
  const upstream = await fetch(t, {
    headers: Object.assign({ "User-Agent": "Mozilla/5.0" }, range ? { Range: range } : {}),
    cf: { cacheTtl: 0 },
  });

  const ct = upstream.headers.get("content-type") || "";
  const isPlaylist = t.includes(".m3u8") || ct.includes("mpegurl");

  const h = new Headers(CORS);
  ["content-type", "content-length", "content-range", "accept-ranges"].forEach((k) => {
    const v = upstream.headers.get(k);
    if (v) h.set(k, v);
  });
  h.set("cache-control", "no-store");

  if (!isPlaylist) {
    // Segment binaire (.m4s / init.mp4) : on relaie tel quel.
    return new Response(upstream.body, { status: upstream.status, headers: h });
  }

  // Manifeste : réécrit chaque URI (relative ou absolue) vers ce proxy.
  const text = await upstream.text();
  const wrap = (u) => url.origin + "/hls?u=" + encodeURIComponent(resolve(t, u));
  const out = text.split("\n").map((line) => {
    const l = line.trim();
    if (!l) return line;
    if (l.startsWith("#")) {
      return line.replace(/URI="([^"]+)"/g, (m, u) => `URI="${wrap(u)}"`);
    }
    return wrap(l);
  }).join("\n");

  h.set("content-type", "application/vnd.apple.mpegurl");
  return new Response(out, { status: 200, headers: h });
}

/* Résout une URI (relative ou absolue) contre l'URL du manifeste parent. */
function resolve(baseUrl, u) {
  if (/^https?:\/\//i.test(u)) return u;
  return new URL(u, baseUrl).toString();
}
