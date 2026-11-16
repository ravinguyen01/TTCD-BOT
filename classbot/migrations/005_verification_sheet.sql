ALTER TABLE profiles ADD COLUMN IF NOT EXISTS consented_at TIMESTAMPTZ;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS consent_version TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS verification_sync (
    guild_id BIGINT PRIMARY KEY,
    sheet_id INTEGER,
    data_version BIGINT NOT NULL DEFAULT 0,
    synced_version BIGINT NOT NULL DEFAULT 0,
    CHECK (data_version >= synced_version)
);
