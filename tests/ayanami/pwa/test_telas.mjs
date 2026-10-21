// P1.4: Parear, Feed (CA-Y56 parte do feed), Tarefas, Ajustes e Confirmação com DOM e `fetch`
// falsos, sem navegador. Dono: P1.4.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { armazemMemoria, criarApi, CHAVE_TOKEN } from "../../../ayanami/pwa/api.js";
import { criarEstado } from "../../../ayanami/pwa/estado.js";
import * as parear from "../../../ayanami/pwa/telas/parear.js";
import * as feed from "../../../ayanami/pwa/telas/feed.js";
import * as tarefas from "../../../ayanami/pwa/telas/tarefas.js";
import * as ajustes from "../../../ayanami/pwa/telas/ajustes.js";
import * as confirma from "../../../ayanami/pwa/telas/confirma.js";

// ---------- DOM falso mínimo

class Elem {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.ouvintes = {};
    this._texto = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.className = "";
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
  getAttribute(k) {
    return this.attrs[k] ?? null;
  }
  addEventListener(ev, fn) {
    (this.ouvintes[ev] ??= []).push(fn);
  }
  removeEventListener() {}
  dispatchEvent(e) {
    for (const fn of this.ouvintes[e.type] ?? []) fn(e);
  }
  disparar(tipo) {
    for (const fn of this.ouvintes[tipo] ?? []) fn({ type: tipo, preventDefault() {} });
  }
}

function criarDoc() {
  const doc = { createElement: (t) => new Elem(doc, t), eventos: [] };
  doc.dispatchEvent = (e) => doc.eventos.push(e.type);
  return doc;
}

function achar(raiz, pred) {
  if (pred(raiz)) return raiz;
  for (const c of raiz.children) {
    const r = achar(c, pred);
    if (r) return r;
  }
  return null;
}
function todos(raiz, pred, out = []) {
  if (pred(raiz)) out.push(raiz);
  for (const c of raiz.children) todos(c, pred, out);
  return out;
}
const campo = (r, n) => achar(r, (e) => e.dataset?.campo === n);
const acao = (r, n) => achar(r, (e) => e.dataset?.acao === n);
const tique = async (n = 6) => {
  for (let i = 0; i < n; i++) await new Promise((ok) => setImmediate(ok));
};

const json = (obj, status = 200, headers = {}) =>
  new Response(obj === null ? null : JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...headers } });

function montarTela(mod, { rotas, params = {}, token = "ayn_falso", armazem, estado, extra = {} } = {}) {
  const chamadas = [];
  const arm = armazem ?? armazemMemoria(token ? { [CHAVE_TOKEN]: token } : {});
  const api = criarApi({
    armazem: arm,
    fetch: async (url, o = {}) => {
      const metodo = o.method ?? "GET";
      chamadas.push({ metodo, url, corpo: o.body ? JSON.parse(o.body) : undefined, auth: o.headers?.Authorization });
      const fn = rotas[`${metodo} ${url.split("?")[0]}`] ?? rotas[`${metodo} ${url}`];
      if (!fn) return json({ msg: "sem rota" }, 404);
      return fn(url, o);
    },
  });
  const est = estado ?? criarEstado({ conexao: "ok_pc" });
  const ouvintes = {};
  const eventos = {
    on(n, fn) {
      (ouvintes[n] ??= new Set()).add(fn);
      return () => ouvintes[n].delete(fn);
    },
    emitir(n, d) {
      for (const fn of ouvintes[n] ?? []) fn(d);
    },
  };
  const navegou = [];
  const doc = criarDoc();
  const el = doc.createElement("main");
  const ctx = { api, estado: est, eventos, params, navegar: (h) => navegou.push(h), armazem: arm, ...extra };
  const desmontar = mod.montar(el, ctx);
  return { el, doc, chamadas, armazem: arm, estado: est, eventos, navegou, desmontar, api };
}

// ---------- Parear

test("parear: ?c= preenche; 201 guarda token e dispositivo e vai à Conversa", async () => {
  const t = montarTela(parear, {
    token: null,
    params: { c: "482913" },
    estado: criarEstado({ conexao: "sem_token" }),
    rotas: { "POST /v1/pareamento/trocar": () => json({ token: "ayn_celular_x", nome: "celular-pedro", escopos: ["conversa", "feed"] }, 201) },
  });
  assert.equal(campo(t.el, "codigo").value, "482913");
  achar(t.el, (e) => e.tagName === "FORM").disparar("submit");
  await tique();
  assert.deepEqual(t.chamadas.map((c) => [c.metodo, c.url, c.corpo]), [
    ["POST", "/v1/pareamento/trocar", { codigo: "482913", nome: "celular-pedro" }],
  ]);
  assert.equal(await t.armazem.ler(CHAVE_TOKEN), "ayn_celular_x");
  assert.deepEqual(await t.armazem.ler(parear.CHAVE_DISPOSITIVO), { nome: "celular-pedro", escopos: ["conversa", "feed"] });
  assert.equal(t.estado.get().conexao, "conectando");
  assert.deepEqual(t.doc.eventos, ["visibilitychange"]);
  assert.deepEqual(t.navegou, ["#/conversa"]);
});

