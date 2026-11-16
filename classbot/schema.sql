CREATE TABLE IF NOT EXISTS classes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    voice_channel_id BIGINT,
    class_role_id BIGINT NOT NULL,
    class_code TEXT NOT NULL,
    spreadsheet_id TEXT,
    attendance_sheet_id INTEGER,
    points_sheet_id INTEGER,
    UNIQUE (guild_id, voice_channel_id),
    UNIQUE (guild_id, class_role_id),
    UNIQUE (guild_id, class_code)
);

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

CREATE TABLE IF NOT EXISTS onboarding_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    verified_role_id BIGINT NOT NULL,
    message_id BIGINT,
    privacy_url TEXT
);

CREATE TABLE IF NOT EXISTS profiles (
    guild_id BIGINT NOT NULL,
    discord_uid BIGINT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    facebook_url TEXT NOT NULL,
    username TEXT NOT NULL,
    role_status TEXT NOT NULL CHECK (role_status IN ('pending', 'granted')),
    consented_at TIMESTAMPTZ,
    consent_version TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, discord_uid)
);

CREATE TABLE IF NOT EXISTS verification_sync (
    guild_id BIGINT PRIMARY KEY,
    sheet_id INTEGER,
    data_version BIGINT NOT NULL DEFAULT 0,
    synced_version BIGINT NOT NULL DEFAULT 0,
    CHECK (data_version >= synced_version)
);

CREATE TABLE IF NOT EXISTS enrollments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    class_id BIGINT NOT NULL REFERENCES classes(id),
    discord_uid BIGINT NOT NULL,
    discord_username TEXT NOT NULL,
    discord_display_name TEXT,
    display_name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (class_id, discord_uid)
);

CREATE TABLE IF NOT EXISTS attendance (
    class_id BIGINT NOT NULL REFERENCES classes(id),
    enrollment_id BIGINT NOT NULL REFERENCES enrollments(id),
    class_date DATE NOT NULL,
    present BOOLEAN NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (class_id, enrollment_id, class_date)
);

CREATE TABLE IF NOT EXISTS point_transactions (
    interaction_id BIGINT PRIMARY KEY,
    class_id BIGINT NOT NULL REFERENCES classes(id),
    enrollment_id BIGINT NOT NULL REFERENCES enrollments(id),
    class_date DATE NOT NULL,
    points NUMERIC(10, 2) NOT NULL,
    actor_uid BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS class_channels (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    class_id BIGINT NOT NULL REFERENCES classes(id),
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS reaction_awards (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    reactor_uid BIGINT NOT NULL,
    emoji TEXT NOT NULL,
    class_id BIGINT NOT NULL REFERENCES classes(id),
    enrollment_id BIGINT NOT NULL REFERENCES enrollments(id),
    class_date DATE NOT NULL,
    points NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, channel_id, message_id, reactor_uid, emoji)
);

CREATE TABLE IF NOT EXISTS sheet_sync (
    class_id BIGINT PRIMARY KEY REFERENCES classes(id),
    data_version BIGINT NOT NULL DEFAULT 0,
    synced_version BIGINT NOT NULL DEFAULT 0,
    CHECK (data_version >= synced_version)
);
