/*
 * Service worker do PWA (spec §14.6). Dono: P1.1; a P2.2 acrescenta `push`/`notificationclick` (§15).
 *
 * - `condessa-shell-v<N>`: lista fixa de TODOS os arquivos (cache-first); `N` sobe a cada deploy
 *   que muda algum arquivo, e o `activate` apaga as versões antigas;
 * - `/v1/feed` sem `antes=` (a 1ª página): network-first com cópia em `condessa-feed` (só o último,
 *   1 entrada) e recaída nela; com `antes=` (páginas antigas): network-only, nunca cacheado;
 * - resto de `/v1/*`, `/saude`, `/ws`, `/mcp`: network-only, nunca cacheado (token, casa, tarefas).
 * - `push` / `notificationclick` (P2.2, spec §15): notificação **sem** botões de ação, nem no
 *   `confirma` (DS17: o card abre no PWA); o clique foca a janela do PWA e leva à `url`, ou abre.
 * - P2.3: badge monocromático `icones/badge-96.png`; push de `confirma` abre
 *   `#/confirma/<ulid>?d=&expira=` (o servidor já manda na `url`; aqui completa se faltar);
 *   `pushsubscriptionchange` reassina sozinho com o token do IndexedDB (`condessa`/`kv`).
 */

const VERSAO = 4; // = VERSAO_SHELL do versao.js
const CACHE_SHELL = "condessa-shell-v" + VERSAO;
const CACHE_FEED = "condessa-feed";
const CHAVE_FEED = "/v1/feed";
const ARQUIVOS = [
  "./",
  "index.html",
  "app.js",
  "api.js",
  "estado.js",
  "estilo.css",
  "gravador.js",
  "manifest.webmanifest",
  "versao.js",
  "telas/conversa.js",
  "telas/tv.js",
  "telas/feed.js",
  "telas/tarefas.js",
  "telas/ajustes.js",
  "telas/parear.js",
  "telas/confirma.js",
  "icones/192.png",
  "icones/512.png",
  "icones/maskable-512.png",
  "icones/badge-96.png",
  "rosto/dormindo.webp",
  "rosto/ouvindo.webp",
  "rosto/pensando.webp",
  "rosto/falando.webp",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_SHELL).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((nomes) =>
        Promise.all(
          nomes.filter((n) => n.startsWith("condessa-shell-") && n !== CACHE_SHELL).map((n) => caches.delete(n)),
        ),
      )
      .then(() => self.clients && self.clients.claim()),
  );
});

async function feedPrimeiroRede(req) {
  try {
    const r = await fetch(req);
    if (r.ok) {
      const cache = await caches.open(CACHE_FEED);
      const copia = r.clone();
      const headers = new Headers(copia.headers);
      headers.set("X-Condessa-Cache-Em", new Date().toISOString());
      const corpo = await copia.blob();
      await cache.put(CHAVE_FEED, new Response(corpo, { status: copia.status, headers }));
    }
    return r;
  } catch (erro) {
    const cache = await caches.open(CACHE_FEED);
    const guardado = await cache.match(CHAVE_FEED);
    if (guardado) return guardado;
    throw erro;
  }
}

async function shellPrimeiroCache(req) {
  const cache = await caches.open(CACHE_SHELL);
  const achado = await cache.match(req, { ignoreSearch: true });
  if (achado) return achado;
  if (req.mode === "navigate") {
    const casca = await cache.match("./");
    if (casca) return casca;
  }
  return fetch(req);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const escopo = new URL("./", self.location.href).pathname;
  if (url.pathname === CHAVE_FEED) {
    if (url.searchParams.has("antes")) return; // página antiga: rede, sem cópia nem recaída
    e.respondWith(feedPrimeiroRede(req));
    return;
  }
  if (url.pathname.startsWith(escopo) && url.pathname !== escopo + "sw.js") {
    e.respondWith(shellPrimeiroCache(req));
  }
  // resto (/v1/*, /saude, /ws, /mcp): network-only, sem respondWith.
});

// ---------- Web Push (P2.2, spec §15)

const URL_PADRAO = "./#/conversa";
const ICONE = "icones/192.png";
const BADGE = "icones/badge-96.png";

/** `url` do payload só se for do mesmo escopo do PWA; senão a Conversa. Devolve absoluta. */
function urlSegura(u) {
  const escopo = new URL("./", self.location.href);
  try {
    const alvo = new URL(u || URL_PADRAO, escopo);
    if (alvo.origin === escopo.origin && alvo.pathname.startsWith(escopo.pathname)) return alvo.href;
  } catch {
    /* url inválida: cai no padrão */
  }
  return new URL(URL_PADRAO, escopo).href;
}

