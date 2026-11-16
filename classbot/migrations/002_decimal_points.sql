ALTER TABLE point_transactions
    ALTER COLUMN points TYPE NUMERIC(10, 2)
    USING points::NUMERIC(10, 2);
