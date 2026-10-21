/**
 * Tela TV — controle remoto (spec §14.2 TV, design §5.6 *Pela Ayanami*). Dono: P1.3.
 *
 * `montar(el, ctx)`: `ctx` = `{api, estado, eventos, params, navegar}` (ver `app.js`) e, opcional,
 * `ctx.relogio` = `{agora, agendar, cancelar}` (injetado nos testes). Devolve a desmontagem.
 *
 * - abas por TV (`TvInfo` de `GET /v1/casa/estado`); `EstadoTv` vivo pelo SSE `estado` e pelo
 *   `dados.estado` do `AcaoResultado`;
 * - botões **só** das `caps` (`botoesDaTv`); `POST /v1/casa/acao` direto `{tv, pedido}`;
 * - "desligar" pede 2º toque em ≤ 3 s e só então manda `confirmed=true` (DS16); um toque só não
 *   manda nada;
 * - vol± segurado repete a cada 200 ms (a casa coalesce, §10.4);
 * - TV `online=false` → botões cinza "TV fora da rede"; casa offline (503 ou `online=false`) →
 *   "a casa está fora do ar";
 * - TV inicial: `#/tv/<id>` → `estado.prefs.tv_padrao` (Ajustes) → `TvInfo.padrao` → a primeira.
 */

export const CONFIRMA_MS = 3000;
export const REPETE_MS = 200;
export const REPETE_MAX = 50; // 10 s segurando: para sozinho (dedo que "sumiu" sem pointerup)
export const MSG_CASA_FORA = "a casa está fora do ar";
export const MSG_TV_FORA = "TV fora da rede";
export const MSG_TOQUE_DE_NOVO = "toque de novo para desligar";
export const MSG_TEMPO = "a TV não respondeu a tempo";
export const MSG_SEM_TV = "nenhuma TV configurada na casa";

/** `AcaoPedido` serializável (spec §1.2): `slots` = pares `[nome, valor]`. */
export function pedido(intent, { slots = {}, args = {}, texto = "", confirmed = false } = {}) {
  return { intent, slots: Object.entries(slots).map(([k, v]) => [k, String(v)]), texto, confirmed, args };
}

function rotuloEntrada(e) {
  const m = /^hdmi(\d)$/.exec(e);
  if (m) return `HDMI ${m[1]}`;
  return e === "tv" ? "TV" : e === "av" ? "AV" : e;
}

const DPAD = [
  ["up", "▲"], ["left", "◀"], ["ok", "OK"], ["right", "▶"], ["down", "▼"],
  ["back", "Voltar"], ["home", "Início"], ["play_pause", "Play/Pausa"],
];

/**
 * Botões de uma `TvInfo`, só das `caps` (CA-Y56). Cada um: `{chave, rotulo, grupo, fazer(estadoTv)
 * → AcaoPedido, repete?, perigosa?}`. `catalogo` = `[AppInfo]` (nome dos apps).
 */
export function botoesDaTv(tv, catalogo = []) {
  const caps = new Set(tv?.caps || []);
  const fixo = (p) => () => p;
  const b = [];
  if (caps.has("power_on")) b.push({ chave: "power_on", rotulo: "Ligar", grupo: "energia", fazer: fixo(pedido("tv.power_on")) });
  if (caps.has("power_off")) {
    b.push({ chave: "power_off", rotulo: "Desligar", grupo: "energia", perigosa: true, fazer: fixo(pedido("tv.power_off", { confirmed: true })) });
  }
  if (caps.has("vol_step")) {
    b.push({ chave: "vol_down", rotulo: "Vol −", grupo: "volume", repete: true, fazer: fixo(pedido("tv.volume", { slots: { volume: "-1" } })) });
    b.push({ chave: "vol_up", rotulo: "Vol +", grupo: "volume", repete: true, fazer: fixo(pedido("tv.volume", { slots: { volume: "+1" } })) });
  }
  if (caps.has("mute")) {
    b.push({ chave: "mute", rotulo: "Mudo", grupo: "volume", fazer: (e) => pedido(e?.mudo === true ? "tv.unmute" : "tv.mute") });
  }
  if (caps.has("channel")) {
    b.push({ chave: "ch_down", rotulo: "Canal −", grupo: "canal", fazer: fixo(pedido("tv.channel", { args: { step: -1 } })) });
    b.push({ chave: "ch_up", rotulo: "Canal +", grupo: "canal", fazer: fixo(pedido("tv.channel", { args: { step: 1 } })) });
  }
  if (caps.has("input")) {
    for (const e of tv.entradas || []) {
      b.push({ chave: `input:${e}`, rotulo: rotuloEntrada(e), grupo: "entradas", fazer: fixo(pedido("tv.input", { slots: { input: e } })) });
    }
  }
  if (caps.has("app")) {
    const nomes = new Map((catalogo || []).map((a) => [a.id, a.nome]));
    for (const id of tv.apps || []) {
      b.push({ chave: `app:${id}`, rotulo: nomes.get(id) || id, grupo: "apps", fazer: fixo(pedido("tv.app", { slots: { app: id } })) });
    }
  }
  if (caps.has("key")) {
    for (const [k, r] of DPAD) b.push({ chave: `key:${k}`, rotulo: r, grupo: "dpad", fazer: fixo(pedido("tv.key", { args: { key: k } })) });
  }
  return b;
}

