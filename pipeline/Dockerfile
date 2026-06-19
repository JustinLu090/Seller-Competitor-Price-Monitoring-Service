FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    pyspark==3.5.1 \
    psycopg2-binary redis python-dotenv kafka-python
COPY spark_consumer.py /app/spark_consumer.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
WORKDIR /app
ENV PYSPARK_PYTHON=python3
CMD ["/app/start.sh"]
