// CA-Y59 (parte do PWA): handlers `push`/`notificationclick` do sw.js e interruptor de push dos
// Ajustes, com `self`/`clients`/`Notification`/`pushManager`/`fetch` falsos, sem navegador. Dono: P2.2.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import { armazemMemoria, criarApi, CHAVE_TOKEN } from "../../../ayanami/pwa/api.js";
import { criarEstado } from "../../../ayanami/pwa/estado.js";
import * as ajustes from "../../../ayanami/pwa/telas/ajustes.js";

const PWA = new URL("../../../ayanami/pwa/", import.meta.url).pathname;
const ORIGEM = "https://ayanami.exemplo.ts.net";
const CODIGO = readFileSync(join(PWA, "sw.js"), "utf8");

// ---------- service worker

function carregarSw({ janelas = [] } = {}) {
  const ouvintes = {};
  const mostradas = [];
  const abertas = [];
  const self = {
    location: new URL(ORIGEM + "/app/sw.js"),
    addEventListener: (t, fn) => (ouvintes[t] = fn),
    skipWaiting: async () => {},
    registration: { showNotification: async (titulo, opcoes) => mostradas.push({ titulo, opcoes }) },
    clients: {
      claim: async () => {},
      matchAll: async () => janelas,
      openWindow: async (u) => abertas.push(u),
    },
  };
  vm.runInNewContext(CODIGO, { self, caches: {}, fetch: async () => {}, URL, Response, Request, Headers, Promise, console });
  async function despachar(tipo, extra) {
    let espera = null;
    ouvintes[tipo]({ ...extra, waitUntil: (p) => (espera = p) });
    await espera;
  }
  const push = (payload) =>
    despachar("push", { data: payload === undefined ? null : { json: () => (typeof payload === "string" ? JSON.parse(payload) : payload) } });
  const clicar = (data) => {
    const n = { data, fechada: false, close() { this.fechada = true; } };
    return despachar("notificationclick", { notification: n }).then(() => n);
  };
  return { push, clicar, mostradas, abertas, ouvintes };
}

function janela(url) {
  const j = { url, focos: 0, navegou: [] };
  j.focus = async () => (j.focos++, j);
  j.navigate = async (u) => (j.navegou.push(u), (j.url = u), j);
  return j;
}

test("sw: push mostra titulo/resumo/tag/url/ícone", async () => {
  const sw = carregarSw();
  await sw.push({ v: 1, tipo: "tarefa", id: "7", titulo: "Pesquisa pronta", resumo: "Monitores OLED 27″",
    url: "/app/#/tarefas/abc", tag: "tarefa-abc", ts: "2026-10-21T10:00:00Z" });
  assert.equal(sw.mostradas.length, 1);
  const { titulo, opcoes } = sw.mostradas[0];
  assert.equal(titulo, "Pesquisa pronta");
  assert.equal(opcoes.body, "Monitores OLED 27″");
  assert.equal(opcoes.tag, "tarefa-abc");
  assert.equal(opcoes.data.url, ORIGEM + "/app/#/tarefas/abc");
  assert.equal(opcoes.icon, ORIGEM + "/app/icones/192.png");
  assert.ok(opcoes.badge);
});

test("CA-Y59 sw: notificação de confirma sem botão de confirmar (DS17)", async () => {
  const sw = carregarSw();
  await sw.push({ v: 1, tipo: "confirma", id: "9", titulo: "Confirma desligar a TV?", resumo: "TV da sala",
    url: "/app/#/confirma/01HXXXXXXXXXXXXXXXXXXXXXXX", tag: "confirma-01HX" });
  const { opcoes } = sw.mostradas[0];
  assert.equal(opcoes.actions, undefined);
  assert.doesNotMatch(JSON.stringify(opcoes), /Confirmar/i);
  assert.equal(opcoes.data.url, ORIGEM + "/app/#/confirma/01HXXXXXXXXXXXXXXXXXXXXXXX");
  assert.doesNotMatch(CODIGO, /actions\s*:/); // nenhuma notificação do SW tem ações
});

test("sw: push sem dados ou com url de fora cai na Conversa", async () => {
  const sw = carregarSw();
  await sw.push(undefined);
  await sw.push({ titulo: "x", url: "https://outro.exemplo/app/" });
  await sw.push({ titulo: "y", url: "/v1/feed" });
  assert.equal(sw.mostradas[0].titulo, "Condessa");
  for (const m of sw.mostradas) assert.equal(m.opcoes.data.url, ORIGEM + "/app/#/conversa");
  assert.equal(sw.mostradas[0].opcoes.tag, undefined);
});

test("CA-Y59 sw: clique sem janela aberta abre a url", async () => {
  const sw = carregarSw();
  const n = await sw.clicar({ url: ORIGEM + "/app/#/confirma/01HZ" });
  assert.equal(n.fechada, true);
  assert.deepEqual(sw.abertas, [ORIGEM + "/app/#/confirma/01HZ"]);
});

