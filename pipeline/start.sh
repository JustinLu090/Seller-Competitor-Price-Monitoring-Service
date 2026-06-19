#!/bin/bash
set -e
PYSPARK_HOME=$(python3 -c "import pyspark, os; print(os.path.dirname(pyspark.__file__))")
exec "$PYSPARK_HOME/bin/spark-submit" \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1 \
  spark_consumer.py