for (const [status, trecho] of [[400, "errado ou expirado"], [429, "Muitas tentativas"], [409, "em uso"]]) {
  test(`parear: ${status} mostra o erro e não guarda nada`, async () => {
    const t = montarTela(parear, {
      token: null,
      estado: criarEstado({ conexao: "sem_token" }),
      rotas: { "POST /v1/pareamento/trocar": () => json({ erro: "x", msg: "x" }, status) },
    });
    campo(t.el, "codigo").value = "111111";
    achar(t.el, (e) => e.tagName === "FORM").disparar("submit");
    await tique();
    const erro = campo(t.el, "erro");
    assert.equal(erro.hidden, false);
    assert.match(erro.textContent, new RegExp(trecho));
    assert.equal(await t.armazem.ler(CHAVE_TOKEN), undefined);
    assert.equal(await t.armazem.ler(parear.CHAVE_DISPOSITIVO), undefined);
    assert.equal(t.estado.get().conexao, "sem_token");
    assert.deepEqual(t.navegou, []);
    assert.equal(acao(t.el, "parear").disabled, false);
  });
}

test("parear: código inválido não chama a API", async () => {
  const t = montarTela(parear, { token: null, rotas: {} });
  campo(t.el, "codigo").value = "12a4";
  achar(t.el, (e) => e.tagName === "FORM").disparar("submit");
  await tique();
  assert.equal(t.chamadas.length, 0);
  assert.match(campo(t.el, "erro").textContent, /6 dígitos/);
});

// ---------- Feed

const cardsDe = (ini, n) =>
  Array.from({ length: n }, (_, i) => ({
    tipo: i % 2 ? "tarefa" : "noticia", titulo: `c${ini + i}`, resumo: "r",
    ts: new Date(Date.UTC(2026, 9, 20, 12, 0, 0) - (ini + i) * 60000).toISOString(),
    ref: i % 2 ? `tarefa:t${ini + i}` : `https://ex.invalid/${ini + i}`,
  }));

test("feed: primeira página n=20 e rolagem com antes=<ts do último>", async () => {
  const urls = [];
  const t = montarTela(feed, {
    rotas: {
      "GET /v1/feed": (url) => {
        urls.push(url);
        return json({ cards: url.includes("antes=") ? cardsDe(20, 5) : cardsDe(0, 20) });
      },
    },
  });
  await t.desmontar.pronto;
  const lista = campo(t.el, "cards");
  assert.equal(lista.children.length, 20);
  assert.equal(campo(t.el, "aviso").hidden, true);
  assert.equal(acao(t.el, "mais").hidden, false);
  const link = achar(lista, (e) => e.tagName === "A" && e.getAttribute("href")?.startsWith("#/"));
  assert.equal(link.getAttribute("href"), "#/tarefas/t1");
  acao(t.el, "mais").disparar("click");
  await tique();
  assert.equal(lista.children.length, 25);
  assert.equal(acao(t.el, "mais").hidden, true); // página curta = fim
  assert.equal(urls[0], "/v1/feed?n=20");
  assert.equal(urls[1], `/v1/feed?n=20&antes=${encodeURIComponent(cardsDe(0, 20)[19].ts)}`);
  t.desmontar();
});

