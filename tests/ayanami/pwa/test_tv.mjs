// CA-Y56 (parte do controle) com DOM, relógio e `fetch` falsos, sem navegador. Dono: P1.3.
import { test } from "node:test";
import assert from "node:assert/strict";
import { criarEstado } from "../../../ayanami/pwa/estado.js";
import { armazemMemoria, criarApi, CHAVE_TOKEN } from "../../../ayanami/pwa/api.js";
import {
  montar, botoesDaTv, criarControle, pedido, CONFIRMA_MS, REPETE_MS,
  MSG_CASA_FORA, MSG_TV_FORA, MSG_TOQUE_DE_NOVO,
} from "../../../ayanami/pwa/telas/tv.js";

// ---------- DOM falso mínimo

class No {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.ouvintes = {};
    this._texto = "";
    this.disabled = false;
    this.className = "";
    this.value = "";
  }
  append(...ns) { for (const n of ns) this.children.push(n); }
  replaceChildren(...ns) { this.children = [...ns]; }
  set textContent(t) { this._texto = String(t); this.children = []; }
  get textContent() { return this._texto + this.children.map((c) => c.textContent).join(""); }
  addEventListener(t, fn) { (this.ouvintes[t] ||= []).push(fn); }
  removeEventListener(t, fn) { this.ouvintes[t] = (this.ouvintes[t] || []).filter((f) => f !== fn); }
  disparar(t) { for (const fn of [...(this.ouvintes[t] || [])]) fn({ preventDefault() {} }); }
  *todos() { for (const c of this.children) { yield c; yield* c.todos(); } }
  achar(f) { for (const n of this.todos()) if (f(n)) return n; return null; }
}
function criarDoc() {
  const doc = { ouvintes: {}, createElement: (t) => new No(doc, t) };
  doc.addEventListener = (t, fn) => (doc.ouvintes[t] ||= []).push(fn);
  doc.removeEventListener = (t, fn) => { doc.ouvintes[t] = (doc.ouvintes[t] || []).filter((f) => f !== fn); };
  doc.disparar = (t) => { for (const fn of [...(doc.ouvintes[t] || [])]) fn({}); };
  return doc;
}

// ---------- relógio falso

function criarRelogio() {
  let agora = 0;
  let seq = 0;
  const fila = new Map();
  return {
    agora: () => agora,
    agendar: (fn, ms) => { const id = ++seq; fila.set(id, { fn, em: agora + ms }); return id; },
    cancelar: (id) => fila.delete(id),
    avancar(ms) {
      const fim = agora + ms;
      for (;;) {
        const prox = [...fila.entries()].filter(([, v]) => v.em <= fim).sort((a, b) => a[1].em - b[1].em)[0];
        if (!prox) break;
        fila.delete(prox[0]);
        agora = prox[1].em;
        prox[1].fn();
      }
      agora = fim;
    },
    pendentes: () => fila.size,
  };
}

// ---------- cenário

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
const tick = () => new Promise((r) => setImmediate(r));

const SALA = {
  id: "sala", nome: "TV da sala", driver: "samsung", caps: ["power_on", "power_off", "vol_step", "mute", "input", "app"],
  entradas: ["hdmi1", "hdmi2"], apps: ["netflix"], padrao: true,
};
const QUARTO = { id: "quarto", nome: "TV do quarto", driver: "roku", caps: ["key", "channel", "text", "power_off"], entradas: [], apps: [] };
const CASA = {
  online: true, visto: "2026-10-20T10:00:00Z", tvs: [SALA, QUARTO],
  estados: [{ id: "sala", nome: "TV da sala", driver: "samsung", online: true, mudo: false }, { id: "quarto", nome: "TV do quarto", driver: "roku", online: true }],
  apps: [{ id: "netflix", nome: "Netflix", apelidos: [] }],
};

function cenario({ casa = CASA, acao = () => json({ ok: true, fala: "Feito." }), estadoInicial = {}, params = {} } = {}) {
  const posts = [];
  const api = criarApi({
    armazem: armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" }),
    fetch: async (url, o) => {
      if (url === "/v1/casa/estado") return typeof casa === "function" ? casa() : json(casa);
      if (url === "/v1/casa/acao") { const corpo = JSON.parse(o.body); posts.push(corpo); return acao(corpo); }
      return json({ erro: "x" }, 404);
    },
  });
  const ouvintes = new Map();
  const eventos = {
    on(n, fn) { ouvintes.set(n, fn); return () => ouvintes.delete(n); },
    emitir(n, d) { ouvintes.get(n)?.(d); },
  };
  const doc = criarDoc();
  const el = doc.createElement("main");
  const estado = criarEstado(estadoInicial);
  const relogio = criarRelogio();
  const desmontar = montar(el, { api, estado, eventos, params, navegar: () => {}, relogio });
  const botao = (acao) => el.achar((n) => n.tagName === "BUTTON" && n.dataset.acao === acao);
  const acoes = () => [...el.todos()].filter((n) => n.dataset.acao).map((n) => n.dataset.acao);
  const papel = (p) => el.achar((n) => n.dataset.papel === p);
  return { el, doc, api, eventos, ouvintes, estado, relogio, desmontar, posts, botao, acoes, papel };
}

