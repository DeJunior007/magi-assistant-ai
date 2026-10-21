/**
 * Casca do PWA (spec §14.1, §14.3). Dono: P1.1.
 *
 * Roteador por hash: `#/conversa | tv/<id> | feed | tarefas[/<id>] | confirma/<ulid> | ajustes |
 * parear[?c=123456]`. Estados globais em `estado.conexao`: `sem_token` → Parear, `conectando`,
 * `ok_pc`, `ok_nuvem`, `sem_ayanami` (faixa "sem conexão com a Ayanami — ligue o Tailscale");
 * `estado.casa_fora` vem de `online.casa` do `/saude`. `/saude` com timeout de 4 s na abertura,
 * a cada `visibilitychange` para visível e a cada 30 s; 401 em qualquer chamada → apaga o token e
 * vai a Parear.
 *
 * Contrato das telas (`telas/<nome>.js`): `export function montar(el, ctx)`, que pode devolver uma
 * função de desmontagem. `ctx` = `{api, estado, eventos, params, navegar, armazem, verificar}`;
 * `eventos.on(nome, fn)` recebe o SSE de `/v1/eventos` (`turno.texto`, `turno.fim`, `evento`,
 * `estado`, `confirma`).
 *
 * Integração (P1.x): na subida as `preferencias` do armazém viram `estado.prefs` (e cada gravação
 * delas pelo `ctx.armazem` atualiza o estado); um SSE `confirma` fora da tela Confirmação leva a
 * `rotaDe(c)`; `reassinarSeMudou` (Ajustes, P2.2) roda na subida, sem pedir permissão.
 */

import { armazemIdb, armazemMemoria, criarApi } from "./api.js";
import { estado as estadoPadrao } from "./estado.js";
import { CHAVE_PREFS, normalizarPrefs, reassinarSeMudou } from "./telas/ajustes.js";
import { rotaDe } from "./telas/confirma.js";

export const TELAS = Object.freeze(["conversa", "tv", "feed", "tarefas", "confirma", "ajustes", "parear"]);
export const FAIXA_SEM_AYANAMI = "sem conexão com a Ayanami — ligue o Tailscale";
export const INTERVALO_SAUDE_MS = 30000;

