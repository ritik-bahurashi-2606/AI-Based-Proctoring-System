ALTER TABLE proctoring_log
  ADD COLUMN device_detection tinyint(2) NOT NULL DEFAULT 0 AFTER phone_detection;
