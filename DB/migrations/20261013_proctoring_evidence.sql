SET @schema_name = DATABASE();

SET @column_exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'proctoring_log'
    AND COLUMN_NAME = 'evidence_file'
);
SET @ddl = IF(@column_exists = 0,
  'ALTER TABLE proctoring_log ADD COLUMN evidence_file varchar(512) DEFAULT NULL',
  'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @column_exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'proctoring_log'
    AND COLUMN_NAME = 'evidence_status'
);
SET @ddl = IF(@column_exists = 0,
  'ALTER TABLE proctoring_log ADD COLUMN evidence_status varchar(20) NOT NULL DEFAULT ''not_required''',
  'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @column_exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'proctoring_log'
    AND COLUMN_NAME = 'event_data'
);
SET @ddl = IF(@column_exists = 0,
  'ALTER TABLE proctoring_log ADD COLUMN event_data longtext DEFAULT NULL',
  'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @column_exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'proctoring_log'
    AND COLUMN_NAME = 'detection_confidence'
);
SET @ddl = IF(@column_exists = 0,
  'ALTER TABLE proctoring_log ADD COLUMN detection_confidence decimal(5,4) DEFAULT NULL',
  'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @column_exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'proctoring_log'
    AND COLUMN_NAME = 'review_status'
);
SET @ddl = IF(@column_exists = 0,
  'ALTER TABLE proctoring_log ADD COLUMN review_status varchar(20) NOT NULL DEFAULT ''unreviewed''',
  'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
