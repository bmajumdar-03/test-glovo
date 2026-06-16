SELECT
    order_id,
    date_add('day', 7, order_date) AS next_week
FROM hive.sales.orders;
