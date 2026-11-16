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