/** Texto curto para o resultado de uma ação (a API já preenche `fala`, §13.2). */
export function mensagemDe(res) {
  if (!res) return "";
  if (res.erro === "casa_fora") return MSG_CASA_FORA;
  if (res.erro === "tempo") return MSG_TEMPO;
  if (res.erro) return res.erro;
  const r = res.resultado || {};
  if (r.ok) return r.fala || "";
  return r.fala || r.motivo || "não deu certo";
}

/**
 * Lógica do controle sem DOM: confirmação do desligar e envio.
 * `aoAviso(texto)` mostra avisos ("toque de novo…"); `aoResultado(res, tvId)` recebe o resultado.
 */
export function criarControle({ api, relogio, aoAviso = () => {}, aoResultado = () => {} }) {
  const r = relogioPadrao(relogio);
  let pendente = null; // {tv, chave, em, t}

  function limparPendente() {
    if (pendente) r.cancelar(pendente.t);
    pendente = null;
  }

  async function enviar(tvId, p) {
    let res;
    try {
      const resultado = await api.post("/v1/casa/acao", { tv: tvId, pedido: p });
      res = { resultado: resultado || {} };
    } catch (e) {
      const st = e?.status;
      res = { erro: st === 503 ? "casa_fora" : st === 504 ? "tempo" : e?.corpo?.msg || e?.corpo?.erro || "falhou", status: st };
    }
    aoResultado(res, tvId);
    return res;
  }

  /** Toque num botão; devolve a promessa do envio ou `null` quando nada foi mandado. */
  function tocar(tvId, botao, estadoTv) {
    if (botao.perigosa) {
      const agora = r.agora();
      if (pendente && pendente.tv === tvId && pendente.chave === botao.chave && agora - pendente.em <= CONFIRMA_MS) {
        limparPendente();
        aoAviso("");
        return enviar(tvId, botao.fazer(estadoTv));
      }
      limparPendente();
      pendente = { tv: tvId, chave: botao.chave, em: agora, t: r.agendar(() => { pendente = null; aoAviso(""); }, CONFIRMA_MS) };
      aoAviso(MSG_TOQUE_DE_NOVO);
      return null;
    }
    limparPendente();
    return enviar(tvId, botao.fazer(estadoTv));
  }

  return { tocar, enviar, parar: limparPendente, pendente: () => pendente };
}

function relogioPadrao(r = {}) {
  return {
    agora: r.agora || (() => Date.now()),
    agendar: r.agendar || ((fn, ms) => setTimeout(fn, ms)),
    cancelar: r.cancelar || ((t) => clearTimeout(t)),
  };
}

const ROTULO_GRUPO = { energia: "", volume: "Volume", canal: "Canal", entradas: "Entradas", apps: "Apps", dpad: "Navegação" };

