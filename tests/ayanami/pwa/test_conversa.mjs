// P1.2: tela Conversa (spec §14.2, §14.5) com DOM, API, SSE, `MediaRecorder` e `<audio>` falsos,
// sem navegador. Dono: P1.2.
import { test } from "node:test";
import assert from "node:assert/strict";
import { armazemMemoria } from "../../../ayanami/pwa/api.js";
import { criarEstado } from "../../../ayanami/pwa/estado.js";
import * as conversa from "../../../ayanami/pwa/telas/conversa.js";

const tick = async (n = 3) => {
  for (let i = 0; i < n; i++) await new Promise((ok) => setImmediate(ok));
};

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
  addEventListener(ev, fn) {
    (this.ouvintes[ev] ??= []).push(fn);
  }
  disparar(tipo, e = {}) {
    return Promise.all((this.ouvintes[tipo] ?? []).map((fn) => fn({ type: tipo, preventDefault() {}, ...e })));
  }
}
const criarDoc = () => {
  const doc = { createElement: (t) => new Elem(doc, t) };
  return doc;
};
function achar(raiz, papel) {
  if (raiz.dataset?.papel === papel) return raiz;
  for (const c of raiz.children ?? []) {
    const r = achar(c, papel);
    if (r) return r;
  }
  return null;
}
const falas = (raiz) => achar(raiz, "historico").children.map((li) => [li.dataset.quem, li.textContent]);

// ---------- relógio, barramento, API, mídia

function relogioFalso(t0 = Date.parse("2026-10-21T12:00:00")) {
  let t = t0;
  let n = 0;
  const fila = new Map();
  return {
    agora: () => t,
    agendar: (fn, ms) => (fila.set(++n, { fn, em: t + ms }), n),
    cancelar: (id) => void fila.delete(id),
    avancar(ms) {
      const alvo = t + ms;
      for (;;) {
        let prox = null;
        for (const [id, x] of fila) if (x.em <= alvo && (!prox || x.em < prox[1].em)) prox = [id, x];
        if (!prox) break;
        fila.delete(prox[0]);
        t = prox[1].em;
        prox[1].fn();
      }
      t = alvo;
    },
  };
}

function barramento() {
  const mapa = new Map();
  return {
    on(nome, fn) {
      if (!mapa.has(nome)) mapa.set(nome, new Set());
      mapa.get(nome).add(fn);
      return () => mapa.get(nome).delete(fn);
    },
    emitir(nome, dados) {
      for (const fn of [...(mapa.get(nome) || [])]) fn(dados);
    },
    total: () => [...mapa.values()].reduce((s, x) => s + x.size, 0),
  };
}

function mediaFalsa() {
  const trilhas = [];
  const midia = {
    getUserMedia: async () => {
      const tr = { parado: false, stop() { this.parado = true; } };
      trilhas.push(tr);
      return { getTracks: () => [tr] };
    },
  };
  class MR {
    static isTypeSupported = (m) => m === "audio/webm;codecs=opus";
    constructor() { this.state = "inactive"; }
    start() { this.state = "recording"; }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["opus"]) });
      queueMicrotask(() => this.onstop?.());
    }
  }
  return { midia, MediaRecorder: MR, trilhas };
}

function montarTela({ resposta = { turno: "T1", modo: "nuvem" }, prefs = {}, armazem = armazemMemoria(), antesDo202 = [], semOpus = false, audioStatus = 200 } = {}) {
  const doc = criarDoc();
  const el = new Elem(doc, "main");
  const eventos = barramento();
  const relogio = relogioFalso();
  const posts = [];
  const brutos = [];
  const api = {
    async post(c, corpo) {
      posts.push([c, corpo]);
      for (const [n, d] of antesDo202) eventos.emitir(n, d);
      return resposta;
    },
    async bruto(c) {
      brutos.push(c);
      return { ok: audioStatus === 200, status: audioStatus, blob: async () => new Blob(["ogg"], { type: "audio/ogg;codecs=opus" }) };
    },
  };
  const audios = [];
  const criarAudio = () => {
    const a = { src: "", tocou: 0, play() { this.tocou++; return Promise.resolve(); }, pause() {} };
    audios.push(a);
    return a;
  };
  const URL = { createObjectURL: () => "blob:falso", revokeObjectURL: () => {} };
  const m = mediaFalsa();
  const estado = criarEstado({ prefs });
  const fim = conversa.montar(el, {
    api, estado, eventos, armazem, relogio, criarAudio, URL,
    midia: m.midia, MediaRecorder: semOpus ? undefined : m.MediaRecorder,
  });
  return { el, eventos, relogio, posts, brutos, audios, fim, m, armazem };
}

