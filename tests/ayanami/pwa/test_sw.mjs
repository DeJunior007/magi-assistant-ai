// CA-Y57: service worker com `caches`/`fetch` falsos (sem navegador) e manifest válido. Dono: P1.1.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import vm from "node:vm";

const PWA = new URL("../../../ayanami/pwa/", import.meta.url).pathname;
const ORIGEM = "https://ayanami.exemplo.ts.net";
const CODIGO = readFileSync(join(PWA, "sw.js"), "utf8");

function cachesFalsos(base) {
  const lojas = new Map();
  const chave = (r) => new URL(typeof r === "string" ? r : r.url, base).href;
  const loja = (nome) => {
    if (!lojas.has(nome)) lojas.set(nome, new Map());
    const m = lojas.get(nome);
    return {
      m,
      async put(r, resp) { m.set(chave(r), resp); },
      async addAll(lista) { for (const r of lista) m.set(chave(r), new Response("arquivo " + r)); },
      async match(r, opc = {}) {
        const k = chave(r);
        if (m.has(k)) return m.get(k).clone();
        if (opc.ignoreSearch) {
          const sem = k.split("?")[0];
          for (const [kk, v] of m) if (kk.split("?")[0] === sem) return v.clone();
        }
        return undefined;
      },
    };
  };
  return {
    lojas,
    async open(nome) { return loja(nome); },
    async keys() { return [...lojas.keys()]; },
    async delete(nome) { return lojas.delete(nome); },
  };
}

function carregarSw({ rede }) {
  const ouvintes = {};
  const chamadas = [];
  const self = {
    location: new URL(ORIGEM + "/app/sw.js"),
    addEventListener: (t, fn) => (ouvintes[t] = fn),
    skipWaiting: async () => {},
    clients: { claim: async () => {} },
  };
  const caches = cachesFalsos(self.location.href);
  const fetch = async (req) => {
    chamadas.push(typeof req === "string" ? req : req.url);
    return rede(req);
  };
  vm.runInNewContext(CODIGO, { self, caches, fetch, URL, Response, Request, Headers, Promise, console });
  async function despachar(tipo, extra = {}) {
    let espera = null;
    let resposta = null;
    const ev = { ...extra, waitUntil: (p) => (espera = p), respondWith: (p) => (resposta = p) };
    ouvintes[tipo](ev);
    await espera;
    return resposta ? await resposta : null;
  }
  const pedir = (caminho, opc = {}) =>
    despachar("fetch", { request: new Request(ORIGEM + caminho, opc) });
  return { despachar, pedir, caches, chamadas, ouvintes };
}

const versao = () => Number(/const VERSAO = (\d+);/.exec(CODIGO)[1]);
const lista = () => JSON.parse(/const ARQUIVOS = (\[[\s\S]*?\]);/.exec(CODIGO)[1].replace(/,\s*\]/, "]"));

test("lista fixa cobre todos os arquivos do PWA (menos o sw.js) e todos existem", () => {
  const todos = [];
  const andar = (d) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      if (statSync(p).isDirectory()) andar(p);
      else todos.push(relative(PWA, p));
    }
  };
  andar(PWA);
  const arquivos = lista();
  assert.ok(arquivos.includes("./"));
  for (const a of arquivos.filter((a) => a !== "./")) assert.ok(existsSync(join(PWA, a)), a);
  assert.deepEqual(todos.filter((a) => a !== "sw.js").sort(), arquivos.filter((a) => a !== "./").sort());
});

test("install guarda a casca em condessa-shell-v<N>", async () => {
  const sw = carregarSw({ rede: () => { throw new TypeError("sem rede"); } });
  await sw.despachar("install");
  const loja = sw.caches.lojas.get("condessa-shell-v" + versao());
  assert.ok(loja.has(ORIGEM + "/app/"));
  assert.ok(loja.has(ORIGEM + "/app/telas/tv.js"));
  assert.equal(loja.size, lista().length);
});

