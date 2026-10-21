/**
 * Tela Ajustes (spec §14.2, §16.1 *Celular*, §2.2 `/v1/dispositivo*`). Dono: P1.4; a P2.2 preenche
 * o interruptor de push (`[data-campo=push]`, aqui **vazio**) e a assinatura.
 *
 * Preferências no armazém (IndexedDB, chave `preferencias`) e espelhadas em
 * `PUT /v1/dispositivo/preferencias` a cada mudança: `push` (true), `push_com_pc` (true),
 * `silencio` ("23:00-07:30" ou ""), `tv_padrao` (id ou null = a da casa), `voz_em_texto` (false).
 * Mostra o dispositivo (nome guardado pelo Parear), a versão e o botão de instalar
 * (`estado.instalar` = `beforeinstallprompt`). **Sair** = `DELETE /v1/dispositivo` → apaga o
 * token e vai a Parear.
 */

import { armazemIdb, armazemMemoria } from "../api.js";

export const VERSAO_APP = "0.1.0";
export const CHAVE_PREFS = "preferencias";
export const PREFS_PADRAO = Object.freeze({
  push: true, push_com_pc: true, silencio: "23:00-07:30", tv_padrao: null, voz_em_texto: false,
});
const RE_SILENCIO = /^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$/;

export const silencioValido = (s) => s === "" || RE_SILENCIO.test(s);

function armazemDe(ctx) {
  if (ctx.armazem) return ctx.armazem;
  return globalThis.indexedDB ? armazemIdb() : armazemMemoria();
}

function h(doc, tag, props = {}, ...filhos) {
  const e = doc.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k in e || k === "textContent" || k === "className") e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const f of filhos) if (f != null) e.append(f);
  return e;
}

/** Junta o guardado aos padrões, só com as chaves conhecidas. */
export function normalizarPrefs(p) {
  const out = { ...PREFS_PADRAO };
  for (const k of Object.keys(PREFS_PADRAO)) if (p && p[k] !== undefined) out[k] = p[k];
  out.tv_padrao = out.tv_padrao || null;
  return out;
}

