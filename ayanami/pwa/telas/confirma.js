/**
 * Tela Confirmação (spec §14.2, §2.2 `POST /v1/confirma/{pedido}`, `Confirma` da §1.2). Dono: P1.4.
 *
 * Card de `#/confirma/<ulid>[?d=<descrição>&expira=<ISO>]` (link do push/feed) e de cada SSE
 * `confirma` que chega com a tela aberta. "Confirmar"/"Recusar" → `POST` `{"resposta":bool}`:
 * `200` → feito; `410` (ou `expira_em` vencido no relógio local) → "expirou"; `409` → "já
 * respondida". As confirmações vistas pelo SSE ficam em `CONFIRMAS` (descrição para a rota).
 * Relógio injetável: `ctx.agora()` (ms) e `ctx.agendar(fn, ms)`.
 */

export const CONFIRMAS = new Map();
export const TEXTO_EXPIROU = "expirou";

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

/** `Confirma` → hash da rota (para o app/push abrirem o card). */
export function rotaDe(c) {
  const q = new URLSearchParams();
  if (c.descricao) q.set("d", c.descricao);
  if (c.expira_em) q.set("expira", c.expira_em);
  const s = q.toString();
  return `#/confirma/${encodeURIComponent(c.pedido)}${s ? "?" + s : ""}`;
}

export function montar(el, ctx) {
  const doc = el.ownerDocument;
  if (!doc?.createElement) {
    el.textContent = "Confirmação"; // sem DOM (teste dos stubs do P1.1)
    return () => {};
  }
  const agora = ctx.agora ?? (() => Date.now());
  const agendar = ctx.agendar ?? ((fn, ms) => setTimeout(fn, ms));
  const cancelar = ctx.cancelar ?? ((t) => clearTimeout(t));
  const lista = h(doc, "div", { className: "confirmas", dataset: { campo: "confirmas" } });
  el.append(h(doc, "h1", { textContent: "Confirmação" }), lista);
  const cards = new Map();
  const timers = new Set();
  let vivo = true;

  function card(c) {
    if (!c?.pedido || cards.has(c.pedido) || c.resposta != null) return;
    const estadoEl = h(doc, "p", { className: "estado", dataset: { campo: "estado" } });
    const sim = h(doc, "button", { type: "button", className: "precisa-rede", textContent: "Confirmar", dataset: { acao: "sim" } });
    const nao = h(doc, "button", { type: "button", className: "precisa-rede", textContent: "Recusar", dataset: { acao: "nao" } });
    const raiz = h(
      doc, "article", { className: "card confirma", dataset: { pedido: c.pedido } },
      h(doc, "h2", { textContent: c.descricao ? `${c.descricao[0].toUpperCase()}${c.descricao.slice(1)}?` : "Confirmar o pedido?" }),
      c.origem ? h(doc, "small", { textContent: `pedido por: ${c.origem}` }) : null,
      estadoEl, sim, nao,
    );
    const fechar = (texto) => {
      estadoEl.textContent = texto;
      sim.disabled = nao.disabled = true;
      raiz.dataset.fim = texto;
    };
    const expiraMs = c.expira_em ? new Date(c.expira_em).getTime() : NaN;
    if (!Number.isNaN(expiraMs)) {
      const resta = expiraMs - agora();
      if (resta <= 0) fechar(TEXTO_EXPIROU);
      else {
        const t = agendar(() => {
          timers.delete(t);
          if (vivo && !raiz.dataset.fim) fechar(TEXTO_EXPIROU);
        }, resta);
        timers.add(t);
      }
    }
    async function responder(resposta) {
      if (raiz.dataset.fim) return;
      sim.disabled = nao.disabled = true;
      try {
        await ctx.api.post(`/v1/confirma/${encodeURIComponent(c.pedido)}`, { resposta });
        if (vivo) fechar(resposta ? "confirmado" : "recusado");
        CONFIRMAS.delete(c.pedido);
      } catch (e) {
        if (!vivo) return;
        if (e?.status === 410) fechar(TEXTO_EXPIROU);
        else if (e?.status === 409) fechar("já respondida");
        else {
          estadoEl.textContent = e?.status ? `falhou (HTTP ${e.status})` : "sem conexão; tente de novo";
          sim.disabled = nao.disabled = false;
        }
      }
    }
    sim.addEventListener("click", () => responder(true));
    nao.addEventListener("click", () => responder(false));
    cards.set(c.pedido, raiz);
    lista.append(raiz);
  }

  const id = ctx.params?.id;
  if (id) {
    const visto = CONFIRMAS.get(id);
    card({
      pedido: id,
      descricao: ctx.params.d ?? visto?.descricao ?? "",
      origem: visto?.origem ?? "",
      expira_em: ctx.params.expira ?? visto?.expira_em ?? null,
    });
  }
  const sair = ctx.eventos?.on?.("confirma", (c) => {
    if (!c?.pedido || c.resposta != null) return;
    CONFIRMAS.set(c.pedido, c);
    if (vivo) card(c);
  });
  return () => {
    vivo = false;
    sair?.();
    for (const t of timers) cancelar(t);
    timers.clear();
  };
}