test("activate apaga shell-v<N-1> e mantém o feed", async () => {
  const sw = carregarSw({ rede: () => new Response("") });
  const n = versao();
  for (const nome of [`condessa-shell-v${n - 1}`, `condessa-shell-v${n}`, "condessa-feed"]) await sw.caches.open(nome);
  await sw.despachar("activate");
  assert.deepEqual((await sw.caches.keys()).sort(), ["condessa-feed", `condessa-shell-v${n}`]);
});

test("/v1/feed: network-first, guarda o último e recai nele sem rede", async () => {
  let online = true;
  const sw = carregarSw({
    rede: () => {
      if (!online) throw new TypeError("sem rede");
      return new Response(JSON.stringify({ cards: [{ titulo: "a" }] }), { headers: { "Content-Type": "application/json" } });
    },
  });
  const r1 = await sw.pedir("/v1/feed?n=20");
  assert.deepEqual(await r1.json(), { cards: [{ titulo: "a" }] });
  assert.equal(sw.chamadas.length, 1);
  const feed = sw.caches.lojas.get("condessa-feed");
  assert.equal(feed.size, 1);
  online = false;
  const r2 = await sw.pedir("/v1/feed?n=20");
  assert.deepEqual(await r2.json(), { cards: [{ titulo: "a" }] });
  assert.ok(r2.headers.get("X-Condessa-Cache-Em"));
  assert.equal(sw.chamadas.length, 2);
});

test("/v1/feed sem rede e sem cópia → erro de rede", async () => {
  const sw = carregarSw({ rede: () => { throw new TypeError("sem rede"); } });
  await assert.rejects(sw.pedir("/v1/feed"));
});

test("/v1/casa/*, /v1/tarefas, /saude e /v1/eventos: network-only, nunca cacheados", async () => {
  const sw = carregarSw({ rede: () => new Response("{}") });
  for (const c of ["/v1/casa/estado", "/v1/tarefas", "/v1/tarefas/1", "/saude", "/v1/eventos", "/mcp"]) {
    assert.equal(await sw.pedir(c), null, c); // sem respondWith: vai direto à rede
  }
  assert.equal(await sw.pedir("/v1/turno", { method: "POST", body: "{}" }), null);
  assert.equal(sw.caches.lojas.size, 0);
});

test("casca: cache-first; navegação cai no index", async () => {
  const sw = carregarSw({ rede: () => { throw new TypeError("sem rede"); } });
  await sw.despachar("install");
  assert.equal(await (await sw.pedir("/app/app.js")).text(), "arquivo app.js");
  assert.equal(await (await sw.pedir("/app/?c=123456")).text(), "arquivo ./");
  assert.equal(sw.chamadas.length, 0);
  assert.equal(await sw.pedir("/app/sw.js"), null);
});

test("manifest com os campos da §14.6 e ícones existentes", () => {
  const m = JSON.parse(readFileSync(join(PWA, "manifest.webmanifest"), "utf8"));
  assert.equal(m.name, "Condessa");
  assert.equal(m.short_name, "Condessa");
  assert.equal(m.start_url, "/app/#/conversa");
  assert.equal(m.scope, "/app/");
  assert.equal(m.display, "standalone");
  assert.equal(m.orientation, "portrait");
  assert.equal(m.background_color, "#0b0b12");
  assert.equal(m.theme_color, "#0b0b12");
  assert.equal(m.lang, "pt-BR");
  assert.deepEqual(m.icons.map((i) => [i.src, i.sizes, i.purpose ?? null]), [
    ["icones/192.png", "192x192", null],
    ["icones/512.png", "512x512", null],
    ["icones/maskable-512.png", "512x512", "maskable"],
  ]);
  for (const i of m.icons) {
    const png = readFileSync(join(PWA, i.src));
    assert.equal(png.subarray(1, 4).toString(), "PNG");
    const [w, h] = [png.readUInt32BE(16), png.readUInt32BE(20)];
    assert.equal(`${w}x${h}`, i.sizes);
  }
});
