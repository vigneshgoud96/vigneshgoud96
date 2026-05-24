# Databricks notebook source
# Silver layer: cleanse, deduplicate, conform from bronze
# Auto-managed by prompt-cicd agent

# COMMAND ----------
# MAGIC %md
# MAGIC ## Silver — Orders cleansed & deduplicated
# MAGIC Reads from bronze.orders_raw, applies quality rules, writes to silver.orders.

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, current_timestamp, trim, upper,
    to_timestamp, when, coalesce, lit
)
from delta.tables import DeltaTable
import logging

spark = SparkSession.builder.getOrCreate()
log = logging.getLogger(__name__)

# COMMAND ----------
# Parameters

dbutils.widgets.text("source_table", "bronze.orders_raw")
dbutils.widgets.text("target_table", "silver.orders")
dbutils.widgets.text("watermark_col", "_ingestion_ts")

source_table = dbutils.widgets.get("source_table")
target_table = dbutils.widgets.get("target_table")
watermark_col = dbutils.widgets.get("watermark_col")

# COMMAND ----------
# Read from bronze

df_bronze = spark.read.table(source_table)

# COMMAND ----------
# Transformation: cleanse and conform

df_clean = (
    df_bronze
    # Standardise string columns
    .withColumn("order_status", upper(trim(col("order_status"))))
    .withColumn("customer_name", trim(col("customer_name")))
    # Parse timestamps
    .withColumn("order_date", to_timestamp(col("order_date"), "yyyy-MM-dd HH:mm:ss"))
    # Null-safe revenue: default to 0 if missing
    .withColumn("revenue", coalesce(col("revenue").cast("double"), lit(0.0)))
    # Deduplicate on business key (keep latest ingestion)
    .dropDuplicates(["order_id"])
    # Filter out invalid / test orders
    .filter(col("order_id").isNotNull())
    .filter(~col("order_status").isin("CANCELLED", "TEST"))
    # Add silver metadata
    .withColumn("_silver_ts", current_timestamp())
)

# COMMAND ----------
# Data quality assertions

assert df_clean.filter(col("order_id").isNull()).count() == 0, "Null order_ids found after cleanse"
assert df_clean.filter(col("revenue") < 0).count() == 0, "Negative revenue found"

row_count = df_clean.count()
log.info("Silver rows after cleanse: %d", row_count)
print(f"Rows to write: {row_count}")

# COMMAND ----------
# Upsert to silver Delta table using MERGE (idempotent)

spark.sql(f"CREATE TABLE IF NOT EXISTS {target_table} USING DELTA LOCATION 'abfss://silver@<storage>.dfs.core.windows.net/orders/'")

delta_table = DeltaTable.forName(spark, target_table)
(
    delta_table.alias("tgt")
    .merge(
        df_clean.alias("src"),
        "tgt.order_id = src.order_id"
    )
    .whenMatchedUpdateAll()
    .whenNotMatchedInsertAll()
    .execute()
)

print(f"Upsert to {target_table} complete.")
dbutils.notebook.exit(f"SUCCESS: {row_count} rows upserted to {target_table}")

