import json
import logging
import os
from datetime import datetime, timezone

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = "price_events"

_producer: KafkaProducer | None = None


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=5,
        )
    return _producer


def send_price_event(product_id: int, scraped: dict) -> None:
    """Send a scraped price record to the Kafka price_events topic."""
    event = {
        "product_id": product_id,
        "item_id": scraped["item_id"],
        "shop_id": scraped["shop_id"],
        "price": scraped["price"],
        "stock": scraped["stock"],
        "sold_count": scraped["sold_count"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_producer().send(TOPIC, value=event)
        get_producer().flush()
        logger.info("Sent price event: product_id=%s price=%.2f", product_id, scraped["price"])
    except NoBrokersAvailable:
        logger.error("Kafka broker not available — event dropped for product_id=%s", product_id)