// ---------- puros

test("botoesDaTv: só as caps; sem caps nada", () => {
  assert.deepEqual(botoesDaTv({ id: "x", caps: [] }), []);
  const chaves = botoesDaTv(SALA, CASA.apps).map((b) => b.chave);
  assert.deepEqual(chaves, ["power_on", "power_off", "vol_down", "vol_up", "mute", "input:hdmi1", "input:hdmi2", "app:netflix"]);
  const q = botoesDaTv(QUARTO).map((b) => b.chave);
  assert.ok(!q.includes("power_on") && q.includes("power_off") && q.includes("key:ok") && q.includes("ch_up"));
  assert.ok(!q.some((c) => c.startsWith("vol") || c === "mute"));
  assert.equal(botoesDaTv(SALA, CASA.apps).find((b) => b.chave === "app:netflix").rotulo, "Netflix");
  assert.equal(botoesDaTv(SALA).find((b) => b.chave === "input:hdmi2").rotulo, "HDMI 2");
});

test("pedido: AcaoPedido com slots em pares", () => {
  assert.deepEqual(pedido("tv.volume", { slots: { volume: "+1" } }), { intent: "tv.volume", slots: [["volume", "+1"]], texto: "", confirmed: false, args: {} });
  const mudo = botoesDaTv(SALA).find((b) => b.chave === "mute");
  assert.equal(mudo.fazer({ mudo: false }).intent, "tv.mute");
  assert.equal(mudo.fazer({ mudo: true }).intent, "tv.unmute");
});

test("controle: desligar com 1 toque não manda nada; 2º em ≤ 3 s manda confirmed=true", async () => {
  const relogio = criarRelogio();
  const enviados = [];
  const avisos = [];
  const ctl = criarControle({ api: { post: async (_c, corpo) => { enviados.push(corpo); return { ok: true }; } }, relogio, aoAviso: (t) => avisos.push(t) });
  const off = botoesDaTv(SALA).find((b) => b.chave === "power_off");
  assert.equal(ctl.tocar("sala", off), null);
  relogio.avancar(CONFIRMA_MS + 1); // expirou
  assert.equal(enviados.length, 0);
  assert.equal(ctl.tocar("sala", off), null);
  relogio.avancar(CONFIRMA_MS - 1);
  await ctl.tocar("sala", off);
  assert.deepEqual(enviados, [{ tv: "sala", pedido: { intent: "tv.power_off", slots: [], texto: "", confirmed: true, args: {} } }]);
  assert.ok(avisos.includes(MSG_TOQUE_DE_NOVO));
  // toque em outra TV não confirma a primeira
  assert.equal(ctl.tocar("sala", off), null);
  assert.equal(ctl.tocar("quarto", off), null);
  assert.equal(enviados.length, 1);
});

// ---------- tela

test("tela: abas por TV, TV padrão, só botões das caps, POST direto", async () => {
  const c = cenario();
  await c.desmontar.pronto;
  const abas = [...c.el.todos()].filter((n) => n.dataset.tv && n.tagName === "BUTTON").map((n) => n.dataset.tv);
  assert.deepEqual(abas, ["sala", "quarto"]);
  assert.deepEqual(c.acoes(), ["power_on", "power_off", "vol_down", "vol_up", "mute", "input:hdmi1", "input:hdmi2", "app:netflix"]);
  c.botao("app:netflix").disparar("click");
  await tick();
  assert.deepEqual(c.posts, [{ tv: "sala", pedido: { intent: "tv.app", slots: [["app", "netflix"]], texto: "", confirmed: false, args: {} } }]);
  assert.equal(c.papel("resultado").textContent, "Feito.");
  // troca de aba
  c.el.achar((n) => n.dataset.tv === "quarto" && n.tagName === "BUTTON").disparar("click");
  assert.ok(c.acoes().includes("key:ok") && !c.acoes().includes("vol_up"));
  assert.ok(c.papel("texto"));
  c.desmontar();
});

test("tela: tv_padrao das preferências e #/tv/<id> vencem o padrao da casa", async () => {
  const a = cenario({ estadoInicial: { prefs: { tv_padrao: "quarto" } } });
  await a.desmontar.pronto;
  assert.ok(a.acoes().includes("key:ok"));
  const b = cenario({ params: { id: "quarto" } });
  await b.desmontar.pronto;
  assert.ok(b.acoes().includes("key:ok"));
  const c = cenario({ estadoInicial: { prefs: { tv_padrao: "sumiu" } } });
  await c.desmontar.pronto;
  assert.ok(c.acoes().includes("vol_up"));
});

