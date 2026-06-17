SELECT
    email
FROM hive.marketing.contacts
WHERE regexp_like(email, '^[A-Za-z0-9._%+-]+@gmail\\.com$');