test("CA-Y59 sw: clique com o PWA aberto foca a janela e leva à url", async () => {
  const outra = janela("https://outro.exemplo/");
  const minha = janela(ORIGEM + "/app/#/conversa");
  const sw = carregarSw({ janelas: [outra, minha] });
  await sw.clicar({ url: ORIGEM + "/app/#/tarefas/abc" });
  assert.equal(minha.focos, 1);
  assert.deepEqual(minha.navegou, [ORIGEM + "/app/#/tarefas/abc"]);
  assert.equal(outra.focos, 0);
  assert.deepEqual(sw.abertas, []);
});

test("sw: clique com url de fora não sai do escopo", async () => {
  const sw = carregarSw();
  await sw.clicar({ url: "https://mal.exemplo/" });
  assert.deepEqual(sw.abertas, [ORIGEM + "/app/#/conversa"]);
});

// ---------- Ajustes: interruptor de push

class Elem {
  constructor(doc, tag) {
    Object.assign(this, { ownerDocument: doc, tagName: tag.toUpperCase(), children: [], dataset: {}, attrs: {}, ouvintes: {} });
    Object.assign(this, { _texto: "", value: "", hidden: false, disabled: false, checked: false, className: "" });
  }
  get textContent() {
    return this._texto + this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this._texto = String(v);
    this.children = [];
  }
  append(...fs) {
    for (const f of fs) this.children.push(typeof f === "string" ? Object.assign(new Elem(this.ownerDocument, "#text"), { _texto: f }) : f);
  }
  replaceChildren(...fs) {
    this.children = [];
    this._texto = "";
    this.append(...fs);
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
  }
  addEventListener(ev, fn) {
    (this.ouvintes[ev] ??= []).push(fn);
  }
  removeEventListener() {}
  disparar(tipo) {
    return (this.ouvintes[tipo] ?? []).map((fn) => fn({ type: tipo, preventDefault() {} }));
  }
}
function achar(raiz, pred) {
  if (pred(raiz)) return raiz;
  for (const c of raiz.children) {
    const r = achar(c, pred);
    if (r) return r;
  }
  return null;
}
const campo = (r, n) => achar(r, (e) => e.dataset?.campo === n);
const json = (obj, status = 200) =>
  new Response(obj === null ? null : JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });

const CHAVE_A = ajustes.bytesParaB64url(new Uint8Array(65).fill(4));
const CHAVE_B = ajustes.bytesParaB64url(new Uint8Array(65).fill(9));

function navegadorFalso({ permissao = "default", resposta = "granted", subChave = null } = {}) {
  const log = [];
  const Notification = {
    permission: permissao,
    requestPermission: () => {
      log.push("requestPermission");
      Notification.permission = resposta;
      return Promise.resolve(resposta);
    },
  };
  let atual = null;
  const criarSub = (chave, n) => ({
    endpoint: `https://push.exemplo/ep-${n}`,
    options: chave ? { applicationServerKey: chave.buffer } : {},
    toJSON() {
      return { endpoint: this.endpoint, keys: { p256dh: "p256dh-falso", auth: "auth-falso" } };
    },
    async unsubscribe() {
      log.push("unsubscribe " + this.endpoint);
      if (atual === this) atual = null;
      return true;
    },
  });
  let n = 0;
  if (subChave) atual = criarSub(ajustes.b64urlParaBytes(subChave), 0);
  const pushManager = {
    getSubscription: async () => atual,
    subscribe: async (o) => {
      log.push("subscribe");
      assert.equal(o.userVisibleOnly, true);
      atual = criarSub(o.applicationServerKey, ++n);
      return atual;
    },
  };
  return { push: { Notification, sw: { ready: Promise.resolve({ pushManager }) } }, log, atual: () => atual };
}

function montar({ nav, chave = CHAVE_A, rotas = {}, armazem } = {}) {
  const chamadas = [];
  const arm = armazem ?? armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" });
  const base = {
    "GET /v1/push/chave": () => json({ chave }),
    "POST /v1/push/assinar": () => json(null, 201),
    "DELETE /v1/push/assinar": () => json(null, 204),
    "PUT /v1/dispositivo/preferencias": () => json(null, 204),
    "GET /v1/casa/estado": () => json({ tvs: [] }),
    ...rotas,
  };
  const api = criarApi({
    armazem: arm,
    fetch: async (url, o = {}) => {
      const metodo = o.method ?? "GET";
      chamadas.push({ metodo, url, corpo: o.body ? JSON.parse(o.body) : undefined });
      const fn = base[`${metodo} ${url}`];
      return fn ? fn(url, o) : json({ msg: "sem rota" }, 404);
    },
  });
  const doc = { createElement: (t) => new Elem(doc, t) };
  const el = doc.createElement("main");
  const ctx = { api, estado: criarEstado({ conexao: "ok_pc" }), eventos: { on: () => () => {} }, params: {},
    navegar: () => {}, armazem: arm, push: nav?.push ?? null };
  const desmontar = ajustes.montar(el, ctx);
  return { el, chamadas, armazem: arm, desmontar, ctx };
}
const so = (chamadas, metodo, url) => chamadas.filter((c) => c.metodo === metodo && c.url === url);