export function montar(el, ctx) {
  const doc = el.ownerDocument;
  if (!doc?.createElement || !ctx?.api) {
    // sem DOM ou sem API (teste de contrato da P1.1): só o título
    el.textContent = "TV";
    return () => {};
  }
  const relogio = relogioPadrao(ctx.relogio);
  const { api, estado, eventos } = ctx;
  const s = { carregado: false, casaOnline: true, tvs: [], estados: new Map(), apps: [], ativa: null, aviso: "", resultado: "", erroCarga: "" };
  let vivo = true;
  let repeticao = null; // {t, n}

  const ctl = criarControle({
    api,
    relogio,
    aoAviso: (t) => { s.aviso = t; desenhar(); },
    aoResultado: (res) => {
      if (!vivo) return;
      if (res.erro === "casa_fora") {
        s.casaOnline = false;
        estado?.set?.({ casa_fora: true });
        pararRepeticao();
      }
      const e = res.resultado?.dados?.estado;
      if (e?.id) s.estados.set(e.id, e);
      s.resultado = mensagemDe(res);
      desenhar();
    },
  });

  function casaFora() {
    return !s.casaOnline || estado?.get?.().casa_fora === true;
  }

  function escolherAtiva() {
    if (s.ativa && s.tvs.some((t) => t.id === s.ativa)) return;
    const ids = s.tvs.map((t) => t.id);
    const prefs = estado?.get?.().prefs || {};
    const candidatas = [ctx.params?.id, prefs.tv_padrao, s.tvs.find((t) => t.padrao)?.id, ids[0]];
    s.ativa = candidatas.find((c) => c && ids.includes(c)) || null;
  }

  async function carregar() {
    try {
      const d = (await api.get("/v1/casa/estado")) || {};
      s.casaOnline = d.online !== false;
      s.tvs = d.tvs || [];
      s.apps = d.apps || [];
      s.estados = new Map((d.estados || []).map((e) => [e.id, e]));
      s.erroCarga = "";
    } catch (e) {
      if (e?.status === 503) s.casaOnline = false;
      else s.erroCarga = "não consegui ler as TVs";
    }
    if (!vivo) return;
    s.carregado = true;
    escolherAtiva();
    desenhar();
  }

  function pararRepeticao() {
    if (repeticao) relogio.cancelar(repeticao.t);
    repeticao = null;
  }

  function comecarRepeticao(tvId, botao) {
    pararRepeticao();
    const rep = { t: null, n: 0 };
    repeticao = rep;
    const passo = () => {
      if (repeticao !== rep || !vivo) return;
      ctl.enviar(tvId, botao.fazer(s.estados.get(tvId)));
      rep.n += 1;
      if (rep.n >= REPETE_MAX) return pararRepeticao();
      rep.t = relogio.agendar(passo, REPETE_MS);
    };
    passo();
  }

  function criar(tag, props = {}, filhos = []) {
    const n = doc.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "dataset") Object.assign(n.dataset, v);
      else n[k] = v;
    }
    if (filhos.length) n.append(...filhos);
    return n;
  }

  function botaoDom(tvId, botao, desabilitado) {
    const n = criar("button", { type: "button", textContent: botao.rotulo, className: "botao-tv precisa-rede precisa-casa", disabled: desabilitado, dataset: { acao: botao.chave } });
    if (botao.perigosa && s.aviso === MSG_TOQUE_DE_NOVO) n.className += " armado";
    if (botao.repete) {
      n.addEventListener("pointerdown", (ev) => { ev?.preventDefault?.(); if (!n.disabled) comecarRepeticao(tvId, botao); });
      for (const t of ["pointerup", "pointerleave", "pointercancel"]) n.addEventListener(t, pararRepeticao);
    } else {
      n.addEventListener("click", () => { if (!n.disabled) ctl.tocar(tvId, botao, s.estados.get(tvId)); });
    }
    return n;
  }

  function desenhar() {
    if (!vivo) return;
    const filhos = [criar("h1", { textContent: "TV" })];
    if (!s.carregado) {
      filhos.push(criar("p", { textContent: "carregando…", dataset: { papel: "aviso" } }));
      return el.replaceChildren(...filhos);
    }
    if (casaFora()) filhos.push(criar("p", { className: "faixa", textContent: MSG_CASA_FORA, dataset: { papel: "casa-fora" } }));
    if (s.erroCarga) filhos.push(criar("p", { textContent: s.erroCarga, dataset: { papel: "erro" } }));
    if (!s.tvs.length) {
      if (!casaFora() && !s.erroCarga) filhos.push(criar("p", { textContent: MSG_SEM_TV, dataset: { papel: "aviso" } }));
      return el.replaceChildren(...filhos);
    }
    if (s.tvs.length > 1) {
      const abas = criar("nav", { className: "abas abas-tv" });
      for (const t of s.tvs) {
        const a = criar("button", { type: "button", textContent: t.nome, className: t.id === s.ativa ? "aba ativa" : "aba", dataset: { tv: t.id } });
        a.addEventListener("click", () => { ctl.parar(); pararRepeticao(); s.ativa = t.id; s.aviso = ""; s.resultado = ""; desenhar(); });
        abas.append(a);
      }
      filhos.push(abas);
    }
    const tv = s.tvs.find((t) => t.id === s.ativa);
    const est = s.estados.get(tv.id);
    const tvFora = est?.online === false;
    const desabilitado = tvFora || casaFora();
    const painel = criar("section", { className: tvFora ? "controle cinza" : "controle", dataset: { tv: tv.id } });
    if (tvFora) painel.append(criar("p", { textContent: MSG_TV_FORA, dataset: { papel: "tv-fora" } }));
    const grupos = new Map();
    for (const b of botoesDaTv(tv, s.apps)) {
      if (!grupos.has(b.grupo)) grupos.set(b.grupo, []);
      grupos.get(b.grupo).push(botaoDom(tv.id, b, desabilitado));
    }
    for (const [g, nos] of grupos) {
      const sec = criar("div", { className: `grupo grupo-${g}` });
      if (ROTULO_GRUPO[g]) sec.append(criar("h2", { textContent: ROTULO_GRUPO[g] }));
      sec.append(...nos);
      painel.append(sec);
    }
    if ((tv.caps || []).includes("text")) {
      const campo = criar("input", { type: "text", placeholder: "digitar na TV", className: "precisa-rede precisa-casa", disabled: desabilitado, dataset: { papel: "texto" } });
      const form = criar("form", { className: "grupo grupo-texto" }, [
        campo,
        criar("button", { type: "submit", textContent: "Enviar", className: "precisa-rede precisa-casa", disabled: desabilitado, dataset: { acao: "text" } }),
      ]);
      form.addEventListener("submit", (ev) => {
        ev?.preventDefault?.();
        const texto = String(campo.value || "");
        if (!texto || campo.disabled) return;
        campo.value = "";
        ctl.enviar(tv.id, pedido("tv.text", { args: { texto } }));
      });
      painel.append(form);
    }
    filhos.push(painel);
    if (s.aviso) filhos.push(criar("p", { textContent: s.aviso, dataset: { papel: "aviso" } }));
    if (s.resultado) filhos.push(criar("p", { textContent: s.resultado, dataset: { papel: "resultado" } }));
    el.replaceChildren(...filhos);
  }

  const saidas = [];
  if (eventos?.on) {
    saidas.push(eventos.on("estado", (d) => {
      for (const e of d?.tvs || []) if (e?.id) s.estados.set(e.id, e);
      s.casaOnline = true;
      desenhar();
    }));
  }
  if (estado?.subscribe) {
    saidas.push(estado.subscribe((novo, antigo) => {
      if (novo.casa_fora !== antigo.casa_fora) {
        if (novo.casa_fora) pararRepeticao();
        else if (!s.casaOnline) return void carregar();
        desenhar();
      }
    }));
  }
  const soltar = () => pararRepeticao();
  doc?.addEventListener?.("pointerup", soltar);
  doc?.addEventListener?.("pointercancel", soltar);

  desenhar();
  const pronto = carregar();

  const desmontar = () => {
    vivo = false;
    pararRepeticao();
    ctl.parar();
    for (const f of saidas) if (typeof f === "function") f();
    doc?.removeEventListener?.("pointerup", soltar);
    doc?.removeEventListener?.("pointercancel", soltar);
  };
  desmontar.pronto = pronto;
  return desmontar;
}
