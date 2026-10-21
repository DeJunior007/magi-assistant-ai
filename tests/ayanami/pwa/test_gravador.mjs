// P1.2: máquina do PTT (spec §14.4, CA-Y55) com `MediaRecorder`/`getUserMedia`/relógio falsos,
// sem navegador. Dono: P1.2.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as gravador from "../../../ayanami/pwa/gravador.js";

const tick = () => new Promise((ok) => setImmediate(ok));

function relogioFalso() {
  let t = 0;
  let n = 0;
  const fila = new Map();
  return {
    agora: () => t,
    agendar: (fn, ms) => {
      fila.set(++n, { fn, em: t + ms });
      return n;
    },
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

function ambiente({ suporta = true, semIsType = false, gumFalha = false, gumManual = false } = {}) {
  const trilhas = [];
  const gravadores = [];
  const pedidos = [];
  let liberar = null;
  const novoStream = () => {
    const tr = { parado: false, stop() { this.parado = true; } };
    trilhas.push(tr);
    return { getTracks: () => [tr] };
  };
  const midia = {
    getUserMedia(r) {
      pedidos.push(r);
      if (gumFalha) return Promise.reject(new Error("NotAllowedError"));
      if (gumManual) return new Promise((ok) => (liberar = () => ok(novoStream())));
      return Promise.resolve(novoStream());
    },
  };
  class MR {
    constructor(stream, opcoes) {
      this.stream = stream;
      this.opcoes = opcoes;
      this.state = "inactive";
      gravadores.push(this);
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["x".repeat(64)]) });
      queueMicrotask(() => this.onstop?.());
    }
  }
  if (!semIsType) MR.isTypeSupported = (m) => suporta && m === "audio/webm;codecs=opus";
  const relogio = relogioFalso();
  const estados = [];
  const toasts = [];
  const blobs = [];
  const gestos = [];
  return {
    trilhas, gravadores, pedidos, relogio, estados, toasts, blobs, gestos, midia, MR,
    liberar: () => liberar(),
    opcoes(extra = {}) {
      return {
        midia, MediaRecorder: MR, relogio,
        aoEstado: (s) => estados.push(s),
        aoToast: (m) => toasts.push(m),
        aoGesto: () => gestos.push(relogio.agora()),
        aoBlob: async (b) => void blobs.push(b),
        ...extra,
      };
    },
  };
}

const todasParadas = (a) => a.trilhas.length > 0 && a.trilhas.every((t) => t.parado);

test("suportado(): sem isTypeSupported ou sem opus → falso; com opus → verdadeiro", () => {
  const sem = ambiente({ semIsType: true });
  assert.equal(gravador.suportado(sem.MR, sem.midia), false);
  const naoOpus = ambiente({ suporta: false });
  assert.equal(gravador.suportado(naoOpus.MR, naoOpus.midia), false);
  const ok = ambiente();
  assert.equal(gravador.suportado(ok.MR, ok.midia), true);
  assert.equal(gravador.suportado(undefined, ok.midia), false);
});

test("gravação normal: restrições, opus 24 kbps, blob webm/opus e microfone solto", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes());
  assert.equal(g.apertar(), true);
  assert.equal(a.gestos.length, 1, "aoGesto roda dentro do gesto");
  await tick();
  assert.deepEqual(a.pedidos[0], { audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  assert.deepEqual(a.gravadores[0].opcoes, { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 24000 });
  assert.equal(g.micAberto(), true);
  a.relogio.avancar(1200);
  g.soltar();
  await tick();
  assert.equal(a.blobs.length, 1);
  assert.equal(a.blobs[0].type, "audio/webm;codecs=opus");
  assert.ok(a.blobs[0].size > 0);
  assert.ok(todasParadas(a));
  assert.equal(g.micAberto(), false);
  assert.deepEqual(a.estados, ["gravando", "enviando", "pensando"]);
  g.falando();
  g.pronto();
  assert.equal(g.estado(), "ocioso");
});

test("< 400 ms é descartado com 'segurou pouco' e solta o microfone", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  await tick();
  a.relogio.avancar(399);
  g.soltar();
  await tick();
  assert.equal(a.blobs.length, 0);
  assert.deepEqual(a.toasts, ["segurou pouco"]);
  assert.ok(todasParadas(a));
  assert.equal(g.estado(), "ocioso");
});