async function escrever(t, texto) {
  achar(t.el, "texto").value = texto;
  await achar(t.el, "form").disparar("submit");
  await tick();
}

test("sem DOM: desenha só o nome (stub da P1.1 continua valendo)", () => {
  const el = { textContent: "" };
  const fim = conversa.montar(el, {});
  assert.equal(el.textContent, "Conversa");
  assert.equal(typeof fim, "function");
});

test("turno de texto: POST JSON, selo nuvem, texto pelo SSE e sem áudio por padrão", async () => {
  const t = montarTela();
  await escrever(t, "que horas são");
  assert.deepEqual(t.posts, [["/v1/turno", { texto: "que horas são" }]]);
  const selo = achar(t.el, "selo");
  assert.equal(selo.hidden, false);
  assert.equal(selo.textContent, "nuvem");
  assert.equal(achar(t.el, "rosto").dataset.estado, "pensando");
  t.eventos.emitir("turno.texto", { turno: "T1", texto: "São meio-dia." });
  assert.deepEqual(falas(t.el), [["eu", "que horas são"], ["ela", "São meio-dia."]]);
  t.eventos.emitir("turno.fim", { turno: "T1", ok: true, texto: "São meio-dia.", fala: "São meio-dia.", audio: true });
  await tick();
  assert.deepEqual(falas(t.el), [["eu", "que horas são"], ["ela", "São meio-dia."]]);
  assert.deepEqual(t.brutos, []);
  assert.equal(t.audios.length, 0);
  assert.equal(achar(t.el, "rosto").dataset.estado, "ocioso");
  t.fim();
});

test("turno de texto com voz_em_texto ligada toca o áudio", async () => {
  const t = montarTela({ prefs: { voz_em_texto: true } });
  await escrever(t, "oi");
  assert.equal(t.audios.length, 1, "o <audio> nasce no gesto do envio");
  t.eventos.emitir("turno.fim", { turno: "T1", ok: true, texto: "Oi.", audio: true });
  await tick();
  assert.deepEqual(t.brutos, ["/v1/turno/T1/audio"]);
  assert.equal(t.audios[0].src, "blob:falso");
  t.fim();
});

test("PTT: multipart com audio, selo PC, <audio> criado no gesto toca GET /v1/turno/{id}/audio", async () => {
  const t = montarTela({ resposta: { turno: "T9", modo: "pc" } });
  const ptt = achar(t.el, "ptt");
  await ptt.disparar("pointerdown", { pointerId: 1 });
  assert.equal(t.audios.length, 1, "criado dentro do pointerdown");
  assert.equal(achar(t.el, "rosto").dataset.estado, "gravando");
  await tick();
  t.relogio.avancar(1500);
  await ptt.disparar("pointerup");
  await tick();
  assert.equal(t.posts.length, 1);
  const [caminho, corpo] = t.posts[0];
  assert.equal(caminho, "/v1/turno");
  assert.ok(corpo instanceof FormData);
  assert.equal(corpo.get("audio").type, "audio/webm;codecs=opus");
  assert.ok(t.m.trilhas.every((x) => x.parado), "microfone solto");
  assert.equal(achar(t.el, "selo").textContent, "PC");
  t.eventos.emitir("turno.fim", { turno: "T9", ok: true, texto: "Feito.", audio: true });
  await tick();
  assert.deepEqual(t.brutos, ["/v1/turno/T9/audio"]);
  assert.equal(t.audios[0].src, "blob:falso");
  assert.equal(achar(t.el, "rosto").dataset.estado, "falando");
  t.audios[0].onended();
  assert.equal(achar(t.el, "rosto").dataset.estado, "ocioso");
  assert.deepEqual(falas(t.el), [["eu", "(voz)"], ["ela", "Feito."]]);
  t.fim();
});

