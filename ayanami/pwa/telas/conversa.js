/**
 * Tela Conversa (spec §14.2 Conversa, §14.4, §14.5; R7.2, R7.3). Dono: P1.2.
 *
 * - histórico do dia (texto) no armazém, chave `conversa` (`{dia, itens:[{quem, texto, hora}]}`);
 * - rosto por estado do PTT (`rosto/{dormindo,ouvindo,pensando,falando}.webp`);
 * - selo PC ou nuvem pelo `modo` do `POST /v1/turno` (`202 {"turno","modo"}`);
 * - campo de texto (`POST /v1/turno` JSON) e botão "segurar para falar" (`gravador.js`, multipart);
 * - o texto chega pelo SSE (`ctx.eventos`: `turno.texto` `{turno, texto}`, `turno.fim` `TurnoFim`)
 *   e é desenhado assim que chega; eventos que chegam antes do 202 ficam guardados pelo id;
 * - o `<audio>` é criado no gesto (destrava o autoplay) e toca `GET /v1/turno/{id}/audio`, lido
 *   por `api.bruto` (o `<audio src>` não manda o Bearer) e entregue como `blob:`; turno de texto
 *   só toca se a pref `voz_em_texto` estiver ligada;
 * - 50 s sem `turno.fim` → "Ela não respondeu; tenta de novo?".
 *
 * `ctx` = `{api, estado, eventos, ...}` do `app.js`, mais (opcionais, para teste) `armazem`,
 * `relogio` `{agora, agendar, cancelar}`, `midia`, `MediaRecorder`, `criarAudio()`, `URL`, `hoje()`.
 */

import { armazemIdb, armazemMemoria } from "../api.js";
import * as gravador from "../gravador.js";

export const CHAVE_HISTORICO = "conversa";
export const PRAZO_MS = 50000;
export const SEM_RESPOSTA = "Ela não respondeu; tenta de novo?";
export const ROSTO = Object.freeze({
  ocioso: "dormindo",
  gravando: "ouvindo",
  enviando: "pensando",
  pensando: "pensando",
  falando: "falando",
});
const ERROS = {
  pc_caiu: "perdi o PC no meio; repete?",
  tempo: SEM_RESPOSTA,
};
const MAX_ITENS = 200;

const relogioReal = {
  agora: () => Date.now(),
  agendar: (fn, ms) => setTimeout(fn, ms),
  cancelar: (t) => clearTimeout(t),
};

function diaLocal(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function armazemDe(ctx) {
  if (ctx.armazem) return ctx.armazem;
  return globalThis.indexedDB ? armazemIdb() : armazemMemoria();
}

function h(doc, tag, props = {}, ...filhos) {
  const e = doc.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "dataset") Object.assign(e.dataset, v);
    else if (k === "class") e.className = v;
    else e[k] = v;
  }
  e.append(...filhos);
  return e;
}

/** Texto do `TurnoFim` para o balão (erro vira frase curta). */
export function textoDoFim(fim) {
  if (!fim) return "";
  if (fim.ok === false) return ERROS[fim.erro] ?? (fim.texto || "não deu certo; tenta de novo?");
  return fim.texto || fim.fala || "";
}

