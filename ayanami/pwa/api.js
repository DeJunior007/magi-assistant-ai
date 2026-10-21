/**
 * Cliente da API da Ayanami (spec §2.2, §14.1, §14.3, §14.5). Dono: P1.1.
 *
 * - `fetch` com `Authorization: Bearer <token>` (token no IndexedDB, `armazemIdb()`);
 * - 401 em qualquer chamada → apaga o token e chama `aoNaoAutorizado()` (o app vai a Parear);
 * - `saude()` com timeout de 4 s (`GET /saude`, sem token);
 * - `eventos(aoEvento)` = SSE de `/v1/eventos` lido por `fetch` (o `EventSource` não manda
 *   cabeçalho), com `Last-Event-ID` e reconexão 1 → 30 s (dobra a cada falha, volta a 1 s
 *   depois de conectar).
 *
 * Tudo injetável para o `node --test`: `fetch`, `armazem`, `dormir`, `agendar`.
 */

export const CHAVE_TOKEN = "token";

export class ErroApi extends Error {
  constructor(status, corpo) {
    super((corpo && corpo.msg) || `HTTP ${status}`);
    this.status = status;
    this.corpo = corpo;
  }
}

/** Armazém chave/valor no IndexedDB (`condessa`/`kv`). */
export function armazemIdb(idb = globalThis.indexedDB, nome = "condessa") {
  let aberto = null;
  const abrir = () =>
    (aberto ??= new Promise((ok, falha) => {
      const req = idb.open(nome, 1);
      req.onupgradeneeded = () => req.result.createObjectStore("kv");
      req.onsuccess = () => ok(req.result);
      req.onerror = () => falha(req.error);
    }));
  const op = (modo, fn) =>
    abrir().then(
      (db) =>
        new Promise((ok, falha) => {
          const req = fn(db.transaction("kv", modo).objectStore("kv"));
          req.onsuccess = () => ok(req.result);
          req.onerror = () => falha(req.error);
        }),
    );
  return {
    ler: (k) => op("readonly", (s) => s.get(k)),
    gravar: (k, v) => op("readwrite", (s) => s.put(v, k)),
    apagar: (k) => op("readwrite", (s) => s.delete(k)),
  };
}

/** Armazém em memória (testes e navegador sem IndexedDB). */
export function armazemMemoria(inicial = {}) {
  const m = new Map(Object.entries(inicial));
  return {
    ler: async (k) => m.get(k),
    gravar: async (k, v) => void m.set(k, v),
    apagar: async (k) => void m.delete(k),
  };
}

const dormirReal = (ms) => new Promise((ok) => setTimeout(ok, ms));

/** Lê um corpo `text/event-stream` e chama `aoBloco({event, data, id})` por evento. */
export async function lerSse(corpo, aoBloco) {
  const leitor = corpo.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let ev = { event: "message", data: [], id: null };
  for (;;) {
    const { value, done } = await leitor.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.search(/\r?\n/)) >= 0) {
      const linha = buf.slice(0, i);
      buf = buf.slice(i + (buf[i] === "\r" ? 2 : 1));
      if (linha === "") {
        if (ev.data.length) aoBloco({ event: ev.event, data: ev.data.join("\n"), id: ev.id });
        ev = { event: "message", data: [], id: null };
        continue;
      }
      if (linha.startsWith(":")) continue;
      const p = linha.indexOf(":");
      const campo = p < 0 ? linha : linha.slice(0, p);
      const valor = p < 0 ? "" : linha.slice(p + 1).replace(/^ /, "");
      if (campo === "event") ev.event = valor;
      else if (campo === "data") ev.data.push(valor);
      else if (campo === "id") ev.id = valor;
    }
  }
}

