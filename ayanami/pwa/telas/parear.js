/**
 * Tela Parear (spec §14.2). Stub do P1.1; dono: P1.4.
 *
 * `montar(el, ctx)`: `ctx` = `{api, estado, eventos, params, navegar}` (ver `app.js`); pode
 * devolver uma função de desmontagem.
 */

export function montar(el, ctx) {
  const h = el.ownerDocument?.createElement?.("h1");
  if (h) {
    h.textContent = "Parear";
    el.append(h);
  } else {
    el.textContent = "Parear";
  }
  return () => {};
}
