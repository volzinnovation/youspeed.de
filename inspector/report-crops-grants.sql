-- Prepared operator action. Apply as administrator/migrator to database youspeed.
-- No writes, DDL, role memberships, processor access or public/network grants.
BEGIN;
DO $$ BEGIN
  IF current_database() <> 'youspeed' THEN
    RAISE EXCEPTION 'Use the dedicated youspeed database';
  END IF;
END $$;
GRANT SELECT ON youspeed.media, youspeed.tombstones, youspeed.authorizations TO youspeed_report;
COMMIT;
