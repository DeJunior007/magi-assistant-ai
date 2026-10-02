-- Tarefa 2.4 (R8.3-R8.5): peso efetivo do gosto = base importada + ajustes + sinais.
--
-- A importação (2.3) faz upsert substituindo ``taste.weight``; os ajustes manuais (``adjust``) vão
-- para ``bonus`` e os sinais ficam só em ``music_signals``. A view recalcula o peso a cada leitura,
-- então reimportar não apaga nada. Deltas por sinal (o maior peso importado vale 1):
-- pulada -0.05, ouvida inteira +0.02, "essa é boa" +0.15, "nunca mais" -0.3 (no artista; a faixa
-- em si sai das escolhas por ``banned_tracks``).

ALTER TABLE taste ADD COLUMN bonus real NOT NULL DEFAULT 0;

CREATE INDEX music_signals_banned_idx ON music_signals (track_uri) WHERE signal = -99;

CREATE VIEW taste_effective AS
WITH s AS (
    SELECT artist,
           sum(CASE signal WHEN -1 THEN -0.05 WHEN 1 THEN 0.02 WHEN 2 THEN 0.15 WHEN -99 THEN -0.3
                           ELSE 0 END) AS delta
    FROM music_signals
    WHERE coalesce(artist, '') <> ''
    GROUP BY artist
)
SELECT t.artist, t.genre, (t.weight + t.bonus + coalesce(s.delta, 0))::real AS weight
FROM taste t LEFT JOIN s ON s.artist = t.artist
UNION ALL
SELECT s.artist, '' AS genre, s.delta::real AS weight
FROM s
WHERE NOT EXISTS (SELECT 1 FROM taste t WHERE t.artist = s.artist);
