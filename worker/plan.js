/**
 * Cloudflare Worker + Durable Object — SUDV11 : état partagé du plan d'images.
 *
 * Un seul objet, nommé "plan", détient tout l'état :
 *   clicks  { "<index>": n }        nombre de clics reçus par chaque image
 *   links   { "<a>:<b>": n }        n = nombre de PERSONNES ayant fait ce lien
 *   vu:<sid>|<a>:<b>                une cle par marque, pour qu'une session ne
 *                                   compte qu'une fois sur une paire donnee
 *
 * Les index sont ceux d'atlas.json, trie par nom de fichier. L'etat partage
 * repose donc sur un atlas fige : ajouter ou retirer une photo decale les
 * index et reattribue silencieusement les clics et les liens de tout le monde.
 * Si l'atlas doit changer, il faut remettre l'etat a zero (voir /reset).
 *
 * `sid` est un identifiant de session aléatoire fabriqué par le navigateur.
 * Ce n'est pas une identité : il ne dit pas qui, seulement « le même onglet ».
 * Rien de personnel n'est stocké, donc rien à déclarer.
 *
 * Routes :
 *   GET  /state          -> { clicks, links, total, n }
 *   POST /click  { i }   -> +1 clic sur l'image i
 *   POST /link   { a, b, sid } -> +1 sur la paire, si cette session ne l'a pas déjà faite
 *   POST /reset          -> efface tout (en-tete x-reset-token requis)
 *   GET  /ws             -> WebSocket : reçoit { type:"state", ... } à chaque changement
 *
 * Déploiement :  cd worker && npx wrangler deploy
 */

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "Content-Type",
};

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...CORS },
  });

export class Plan {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.sockets = new Set();
    state.blockConcurrencyWhile(async () => {
      this.clicks = (await state.storage.get("clicks")) || {};
      this.links = (await state.storage.get("links")) || {};
    });
  }

  snapshot() {
    let total = 0;
    for (const k in this.clicks) total += this.clicks[k];
    return { clicks: this.clicks, links: this.links, total, n: Object.keys(this.links).length };
  }

  broadcast() {
    const msg = JSON.stringify({ type: "state", ...this.snapshot() });
    for (const ws of this.sockets) {
      try { ws.send(msg); } catch (e) { this.sockets.delete(ws); }
    }
  }

  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/ws") {
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      this.sockets.add(server);
      server.addEventListener("close", () => this.sockets.delete(server));
      server.addEventListener("error", () => this.sockets.delete(server));
      server.send(JSON.stringify({ type: "state", ...this.snapshot() }));
      return new Response(null, { status: 101, webSocket: client });
    }

    if (url.pathname === "/state") return json(this.snapshot());

    if (url.pathname === "/click" && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      // un lot de clics : { i: 12 } ou { batch: { "12": 2, "88": 1 } }
      const add = body.batch && typeof body.batch === "object"
        ? body.batch
        : (Number.isInteger(body.i) ? { [body.i]: 1 } : null);
      if (!add) return json({ error: "i ou batch attendu" }, 400);
      for (const k in add) {
        const i = parseInt(k, 10), v = Math.min(50, Math.max(0, add[k] | 0));
        if (!Number.isInteger(i) || i < 0 || i > 5000 || !v) continue;
        this.clicks[i] = (this.clicks[i] || 0) + v;
      }
      await this.state.storage.put("clicks", this.clicks);
      this.broadcast();
      return json(this.snapshot());
    }

    if (url.pathname === "/link" && request.method === "POST") {
      const { a, b, sid } = await request.json().catch(() => ({}));
      if (!Number.isInteger(a) || !Number.isInteger(b) || a === b ||
          typeof sid !== "string" || sid.length < 8 || sid.length > 64) {
        return json({ error: "a, b, sid attendus" }, 400);
      }
      const key = a < b ? `${a}:${b}` : `${b}:${a}`;
      // Une cle par marque. La version d'avant gardait un Set en memoire et le
      // reecrivait EN ENTIER a chaque nouveau lien : la valeur grossissait sans
      // borne et aurait fini par buter sur la limite de taille du stockage.
      const mark = `vu:${sid}|${key}`;
      if (!(await this.state.storage.get(mark))) {
        this.links[key] = (this.links[key] || 0) + 1;
        await this.state.storage.put(mark, 1);
        await this.state.storage.put("links", this.links);
        this.broadcast();
      }
      return json(this.snapshot());
    }

    // Reprendre la main : le plan est commun et definitif, il lui faut une
    // porte. Le secret se pose avec `npx wrangler secret put RESET_TOKEN`.
    // Sans secret defini, la route n'existe pas.
    if (url.pathname === "/reset" && request.method === "POST") {
      const attendu = this.env && this.env.RESET_TOKEN;
      const donne = request.headers.get("x-reset-token");
      if (!attendu || donne !== attendu) return json({ error: "refuse" }, 403);
      await this.state.storage.deleteAll();
      this.clicks = {};
      this.links = {};
      this.broadcast();
      return json(this.snapshot());
    }

    return json({ error: "route inconnue" }, 404);
  }
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const id = env.PLAN.idFromName("plan");          // un seul plan, un seul objet
    return env.PLAN.get(id).fetch(request);
  },
};