test("tela: desligar pede 2º toque; um toque só não manda nada (CA-Y56)", async () => {
  const c = cenario();
  await c.desmontar.pronto;
  c.botao("power_off").disparar("click");
  await tick();
  assert.equal(c.posts.length, 0);
  assert.equal(c.papel("aviso").textContent, MSG_TOQUE_DE_NOVO);
  c.relogio.avancar(CONFIRMA_MS + 10);
  assert.equal(c.papel("aviso"), null);
  c.botao("power_off").disparar("click");
  c.relogio.avancar(2000);
  c.botao("power_off").disparar("click");
  await tick();
  assert.equal(c.posts.length, 1);
  assert.equal(c.posts[0].pedido.intent, "tv.power_off");
  assert.equal(c.posts[0].pedido.confirmed, true);
  c.desmontar();
});

test("tela: vol+ segurado repete a cada 200 ms e para ao soltar (inclusive no documento)", async () => {
  const c = cenario();
  await c.desmontar.pronto;
  c.botao("vol_up").disparar("pointerdown");
  c.relogio.avancar(REPETE_MS * 3);
  c.botao("vol_up").disparar("pointerup");
  c.relogio.avancar(REPETE_MS * 5);
  await tick();
  assert.equal(c.posts.length, 4);
  assert.ok(c.posts.every((p) => p.pedido.intent === "tv.volume" && p.pedido.slots[0][1] === "+1"));
  // soltar fora do botão (o botão foi redesenhado no meio)
  c.botao("vol_down").disparar("pointerdown");
  c.relogio.avancar(REPETE_MS);
  c.doc.disparar("pointerup");
  c.relogio.avancar(REPETE_MS * 5);
  await tick();
  assert.equal(c.posts.length, 6);
  assert.equal(c.posts[5].pedido.slots[0][1], "-1");
  c.desmontar();
  assert.equal(c.relogio.pendentes(), 0);
});

test("tela: SSE estado com online=false deixa os botões cinza com 'TV fora da rede'", async () => {
  const c = cenario();
  await c.desmontar.pronto;
  c.eventos.emitir("estado", { tvs: [{ id: "sala", nome: "TV da sala", driver: "samsung", online: false }] });
  assert.equal(c.papel("tv-fora").textContent, MSG_TV_FORA);
  assert.ok(c.botao("vol_up").disabled && c.botao("power_on").disabled);
  c.botao("power_on").disparar("click");
  c.botao("vol_up").disparar("pointerdown");
  await tick();
  assert.equal(c.posts.length, 0);
  c.eventos.emitir("estado", { tvs: [{ id: "sala", nome: "TV da sala", driver: "samsung", online: true }] });
  assert.equal(c.papel("tv-fora"), null);
  assert.equal(c.botao("vol_up").disabled, false);
  c.desmontar();
  assert.equal(c.ouvintes.size, 0);
});

test("tela: casa offline (503 na ação ou online=false) → 'a casa está fora do ar'", async () => {
  const c = cenario({ acao: () => json({ erro: "casa_offline", msg: "x" }, 503) });
  await c.desmontar.pronto;
  c.botao("power_on").disparar("click");
  await tick();
  await tick();
  assert.equal(c.papel("casa-fora").textContent, MSG_CASA_FORA);
  assert.equal(c.estado.get().casa_fora, true);
  assert.ok(c.botao("power_on").disabled);
  c.desmontar();

  const d = cenario({ casa: { ...CASA, online: false } });
  await d.desmontar.pronto;
  assert.equal(d.papel("casa-fora").textContent, MSG_CASA_FORA);
  const e = cenario({ casa: () => json({ erro: "casa_offline" }, 503) });
  await e.desmontar.pronto;
  assert.equal(e.papel("casa-fora").textContent, MSG_CASA_FORA);
});

test("tela: digitar texto manda tv.text; resultado com estado atualiza o mudo", async () => {
  const c = cenario({
    params: { id: "quarto" },
    acao: (corpo) => json({ ok: true, fala: "", dados: { estado: { id: corpo.tv, nome: "x", driver: "roku", online: true, mudo: true } } }),
  });
  await c.desmontar.pronto;
  c.papel("texto").value = "breaking bad";
  c.el.achar((n) => n.tagName === "FORM").disparar("submit");
  await tick();
  assert.deepEqual(c.posts[0].pedido, { intent: "tv.text", slots: [], texto: "", confirmed: false, args: { texto: "breaking bad" } });
  c.desmontar();

  const m = cenario({ acao: (corpo) => json({ ok: true, dados: { estado: { id: corpo.tv, online: true, mudo: true } } }) });
  await m.desmontar.pronto;
  m.botao("mute").disparar("click");
  await tick();
  await tick();
  m.botao("mute").disparar("click");
  await tick();
  assert.deepEqual(m.posts.map((p) => p.pedido.intent), ["tv.mute", "tv.unmute"]);
  m.desmontar();
});
