/**
 * Gravação do push-to-talk (spec §14.4, CA-Y55). Dono: P1.2.
 *
 * Máquina: `ocioso → gravando` (pointerdown) `→ enviando` (pointerup ou 15 s automáticos)
 * `→ pensando → falando → ocioso`; erro em qualquer passo → `ocioso` + toast.
 *
 * - `getUserMedia` só no gesto (`apertar`), com canal mono, eco e ruído cancelados;
 * - `MediaRecorder` `audio/webm;codecs=opus` a 24 kbps, só depois de `isTypeSupported`;
 *   sem suporte → `suportado()` é falso e o botão some (fica só texto);
 * - gravação < 400 ms é descartada ("segurou pouco"); arrastar para fora cancela;
 * - o microfone é solto (`track.stop()`) em todo caminho que encerra a gravação.
 *
 * `criarGravador(opcoes)` é a máquina sem DOM (testada no `node --test`); `montar(el, ctx)`
 * desenha o botão "segurar para falar" e liga os eventos de ponteiro a ela.
 */

export const MIME = "audio/webm;codecs=opus";
export const BITS = 24000;
export const MINIMO_MS = 400;
export const MAXIMO_MS = 15000;
export const RESTRICOES = Object.freeze({
  audio: Object.freeze({ channelCount: 1, echoCancellation: true, noiseSuppression: true }),
});
export const ESTADOS = Object.freeze(["ocioso", "gravando", "enviando", "pensando", "falando"]);

/** O navegador grava opus em webm? (`MediaRecorder.isTypeSupported`). */
export function suportado(MR = globalThis.MediaRecorder, midia = globalThis.navigator?.mediaDevices) {
  try {
    return Boolean(MR && typeof MR.isTypeSupported === "function" && MR.isTypeSupported(MIME) && midia?.getUserMedia);
  } catch {
    return false;
  }
}

const relogioReal = {
  agora: () => Date.now(),
  agendar: (fn, ms) => setTimeout(fn, ms),
  cancelar: (t) => clearTimeout(t),
};

/**
 * Máquina do PTT. Opções (todas injetáveis):
 * `midia` (`navigator.mediaDevices`), `MediaRecorder`, `Blob`, `relogio` `{agora, agendar,
 * cancelar}`, `aoEstado(novo, antigo)`, `aoToast(msg)`, `aoGesto()` (síncrono, dentro do gesto:
 * a Conversa cria o `<audio>` aí) e `aoBlob(blob)` (envia; pode devolver Promise).
 */