export function montar(el, ctx) {
  const doc = el.ownerDocument;
  if (!doc?.createElement) {
    el.textContent = "Ajustes"; // sem DOM (teste dos stubs do P1.1)
    return () => {};
  }
  const armazem = armazemDe(ctx);
  let prefs = { ...PREFS_PADRAO };
  let vivo = true;

  const aviso = h(doc, "p", { className: "aviso", hidden: true, dataset: { campo: "aviso" } });
  const avisar = (t) => {
    aviso.textContent = t;
    aviso.hidden = !t;
  };
  const dispositivo = h(doc, "p", { textContent: "—", dataset: { campo: "dispositivo" } });
  const push = h(doc, "div", { className: "push", dataset: { campo: "push" } }); // P2.2
  const pushPc = h(doc, "input", { type: "checkbox", dataset: { campo: "push_com_pc" } });
  const silencio = h(doc, "input", { placeholder: "23:00-07:30", dataset: { campo: "silencio" } });
  const voz = h(doc, "input", { type: "checkbox", dataset: { campo: "voz_em_texto" } });
  const tv = h(doc, "select", { dataset: { campo: "tv_padrao" } });
  const instalar = h(doc, "button", { type: "button", textContent: "Instalar app", hidden: true, dataset: { acao: "instalar" } });
  const sair = h(doc, "button", { type: "button", className: "perigo precisa-rede", textContent: "Sair (revoga o token)", dataset: { acao: "sair" } });

  function opcoesTv(tvs) {
    const atual = prefs.tv_padrao ?? "";
    const lista = [{ id: "", nome: "a da casa" }, ...tvs];
    if (atual && !tvs.some((t) => t.id === atual)) lista.push({ id: atual, nome: atual });
    tv.replaceChildren(...lista.map((t) => h(doc, "option", { value: t.id, textContent: t.nome || t.id })));
    tv.value = atual;
  }

  function desenhar() {
    pushPc.checked = Boolean(prefs.push_com_pc);
    voz.checked = Boolean(prefs.voz_em_texto);
    silencio.value = prefs.silencio ?? "";
    tv.value = prefs.tv_padrao ?? "";
  }

  /** Grava local e espelha no servidor; devolve true se o PUT passou. */
  async function salvar(parcial) {
    prefs = normalizarPrefs({ ...prefs, ...parcial });
    await armazem.gravar(CHAVE_PREFS, prefs);
    try {
      await ctx.api.put("/v1/dispositivo/preferencias", prefs);
      if (vivo) avisar("");
      return true;
    } catch (e) {
      if (vivo) avisar(e?.status ? `Não salvou na Ayanami (HTTP ${e.status}).` : "Guardado no celular; a Ayanami recebe quando voltar a conexão.");
      return false;
    }
  }

  pushPc.addEventListener("change", () => salvar({ push_com_pc: pushPc.checked }));
  voz.addEventListener("change", () => salvar({ voz_em_texto: voz.checked }));
  tv.addEventListener("change", () => salvar({ tv_padrao: tv.value || null }));
  silencio.addEventListener("change", () => {
    const v = String(silencio.value).trim();
    if (!silencioValido(v)) return avisar('Silêncio no formato "23:00-07:30" (ou vazio).');
    salvar({ silencio: v });
  });
  instalar.addEventListener("click", async () => {
    const p = ctx.estado.get().instalar;
    if (!p) return;
    await p.prompt?.();
    ctx.estado.set({ instalar: null });
  });
  sair.addEventListener("click", async () => {
    sair.disabled = true;
    try {
      await ctx.api.del("/v1/dispositivo");
    } catch (e) {
      if (e?.status !== 401) {
        if (vivo) {
          sair.disabled = false;
          avisar(e?.status ? `Não saiu (HTTP ${e.status}).` : "Sem conexão: não deu para revogar o token.");
        }
        return;
      }
    }
    await ctx.api.apagarToken();
    ctx.estado.set({ conexao: "sem_token" });
    ctx.navegar("#/parear");
  });

  const mostrarInstalar = (s) => {
    instalar.hidden = !s.instalar;
  };
  const sairEstado = ctx.estado.subscribe(mostrarInstalar);
  mostrarInstalar(ctx.estado.get());

  const campo = (rotulo, entrada) => h(doc, "label", { textContent: rotulo + " " }, entrada);
  el.append(
    h(doc, "h1", { textContent: "Ajustes" }),
    aviso,
    h(doc, "section", {}, h(doc, "h2", { textContent: "Dispositivo" }), dispositivo),
    h(doc, "section", {}, h(doc, "h2", { textContent: "Avisos" }), push,
      campo("Avisar mesmo com o PC ligado", pushPc), campo("Silêncio", silencio)),
    h(doc, "section", {}, h(doc, "h2", { textContent: "Conversa e TV" }),
      campo("Voz da Condessa só em texto", voz), campo("TV padrão", tv)),
    h(doc, "section", {}, h(doc, "p", { textContent: `Versão ${VERSAO_APP}`, dataset: { campo: "versao" } }), instalar, sair),
  );

  const pronto = (async () => {
    const [guardadas, disp] = await Promise.all([armazem.ler(CHAVE_PREFS), armazem.ler("dispositivo")]);
    if (!vivo) return;
    prefs = normalizarPrefs(guardadas);
    dispositivo.textContent = disp?.nome ?? "este celular";
    opcoesTv([]);
    desenhar();
    try {
      const casa = await ctx.api.get("/v1/casa/estado");
      if (vivo) opcoesTv((casa?.tvs ?? []).map((t) => ({ id: t.id, nome: t.nome })));
    } catch {
      /* casa fora ou sem escopo: fica "a da casa" */
    }
  })();

  const desmontar = () => {
    vivo = false;
    sairEstado();
  };
  desmontar.pronto = pronto;
  return desmontar;
}
