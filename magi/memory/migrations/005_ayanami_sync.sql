-- 005_ayanami_sync: chaves da sincronização com a Ayanami ([DS5], spec §3 e §5.2).
--
-- Só aditiva e reexecutável: colunas novas, nulas nas linhas locais; nenhuma linha muda.
--   news_items.ayanami_uid = news_items.uid da Ayanami (item puxado por magi-news-sync)
--   costs.origem_uid       = costs.uid da Ayanami (gasto da nuvem copiado para o PC)

ALTER TABLE news_items ADD COLUMN IF NOT EXISTS ayanami_uid uuid UNIQUE;
ALTER TABLE costs ADD COLUMN IF NOT EXISTS origem_uid uuid UNIQUE;
