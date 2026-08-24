/**
 * Cloudflare Worker — relais CORS pour l'état du live Mixcloud de M_GO.
 *
 * Pourquoi : l'API Mixcloud qui donne l'état réel du stream (GraphQL,
 * champ streamStatus) ne renvoie pas d'en-tête CORS, donc le site statique
 * (GitHub Pages) ne peut pas l'appeler directement. Ce Worker fait l'appel
 * côté serveur et renvoie un petit JSON { live, status } avec CORS ouvert.
 *
 * Déploiement (une seule fois) :
 *  1. Compte gratuit sur https://dash.cloudflare.com  → Workers & Pages
 *  2. Create → Worker → coller ce fichier → Deploy
 *  3. Copier l'URL du Worker (ex: https://sudv11-live.xxxx.workers.dev)
 *  4. La coller dans index.html à la constante STATUS_ENDPOINT
 */
export default {
  async fetch() {
    const USER = "M_GO";
    const query =
      `{ userLookup(lookup:{username:"${USER}"}){ liveStream { streamStatus } } }`;
    const url = "https://app.mixcloud.com/graphql?query=" + encodeURIComponent(query);

    let status = null;
    try {
      const r = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0", Accept: "application/json" },
        cf: { cacheTtl: 0 },
      });
      const j = await r.json();
      status = j?.data?.userLookup?.liveStream?.streamStatus ?? null;
    } catch (e) {
      status = null;
    }

    // "ENDED" = terminé ; toute autre valeur non nulle = en cours de diffusion.
    const live = !!status && status !== "ENDED";

    return new Response(JSON.stringify({ live, status }), {
      headers: {
        "content-type": "application/json",
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      },
    });
  },
};