export function montar(el, ctx = {}) {
  const doc = el.ownerDocument;
  if (!doc?.createElement) {
    el.textContent = "Conversa";
    return () => {};
  }
  const { api, estado, eventos } = ctx;
  const relogio = ctx.relogio ?? relogioReal;
  const armazem = armazemDe(ctx);
  const URLs = ctx.URL ?? globalThis.URL;
  const criarAudio = ctx.criarAudio ?? (() => (globalThis.Audio ? new globalThis.Audio() : doc.createElement("audio")));
  const hoje = ctx.hoje ?? (() => diaLocal(relogio.agora()));

  // ---------- DOM
  const selo = h(doc, "span", { class: "selo", dataset: { papel: "selo" }, hidden: true });
  const rosto = h(doc, "img", { class: "rosto", dataset: { papel: "rosto" }, alt: "Condessa" });
  const historico = h(doc, "ol", { class: "historico", dataset: { papel: "historico" } });
  const aviso = h(doc, "p", { class: "aviso", dataset: { papel: "aviso" }, hidden: true });
  const toast = h(doc, "p", { class: "toast", dataset: { papel: "toast" }, hidden: true });
  const campo = h(doc, "input", { type: "text", placeholder: "escreva aqui", dataset: { papel: "texto" } });
  const enviar = h(doc, "button", { type: "submit", class: "precisa-rede", dataset: { papel: "enviar" } }, "enviar");
  const form = h(doc, "form", { class: "campo-texto", dataset: { papel: "form" } }, campo, enviar);
  const areaPtt = h(doc, "div", { class: "area-ptt", dataset: { papel: "area-ptt" } });
  el.append(h(doc, "header", { class: "conversa-topo" }, rosto, selo), historico, aviso, toast, areaPtt, form);

  // ---------- estado da tela
  let vivo = true;
  let itens = [];
  let audio = null; // `<audio>` criado no gesto do turno atual
  let urlAudio = null;
  let atual = null; // {id, voz, prazo, balao, fim}
  const pendentes = new Map(); // eventos do SSE que chegaram antes do 202
  let toastT = null;

  function mostrarToast(msg) {
    toast.textContent = msg;
    toast.hidden = false;
    if (toastT !== null) relogio.cancelar(toastT);
    toastT = relogio.agendar(() => {
      toastT = null;
      toast.hidden = true;
    }, 3000);
  }

  function rostoDe(s) {
    rosto.src = `rosto/${ROSTO[s] ?? "dormindo"}.webp`;
    rosto.dataset.estado = s;
    areaPtt.dataset.estado = s;
  }

  function desenharItem(it) {
    const li = h(doc, "li", { class: `fala ${it.quem}`, dataset: { quem: it.quem } }, it.texto);
    historico.append(li);
    return li;
  }

  function guardar() {
    const dia = hoje();
    Promise.resolve(armazem.gravar(CHAVE_HISTORICO, { dia, itens: itens.slice(-MAX_ITENS) })).catch(() => {});
  }

  function acrescentar(quem, texto) {
    const it = { quem, texto, hora: relogio.agora() };
    itens.push(it);
    guardar();
    return { it, li: desenharItem(it) };
  }

  function atualizar(balao, texto) {
    balao.it.texto = texto;
    balao.li.textContent = texto;
    guardar();
  }

  // histórico do dia (o de ontem é descartado)
  Promise.resolve(armazem.ler(CHAVE_HISTORICO))
    .then((h0) => {
      if (!vivo || !h0 || h0.dia !== hoje() || !Array.isArray(h0.itens)) return;
      const novos = itens;
      itens = [...h0.itens, ...novos];
      historico.replaceChildren();
      for (const it of itens) desenharItem(it);
      for (const n of novos) {
        // os balões criados antes da leitura foram redesenhados: reaponta
        if (atual?.balao?.it === n) atual.balao.li = historico.children[itens.indexOf(n)];
      }
    })
    .catch(() => {});

  function prefs() {
    return estado?.get?.().prefs ?? {};
  }

  function liberarAudio() {
    if (urlAudio && URLs?.revokeObjectURL) URLs.revokeObjectURL(urlAudio);
    urlAudio = null;
  }

  /** Cria (ou reaproveita) o `<audio>` dentro do gesto e o "destrava". */
  function audioNoGesto() {
    try {
      audio ??= criarAudio();
      const p = audio.play?.();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } catch {
      /* sem áudio, segue com texto */
    }
  }

  async function tocar(id) {
    if (!audio || !api?.bruto) return false;
    try {
      const r = await api.bruto(`/v1/turno/${encodeURIComponent(id)}/audio`);
      if (!r.ok || !vivo || atual?.id !== id) return false;
      const blob = await r.blob();
      if (!vivo || atual?.id !== id) return false;
      liberarAudio();
      urlAudio = URLs.createObjectURL(blob);
      audio.src = urlAudio;
      g.falando();
      const fim = () => {
        if (atual?.id === id || !atual) g.pronto();
      };
      audio.onended = fim;
      audio.onerror = fim;
      await audio.play();
      return true;
    } catch {
      g.pronto();
      return false;
    }
  }

  function encerrarTurno(id) {
    if (atual?.id !== id) return;
    if (atual.prazo !== null) relogio.cancelar(atual.prazo);
    atual.prazo = null;
  }

  function aplicar(nome, dados) {
    if (!atual || dados?.turno !== atual.id) return;
    if (nome === "turno.texto") {
      if (!dados.texto) return;
      if (atual.balao) atualizar(atual.balao, dados.texto);
      else atual.balao = acrescentar("ela", dados.texto);
      return;
    }
    // turno.fim
    if (atual.fim) return;
    atual.fim = dados;
    encerrarTurno(atual.id);
    aviso.hidden = true;
    const texto = textoDoFim(dados);
    if (texto) {
      if (atual.balao) {
        if (atual.balao.it.texto !== texto) atualizar(atual.balao, texto);
      } else atual.balao = acrescentar(dados.ok === false ? "erro" : "ela", texto);
    }
    const querVoz = atual.voz || Boolean(prefs().voz_em_texto);
    if (dados.ok !== false && dados.audio && querVoz) tocar(atual.id);
    else g.pronto();
  }

  function aoSse(nome) {
    return (dados) => {
      if (!vivo || !dados?.turno) return;
      if (atual?.id === dados.turno) aplicar(nome, dados);
      else {
        const lista = pendentes.get(dados.turno) ?? [];
        lista.push([nome, dados]);
        pendentes.set(dados.turno, lista);
        if (pendentes.size > 20) pendentes.delete(pendentes.keys().next().value);
      }
    };
  }

  const cancelamentos = [];
  if (eventos?.on) {
    cancelamentos.push(eventos.on("turno.texto", aoSse("turno.texto")));
    cancelamentos.push(eventos.on("turno.fim", aoSse("turno.fim")));
  }

  function selar(modo) {
    if (modo !== "pc" && modo !== "nuvem") return;
    selo.hidden = false;
    selo.dataset.modo = modo;
    selo.textContent = modo === "pc" ? "PC" : "nuvem";
  }

  function comecar(resp, voz) {
    if (atual && atual.prazo !== null) relogio.cancelar(atual.prazo);
    const id = resp?.turno;
    atual = { id, voz, prazo: null, balao: null, fim: null };
    selar(resp?.modo);
    aviso.hidden = true;
    atual.prazo = relogio.agendar(() => {
      if (!vivo || atual?.id !== id || atual.fim) return;
      atual.prazo = null;
      aviso.textContent = SEM_RESPOSTA;
      aviso.hidden = false;
      g.pronto();
    }, PRAZO_MS);
    for (const [nome, dados] of pendentes.get(id) ?? []) aplicar(nome, dados);
    pendentes.delete(id);
  }

  function erroDe(e) {
    if (e?.status === 429) return "devagar: muitos pedidos por minuto";
    if (e?.status === 413) return "áudio longo demais";
    if (e?.status === 415) return "formato de áudio não aceito";
    if (e?.status === 0 || e instanceof TypeError) return "sem conexão com a Ayanami";
    return (e && e.corpo && e.corpo.msg) || "não deu para enviar";
  }

  // ---------- PTT
  const ptt = gravador.montar(areaPtt, {
    midia: "midia" in ctx ? ctx.midia : globalThis.navigator?.mediaDevices,
    MediaRecorder: "MediaRecorder" in ctx ? ctx.MediaRecorder : globalThis.MediaRecorder,
    relogio,
    aoEstado: (s) => rostoDe(s),
    aoToast: mostrarToast,
    aoGesto: audioNoGesto,
    aoBlob: async (blob) => {
      const fd = new FormData();
      fd.append("audio", blob, "fala.webm");
      let resp;
      try {
        resp = await api.post("/v1/turno", fd);
      } catch (e) {
        throw new Error(erroDe(e));
      }
      if (!vivo) return;
      acrescentar("eu", "(voz)");
      g.pensando();
      comecar(resp, true);
    },
  });
  const g = ptt.gravador;
  rostoDe("ocioso");

  // ---------- texto
  form.addEventListener("submit", async (e) => {
    e?.preventDefault?.();
    const texto = String(campo.value ?? "").trim();
    if (!texto || enviar.disabled) return;
    if (g.estado() === "gravando") return;
    if (prefs().voz_em_texto) audioNoGesto();
    campo.value = "";
    acrescentar("eu", texto);
    g.pensando();
    try {
      const resp = await api.post("/v1/turno", { texto });
      if (!vivo) return;
      comecar(resp, false);
    } catch (err) {
      if (!vivo) return;
      g.erro(erroDe(err));
    }
  });

  return () => {
    vivo = false;
    for (const c of cancelamentos) if (typeof c === "function") c();
    if (atual?.prazo != null) relogio.cancelar(atual.prazo);
    if (toastT !== null) relogio.cancelar(toastT);
    ptt.fechar();
    try {
      audio?.pause?.();
    } catch {
      /* nada */
    }
    liberarAudio();
  };
}