function lerPayload(dados) {
  if (!dados) return {};
  try {
    const d = dados.json();
    return d && typeof d === "object" ? d : {};
  } catch {
    return {};
  }
}

/** `confirma` sem `?d=&expira=` na `url` (payload antigo): completa com os campos do payload. */
function urlDoPush(d) {
  const u = d.url;
  if (d.tipo !== "confirma" || typeof u !== "string" || !u.includes("#/confirma/") || u.includes("?")) return u;
  const q = new URLSearchParams();
  if (d.d || d.resumo) q.set("d", String(d.d || d.resumo));
  if (d.expira) q.set("expira", String(d.expira));
  const s = q.toString();
  return s ? `${u}?${s}` : u;
}

self.addEventListener("push", (e) => {
  const d = lerPayload(e.data);
  const icone = new URL(ICONE, self.location.href).href;
  const opcoes = {
    body: String(d.resumo ?? ""),
    data: { url: urlSegura(urlDoPush(d)), tipo: d.tipo ?? null },
    icon: icone,
    badge: new URL(BADGE, self.location.href).href,
    // DS17: nenhum `actions` (nem "Confirmar" no `confirma`): tocar só abre o card no PWA.
  };
  if (d.tag) opcoes.tag = String(d.tag);
  e.waitUntil(self.registration.showNotification(String(d.titulo || "Condessa"), opcoes));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const alvo = urlSegura(e.notification.data?.url);
  const escopo = new URL("./", self.location.href).href;
  e.waitUntil(
    (async () => {
      const janelas = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const minha = janelas.find((c) => c.url.startsWith(escopo));
      if (minha) {
        const focada = (await minha.focus()) || minha;
        if (focada.url !== alvo && focada.navigate) {
          try {
            await focada.navigate(alvo);
          } catch {
            /* janela não controlada: fica só focada */
          }
        }
        return;
      }
      await self.clients.openWindow(alvo);
    })(),
  );
});

// ---------- pushsubscriptionchange (P2.3, spec §15 *Assinatura*)

/** Lê uma chave do armazém do app (IndexedDB `condessa`/`kv`, o mesmo do `api.js`); `null` se falhar. */
function lerKv(chave) {
  return new Promise((ok) => {
    try {
      const req = indexedDB.open("condessa", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("kv");
      req.onerror = () => ok(null);
      req.onsuccess = () => {
        try {
          const g = req.result.transaction("kv", "readonly").objectStore("kv").get(chave);
          g.onsuccess = () => ok(g.result ?? null);
          g.onerror = () => ok(null);
        } catch {
          ok(null);
        }
      };
    } catch {
      ok(null);
    }
  });
}

function b64urlParaBytes(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function apiSw(token, metodo, caminho, corpo) {
  const url = new URL(caminho, self.location.origin).href;
  const opc = { method: metodo, headers: { Authorization: `Bearer ${token}` } };
  if (corpo !== undefined) {
    opc.headers["Content-Type"] = "application/json";
    opc.body = JSON.stringify(corpo);
  }
  const r = await fetch(url, opc);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.status === 204 ? null : r.json().catch(() => null);
}

/**
 * O navegador trocou (ou perdeu) a assinatura: assina de novo com a chave do servidor
 * (`GET /v1/push/chave`; recai na da assinatura velha) e manda a nova em `POST /v1/push/assinar`.
 * A velha sai com `DELETE` (melhor esforço; o servidor também a apaga no 404/410). Sem token
 * (aparelho desconectado) não faz nada. Devolve `"reassinou" | "nada"`.
 */
async function reassinarNoSw(e) {
  const token = await lerKv("token");
  if (!token) return "nada";
  const velha = e.oldSubscription ?? null;
  let nova = e.newSubscription ?? null;
  if (!nova) {
    let chave = null;
    try {
      chave = b64urlParaBytes((await apiSw(token, "GET", "/v1/push/chave"))?.chave ?? "");
    } catch {
      chave = null;
    }
    if (!chave?.length) chave = velha?.options?.applicationServerKey ?? null;
    if (!chave) return "nada";
    nova = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chave });
  }
  await apiSw(token, "POST", "/v1/push/assinar", nova.toJSON());
  if (velha?.endpoint && velha.endpoint !== nova.endpoint) {
    await apiSw(token, "DELETE", "/v1/push/assinar", { endpoint: velha.endpoint }).catch(() => {});
  }
  return "reassinou";
}

self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil(reassinarNoSw(e).catch(() => "nada"));
});
