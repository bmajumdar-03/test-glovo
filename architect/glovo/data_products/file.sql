SELECT
    customer_id,
    ARRAY[101, 102, 103] AS product_ids
FROM hive.sales.customers;
