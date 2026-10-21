/**
 * Tela Parear (spec §14.2, §2.2 `POST /v1/pareamento/trocar`). Dono: P1.4.
 *
 * Campo de 6 dígitos (o QR abre `#/parear?c=123456` e preenche) e nome do aparelho. `201` → token
 * no IndexedDB (`api.gravarToken`) e `{nome, escopos}` em `dispositivo` no armazém; `400`/`409`/
 * `429` → mostra o erro e **não guarda nada**. Depois do token: `conexao = "conectando"`, pede a
 * verificação do app (`ctx.verificar` ou um `visibilitychange`) e vai à Conversa.
 */

import { armazemIdb, armazemMemoria } from "../api.js";

export const CHAVE_DISPOSITIVO = "dispositivo";
export const NOME_PADRAO = "celular-pedro";

export const ERROS_PAREAR = Object.freeze({
  400: "Código errado ou expirado. Peça um novo no PC.",
  409: "Esse nome já está em uso; escolha outro.",
  429: "Muitas tentativas. Espere um minuto e peça um código novo.",
  0: "Sem conexão com a Ayanami — ligue o Tailscale.",
});

/** Armazém chave/valor das telas: `ctx.armazem`, senão IndexedDB, senão memória. */
export function armazemDe(ctx) {
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

export const codigoValido = (c) => /^\d{6}$/.test(String(c ?? ""));

export function montar(el, ctx) {
  const doc = el.ownerDocument;
  if (!doc?.createElement) {
    el.textContent = "Parear"; // sem DOM (teste dos stubs do P1.1)
    return () => {};
  }
  const armazem = armazemDe(ctx);
  const c = String(ctx.params?.c ?? "").replace(/\D/g, "").slice(0, 6);
  const codigo = h(doc, "input", {
    name: "codigo", inputMode: "numeric", autocomplete: "one-time-code", maxLength: 6,
    placeholder: "000000", value: c, dataset: { campo: "codigo" },
  });
  const nome = h(doc, "input", { name: "nome", value: NOME_PADRAO, maxLength: 40, dataset: { campo: "nome" } });
  const erro = h(doc, "p", { className: "erro", role: "alert", hidden: true, dataset: { campo: "erro" } });
  const botao = h(doc, "button", { type: "submit", textContent: "Parear", dataset: { acao: "parear" } });
  let vivo = true;

  function mostrarErro(msg) {
    erro.textContent = msg;
    erro.hidden = !msg;
  }

  async function enviar(ev) {
    ev?.preventDefault?.();
    const cod = String(codigo.value).trim();
    const n = String(nome.value).trim() || NOME_PADRAO;
    if (!codigoValido(cod)) return mostrarErro("O código tem 6 dígitos.");
    mostrarErro("");
    botao.disabled = true;
    let r;
    try {
      r = await ctx.api.post("/v1/pareamento/trocar", { codigo: cod, nome: n });
    } catch (e) {
      if (!vivo) return;
      botao.disabled = false;
      const status = e?.status ?? 0;
      return mostrarErro(ERROS_PAREAR[status] ?? (e?.corpo?.msg || `Falhou (HTTP ${status}).`));
    }
    if (!r?.token) {
      botao.disabled = false;
      return mostrarErro("Resposta sem token; tente de novo.");
    }
    await ctx.api.gravarToken(r.token);
    await armazem.gravar(CHAVE_DISPOSITIVO, { nome: r.nome ?? n, escopos: r.escopos ?? [] });
    ctx.estado.set({ conexao: "conectando" });
    if (typeof ctx.verificar === "function") ctx.verificar();
    else doc.dispatchEvent?.(new Event("visibilitychange"));
    ctx.navegar("#/conversa");
  }

  const form = h(
    doc, "form", { className: "parear", on: { submit: enviar } },
    h(doc, "h1", { textContent: "Parear com a Ayanami" }),
    h(doc, "p", { textContent: "Digite o código de 6 dígitos que aparece no HUD do PC." }),
    h(doc, "label", { textContent: "Código " }, codigo),
    h(doc, "label", { textContent: "Nome do aparelho " }, nome),
    erro,
    botao,
  );
  el.append(form);
  return () => {
    vivo = false;
  };
}
