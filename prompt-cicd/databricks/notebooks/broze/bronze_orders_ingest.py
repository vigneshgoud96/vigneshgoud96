# Databricks notebook source
# Bronze layer: raw ingestion from ADLS Gen2
# Auto-managed by prompt-cicd agent

# COMMAND ----------
# MAGIC %md
# MAGIC ## Bronze — Orders raw ingestion
# MAGIC Reads raw CSV/Parquet from ADLS landing zone and writes to Delta bronze table.

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import current_timestamp, input_file_name, lit
from pyspark.sql.types import StructType
import logging

spark = SparkSession.builder.getOrCreate()
log = logging.getLogger(__name__)

# COMMAND ----------
# Parameters (overridable via Databricks job parameters)

dbutils.widgets.text("source_path", "abfss://landing@<storage>.dfs.core.windows.net/orders/")
dbutils.widgets.text("target_table", "bronze.orders_raw")
dbutils.widgets.text("load_date", "")

source_path = dbutils.widgets.get("source_path")
target_table = dbutils.widgets.get("target_table")
load_date = dbutils.widgets.get("load_date")

# COMMAND ----------
# Read raw files from landing zone

df_raw = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(source_path)
    .withColumn("_ingestion_ts", current_timestamp())
    .withColumn("_source_file", input_file_name())
    .withColumn("_load_date", lit(load_date) if load_date else current_timestamp().cast("date"))
)

row_count = df_raw.count()
log.info("Ingested %d rows from %s", row_count, source_path)
print(f"Rows ingested: {row_count}")

# COMMAND ----------
# Data quality gate: fail early if source is empty

assert row_count > 0, f"No data found in source path: {source_path}"

# COMMAND ----------
# Write to bronze Delta table (append mode — full history preserved)

(
    df_raw.write
    .format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .saveAsTable(target_table)
)

print(f"Written to {target_table} successfully.")
dbutils.notebook.exit(f"SUCCESS: {row_count} rows written to {target_table}")

