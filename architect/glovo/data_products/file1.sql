select
    customer_id,
    date_diff('day', signup_date, current_date) AS days_active
FROM hive.crm.customers;
