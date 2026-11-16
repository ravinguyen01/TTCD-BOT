CREATE TABLE IF NOT EXISTS account_links (
    guild_id BIGINT NOT NULL,
    secondary_uid BIGINT NOT NULL,
    primary_uid BIGINT NOT NULL,
    actor_uid BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, secondary_uid),
    CHECK (secondary_uid <> primary_uid)
);
CREATE INDEX IF NOT EXISTS account_links_primary_idx ON account_links(guild_id, primary_uid);
