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
 *
 * Interruptor de push (P2.2, spec §15 *Assinatura*): ligar → `Notification.requestPermission()`
 * **só no toque** → `pushManager.subscribe({userVisibleOnly, applicationServerKey})` com a chave
 * pública de `GET /v1/push/chave` (`{"chave": base64url}`) → `POST /v1/push/assinar`
 * (`toJSON()`); desligar → `DELETE /v1/push/assinar {endpoint}` e `unsubscribe()`. A chave usada
 * fica no armazém (`push_chave`); `reassinarSeMudou(ctx)` (ao abrir) troca a assinatura quando a
 * chave do servidor mudou. Navegador e permissão injetáveis em `ctx.push = {Notification, sw}`.
 */

import { armazemIdb, armazemMemoria } from "../api.js";
import { VERSAO_APP } from "../versao.js";

export { VERSAO_APP };
export const CHAVE_PREFS = "preferencias";
export const CHAVE_PUSH = "push_chave";
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

// ---------- Web Push (P2.2)

export function b64urlParaBytes(s) {
  const b64 = String(s).replace(/-/g, "+").replace(/_/g, "/") + "===".slice((String(s).length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function bytesParaB64url(buf) {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** `{Notification, sw}` do `ctx.push` ou do navegador; `null` sem suporte a Web Push. */
export function apoioPush(ctx = {}) {
  const p = ctx.push ?? {
    Notification: globalThis.Notification,
    sw: globalThis.navigator?.serviceWorker,
  };
  return p?.Notification && p?.sw ? p : null;
}

async function registro(apoio) {
  const reg = await apoio.sw.ready;
  return reg?.pushManager ? reg : null;
}

async function chaveServidor(api) {
  const r = await api.get("/v1/push/chave");
  if (!r?.chave) throw new Error("sem_chave");
  return r.chave;
}

/** Chave da assinatura atual: a de `options` (se o navegador expõe) ou a guardada. */
async function chaveDaAssinatura(sub, armazem) {
  const k = sub?.options?.applicationServerKey;
  if (k) return bytesParaB64url(k);
  return armazem.ler(CHAVE_PUSH);
}

async function assinarCom(api, armazem, reg, chave) {
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64urlParaBytes(chave) });
  await api.post("/v1/push/assinar", sub.toJSON());
  await armazem.gravar(CHAVE_PUSH, chave);
  return sub;
}

/** Desliga: avisa o servidor (falha de rede não impede) e cancela no navegador. */
async function desassinarCom(api, armazem, reg) {
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    try {
      await api.pedir("DELETE", "/v1/push/assinar", { endpoint: sub.endpoint });
    } finally {
      await sub.unsubscribe();
      await armazem.apagar(CHAVE_PUSH);
    }
  }
}

/**
 * Ao abrir o app: com permissão dada e a pref `push` ligada, garante a assinatura com a chave atual
 * do servidor (trocar as chaves VAPID invalida todas, spec §15). Nunca pede permissão.
 * Devolve `"assinou" | "reassinou" | "ok" | "nada"`; erros de rede viram `"nada"`.
 */
export async function reassinarSeMudou(ctx) {
  const apoio = apoioPush(ctx);
  if (!apoio || apoio.Notification.permission !== "granted") return "nada";
  const armazem = armazemDe(ctx);
  const prefs = normalizarPrefs(await armazem.ler(CHAVE_PREFS));
  if (!prefs.push) return "nada";
  try {
    const reg = await registro(apoio);
    if (!reg) return "nada";
    const chave = await chaveServidor(ctx.api);
    const sub = await reg.pushManager.getSubscription();
    if (sub && (await chaveDaAssinatura(sub, armazem)) === chave) return "ok";
    if (sub) await sub.unsubscribe();
    await assinarCom(ctx.api, armazem, reg, chave);
    return sub ? "reassinou" : "assinou";
  } catch {
    return "nada";
  }
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
  const push = h(doc, "div", { className: "push", dataset: { campo: "push" } });
  const apoio = apoioPush(ctx);
  const pushLigado = h(doc, "input", { type: "checkbox", dataset: { campo: "push_ligado" } });
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

  /** Interruptor: `requestPermission` é a 1ª chamada do toque (precisa do gesto do usuário). */
  function aoMudarPush() {
    if (pushLigado.checked) {
      const pedido = apoio.Notification.permission === "granted"
        ? Promise.resolve("granted")
        : Promise.resolve(apoio.Notification.requestPermission());
      pushLigado.disabled = true;
      return pedido
        .then(async (perm) => {
          if (perm !== "granted") throw Object.assign(new Error("negado"), { negado: true });
          const reg = await registro(apoio);
          if (!reg) throw new Error("sem_registro");
          await assinarCom(ctx.api, armazem, reg, await chaveServidor(ctx.api));
          await salvar({ push: true });
        })
        .catch((e) => {
          pushLigado.checked = false;
          if (!vivo) return;
          if (e?.negado) avisar("Avisos bloqueados: libere as notificações da Condessa no navegador.");
          else if (e?.status) avisar(`Não assinou os avisos (HTTP ${e.status}).`);
          else avisar("Não deu para ligar os avisos agora; tenta de novo com conexão.");
        })
        .finally(() => (pushLigado.disabled = false));
    }
    pushLigado.disabled = true;
    return (async () => {
      try {
        const reg = await registro(apoio);
        if (reg) await desassinarCom(ctx.api, armazem, reg);
        await salvar({ push: false });
      } catch (e) {
        if (vivo) avisar(e?.status ? `Não desligou na Ayanami (HTTP ${e.status}).` : "Sem conexão: desligado só no celular.");
        await salvar({ push: false }).catch(() => {});
      } finally {
        pushLigado.disabled = false;
      }
    })();
  }
  if (apoio) {
    pushLigado.addEventListener("change", aoMudarPush);
    push.append(h(doc, "label", { textContent: "Avisos no celular " }, pushLigado));
  } else {
    push.textContent = "Este navegador não recebe avisos (Web Push).";
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
    if (apoio) {
      await reassinarSeMudou({ ...ctx, armazem });
      let sub = null;
      try {
        sub = await (await registro(apoio))?.pushManager.getSubscription();
      } catch {
        /* sem registro do SW: fica desligado */
      }
      if (vivo) pushLigado.checked = Boolean(prefs.push && sub && apoio.Notification.permission === "granted");
    }
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
