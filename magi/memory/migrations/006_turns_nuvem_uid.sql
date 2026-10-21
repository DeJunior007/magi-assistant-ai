-- 006_turns_nuvem_uid: chave da reconciliação resumo_nuvem em turns (Y6.5b; spec §6.6, D6a).
--
-- Só aditiva e reexecutável: colunas novas, nulas nas linhas locais; nenhuma linha muda.
--   turns.nuvem_uid   = nuvem_turnos.uid da Ayanami (turno do modo nuvem gravado pelo PC)
--   turns.ferramentas = ferramentas usadas no turno da nuvem (lista de nomes, jsonb)
-- As linhas da Y6.5 com intent = 'nuvem:<uid>' ficam como estão: o PC ainda lê esse formato
-- para não duplicar (magi/elo/reconciliar.py).

ALTER TABLE turns ADD COLUMN IF NOT EXISTS nuvem_uid uuid;
ALTER TABLE turns ADD COLUMN IF NOT EXISTS ferramentas jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS turns_nuvem_uid_key ON turns (nuvem_uid) WHERE nuvem_uid IS NOT NULL;
