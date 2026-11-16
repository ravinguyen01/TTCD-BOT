-- A roster can be created from any role before it is linked to a voice channel.
ALTER TABLE classes ALTER COLUMN voice_channel_id DROP NOT NULL;
