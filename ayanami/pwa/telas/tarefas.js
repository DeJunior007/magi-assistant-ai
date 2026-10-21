/**
 * Tela Tarefas (spec §14.2, §2.2 `/v1/tarefas*`). Dono: P1.4.
 *
 * `#/tarefas`: `GET /v1/tarefas?n=50` agrupada por estado (rodando, na fila, prontas, falharam,
 * canceladas), com barra de progresso, idade ("há 5 min") e a `frase`. Recarrega no SSE `evento`
 * de tarefa (`tarefa_pronta`/`tarefa_falhou` ou `ref` `tarefa:`).
 * `#/tarefas/<id>`: `GET /v1/tarefas/{id}` (resultado ou erro) e **cancelar** = `DELETE`
 * (`202` → `cancelando`/`cancelada`; `409` → "já terminou").
 * Relógio injetável: `ctx.agora()` (ms).
 */

export const ORDEM = Object.freeze(["rodando", "na_fila", "ok", "falhou", "cancelada"]);
export const ROTULO = Object.freeze({
  rodando: "Rodando", na_fila: "Na fila", ok: "Prontas", falhou: "Falharam", cancelada: "Canceladas",
  cancelando: "Cancelando",
});
const ATIVAS = new Set(["rodando", "na_fila"]);

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

/** Idade legível de `iso` em relação a `agora` (ms). */
export function idade(iso, agora = Date.now()) {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((agora - t) / 1000));
  if (s < 60) return "agora";
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m} min`;
  const hh = Math.floor(m / 60);
  if (hh < 24) return `há ${hh} h`;
  return `há ${Math.floor(hh / 24)} d`;
}

/** `[TarefaOut]` → `[[estado, [TarefaOut]]]` na `ORDEM` (estados vazios fora; desconhecidos no fim). */
export function agrupar(tarefas) {
  const grupos = new Map();
  for (const t of tarefas) {
    if (!grupos.has(t.estado)) grupos.set(t.estado, []);
    grupos.get(t.estado).push(t);
  }
  const chaves = [...ORDEM.filter((e) => grupos.has(e)), ...[...grupos.keys()].filter((e) => !ORDEM.includes(e))];
  return chaves.map((e) => [e, grupos.get(e)]);
}

const eDeTarefa = (ev) =>
  ev && (String(ev.tipo ?? "").startsWith("tarefa") || String(ev.ref ?? "").startsWith("tarefa:"));

export function montar(el, ctx) {
  const doc = el.ownerDocument;
  if (!doc?.createElement) {
    el.textContent = "Tarefas"; // sem DOM (teste dos stubs do P1.1)
    return () => {};
  }
  const agora = ctx.agora ?? (() => Date.now());
  const id = ctx.params?.id;
  const msg = h(doc, "p", { className: "aviso", hidden: true, dataset: { campo: "aviso" } });
  const corpo = h(doc, "div", { dataset: { campo: "corpo" } });
  el.append(h(doc, "h1", { textContent: id ? "Tarefa" : "Tarefas" }), msg, corpo);
  let vivo = true;

  const avisar = (texto) => {
    msg.textContent = texto;
    msg.hidden = !texto;
  };
  const erroTexto = (e) => (e?.status ? e?.corpo?.msg || `HTTP ${e.status}` : "Sem conexão com a Ayanami.");

  function barra(t) {
    if (t.progresso == null) return null;
    return h(doc, "progress", { max: 100, value: t.progresso, textContent: `${t.progresso}%` });
  }

  async function lista() {
    try {
      const r = await ctx.api.get("/v1/tarefas?n=50");
      if (!vivo) return;
      avisar("");
      const grupos = agrupar(r?.tarefas ?? []);
      corpo.replaceChildren();
      if (!grupos.length) corpo.append(h(doc, "p", { textContent: "Nenhuma tarefa." }));
      for (const [estado, ts] of grupos) {
        const ol = h(doc, "ul", { className: "tarefas" });
        for (const t of ts) {
          ol.append(
            h(
              doc, "li", { dataset: { tarefa: t.id, estado } },
              h(doc, "a", { href: `#/tarefas/${encodeURIComponent(t.id)}`, textContent: t.titulo || t.tipo || t.id }),
              barra(t),
              h(doc, "small", { textContent: idade(t.criada, agora()) }),
              t.frase ? h(doc, "p", { textContent: t.frase }) : null,
            ),
          );
        }
        corpo.append(h(doc, "section", { dataset: { grupo: estado } }, h(doc, "h2", { textContent: `${ROTULO[estado] ?? estado} (${ts.length})` }), ol));
      }
    } catch (e) {
      if (vivo) avisar(erroTexto(e));
    }
  }

  async function detalhe() {
    let t;
    try {
      t = await ctx.api.get(`/v1/tarefas/${encodeURIComponent(id)}`);
    } catch (e) {
      if (vivo) avisar(e?.status === 404 ? "Tarefa não encontrada." : erroTexto(e));
      return;
    }
    if (!vivo) return;
    const estadoEl = h(doc, "p", { textContent: ROTULO[t.estado] ?? t.estado, dataset: { campo: "estado" } });
    const cancelar = h(doc, "button", {
      type: "button", className: "precisa-rede", textContent: "Cancelar", hidden: !ATIVAS.has(t.estado),
      dataset: { acao: "cancelar" }, on: { click: aoCancelar },
    });
    async function aoCancelar() {
      cancelar.disabled = true;
      try {
        const r = await ctx.api.del(`/v1/tarefas/${encodeURIComponent(id)}`);
        if (!vivo) return;
        estadoEl.textContent = ROTULO[r?.estado] ?? r?.estado ?? "Cancelando";
        cancelar.hidden = true;
        avisar("");
      } catch (e) {
        if (!vivo) return;
        if (e?.status === 409) {
          avisar("Essa tarefa já terminou.");
          cancelar.hidden = true;
        } else {
          avisar(erroTexto(e));
          cancelar.disabled = false;
        }
      }
    }
    corpo.replaceChildren(...[
      h(doc, "h2", { textContent: t.titulo || t.tipo || t.id }),
      estadoEl,
      barra(t),
      h(doc, "small", { textContent: `criada ${idade(t.criada, agora())}` }),
      t.frase ? h(doc, "p", { textContent: t.frase }) : null,
      t.resultado?.texto ? h(doc, "p", { className: "resultado", textContent: t.resultado.texto, dataset: { campo: "resultado" } }) : null,
      t.erro ? h(doc, "p", { className: "erro", textContent: t.erro, dataset: { campo: "erro" } }) : null,
      cancelar,
      h(doc, "a", { href: "#/tarefas", textContent: "← tarefas" }),
    ].filter(Boolean));
  }

  const pronto = id ? detalhe() : lista();
  const sair = ctx.eventos?.on?.("evento", (ev) => {
    if (vivo && eDeTarefa(ev)) (id ? detalhe : lista)();
  });
  const desmontar = () => {
    vivo = false;
    sair?.();
  };
  desmontar.pronto = pronto;
  return desmontar;
}