test("b64url ida e volta", () => {
  const b = new Uint8Array([0, 251, 255, 62, 63, 1]);
  assert.deepEqual([...ajustes.b64urlParaBytes(ajustes.bytesParaB64url(b))], [...b]);
  assert.doesNotMatch(ajustes.bytesParaB64url(b), /[+/=]/);
});

test("ajustes: sem suporte a Web Push o interruptor some e avisa", async () => {
  const t = montar({ nav: null });
  await t.desmontar.pronto;
  assert.equal(campo(t.el, "push_ligado"), null);
  assert.match(campo(t.el, "push").textContent, /não recebe avisos/);
});

test("ajustes: abrir a tela não pede permissão; ligar pede só no toque e assina", async () => {
  const nav = navegadorFalso();
  const t = montar({ nav });
  await t.desmontar.pronto;
  assert.deepEqual(nav.log, []);
  const chave = campo(t.el, "push_ligado");
  assert.equal(chave.checked, false);
  chave.checked = true;
  await Promise.all(chave.disparar("change"));
  assert.equal(nav.log[0], "requestPermission");
  assert.deepEqual(nav.log, ["requestPermission", "subscribe"]);
  const posts = so(t.chamadas, "POST", "/v1/push/assinar");
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].corpo, { endpoint: "https://push.exemplo/ep-1", keys: { p256dh: "p256dh-falso", auth: "auth-falso" } });
  assert.equal(await t.armazem.ler(ajustes.CHAVE_PUSH), CHAVE_A);
  assert.equal(chave.checked, true);
  assert.equal(so(t.chamadas, "PUT", "/v1/dispositivo/preferencias").at(-1).corpo.push, true);
  t.desmontar();
});

test("ajustes: permissão negada não assina nem chama a API de push", async () => {
  const nav = navegadorFalso({ resposta: "denied" });
  const t = montar({ nav });
  await t.desmontar.pronto;
  const chave = campo(t.el, "push_ligado");
  chave.checked = true;
  await Promise.all(chave.disparar("change"));
  assert.deepEqual(nav.log, ["requestPermission"]);
  assert.equal(so(t.chamadas, "POST", "/v1/push/assinar").length, 0);
  assert.equal(chave.checked, false);
  assert.match(campo(t.el, "aviso").textContent, /bloqueados/);
});

test("ajustes: desligar manda DELETE {endpoint} e cancela no navegador", async () => {
  const nav2 = navegadorFalso({ permissao: "granted", subChave: CHAVE_A });
  const t = montar({ nav: nav2 });
  await t.desmontar.pronto;
  const chave = campo(t.el, "push_ligado");
  assert.equal(chave.checked, true);
  assert.equal(so(t.chamadas, "POST", "/v1/push/assinar").length, 0); // mesma chave: nada a refazer
  chave.checked = false;
  await Promise.all(chave.disparar("change"));
  const dels = so(t.chamadas, "DELETE", "/v1/push/assinar");
  assert.deepEqual(dels.map((d) => d.corpo), [{ endpoint: "https://push.exemplo/ep-0" }]);
  assert.equal(nav2.atual(), null);
  assert.equal(so(t.chamadas, "PUT", "/v1/dispositivo/preferencias").at(-1).corpo.push, false);
  assert.equal(await t.armazem.ler(ajustes.CHAVE_PUSH), undefined);
});

test("reassinarSeMudou: chave do servidor mudou → cancela e reassina com a nova", async () => {
  const nav = navegadorFalso({ permissao: "granted", subChave: CHAVE_A });
  const t = montar({ nav, chave: CHAVE_B });
  await t.desmontar.pronto;
  assert.ok(nav.log.includes("unsubscribe https://push.exemplo/ep-0"));
  assert.ok(nav.log.includes("subscribe"));
  assert.equal(so(t.chamadas, "POST", "/v1/push/assinar").length, 1);
  assert.equal(await t.armazem.ler(ajustes.CHAVE_PUSH), CHAVE_B);
  assert.equal(campo(t.el, "push_ligado").checked, true);
  assert.equal(await ajustes.reassinarSeMudou(t.ctx), "ok");
});

test("reassinarSeMudou: sem permissão ou com push desligado não faz nada", async () => {
  const nav = navegadorFalso();
  const arm = armazemMemoria({ [CHAVE_TOKEN]: "ayn_falso" });
  const api = { get: async () => assert.fail("não devia chamar a API") };
  assert.equal(await ajustes.reassinarSeMudou({ api, armazem: arm, push: nav.push }), "nada");
  const nav2 = navegadorFalso({ permissao: "granted" });
  await arm.gravar(ajustes.CHAVE_PREFS, { push: false });
  assert.equal(await ajustes.reassinarSeMudou({ api, armazem: arm, push: nav2.push }), "nada");
  assert.deepEqual([...nav.log, ...nav2.log], []);
});
