"""
Spark Streaming consumer: reads price_events from Kafka,
detects price drops, writes to PostgreSQL, sends email alerts.
"""
import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg2
import redis as redis_lib
from dotenv import load_dotenv
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, from_json
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

redis_client = redis_lib.from_url(REDIS_URL, decode_responses=True)

PRICE_EVENT_SCHEMA = StructType([
    StructField("product_id", IntegerType()),
    StructField("item_id", LongType()),
    StructField("shop_id", LongType()),
    StructField("price", DoubleType()),
    StructField("stock", IntegerType()),
    StructField("sold_count", IntegerType()),
    StructField("scraped_at", StringType()),
])


def get_db_conn():
    return psycopg2.connect(DATABASE_URL)


def get_product_info(product_id: int) -> dict | None:
    """Fetch product + user email for alert notifications."""
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.name, p.alert_threshold_pct, u.email
                FROM products p
                JOIN users u ON u.id = p.user_id
                WHERE p.id = %s AND p.active = TRUE
                """,
                (product_id,),
            )
            row = cur.fetchone()
            if row:
                return {"name": row[0], "threshold": float(row[1]), "email": row[2]}
    finally:
        conn.close()
    return None


def write_price_history(product_id: int, price: float, stock: int, sold_count: int):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO price_history (product_id, price, stock, sold_count) VALUES (%s, %s, %s, %s)",
                (product_id, price, stock, sold_count),
            )
        conn.commit()
    finally:
        conn.close()


def write_alert(product_id: int, old_price: float, new_price: float, change_pct: float):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (product_id, old_price, new_price, change_pct, email_sent)
                VALUES (%s, %s, %s, %s, TRUE)
                """,
                (product_id, old_price, new_price, round(change_pct, 2)),
            )
        conn.commit()
    finally:
        conn.close()


def send_alert_email(user_email: str, product_name: str, old_price: float, new_price: float, change_pct: float):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not set — skipping email")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚠️ 競品降價警報：{product_name}"
    msg["From"] = GMAIL_USER
    msg["To"] = user_email

    text = (
        f"競品降價通知\n\n"
        f"商品：{product_name}\n"
        f"原價：NT${old_price:.0f}\n"
        f"現價：NT${new_price:.0f}\n"
        f"降幅：{change_pct:.1f}%\n\n"
        f"建議您考慮調整自己的定價。"
    )
    html = f"""
    <html><body>
    <h2>⚠️ 競品降價警報</h2>
    <table>
      <tr><td><b>商品</b></td><td>{product_name}</td></tr>
      <tr><td><b>原價</b></td><td>NT${old_price:.0f}</td></tr>
      <tr><td><b>現價</b></td><td style="color:red">NT${new_price:.0f}</td></tr>
      <tr><td><b>降幅</b></td><td style="color:red">▼ {change_pct:.1f}%</td></tr>
    </table>
    </body></html>
    """
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        logger.info("Alert email sent to %s for product %s", user_email, product_name)
    except Exception as e:
        logger.error("Failed to send alert email: %s", e)


def process_batch(batch_df, batch_id: int):
    rows = batch_df.collect()
    if not rows:
        return

    logger.info("Processing batch %d with %d events", batch_id, len(rows))

    for row in rows:
        product_id = row.product_id
        new_price = row.price

        # Fetch product info (threshold + user email)
        info = get_product_info(product_id)
        if not info:
            continue

        # Compare with last known price in Redis
        cache_key = f"latest_price:{product_id}"
        last_price_str = redis_client.get(cache_key)

        if last_price_str is not None:
            last_price = float(last_price_str)
            if last_price > 0:
                change_pct = (last_price - new_price) / last_price * 100

                if change_pct >= info["threshold"]:
                    logger.info(
                        "Price drop detected: product=%d %.2f → %.2f (%.1f%%)",
                        product_id, last_price, new_price, change_pct,
                    )
                    write_alert(product_id, last_price, new_price, change_pct)
                    send_alert_email(
                        info["email"], info["name"],
                        last_price, new_price, change_pct,
                    )

        # Update Redis cache and persist to DB
        redis_client.set(cache_key, new_price, ex=3600)
        write_price_history(product_id, new_price, row.stock, row.sold_count)


def main():
    spark = (
        SparkSession.builder.appName("PriceMonitor")
        .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1")
        .config("spark.sql.streaming.checkpointLocation", "/tmp/spark-checkpoint")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw_df = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", "price_events")
        .option("startingOffsets", "latest")
        .load()
    )

    parsed_df = raw_df.select(
        from_json(col("value").cast("string"), PRICE_EVENT_SCHEMA).alias("d")
    ).select("d.*")

    query = (
        parsed_df.writeStream.foreachBatch(process_batch)
        .outputMode("append")
        .start()
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