export function criarApi({
  fetch: buscar = globalThis.fetch?.bind(globalThis),
  armazem = armazemMemoria(),
  base = "",
  aoNaoAutorizado = () => {},
  dormir = dormirReal,
  agendar = (fn, ms) => setTimeout(fn, ms),
  cancelar = (t) => clearTimeout(t),
} = {}) {
  const token = () => armazem.ler(CHAVE_TOKEN);

  async function naoAutorizado() {
    await armazem.apagar(CHAVE_TOKEN);
    aoNaoAutorizado();
  }

  /** `fetch` cru com Bearer; trata o 401. Devolve o `Response`. */
  async function bruto(caminho, opcoes = {}) {
    const t = await token();
    const headers = { ...(opcoes.headers || {}) };
    if (t) headers.Authorization = `Bearer ${t}`;
    const r = await buscar(base + caminho, { ...opcoes, headers });
    if (r.status === 401) await naoAutorizado();
    return r;
  }

  /** Chamada JSON: `corpo` vira JSON; 2xx → objeto (ou null em 204); resto → `ErroApi`. */
  async function pedir(metodo, caminho, corpo, opcoes = {}) {
    const o = { method: metodo, ...opcoes };
    if (corpo !== undefined && !(corpo instanceof FormData)) {
      o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
      o.body = JSON.stringify(corpo);
    } else if (corpo !== undefined) o.body = corpo;
    const r = await bruto(caminho, o);
    const texto = r.status === 204 ? "" : await r.text();
    let dados = null;
    try {
      dados = texto ? JSON.parse(texto) : null;
    } catch {
      dados = texto;
    }
    if (!r.ok) throw new ErroApi(r.status, dados);
    return dados;
  }

  /** `GET /saude` com timeout (4 s); devolve `{ok, status, dados}` e nunca lança. */
  async function saude(timeoutMs = 4000) {
    const ctl = new AbortController();
    const t = agendar(() => ctl.abort(), timeoutMs);
    try {
      const r = await buscar(base + "/saude", { signal: ctl.signal, cache: "no-store" });
      let dados = null;
      try {
        dados = await r.json();
      } catch {
        dados = null;
      }
      return { ok: r.ok, status: r.status, dados };
    } catch {
      return { ok: false, status: 0, dados: null };
    } finally {
      cancelar(t);
    }
  }

  /**
   * SSE de `/v1/eventos`. `aoEvento(nome, dados, id)`; `aoEstado(conectado: bool)`.
   * Devolve `{parar(), ultimoId()}`. Reconexão 1 → 30 s com `Last-Event-ID`.
   */
  function eventos(aoEvento, { aoEstado = () => {}, ultimoId = null, minMs = 1000, maxMs = 30000 } = {}) {
    let parado = false;
    let ctl = null;
    let id = ultimoId;
    let espera = minMs;
    const pronto = (async () => {
      while (!parado) {
        ctl = new AbortController();
        try {
          const headers = { Accept: "text/event-stream" };
          if (id != null) headers["Last-Event-ID"] = String(id);
          const r = await bruto("/v1/eventos", { headers, signal: ctl.signal, cache: "no-store" });
          if (r.status === 401) return;
          if (!r.ok || !r.body) throw new ErroApi(r.status, null);
          espera = minMs;
          aoEstado(true);
          await lerSse(r.body, (b) => {
            if (b.id != null) id = b.id;
            let dados = b.data;
            try {
              dados = JSON.parse(b.data);
            } catch {
              /* texto cru */
            }
            aoEvento(b.event, dados, b.id);
          });
        } catch {
          /* cai para a reconexão */
        }
        if (parado) return;
        aoEstado(false);
        await dormir(espera);
        espera = Math.min(espera * 2, maxMs);
      }
    })();
    return {
      parar() {
        parado = true;
        ctl?.abort();
      },
      ultimoId: () => id,
      pronto,
    };
  }

  return {
    token,
    gravarToken: (t) => armazem.gravar(CHAVE_TOKEN, t),
    apagarToken: () => armazem.apagar(CHAVE_TOKEN),
    bruto,
    pedir,
    get: (c, o) => pedir("GET", c, undefined, o),
    post: (c, corpo, o) => pedir("POST", c, corpo, o),
    put: (c, corpo, o) => pedir("PUT", c, corpo, o),
    del: (c, o) => pedir("DELETE", c, undefined, o),
    saude,
    eventos,
  };
}
