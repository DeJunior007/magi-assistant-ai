// CA-Y56 (parte global) + estado.js/api.js com `fetch` falso, sem navegador. Dono: P1.1.
import { test } from "node:test";
import assert from "node:assert/strict";
import { criarEstado } from "../../../ayanami/pwa/estado.js";
import { armazemMemoria, criarApi, CHAVE_TOKEN, ErroApi } from "../../../ayanami/pwa/api.js";
import { criarApp, rota, conexaoDaSaude, FAIXA_SEM_AYANAMI } from "../../../ayanami/pwa/app.js";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
const SAUDE_OK = { ok: true, online: { pc: true, casa: true, celulares: 1 } };

function sseCorpo(texto) {
  const bytes = new TextEncoder().encode(texto);
  return new ReadableStream({
    start(c) {
      c.enqueue(bytes.subarray(0, 7)); // quebra no meio de uma linha
      c.enqueue(bytes.subarray(7));
      c.close();
    },
  });
}

// ---------- estado.js

test("estado: set junta, subscribe avisa só em mudança e cancela", () => {
  const e = criarEstado();
  const vistos = [];
  const sair = e.subscribe((novo, antigo) => vistos.push([antigo.conexao, novo.conexao]));
  e.set({ conexao: "ok_pc" });
  e.set({ conexao: "ok_pc" });
  assert.deepEqual(vistos, [["conectando", "ok_pc"]]);
  sair();
  e.set({ conexao: "sem_ayanami" });
  assert.equal(vistos.length, 1);
  assert.equal(e.get().conexao, "sem_ayanami");
  assert.ok(Object.isFrozen(e.get()));
});

// ---------- api.js

test("api: Bearer do armazém; 401 apaga o token e chama aoNaoAutorizado", async () => {
  const armazem = armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" });
  const vistos = [];
  let saiu = 0;
  const api = criarApi({
    armazem,
    aoNaoAutorizado: () => saiu++,
    fetch: async (url, o) => {
      vistos.push([url, o.headers.Authorization]);
      return url.endsWith("/v1/feed") ? json({ cards: [] }) : json({ erro: "nao_autorizado", msg: "x" }, 401);
    },
  });
  assert.deepEqual(await api.get("/v1/feed"), { cards: [] });
  await assert.rejects(api.get("/v1/tarefas"), (e) => e instanceof ErroApi && e.status === 401);
  assert.deepEqual(vistos, [["/v1/feed", "Bearer ayn_falso"], ["/v1/tarefas", "Bearer ayn_falso"]]);
  assert.equal(await armazem.ler(CHAVE_TOKEN), undefined);
  assert.equal(saiu, 1);
});

test("api: POST JSON e 204", async () => {
  let corpo = null;
  const api = criarApi({
    fetch: async (_u, o) => {
      corpo = [o.method, o.headers["Content-Type"], o.body];
      return new Response(null, { status: 204 });
    },
  });
  assert.equal(await api.put("/v1/dispositivo/preferencias", { push: true }), null);
  assert.deepEqual(corpo, ["PUT", "application/json", '{"push":true}']);
});

test("api.saude: timeout de 4 s aborta e devolve ok=false sem lançar", async () => {
  let agendado = null;
  const api = criarApi({
    agendar: (fn, ms) => ((agendado = ms), setTimeout(fn, 1)),
    fetch: (_u, o) =>
      new Promise((_ok, falha) => o.signal.addEventListener("abort", () => falha(new Error("abortado")))),
  });
  const r = await api.saude();
  assert.equal(agendado, 4000);
  assert.deepEqual(r, { ok: false, status: 0, dados: null });
});

