CREATE TABLE IF NOT EXISTS onboarding_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    verified_role_id BIGINT NOT NULL,
    message_id BIGINT,
    privacy_url TEXT
);
