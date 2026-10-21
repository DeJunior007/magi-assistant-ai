/**
 * Gravação do push-to-talk (spec §14.4). Stub do P1.1; dono: P1.2.
 *
 * A P1.2 troca este stub pela máquina `ocioso → gravando → enviando → pensando → falando →
 * ocioso` (`getUserMedia` no gesto, `MediaRecorder` opus 24 kbps, < 400 ms descarta, 15 s para
 * sozinho, `track.stop()` sempre).
 */

export function montar(el, ctx) {
  return () => {};
}

/** Sem a P1.2 o PWA fica só com texto. */
export function suportado() {
  return false;
}
