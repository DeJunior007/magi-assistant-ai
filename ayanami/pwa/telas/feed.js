/**
 * Tela Feed (spec §14.2, §2.2 `GET /v1/feed`, CA-Y56). Dono: P1.4.
 *
 * Cards da Ayanami (notícia, tarefa, lembrete) com rolagem infinita: `GET /v1/feed?n=20` e depois
 * `&antes=<ts do último card>` (pelo `IntersectionObserver` do sentinela ou pelo botão "carregar
 * mais"). Sem rede (o `fetch` falha) → lê a cópia que o `sw.js` guarda em `condessa-feed`
 * (chave `/v1/feed`) e mostra "sem conexão — feed guardado às HH:MM" (cabeçalho
 * `X-Condessa-Cache-Em`); resposta servida pelo SW da cópia também traz o cabeçalho e o aviso.
 * Ao voltar a conexão (`estado.conexao` sai de `sem_ayanami`), recarrega.
 */

export const POR_PAGINA = 20;
export const CACHE_FEED = "condessa-feed";
export const CHAVE_FEED = "/v1/feed";
export const CAB_CACHE = "X-Condessa-Cache-Em";

function h(doc, tag, props = {}, ...filhos) {
  const e = doc.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k in e || k === "textContent" || k === "className") e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const f of filhos) if (f != null) e.append(f);
  return e;
}

const dois = (n) => String(n).padStart(2, "0");

/** ISO → "HH:MM" no fuso do aparelho ("" se inválido). */
export function horaCurta(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : `${dois(d.getHours())}:${dois(d.getMinutes())}`;
}

/** `ref` do card → link: URL http(s), `tarefa:<id>` → `#/tarefas/<id>`, `confirma:<id>`. */
export function linkDoCard(ref) {
  if (typeof ref !== "string" || !ref) return null;
  if (/^https?:\/\//i.test(ref)) return { href: ref, externo: true };
  const [tipo, id] = ref.split(":", 2);
  if (tipo === "tarefa" && id) return { href: `#/tarefas/${encodeURIComponent(id)}`, externo: false };
  if (tipo === "confirma" && id) return { href: `#/confirma/${encodeURIComponent(id)}`, externo: false };
  return null;
}

/** Lê a cópia do feed guardada pelo SW; `{cards, em}` ou null. */
export async function feedDoCache(cachesApi = globalThis.caches) {
  try {
    if (!cachesApi) return null;
    const cache = await cachesApi.open(CACHE_FEED);
    const r = await cache.match(CHAVE_FEED);
    if (!r) return null;
    const dados = await r.json();
    return { cards: dados?.cards ?? [], em: r.headers.get(CAB_CACHE) };
  } catch {
    return null;
  }
}

/**
 * Uma página do feed. `{cards, em}`: `em` = ISO da cópia quando veio do cache (SW ou recaída
 * local), `null` quando veio da rede. Lança `ErroApi` em status ≠ 2xx.
 */
export async function buscarFeed(api, { antes = null, n = POR_PAGINA, caches: cachesApi } = {}) {
  const q = new URLSearchParams({ n: String(n) });
  if (antes) q.set("antes", antes);
  let r;
  try {
    r = await api.bruto(`/v1/feed?${q}`, { headers: { Accept: "application/json" } });
  } catch (erro) {
    if (antes) throw erro; // sem rede no meio da rolagem: fica o que já está na tela
    const guardado = await feedDoCache(cachesApi);
    if (guardado) return guardado;
    throw erro;
  }
  if (!r.ok) {
    let corpo = null;
    try {
      corpo = await r.json();
    } catch {
      corpo = null;
    }
    const e = new Error(corpo?.msg || `HTTP ${r.status}`);
    e.status = r.status;
    e.corpo = corpo;
    throw e;
  }
  const dados = await r.json();
  return { cards: dados?.cards ?? [], em: r.headers.get(CAB_CACHE) };
}

export function montar(el, ctx) {
  const doc = el.ownerDocument;
  if (!doc?.createElement) {
    el.textContent = "Feed"; // sem DOM (teste dos stubs do P1.1)
    return () => {};
  }
  const cachesApi = ctx.caches ?? globalThis.caches;
  const aviso = h(doc, "p", { className: "aviso", hidden: true, dataset: { campo: "aviso" } });
  const lista = h(doc, "ol", { className: "cards", dataset: { campo: "cards" } });
  const vazio = h(doc, "p", { textContent: "Nada no feed ainda.", hidden: true, dataset: { campo: "vazio" } });
  const mais = h(doc, "button", {
    type: "button", className: "precisa-rede", textContent: "Carregar mais", hidden: true,
    dataset: { acao: "mais" }, on: { click: () => carregar(false) },
  });
  el.append(h(doc, "h1", { textContent: "Feed" }), aviso, lista, vazio, mais);

  let vivo = true;
  let ocupado = false;
  let fim = false;
  let ultimoTs = null;
  let doCache = false;

  function card(c) {
    const link = linkDoCard(c.ref);
    const titulo = link
      ? h(doc, "a", { href: link.href, textContent: c.titulo ?? "", ...(link.externo ? { target: "_blank", rel: "noopener" } : {}) })
      : h(doc, "span", { textContent: c.titulo ?? "" });
    return h(
      doc, "li", { className: `card card-${c.tipo ?? "noticia"}`, dataset: { tipo: c.tipo ?? "" } },
      h(doc, "h2", {}, titulo),
      c.resumo ? h(doc, "p", { textContent: c.resumo }) : null,
      h(doc, "time", { dateTime: c.ts ?? "", textContent: horaCurta(c.ts) }),
    );
  }

  /** `primeira`: recomeça do topo. */
  async function carregar(primeira = true) {
    if (ocupado || (!primeira && (fim || doCache))) return;
    ocupado = true;
    try {
      const pag = await buscarFeed(ctx.api, { antes: primeira ? null : ultimoTs, caches: cachesApi });
      if (!vivo) return;
      if (primeira) lista.replaceChildren();
      for (const c of pag.cards) lista.append(card(c));
      if (pag.cards.length) ultimoTs = pag.cards[pag.cards.length - 1].ts ?? ultimoTs;
      doCache = Boolean(pag.em);
      fim = doCache || pag.cards.length < POR_PAGINA;
      aviso.hidden = !doCache;
      aviso.textContent = doCache ? `Sem conexão — feed guardado às ${horaCurta(pag.em) || "?"}` : "";
      vazio.hidden = lista.children.length > 0;
      mais.hidden = fim;
    } catch (e) {
      if (!vivo) return;
      if (primeira) {
        aviso.hidden = false;
        aviso.textContent = e?.status ? `Feed indisponível (HTTP ${e.status}).` : "Sem conexão e sem feed guardado.";
      }
    } finally {
      ocupado = false;
    }
  }

  let observador = null;
  const sentinela = h(doc, "div", { className: "sentinela" });
  el.append(sentinela);
  const IO = ctx.IntersectionObserver ?? globalThis.IntersectionObserver;
  if (IO) {
    observador = new IO((itens) => {
      if (itens.some((i) => i.isIntersecting)) carregar(false);
    });
    observador.observe(sentinela);
  }

  const sair = ctx.estado.subscribe((novo, antigo) => {
    if (antigo.conexao === "sem_ayanami" && novo.conexao !== "sem_ayanami" && novo.conexao !== "sem_token") carregar(true);
  });

  const pronto = carregar(true);
  const desmontar = () => {
    vivo = false;
    sair();
    observador?.disconnect?.();
  };
  desmontar.pronto = pronto;
  desmontar.carregar = carregar;
  return desmontar;
}
