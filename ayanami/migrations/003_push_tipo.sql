-- 003_push_tipo: tipo da assinatura de push (condessa-celular spec §9.6, dono: M1.5).
--
-- 'webpush' = PWA (navegador); 'unifiedpush' = app Android via ntfy (endpoint em [push] ntfy_hosts).
-- Assinaturas já gravadas seguem 'webpush' pelo DEFAULT.

ALTER TABLE push_assinaturas ADD COLUMN tipo text NOT NULL DEFAULT 'webpush'
    CHECK (tipo IN ('webpush', 'unifiedpush'));