export function criarGravador({
  midia = globalThis.navigator?.mediaDevices,
  MediaRecorder: MR = globalThis.MediaRecorder,
  Blob: B = globalThis.Blob,
  relogio = relogioReal,
  aoEstado = () => {},
  aoToast = () => {},
  aoGesto = () => {},
  aoBlob = async () => {},
} = {}) {
  let estado = "ocioso";
  let sessao = 0; // cada gravação tem um número; respostas atrasadas de outra são ignoradas
  let stream = null;
  let gravador = null;
  let pedaços = [];
  let inicio = null;
  let soltou = false;
  let cancelado = false;
  let limite = null;

  function ir(novo) {
    if (novo === estado) return;
    const antes = estado;
    estado = novo;
    aoEstado(novo, antes);
  }

  /** Solta o microfone (idempotente). */
  function soltarMic() {
    if (limite !== null) {
      relogio.cancelar(limite);
      limite = null;
    }
    const s = stream;
    stream = null;
    if (!s) return;
    for (const t of s.getTracks?.() ?? []) {
      try {
        t.stop();
      } catch {
        /* segue soltando as outras */
      }
    }
  }

  function falhar(msg) {
    soltarMic();
    gravador = null;
    pedaços = [];
    sessao++;
    ir("ocioso");
    if (msg) aoToast(msg);
  }

  async function aoParar(minha, duracao) {
    soltarMic();
    const partes = pedaços;
    gravador = null;
    pedaços = [];
    if (minha !== sessao) return;
    if (cancelado) {
      ir("ocioso");
      return;
    }
    if (duracao < MINIMO_MS) {
      ir("ocioso");
      aoToast("segurou pouco");
      return;
    }
    ir("enviando");
    try {
      await aoBlob(new B(partes, { type: MIME }));
      if (minha === sessao && estado === "enviando") ir("pensando");
    } catch (e) {
      if (minha === sessao) falhar((e && e.message) || "não deu para enviar");
    }
  }

  function encerrar() {
    if (!gravador) {
      // ainda esperando o getUserMedia: o `then` vê `soltou` e descarta
      return;
    }
    const duracao = relogio.agora() - inicio;
    const g = gravador;
    const minha = sessao;
    let parou = false;
    g.onstop = () => {
      if (parou) return;
      parou = true;
      aoParar(minha, duracao);
    };
    try {
      if (g.state !== "inactive") g.stop();
      else g.onstop();
    } catch {
      falhar("a gravação falhou");
    }
  }

  /** pointerdown: pede o microfone (no gesto) e começa a gravar. */
  function apertar() {
    if (estado !== "ocioso") return false;
    if (!suportado(MR, midia)) {
      aoToast("seu navegador não grava opus");
      return false;
    }
    const minha = ++sessao;
    soltou = false;
    cancelado = false;
    pedaços = [];
    inicio = null;
    try {
      aoGesto();
    } catch {
      /* o áudio é opcional */
    }
    ir("gravando");
    let pedido;
    try {
      pedido = Promise.resolve(midia.getUserMedia(RESTRICOES));
    } catch (e) {
      pedido = Promise.reject(e);
    }
    pedido.then(
      (s) => {
        if (minha !== sessao || soltou) {
          // soltou antes do microfone abrir: fecha já e descarta
          for (const t of s?.getTracks?.() ?? []) t.stop();
          if (minha === sessao) {
            ir("ocioso");
            if (!cancelado) aoToast("segurou pouco");
          }
          return;
        }
        stream = s;
        try {
          gravador = new MR(s, { mimeType: MIME, audioBitsPerSecond: BITS });
          gravador.ondataavailable = (ev) => {
            if (ev?.data && ev.data.size !== 0) pedaços.push(ev.data);
          };
          gravador.onerror = () => {
            if (minha === sessao) falhar("a gravação falhou");
          };
          gravador.start();
          inicio = relogio.agora();
          limite = relogio.agendar(() => {
            limite = null;
            if (minha === sessao && estado === "gravando") soltar();
          }, MAXIMO_MS);
        } catch {
          falhar("a gravação falhou");
        }
      },
      () => {
        if (minha === sessao) falhar("sem acesso ao microfone");
      },
    );
    return true;
  }

  /** pointerup (ou os 15 s): para e envia (ou descarta se < 400 ms). */
  function soltar() {
    if (estado !== "gravando" || soltou) return;
    soltou = true;
    encerrar();
  }

  /** Saiu do botão / pointercancel: para sem enviar. */
  function cancelar() {
    if (estado !== "gravando" || soltou) return;
    soltou = true;
    cancelado = true;
    if (!gravador) {
      ir("ocioso");
      return;
    }
    encerrar();
  }

  return {
    estado: () => estado,
    apertar,
    soltar,
    cancelar,
    /** A Conversa avança a máquina conforme a resposta chega. */
    pensando: () => (estado === "enviando" || estado === "ocioso") && ir("pensando"),
    falando: () => estado !== "gravando" && ir("falando"),
    pronto: () => estado !== "gravando" && ir("ocioso"),
    erro: (msg) => falhar(msg),
    /** Desmontagem: solta tudo. */
    fechar() {
      cancelado = true;
      soltou = true;
      const g = gravador;
      sessao++;
      gravador = null;
      try {
        if (g && g.state !== "inactive") g.stop();
      } catch {
        /* nada */
      }
      soltarMic();
    },
    /** Só para teste: o microfone está aberto? */
    micAberto: () => stream !== null,
  };
}

/**
 * Desenha o botão "segurar para falar" em `el`. `ctx`: as mesmas opções de `criarGravador`.
 * Devolve `{gravador, botao, fechar}`; sem opus, o botão some e aparece o aviso.
 */
export function montar(el, ctx = {}) {
  const doc = el.ownerDocument;
  const MR = "MediaRecorder" in ctx ? ctx.MediaRecorder : globalThis.MediaRecorder;
  const midia = "midia" in ctx ? ctx.midia : globalThis.navigator?.mediaDevices;
  const g = criarGravador({ ...ctx, MediaRecorder: MR, midia });
  if (!doc?.createElement) return Object.assign(() => g.fechar(), { gravador: g, botao: null, fechar: g.fechar });
  if (!suportado(MR, midia)) {
    const p = doc.createElement("p");
    p.className = "aviso-ptt";
    p.dataset.papel = "sem-opus";
    p.textContent = "seu navegador não grava opus";
    el.append(p);
    return Object.assign(() => {}, { gravador: g, botao: null, fechar: () => {} });
  }
  const b = doc.createElement("button");
  b.type = "button";
  b.className = "ptt precisa-rede";
  b.dataset.papel = "ptt";
  b.setAttribute("style", "touch-action: none");
  b.textContent = "segurar para falar";
  const sem = (e) => e?.preventDefault?.();
  b.addEventListener("pointerdown", (e) => {
    sem(e);
    if (b.disabled) return;
    // o toque captura o ponteiro sozinho: solta para o `pointerleave` cancelar
    try {
      if (e?.pointerId !== undefined) b.releasePointerCapture?.(e.pointerId);
    } catch {
      /* nada */
    }
    g.apertar();
  });
  b.addEventListener("pointerup", (e) => {
    sem(e);
    g.soltar();
  });
  b.addEventListener("pointerleave", () => g.cancelar());
  b.addEventListener("pointercancel", () => g.cancelar());
  b.addEventListener("contextmenu", sem);
  el.append(b);
  return Object.assign(() => g.fechar(), { gravador: g, botao: b, fechar: g.fechar });
}
