-- Phase 4 renamed four settings so the keys match the registry inventory.
UPDATE settings SET key = 'feature.passive_curse_replies' WHERE key = 'feature.curse_replies'
  AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'feature.passive_curse_replies');
UPDATE settings SET key = 'emoji.link_summary' WHERE key = 'feature.link_summary_emoji'
  AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'emoji.link_summary');
UPDATE settings SET key = 'limit.media_per_user' WHERE key = 'limit.local_media_max_per_user'
  AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'limit.media_per_user');
UPDATE settings SET key = 'limit.media_global' WHERE key = 'limit.local_media_max_global'
  AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'limit.media_global');
DELETE FROM settings WHERE key IN ('feature.curse_replies', 'feature.link_summary_emoji',
                                   'limit.local_media_max_per_user', 'limit.local_media_max_global');