test("áudio 410 (já apagado) não quebra: fica o texto e o rosto volta a dormir", async () => {
  const t = montarTela({ audioStatus: 410 });
  const ptt = achar(t.el, "ptt");
  await ptt.disparar("pointerdown", { pointerId: 1 });
  await tick();
  t.relogio.avancar(1000);
  await ptt.disparar("pointerup");
  await tick();
  t.eventos.emitir("turno.fim", { turno: "T1", ok: true, texto: "Ok.", audio: true });
  await tick();
  assert.equal(t.audios[0].src, "");
  t.fim();
});

test("eventos do SSE que chegam antes do 202 são aplicados quando o id volta", async () => {
  const t = montarTela({
    antesDo202: [
      ["turno.texto", { turno: "T1", texto: "Rápida." }],
      ["turno.fim", { turno: "T1", ok: true, texto: "Rápida.", audio: false }],
    ],
  });
  await escrever(t, "seja rápida");
  assert.deepEqual(falas(t.el), [["eu", "seja rápida"], ["ela", "Rápida."]]);
  t.relogio.avancar(60000);
  assert.equal(achar(t.el, "aviso").hidden, true, "turno fechado não mostra o aviso");
  t.fim();
});

test("50 s sem turno.fim → 'Ela não respondeu; tenta de novo?'", async () => {
  const t = montarTela();
  await escrever(t, "alô");
  t.relogio.avancar(49999);
  assert.equal(achar(t.el, "aviso").hidden, true);
  t.relogio.avancar(1);
  const aviso = achar(t.el, "aviso");
  assert.equal(aviso.hidden, false);
  assert.equal(aviso.textContent, "Ela não respondeu; tenta de novo?");
  assert.equal(achar(t.el, "rosto").dataset.estado, "ocioso");
  t.fim();
});

test("pc_caiu vira a frase da spec; outro turno é ignorado", async () => {
  const t = montarTela({ resposta: { turno: "T2", modo: "pc" } });
  await escrever(t, "liga a tv");
  t.eventos.emitir("turno.texto", { turno: "OUTRO", texto: "não é meu" });
  t.eventos.emitir("turno.fim", { turno: "T2", ok: false, erro: "pc_caiu" });
  await tick();
  assert.deepEqual(falas(t.el), [["eu", "liga a tv"], ["erro", "perdi o PC no meio; repete?"]]);
  t.fim();
});

test("histórico do dia: hoje volta, ontem é descartado; novas falas são guardadas", async () => {
  const hojeA = armazemMemoria({ conversa: { dia: "2026-10-21", itens: [{ quem: "eu", texto: "bom dia", hora: 1 }] } });
  const t = montarTela({ armazem: hojeA });
  await tick();
  assert.deepEqual(falas(t.el), [["eu", "bom dia"]]);
  await escrever(t, "e aí");
  const salvo = await hojeA.ler("conversa");
  assert.equal(salvo.dia, "2026-10-21");
  assert.deepEqual(salvo.itens.map((i) => i.texto), ["bom dia", "e aí"]);
  t.fim();

  const ontem = armazemMemoria({ conversa: { dia: "2026-10-20", itens: [{ quem: "eu", texto: "velho", hora: 1 }] } });
  const t2 = montarTela({ armazem: ontem });
  await tick();
  assert.deepEqual(falas(t2.el), []);
  t2.fim();
});

test("sem opus: sem botão de PTT, aviso e o texto continua funcionando", async () => {
  const t = montarTela({ semOpus: true });
  assert.equal(achar(t.el, "ptt"), null);
  assert.match(achar(t.el, "sem-opus").textContent, /não grava opus/);
  await escrever(t, "só texto");
  assert.equal(t.posts.length, 1);
  t.fim();
});

test("desmontar cancela as inscrições do SSE e solta o microfone", async () => {
  const t = montarTela();
  assert.equal(t.eventos.total(), 2);
  const ptt = achar(t.el, "ptt");
  await ptt.disparar("pointerdown", { pointerId: 1 });
  await tick();
  t.fim();
  assert.equal(t.eventos.total(), 0);
  assert.ok(t.m.trilhas.every((x) => x.parado));
});
