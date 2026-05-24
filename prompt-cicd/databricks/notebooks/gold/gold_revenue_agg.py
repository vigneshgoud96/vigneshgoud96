# Databricks notebook source
# Gold layer: business aggregations for BI / reporting
# Auto-managed by prompt-cicd agent

# COMMAND ----------
# MAGIC %md
# MAGIC ## Gold — Revenue aggregation by region and month
# MAGIC Reads from silver.orders, aggregates for BI consumption.

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, sum as _sum, count, avg, date_trunc,
    current_timestamp, round as _round
)
import logging

spark = SparkSession.builder.getOrCreate()
log = logging.getLogger(__name__)

# COMMAND ----------
# Parameters

dbutils.widgets.text("source_table", "silver.orders")
dbutils.widgets.text("target_table", "gold.revenue_by_region_month")

source_table = dbutils.widgets.get("source_table")
target_table = dbutils.widgets.get("target_table")

# COMMAND ----------
# Read cleansed silver data

df_silver = spark.read.table(source_table).filter(col("order_status") == "COMPLETED")

# COMMAND ----------
# Aggregate: revenue, order count, avg order value by region + month

df_gold = (
    df_silver
    .withColumn("order_month", date_trunc("month", col("order_date")))
    .groupBy("region", "order_month")
    .agg(
        _round(_sum("revenue"), 2).alias("total_revenue"),
        count("order_id").alias("order_count"),
        _round(avg("revenue"), 2).alias("avg_order_value"),
    )
    .withColumn("_gold_ts", current_timestamp())
    .orderBy("region", "order_month")
)

row_count = df_gold.count()
log.info("Gold aggregation rows: %d", row_count)
print(f"Gold rows: {row_count}")

# COMMAND ----------
# Write to gold Delta table (full overwrite — aggregations are deterministic)

(
    df_gold.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target_table)
)

print(f"Written to {target_table}.")
dbutils.notebook.exit(f"SUCCESS: {row_count} rows written to {target_table}")

