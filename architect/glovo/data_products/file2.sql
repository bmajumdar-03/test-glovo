SELECT
    user_id,
    try_cast(age AS bigint) AS age_num
FROM hive.users.profile;