test("CA-Y56 feed: sem rede → feed do cache com a hora", async () => {
  const em = "2026-10-20T09:41:00.000Z";
  const caches = {
    open: async (nome) => {
      assert.equal(nome, "condessa-feed");
      return { match: async (k) => (k === "/v1/feed" ? json({ cards: cardsDe(0, 3) }, 200, { "X-Condessa-Cache-Em": em }) : undefined) };
    },
  };
  const t = montarTela(feed, {
    estado: criarEstado({ conexao: "sem_ayanami" }),
    extra: { caches },
    rotas: { "GET /v1/feed": () => Promise.reject(new TypeError("Failed to fetch")) },
  });
  await t.desmontar.pronto;
  assert.equal(campo(t.el, "cards").children.length, 3);
  const aviso = campo(t.el, "aviso");
  assert.equal(aviso.hidden, false);
  assert.equal(aviso.textContent, `Sem conexão — feed guardado às ${feed.horaCurta(em)}`);
  assert.match(aviso.textContent, /\d\d:\d\d$/);
  assert.equal(acao(t.el, "mais").hidden, true);
  // botões de TV e PTT (`.precisa-rede`/`.precisa-casa`) desabilitados pelo CSS do P1.1
  const css = readFileSync(new URL("../../../ayanami/pwa/estilo.css", import.meta.url), "utf8");
  assert.match(css, /body\[data-conexao="sem_ayanami"\] \.precisa-rede[^{]*\{[^}]*pointer-events: none/);
  assert.match(acao(t.el, "mais").className, /precisa-rede/);
  t.desmontar();
});

test("feed: resposta da cópia do SW (cabeçalho) também avisa; volta da rede recarrega", async () => {
  let online = false;
  const t = montarTela(feed, {
    estado: criarEstado({ conexao: "sem_ayanami" }),
    rotas: {
      "GET /v1/feed": () =>
        online ? json({ cards: cardsDe(0, 2) }) : json({ cards: cardsDe(0, 1) }, 200, { "X-Condessa-Cache-Em": "2026-10-20T08:05:00Z" }),
    },
  });
  await t.desmontar.pronto;
  assert.match(campo(t.el, "aviso").textContent, /feed guardado às/);
  online = true;
  t.estado.set({ conexao: "ok_nuvem" });
  await tique();
  assert.equal(campo(t.el, "cards").children.length, 2);
  assert.equal(campo(t.el, "aviso").hidden, true);
  t.desmontar();
});

test("feed: sem rede e sem cópia → aviso", async () => {
  const t = montarTela(feed, { extra: { caches: { open: async () => ({ match: async () => undefined }) } }, rotas: { "GET /v1/feed": () => Promise.reject(new TypeError("x")) } });
  await t.desmontar.pronto;
  assert.match(campo(t.el, "aviso").textContent, /sem feed guardado/);
});

// ---------- Tarefas

const AGORA = Date.parse("2026-10-20T12:00:00Z");
const tarefa = (id, estado, extra = {}) => ({
  id, tipo: "pesquisa", titulo: `T ${id}`, estado, progresso: null, frase: null, origem: "celular",
  criada: new Date(AGORA - 5 * 60000).toISOString(), atualizada: null, resultado: null, erro: null, ...extra,
});

test("tarefas: agrupa por estado na ordem, progresso e idade", async () => {
  const t = montarTela(tarefas, {
    extra: { agora: () => AGORA },
    rotas: {
      "GET /v1/tarefas": () =>
        json({ tarefas: [tarefa("a", "ok"), tarefa("b", "rodando", { progresso: 40, frase: "lendo" }), tarefa("c", "na_fila"), tarefa("d", "falhou")] }),
    },
  });
  await t.desmontar.pronto;
  assert.equal(t.chamadas[0].url, "/v1/tarefas?n=50");
  const grupos = todos(t.el, (e) => e.dataset?.grupo).map((e) => e.dataset.grupo);
  assert.deepEqual(grupos, ["rodando", "na_fila", "ok", "falhou"]);
  const b = achar(t.el, (e) => e.dataset?.tarefa === "b");
  assert.equal(achar(b, (e) => e.tagName === "PROGRESS").value, 40);
  assert.match(b.textContent, /há 5 min/);
  assert.equal(achar(b, (e) => e.tagName === "A").getAttribute("href"), "#/tarefas/b");
  assert.equal(tarefas.idade(new Date(AGORA - 3 * 3600e3).toISOString(), AGORA), "há 3 h");
  // SSE de tarefa recarrega
  t.eventos.emitir("evento", { seq: 9, tipo: "tarefa_pronta", titulo: "x" });
  await tique();
  assert.equal(t.chamadas.length, 2);
  t.eventos.emitir("evento", { seq: 10, tipo: "lembrete", titulo: "x" });
  await tique();
  assert.equal(t.chamadas.length, 2);
  t.desmontar();
});

test("tarefas: ver e cancelar (202) e 409 = já terminou", async () => {
  let resposta = () => json({ estado: "cancelando" }, 202);
  const t = montarTela(tarefas, {
    params: { id: "b" },
    extra: { agora: () => AGORA },
    rotas: {
      "GET /v1/tarefas/b": () => json(tarefa("b", "rodando", { progresso: 10, resultado: { texto: "parcial" } })),
      "DELETE /v1/tarefas/b": () => resposta(),
    },
  });
  await t.desmontar.pronto;
  assert.equal(campo(t.el, "resultado").textContent, "parcial");
  const btn = acao(t.el, "cancelar");
  assert.equal(btn.hidden, false);
  btn.disparar("click");
  await tique();
  assert.equal(t.chamadas.at(-1).metodo, "DELETE");
  assert.equal(campo(t.el, "estado").textContent, "Cancelando");
  assert.equal(btn.hidden, true);

  resposta = () => json({ erro: "ja_terminou", msg: "x" }, 409);
  const t2 = montarTela(tarefas, {
    params: { id: "b" },
    rotas: { "GET /v1/tarefas/b": () => json(tarefa("b", "na_fila")), "DELETE /v1/tarefas/b": () => resposta() },
  });
  await t2.desmontar.pronto;
  acao(t2.el, "cancelar").disparar("click");
  await tique();
  assert.match(campo(t2.el, "aviso").textContent, /já terminou/);
});

test("tarefas: tarefa pronta não mostra cancelar", async () => {
  const t = montarTela(tarefas, { params: { id: "a" }, rotas: { "GET /v1/tarefas/a": () => json(tarefa("a", "ok", { erro: null })) } });
  await t.desmontar.pronto;
  assert.equal(acao(t.el, "cancelar").hidden, true);
});

// ---------- Ajustes

test("ajustes: padrões, espelha no PUT, TV da casa, push vazio e versão", async () => {
  const puts = [];
  const t = montarTela(ajustes, {
    armazem: armazemMemoria({ [CHAVE_TOKEN]: "ayn_x", dispositivo: { nome: "celular-pedro", escopos: [] } }),
    rotas: {
      "GET /v1/casa/estado": () => json({ online: true, tvs: [{ id: "sala", nome: "TV da sala" }, { id: "quarto", nome: "TV do quarto" }], estados: [], apps: [] }),
      "PUT /v1/dispositivo/preferencias": (u, o) => (puts.push(JSON.parse(o.body)), json(null, 204)),
    },
  });
  await t.desmontar.pronto;
  assert.equal(campo(t.el, "dispositivo").textContent, "celular-pedro");
  assert.equal(campo(t.el, "push").children.length, 0); // a P2.2 preenche
  assert.match(campo(t.el, "versao").textContent, /Versão/);
  assert.equal(campo(t.el, "push_com_pc").checked, true);
  assert.equal(campo(t.el, "silencio").value, "23:00-07:30");
  const tv = campo(t.el, "tv_padrao");
  assert.deepEqual(tv.children.map((o) => o.value), ["", "sala", "quarto"]);

  campo(t.el, "push_com_pc").checked = false;
  campo(t.el, "push_com_pc").disparar("change");
  await tique();
  tv.value = "quarto";
  tv.disparar("change");
  await tique();
  campo(t.el, "silencio").value = "25:00-07:00";
  campo(t.el, "silencio").disparar("change");
  await tique();
  assert.match(campo(t.el, "aviso").textContent, /formato/);
  campo(t.el, "voz_em_texto").checked = true;
  campo(t.el, "voz_em_texto").disparar("change");
  await tique();
  assert.equal(puts.length, 3);
  assert.deepEqual(puts[0], { push: true, push_com_pc: false, silencio: "23:00-07:30", tv_padrao: null, voz_em_texto: false });
  assert.deepEqual(puts[2], { push: true, push_com_pc: false, silencio: "23:00-07:30", tv_padrao: "quarto", voz_em_texto: true });
  assert.deepEqual(await t.armazem.ler(ajustes.CHAVE_PREFS), puts[2]);
  t.desmontar();
});

test("ajustes: PUT sem rede guarda no celular e avisa", async () => {
  const t = montarTela(ajustes, { rotas: { "PUT /v1/dispositivo/preferencias": () => Promise.reject(new TypeError("x")) } });
  await t.desmontar.pronto;
  campo(t.el, "silencio").value = "";
  campo(t.el, "silencio").disparar("change");
  await tique();
  assert.equal((await t.armazem.ler(ajustes.CHAVE_PREFS)).silencio, "");
  assert.match(campo(t.el, "aviso").textContent, /Guardado no celular/);
});

test("ajustes: sair = DELETE /v1/dispositivo, apaga o token e vai a Parear", async () => {
  const t = montarTela(ajustes, { rotas: { "DELETE /v1/dispositivo": () => json(null, 204) } });
  await t.desmontar.pronto;
  acao(t.el, "sair").disparar("click");
  await tique();
  assert.ok(t.chamadas.some((c) => c.metodo === "DELETE" && c.url === "/v1/dispositivo" && c.auth === "Bearer ayn_falso"));
  assert.equal(await t.armazem.ler(CHAVE_TOKEN), undefined);
  assert.equal(t.estado.get().conexao, "sem_token");
  assert.deepEqual(t.navegou, ["#/parear"]);
});

test("ajustes: sair sem rede não apaga o token", async () => {
  const t = montarTela(ajustes, { rotas: { "DELETE /v1/dispositivo": () => Promise.reject(new TypeError("x")) } });
  await t.desmontar.pronto;
  acao(t.el, "sair").disparar("click");
  await tique();
  assert.equal(await t.armazem.ler(CHAVE_TOKEN), "ayn_falso");
  assert.deepEqual(t.navegou, []);
});

test("ajustes: botão instalar usa o beforeinstallprompt", async () => {
  let pediu = 0;
  const estado = criarEstado({ conexao: "ok_pc" });
  const t = montarTela(ajustes, { estado, rotas: {} });
  await t.desmontar.pronto;
  assert.equal(acao(t.el, "instalar").hidden, true);
  estado.set({ instalar: { prompt: async () => pediu++ } });
  assert.equal(acao(t.el, "instalar").hidden, false);
  acao(t.el, "instalar").disparar("click");
  await tique();
  assert.equal(pediu, 1);
  assert.equal(acao(t.el, "instalar").hidden, true);
});

// ---------- Confirmação

function relogio(inicio) {
  let agora = inicio;
  const fila = [];
  return {
    agora: () => agora,
    agendar: (fn, ms) => {
      const t = { quando: agora + ms, fn };
      fila.push(t);
      return t;
    },
    cancelar: (t) => fila.splice(fila.indexOf(t), 1),
    andar(ms) {
      agora += ms;
      for (const t of fila.filter((x) => x.quando <= agora)) {
        fila.splice(fila.indexOf(t), 1);
        t.fn();
      }
    },
  };
}

test("confirma: card da rota, confirmar → POST resposta=true", async () => {
  const t = montarTela(confirma, {
    params: { id: "01JCONF", d: "desligar a TV da sala" },
    rotas: { "POST /v1/confirma/01JCONF": () => json({ ok: true }) },
  });
  const card = achar(t.el, (e) => e.dataset?.pedido === "01JCONF");
  assert.match(card.textContent, /Desligar a TV da sala\?/);
  acao(card, "sim").disparar("click");
  await tique();
  assert.deepEqual(t.chamadas.map((c) => [c.metodo, c.url, c.corpo]), [["POST", "/v1/confirma/01JCONF", { resposta: true }]]);
  assert.equal(campo(card, "estado").textContent, "confirmado");
  assert.equal(acao(card, "nao").disabled, true);
});

test("confirma: 410 → expirou; 409 → já respondida", async () => {
  for (const [status, texto] of [[410, "expirou"], [409, "já respondida"]]) {
    const t = montarTela(confirma, { params: { id: "X" + status }, rotas: { [`POST /v1/confirma/X${status}`]: () => json({ msg: "x" }, status) } });
    acao(t.el, "nao").disparar("click");
    await tique();
    assert.equal(campo(t.el, "estado").textContent, texto);
    assert.equal(t.chamadas[0].corpo.resposta, false);
  }
});

test("confirma: SSE confirma desenha o card e expira pelo relógio sem POST", async () => {
  const r = relogio(AGORA);
  const t = montarTela(confirma, { extra: r, rotas: {} });
  t.eventos.emitir("confirma", { pedido: "01JSSE", descricao: "abrir a Netflix", origem: "mcp", expira_em: new Date(AGORA + 120000).toISOString() });
  t.eventos.emitir("confirma", { pedido: "01JVELHO", descricao: "x", expira_em: new Date(AGORA - 1).toISOString() });
  const card = achar(t.el, (e) => e.dataset?.pedido === "01JSSE");
  assert.ok(card);
  assert.equal(campo(achar(t.el, (e) => e.dataset?.pedido === "01JVELHO"), "estado").textContent, "expirou");
  assert.equal(campo(card, "estado").textContent, "");
  r.andar(120000);
  assert.equal(campo(card, "estado").textContent, "expirou");
  acao(card, "sim").disparar("click");
  await tique();
  assert.equal(t.chamadas.length, 0);
  assert.equal(confirma.rotaDe({ pedido: "01JSSE", descricao: "abrir a Netflix" }), "#/confirma/01JSSE?d=abrir+a+Netflix");
  // a rota reaproveita a descrição vista pelo SSE
  const t2 = montarTela(confirma, { params: { id: "01JSSE" }, extra: r, rotas: {} });
  assert.match(t2.el.textContent, /Abrir a Netflix\?/);
  t.desmontar();
  t2.desmontar();
});