test("api.eventos: SSE por fetch, Last-Event-ID na reconexão e espera 1 → 30 s", async () => {
  const pedidos = [];
  const esperas = [];
  const recebidos = [];
  let api;
  let sse;
  api = criarApi({
    armazem: armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" }),
    dormir: async (ms) => {
      esperas.push(ms);
      if (esperas.length >= 7) sse.parar();
    },
    fetch: async (_u, o) => {
      pedidos.push(o.headers["Last-Event-ID"] ?? null);
      if (pedidos.length === 1) {
        return new Response(
          sseCorpo(': ping\n\nevent: evento\nid: 41\ndata: {"a":1}\n\nevent: turno.texto\ndata: {"texto":"oi"}\n\nid: 42\nevent: estado\ndata: {"b":\ndata: 2}\n\n'),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      throw new TypeError("sem rede");
    },
  });
  sse = api.eventos((nome, dados, id) => recebidos.push([nome, dados, id]));
  await sse.pronto;
  assert.deepEqual(recebidos, [
    ["evento", { a: 1 }, "41"],
    ["turno.texto", { texto: "oi" }, null],
    ["estado", { b: 2 }, "42"],
  ]);
  assert.equal(pedidos[0], null);
  assert.ok(pedidos.slice(1).every((p) => p === "42"));
  assert.deepEqual(esperas, [1000, 2000, 4000, 8000, 16000, 30000, 30000]);
});

// ---------- app.js

test("rota: hash → tela e params", () => {
  assert.deepEqual(rota("#/tv/sala"), { tela: "tv", params: { id: "sala" } });
  assert.deepEqual(rota("#/tarefas"), { tela: "tarefas", params: {} });
  assert.deepEqual(rota("#/tarefas/7"), { tela: "tarefas", params: { id: "7" } });
  assert.deepEqual(rota("#/confirma/01HZX"), { tela: "confirma", params: { id: "01HZX" } });
  assert.deepEqual(rota("#/parear?c=123456"), { tela: "parear", params: { c: "123456" } });
  assert.deepEqual(rota(""), { tela: "conversa", params: {} });
  assert.deepEqual(rota("#/qualquer"), { tela: "conversa", params: {} });
  assert.deepEqual(rota("#/confirma"), { tela: "conversa", params: {} });
});

test("conexaoDaSaude: pc/nuvem/casa e falha", () => {
  assert.deepEqual(conexaoDaSaude({ ok: true, dados: SAUDE_OK }), { conexao: "ok_pc", casa_fora: false });
  assert.deepEqual(conexaoDaSaude({ ok: true, dados: { online: { pc: false, casa: false } } }), {
    conexao: "ok_nuvem",
    casa_fora: true,
  });
  assert.equal(conexaoDaSaude({ ok: false, status: 503, dados: { ok: false } }).conexao, "sem_ayanami");
  assert.equal(conexaoDaSaude({ ok: false, status: 0, dados: null }).conexao, "sem_ayanami");
});

function ambiente(hash = "#/conversa") {
  const ouvintesJ = {};
  const ouvintesD = {};
  const intervalos = [];
  const el = (id) => ({ id, hidden: false, textContent: "", dataset: {}, filhos: 0, replaceChildren() {} });
  const elementos = { faixa: el("faixa"), tela: el("tela") };
  const janela = {
    location: {
      _h: hash,
      get hash() { return this._h; },
      set hash(v) { this._h = v; ouvintesJ.hashchange?.(); },
    },
    addEventListener: (t, fn) => (ouvintesJ[t] = fn),
    removeEventListener: (t) => delete ouvintesJ[t],
    setInterval: (fn, ms) => (intervalos.push([fn, ms]), intervalos.length),
    clearInterval: () => {},
  };
  const documento = {
    visibilityState: "visible",
    body: { dataset: {} },
    getElementById: (id) => elementos[id],
    addEventListener: (t, fn) => (ouvintesD[t] = fn),
    removeEventListener: (t) => delete ouvintesD[t],
  };
  const montadas = [];
  const carregarTela = async (nome) => ({ montar: (_el, ctx) => montadas.push([nome, ctx.params]) });
  return { janela, documento, elementos, ouvintesD, intervalos, montadas, carregarTela };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

test("CA-Y56: /saude falhando → sem_ayanami e faixa 'ligue o Tailscale'; volta ao abrir de novo", async () => {
  const amb = ambiente();
  let rede = false;
  const chamadas = [];
  const api = criarApi({
    armazem: armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" }),
    dormir: () => new Promise(() => {}),
    fetch: async (url) => {
      chamadas.push(url);
      if (!rede) throw new TypeError("Failed to fetch");
      if (url === "/saude") return json(SAUDE_OK);
      return new Response(new ReadableStream({ start() {} }), { headers: { "Content-Type": "text/event-stream" } });
    },
  });
  const estado = criarEstado();
  const app = criarApp({ ...amb, api, estado });
  await app.iniciar();
  assert.equal(estado.get().conexao, "sem_ayanami");
  assert.equal(amb.elementos.faixa.hidden, false);
  assert.equal(amb.elementos.faixa.textContent, FAIXA_SEM_AYANAMI);
  assert.match(FAIXA_SEM_AYANAMI, /ligue o Tailscale/);
  assert.equal(amb.documento.body.dataset.conexao, "sem_ayanami");
  assert.deepEqual(amb.montadas, [["conversa", {}]]);
  assert.equal(amb.intervalos[0][1], 30000);
  assert.ok(!chamadas.includes("/v1/eventos"));

  rede = true;
  amb.ouvintesD.visibilitychange();
  await tick();
  await tick();
  assert.equal(estado.get().conexao, "ok_pc");
  assert.equal(amb.elementos.faixa.hidden, true);
  assert.ok(chamadas.includes("/v1/eventos"));

  rede = false;
  await amb.intervalos[0][0]();
  await tick();
  assert.equal(estado.get().conexao, "sem_ayanami");
  app.parar();
});

test("CA-Y56: 401 → apaga o token e vai a Parear", async () => {
  const amb = ambiente("#/tarefas");
  const armazem = armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" });
  const estado = criarEstado();
  let app;
  const api = criarApi({
    armazem,
    aoNaoAutorizado: () => app.irParear(),
    dormir: () => new Promise(() => {}),
    fetch: async (url) => (url === "/saude" ? json(SAUDE_OK) : json({ erro: "nao_autorizado" }, 401)),
  });
  app = criarApp({ ...amb, api, estado });
  await app.iniciar();
  await tick();
  assert.equal(await armazem.ler(CHAVE_TOKEN), undefined);
  assert.equal(estado.get().conexao, "sem_token");
  assert.equal(amb.janela.location.hash, "#/parear");
  await tick();
  assert.equal(amb.montadas.at(-1)[0], "parear");
  app.parar();
});

test("sem token na abertura → Parear e nenhuma tela além dela", async () => {
  const amb = ambiente("#/tv/sala");
  const estado = criarEstado();
  const api = criarApi({ fetch: async () => json(SAUDE_OK) });
  const app = criarApp({ ...amb, api, estado });
  await app.iniciar();
  await tick();
  assert.equal(estado.get().conexao, "sem_token");
  assert.equal(amb.janela.location.hash, "#/parear");
  assert.deepEqual(amb.montadas.map((m) => m[0]), ["parear"]);
  app.parar();
});

test("stubs das telas: montar(el, ctx) existe e desenha algo", async () => {
  for (const nome of ["conversa", "tv", "feed", "tarefas", "ajustes", "parear", "confirma"]) {
    const mod = await import(`../../../ayanami/pwa/telas/${nome}.js`);
    const el = { textContent: "" };
    const fim = mod.montar(el, {});
    assert.ok(el.textContent.length > 0, nome);
    assert.equal(typeof fim, "function");
  }
  const g = await import("../../../ayanami/pwa/gravador.js");
  assert.equal(typeof g.montar, "function");
});
