/**
 * Versão do PWA num lugar só (P2.3; era a `VERSAO_APP` solta do `telas/ajustes.js`).
 *
 * `VERSAO_SHELL` tem de ser igual ao `const VERSAO` do `sw.js` (o SW é script clássico e não importa
 * módulos; o `test_sw.mjs` confere). Subir as duas juntas a cada deploy que muda algum arquivo.
 */
export const VERSAO_SHELL = 5;
export const VERSAO_APP = `0.1.${VERSAO_SHELL}`;
