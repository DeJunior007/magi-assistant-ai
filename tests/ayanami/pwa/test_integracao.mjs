// P1.x: integração do PWA (prefs no estado, ctx, SSE `confirma` global, reassinar na subida,
// `/v1/feed?antes=` fora do cache, CSS das telas). Sem navegador.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { criarEstado } from "../../../ayanami/pwa/estado.js";
import { armazemMemoria, criarApi, CHAVE_TOKEN } from "../../../ayanami/pwa/api.js";
import { criarApp } from "../../../ayanami/pwa/app.js";
import { CHAVE_PREFS, PREFS_PADRAO } from "../../../ayanami/pwa/telas/ajustes.js";
import { rotaDe } from "../../../ayanami/pwa/telas/confirma.js";

const PWA = new URL("../../../ayanami/pwa/", import.meta.url).pathname;
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
const SAUDE_OK = { ok: true, online: { pc: true, casa: true, celulares: 1 } };
const tick = () => new Promise((r) => setTimeout(r, 0));

function ambiente(hash = "#/conversa") {
  const ouvintesJ = {};
  const el = (id) => ({ id, hidden: false, textContent: "", dataset: {}, replaceChildren() {} });
  const elementos = { faixa: el("faixa"), tela: el("tela") };
  const janela = {
    location: {
      _h: hash,
      get hash() { return this._h; },
      set hash(v) { this._h = v; ouvintesJ.hashchange?.(); },
    },
    addEventListener: (t, fn) => (ouvintesJ[t] = fn),
    removeEventListener: (t) => delete ouvintesJ[t],
    setInterval: () => 1,
    clearInterval: () => {},
  };
  const documento = {
    visibilityState: "visible",
    body: { dataset: {} },
    getElementById: (id) => elementos[id],
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  const montadas = [];
  const carregarTela = async (nome) => ({ montar: (_el, ctx) => montadas.push([nome, ctx]) });
  return { janela, documento, montadas, carregarTela };
}

function montarApp({ hash, prefs, token = "ayn_falso", reassinar = async () => "nada", avisos = [] } = {}) {
  const amb = ambiente(hash);
  const inicial = token ? { [CHAVE_TOKEN]: token } : {};
  if (prefs) inicial[CHAVE_PREFS] = prefs;
  const armazem = armazemMemoria(inicial);
  const api = criarApi({
    armazem,
    dormir: () => new Promise(() => {}),
    fetch: async (url) =>
      url === "/saude"
        ? json(SAUDE_OK)
        : new Response(new ReadableStream({ start() {} }), { headers: { "Content-Type": "text/event-stream" } }),
  });
  const estado = criarEstado();
  const agora = () => Date.parse("2026-10-21T11:59:00Z"); // relógio fixo (P2.4: expira_em decide)
  const app = criarApp({ ...amb, api, armazem, estado, reassinar, agora, avisarSw: (m) => avisos.push(m) });
  return { amb, app, estado, armazem };
}

test("subida: preferencias do armazém viram estado.prefs (normalizadas)", async () => {
  const { app, estado } = montarApp({ prefs: { tv_padrao: "sala", voz_em_texto: true, lixo: 1 } });
  await app.iniciar();
  assert.deepEqual(estado.get().prefs, { ...PREFS_PADRAO, tv_padrao: "sala", voz_em_texto: true });
  app.parar();
});

test("subida sem preferencias guardadas → padrões", async () => {
  const { app, estado } = montarApp();
  await app.iniciar();
  assert.deepEqual(estado.get().prefs, { ...PREFS_PADRAO });
  app.parar();
});

test("ctx das telas leva armazem e verificar; gravar as prefs pelo ctx atualiza o estado", async () => {
  const { amb, app, estado, armazem } = montarApp({ hash: "#/ajustes" });
  await app.iniciar();
  const [nome, ctx] = amb.montadas.at(-1);
  assert.equal(nome, "ajustes");
  assert.equal(typeof ctx.verificar, "function");
  assert.equal(ctx.verificar, app.verificar);
  assert.equal(await ctx.armazem.ler(CHAVE_TOKEN), "ayn_falso");
  await ctx.armazem.gravar(CHAVE_PREFS, { ...PREFS_PADRAO, tv_padrao: "quarto" });
  assert.equal(estado.get().prefs.tv_padrao, "quarto");
  assert.equal((await armazem.ler(CHAVE_PREFS)).tv_padrao, "quarto");
  await ctx.armazem.gravar("outra", 1);
  assert.equal(await armazem.ler("outra"), 1);
  app.parar();
});

test("SSE confirma fora da tela → navega para rotaDe(c); dentro dela não navega", async () => {
  const { amb, app } = montarApp({ hash: "#/feed" });
  await app.iniciar();
  const c = { pedido: "01HZXCONF", descricao: "desligar a TV da sala", expira_em: "2026-10-21T12:00:00Z" };
  app.eventos.emitir("confirma", c, "9");
  await tick();
  assert.equal(amb.janela.location.hash, rotaDe(c));
  assert.equal(amb.montadas.at(-1)[0], "confirma");
  assert.equal(amb.montadas.at(-1)[1].params.id, "01HZXCONF");

  const n = amb.montadas.length;
  app.eventos.emitir("confirma", { pedido: "01HZXOUTRO" }, "10");
  await tick();
  assert.equal(amb.janela.location.hash, rotaDe(c));
  assert.equal(amb.montadas.length, n);
  app.parar();
});

test("SSE confirma já respondida ou sem pedido → não navega", async () => {
  const { amb, app } = montarApp({ hash: "#/feed" });
  await app.iniciar();
  app.eventos.emitir("confirma", { pedido: "01HZX", resposta: true });
  app.eventos.emitir("confirma", {});
  await tick();
  assert.equal(amb.janela.location.hash, "#/feed");
  app.parar();
});

test("subida chama reassinarSeMudou com api e armazem (sem token, não chama)", async () => {
  const chamadas = [];
  const reassinar = async (ctx) => (chamadas.push(ctx), "ok");
  const a = montarApp({ reassinar });
  await a.app.iniciar();
  await tick();
  assert.equal(chamadas.length, 1);
  assert.equal(chamadas[0].api, a.app.api);
  assert.equal(chamadas[0].armazem, a.app.armazem);
  a.app.parar();

  const b = montarApp({ token: null, reassinar });
  await b.app.iniciar();
  await tick();
  assert.equal(chamadas.length, 1);
  b.app.parar();
});

test("reassinar que falha ou nunca resolve não trava a subida", async () => {
  const a = montarApp({ reassinar: async () => { throw new Error("x"); } });
  await a.app.iniciar();
  await tick();
  a.app.parar();
  const b = montarApp({ reassinar: () => new Promise(() => {}) });
  await b.app.iniciar();
  assert.equal(b.estado.get().conexao, "ok_pc");
  b.app.parar();
});

// ---------- sw.js: /v1/feed?antes= não entra no cache

function carregarSw(rede) {
  const ouvintes = {};
  const lojas = new Map();
  const caches = {
    async open(nome) {
      if (!lojas.has(nome)) lojas.set(nome, new Map());
      const m = lojas.get(nome);
      return {
        async put(r, resp) { m.set(String(r), resp); },
        async match(r) { return m.get(String(r))?.clone(); },
        async addAll() {},
      };
    },
    async keys() { return [...lojas.keys()]; },
    async delete(n) { return lojas.delete(n); },
  };
  const self = { location: new URL("https://ayanami.exemplo.ts.net/app/sw.js"), addEventListener: (t, fn) => (ouvintes[t] = fn) };
  const codigo = readFileSync(PWA + "sw.js", "utf8");
  vm.runInNewContext(codigo, { self, caches, fetch: async (r) => rede(r), URL, Response, Request, Headers, Promise, console });
  const pedir = async (caminho) => {
    let resposta = null;
    ouvintes.fetch({ request: new Request(self.location.origin + caminho), respondWith: (p) => (resposta = p) });
    return resposta ? await resposta : null;
  };
  return { pedir, lojas, codigo };
}

test("sw: /v1/feed?antes= é network-only (sem respondWith e sem cópia); sem antes, cacheia", async () => {
  const sw = carregarSw(() => json({ cards: [{ titulo: "a" }] }));
  assert.equal(await sw.pedir("/v1/feed?n=20&antes=2026-10-20T10:00:00Z"), null);
  assert.equal(sw.lojas.get("condessa-feed"), undefined);
  const r = await sw.pedir("/v1/feed?n=20");
  assert.deepEqual(await r.json(), { cards: [{ titulo: "a" }] });
  assert.equal(sw.lojas.get("condessa-feed").size, 1);
  assert.ok(Number(/const VERSAO = (\d+);/.exec(sw.codigo)[1]) >= 3);
});

// ---------- estilo.css: regras das classes das telas (Sobras P1.2/P1.3)

test("estilo.css tem regra para as classes da Conversa e da TV", () => {
  const css = readFileSync(PWA + "estilo.css", "utf8");
  for (const sel of [
    ".ptt", ".historico", ".fala.eu", ".fala.ela", ".selo", ".toast", ".aviso", ".aviso-ptt",
    '.area-ptt[data-estado="gravando"]', ".campo-texto", ".controle.cinza", ".grupo-dpad",
    ".grupo-texto", ".abas-tv", ".botao-tv.armado", '[data-papel="casa-fora"]', '[data-acao="key:up"]',
  ]) {
    assert.ok(css.includes(sel + " ") || css.includes(sel + ",") || css.includes(sel + "{"), sel);
  }
});

test("P2.4: confirma que fecha (outro lugar/expirada) não navega e fecha a notificação no SW", async () => {
  const avisos = [];
  const { amb, app } = montarApp({ hash: "#/feed", avisos });
  await app.iniciar();
  app.eventos.emitir("confirma", { pedido: "01HZXA", resposta: false, expira_em: "2026-10-21T12:00:00Z" }, "11");
  app.eventos.emitir("confirma", { pedido: "01HZXB", resposta: null, expira_em: "2026-10-21T11:58:00Z" }, "12");
  await tick();
  assert.equal(amb.janela.location.hash, "#/feed");
  assert.deepEqual(avisos, [
    { tipo: "fechar-notificacao", tag: "confirma-01HZXA" },
    { tipo: "fechar-notificacao", tag: "confirma-01HZXB" },
  ]);
  app.parar();
});