test("15 s para sozinho e envia", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  await tick();
  a.relogio.avancar(14999);
  assert.equal(a.gravadores[0].state, "recording");
  a.relogio.avancar(1);
  await tick();
  assert.equal(a.gravadores[0].state, "inactive");
  assert.equal(a.blobs.length, 1);
  assert.ok(todasParadas(a));
  assert.equal(g.estado(), "pensando");
  g.soltar(); // o pointerup que vem depois não faz nada
  await tick();
  assert.equal(a.blobs.length, 1);
});

test("cancelar (saiu do botão) não envia e solta o microfone", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  await tick();
  a.relogio.avancar(3000);
  g.cancelar();
  await tick();
  assert.equal(a.blobs.length, 0);
  assert.deepEqual(a.toasts, []);
  assert.ok(todasParadas(a));
  assert.equal(g.estado(), "ocioso");
});

test("soltou antes do microfone abrir: a trilha que chega depois é parada e nada grava", async () => {
  const a = ambiente({ gumManual: true });
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  g.soltar();
  a.liberar();
  await tick();
  assert.equal(a.gravadores.length, 0);
  assert.ok(todasParadas(a));
  assert.equal(a.blobs.length, 0);
  assert.equal(g.estado(), "ocioso");
});

test("getUserMedia recusado → ocioso + toast, nada aberto", async () => {
  const a = ambiente({ gumFalha: true });
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  await tick();
  assert.equal(g.estado(), "ocioso");
  assert.deepEqual(a.toasts, ["sem acesso ao microfone"]);
  assert.equal(g.micAberto(), false);
});

test("erro do MediaRecorder → ocioso + toast, microfone solto", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  await tick();
  a.gravadores[0].onerror();
  assert.equal(g.estado(), "ocioso");
  assert.ok(todasParadas(a));
  assert.equal(a.toasts.length, 1);
});

test("envio falhou → ocioso + toast, microfone solto", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes({ aoBlob: async () => { throw new Error("sem conexão"); } }));
  g.apertar();
  await tick();
  a.relogio.avancar(1000);
  g.soltar();
  await tick();
  await tick();
  assert.equal(g.estado(), "ocioso");
  assert.deepEqual(a.toasts, ["sem conexão"]);
  assert.ok(todasParadas(a));
});

test("fechar no meio da gravação solta o microfone", async () => {
  const a = ambiente();
  const g = gravador.criarGravador(a.opcoes());
  g.apertar();
  await tick();
  g.fechar();
  await tick();
  assert.ok(todasParadas(a));
  assert.equal(a.blobs.length, 0);
});

test("sem opus: apertar não pede microfone e avisa", () => {
  const a = ambiente({ suporta: false });
  const g = gravador.criarGravador(a.opcoes());
  assert.equal(g.apertar(), false);
  assert.equal(a.pedidos.length, 0);
  assert.deepEqual(a.toasts, ["seu navegador não grava opus"]);
});

// ---------- botão (DOM falso)

function elem(doc, tag) {
  return {
    ownerDocument: doc, tagName: tag.toUpperCase(), children: [], dataset: {}, attrs: {}, ouvintes: {},
    textContent: "", className: "", disabled: false,
    append(...fs) { this.children.push(...fs); },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(ev, fn) { (this.ouvintes[ev] ??= []).push(fn); },
    disparar(tipo, e = {}) { for (const fn of this.ouvintes[tipo] ?? []) fn({ type: tipo, preventDefault() {}, ...e }); },
  };
}
const doc = { createElement: (t) => elem(doc, t) };

test("montar: sem opus o botão some e fica o aviso", () => {
  const a = ambiente({ semIsType: true });
  const raiz = elem(doc, "div");
  const r = gravador.montar(raiz, a.opcoes());
  assert.equal(r.botao, null);
  assert.equal(raiz.children.length, 1);
  assert.equal(raiz.children[0].dataset.papel, "sem-opus");
  assert.match(raiz.children[0].textContent, /não grava opus/);
});

test("montar: pointerdown/up grava e envia; pointerleave cancela", async () => {
  const a = ambiente();
  const raiz = elem(doc, "div");
  const r = gravador.montar(raiz, a.opcoes());
  const b = r.botao;
  assert.equal(b.dataset.papel, "ptt");
  b.disparar("pointerdown", { pointerId: 1 });
  await tick();
  a.relogio.avancar(800);
  b.disparar("pointerup");
  await tick();
  assert.equal(a.blobs.length, 1);
  r.gravador.pronto();

  b.disparar("pointerdown", { pointerId: 2 });
  await tick();
  a.relogio.avancar(2000);
  b.disparar("pointerleave");
  await tick();
  assert.equal(a.blobs.length, 1);
  assert.ok(todasParadas(a));
  assert.equal(r.gravador.estado(), "ocioso");
  r.fechar();
});
