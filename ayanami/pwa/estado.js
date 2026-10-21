/**
 * Store mínima com `subscribe` (spec §14.1, §14.3). Dono: P1.1.
 *
 * Campos globais: `conexao` ∈ CONEXAO; `casa_fora` (bool, a aba TV mostra "a casa está fora do
 * ar"); `rota` ({tela, params}); `saude` (último JSON do `/saude` ou null).
 */

export const CONEXAO = Object.freeze(["sem_token", "conectando", "ok_pc", "ok_nuvem", "sem_ayanami"]);

export function criarEstado(inicial = {}) {
  let atual = Object.freeze({ conexao: "conectando", casa_fora: false, rota: null, saude: null, ...inicial });
  const ouvintes = new Set();
  return {
    get: () => atual,
    /** Junta `parcial` ao estado; avisa os ouvintes só se algum campo mudou. */
    set(parcial) {
      const mudou = Object.keys(parcial).some((k) => !Object.is(atual[k], parcial[k]));
      if (!mudou) return atual;
      const antes = atual;
      atual = Object.freeze({ ...atual, ...parcial });
      for (const fn of [...ouvintes]) fn(atual, antes);
      return atual;
    },
    /** `fn(novo, antigo)` a cada mudança; devolve a função que cancela a inscrição. */
    subscribe(fn) {
      ouvintes.add(fn);
      return () => ouvintes.delete(fn);
    },
  };
}

export const estado = criarEstado();