/** `"#/tv/sala?x=1"` → `{tela: "tv", params: {id: "sala", x: "1"}}`; desconhecida → conversa. */
export function rota(hash = "") {
  const semCerquilha = String(hash).replace(/^#\/?/, "");
  const [caminho, busca = ""] = semCerquilha.split("?");
  const partes = caminho.split("/").filter(Boolean).map(decodeURIComponent);
  const params = Object.fromEntries(new URLSearchParams(busca));
  const tela = partes[0];
  if (!TELAS.includes(tela)) return { tela: "conversa", params: {} };
  if (partes[1] !== undefined && ["tv", "tarefas", "confirma"].includes(tela)) params.id = partes[1];
  if (tela === "confirma" && !params.id) return { tela: "conversa", params: {} };
  return { tela, params };
}

/** Resultado de `api.saude()` → `{conexao, casa_fora}`. */
export function conexaoDaSaude(res) {
  if (!res || !res.ok || !res.dados) return { conexao: "sem_ayanami", casa_fora: false };
  const online = res.dados.online || {};
  return { conexao: online.pc ? "ok_pc" : "ok_nuvem", casa_fora: online.casa === false };
}

function criarBarramento() {
  const mapa = new Map();
  return {
    on(nome, fn) {
      if (!mapa.has(nome)) mapa.set(nome, new Set());
      mapa.get(nome).add(fn);
      return () => mapa.get(nome).delete(fn);
    },
    emitir(nome, dados, id) {
      for (const fn of [...(mapa.get(nome) || [])]) fn(dados, id);
      for (const fn of [...(mapa.get("*") || [])]) fn(nome, dados, id);
    },
  };
}

export function criarApp({
  janela = globalThis.window,
  documento = globalThis.document,
  estado = estadoPadrao,
  api = null,
  armazem = null,
  reassinar = reassinarSeMudou,
  push = undefined,
  carregarTela = (nome) => import(`./telas/${nome}.js`),
  intervaloMs = INTERVALO_SAUDE_MS,
} = {}) {
  const eventos = criarBarramento();
  let sse = null;
  let relogio = null;
  let desmontar = null;
  let montagem = 0;

  const navegar = (hash) => {
    if (janela.location.hash === hash) aoMudarHash();
    else janela.location.hash = hash;
  };

  function irParear() {
    pararSse();
    estado.set({ conexao: "sem_token" });
    if (rota(janela.location.hash).tela !== "parear") navegar("#/parear");
  }

  const base = armazem ?? (globalThis.indexedDB ? armazemIdb() : armazemMemoria());
  api ??= criarApi({ armazem: base, aoNaoAutorizado: irParear });

  /** O armazém das telas: gravar as `preferencias` também atualiza `estado.prefs`. */
  const armazemCtx = {
    ler: (k) => base.ler(k),
    apagar: (k) => base.apagar(k),
    async gravar(k, v) {
      await base.gravar(k, v);
      if (k === CHAVE_PREFS) estado.set({ prefs: normalizarPrefs(v) });
    },
  };

  async function carregarPrefs() {
    let p;
    try {
      p = await base.ler(CHAVE_PREFS);
    } catch {
      p = null; // armazém indisponível: fica nos padrões
    }
    estado.set({ prefs: normalizarPrefs(p) });
  }

  eventos.on("confirma", (c) => {
    if (!c?.pedido || c.resposta != null) return;
    if (estado.get().rota?.tela !== "confirma") navegar(rotaDe(c));
  });

  function pararSse() {
    sse?.parar();
    sse = null;
  }

  function iniciarSse() {
    if (sse) return;
    sse = api.eventos((nome, dados, id) => eventos.emitir(nome, dados, id));
  }

  /** Confere token e `/saude`; atualiza `conexao`/`casa_fora`/`saude`. */
  async function verificar() {
    if (!(await api.token())) return irParear();
    if (estado.get().conexao === "sem_token") estado.set({ conexao: "conectando" });
    const res = await api.saude();
    if (!(await api.token())) return irParear();
    estado.set({ ...conexaoDaSaude(res), saude: res.dados ?? null });
    if (estado.get().conexao === "sem_ayanami") pararSse();
    else iniciarSse();
  }

  function desenharFaixa(s) {
    const faixa = documento.getElementById("faixa");
    if (faixa) {
      const sem = s.conexao === "sem_ayanami";
      faixa.hidden = !sem;
      faixa.textContent = sem ? FAIXA_SEM_AYANAMI : "";
    }
    if (documento.body?.dataset) {
      documento.body.dataset.conexao = s.conexao;
      documento.body.dataset.casa = s.casa_fora ? "fora" : "ok";
    }
  }

  async function aoMudarHash() {
    const r = rota(janela.location.hash);
    if (r.tela !== "parear" && estado.get().conexao === "sem_token") return navegar("#/parear");
    estado.set({ rota: r });
    const minha = ++montagem;
    desmontar?.();
    desmontar = null;
    const el = documento.getElementById("tela");
    const mod = await carregarTela(r.tela);
    if (minha !== montagem || !el) return;
    el.replaceChildren?.();
    if (el.dataset) el.dataset.tela = r.tela;
    const ctx = { api, estado, eventos, params: r.params, navegar, armazem: armazemCtx, verificar };
    if (push !== undefined) ctx.push = push;
    const fim = mod.montar(el, ctx);
    desmontar = typeof fim === "function" ? fim : null;
  }

  const aoVisibilidade = () => {
    if (documento.visibilityState === "visible") verificar();
  };

  async function iniciar() {
    estado.subscribe(desenharFaixa);
    desenharFaixa(estado.get());
    janela.addEventListener("hashchange", aoMudarHash);
    janela.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault?.();
      estado.set({ instalar: e });
    });
    documento.addEventListener("visibilitychange", aoVisibilidade);
    janela.navigator?.serviceWorker?.register("sw.js", { scope: "./" }).catch(() => {});
    relogio = janela.setInterval(() => {
      if (documento.visibilityState !== "hidden") verificar();
    }, intervaloMs);
    await carregarPrefs();
    if (!(await api.token())) estado.set({ conexao: "sem_token" });
    if (!janela.location.hash) janela.location.hash = "#/conversa";
    await aoMudarHash();
    await verificar();
    if (estado.get().conexao !== "sem_token") {
      const ctxPush = { api, armazem: armazemCtx };
      if (push !== undefined) ctxPush.push = push;
      // sem await: `serviceWorker.ready` pode nunca resolver (SW não registrado)
      Promise.resolve().then(() => reassinar(ctxPush)).catch(() => {});
    }
  }

  function parar() {
    janela.clearInterval(relogio);
    janela.removeEventListener("hashchange", aoMudarHash);
    documento.removeEventListener("visibilitychange", aoVisibilidade);
    pararSse();
    desmontar?.();
  }

  return { iniciar, parar, verificar, navegar, irParear, aoMudarHash, eventos, api, estado, armazem: armazemCtx };
}

if (typeof window !== "undefined" && typeof document !== "undefined" && !globalThis.__CONDESSA_TESTE__) {
  criarApp().iniciar();
}
