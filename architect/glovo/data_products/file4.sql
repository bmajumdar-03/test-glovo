SELECT
    order_id
FROM hive.sales.orders
WHERE contains(tags, 'priority');
