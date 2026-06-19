# 電商賣家競品價格監控服務

> NTU Big Data Systems — Final Project  
> GitHub: _your-github-url-here_  
> Live Demo: _your-railway-url-here_

## System Architecture

```
[Shopee Public API]
       ↓ (Scrapy Spider, every 30 min)
[Kafka Topic: price_events]
       ↓ (Spark Streaming Consumer)
 ┌─────────────────────────────────┐
 │ Spark: detect price drops       │
 │   → write alerts to PostgreSQL  │
 │   → send Email via Gmail SMTP   │
 └─────────────────────────────────┘
       ↓                    ↓
[PostgreSQL]           [Redis Cache]
(price_history,         (latest price
 alerts, users)          per product)
       ↓
[FastAPI] ←→ [Flask Dashboard]
```

## Quick Start (Local)

**Prerequisites**: Docker & Docker Compose

```bash
# 1. Clone and configure
git clone <this-repo>
cd BDS_final
cp .env.example .env
# Edit .env: fill in GMAIL_USER and GMAIL_APP_PASSWORD

# 2. Start all services
docker-compose up --build

# 3. Open dashboard
open http://localhost:5000
```

Services started by docker-compose:
| Service | Port | Description |
|---------|------|-------------|
| dashboard | 5000 | Flask web UI |
| api | 8000 | FastAPI REST backend |
| postgresql | 5432 | Database |
| redis | 6379 | Cache + session store |
| kafka | 9092 | Message queue |
| zookeeper | 2181 | Kafka coordinator |
| scraper | — | Scheduler + Scrapy spiders |
| pipeline | — | Spark Streaming consumer |

## Usage

1. Register an account at `http://localhost:5000/register`
2. Click **+ 新增競品**, paste a Shopee product URL, set your price and alert threshold
3. The scraper runs every 30 minutes; a price drop exceeding the threshold triggers an Email alert
4. View the 30-day price chart by clicking on any product

**Shopee URL format** accepted:
```
https://shopee.tw/any-product-name-i.SHOPID.ITEMID
```

## Gmail App Password Setup

1. Enable 2-Step Verification on your Google account
2. Go to Google Account → Security → App Passwords
3. Generate a password for "Mail" and paste it as `GMAIL_APP_PASSWORD` in `.env`

## Project Structure

```
BDS_final/
├── docker-compose.yml        # Orchestration
├── .env.example              # Environment template
├── init-db/schema.sql        # PostgreSQL schema
├── scraper/                  # Scrapy spider + Kafka producer + APScheduler
├── pipeline/                 # Spark Streaming consumer
├── api/                      # FastAPI REST backend
├── dashboard/                # Flask frontend + templates
└── survey/questionnaire.md   # Demand validation questionnaire
```

## Cloud Deployment (Railway)

```bash
# Install Railway CLI
brew install railway

# Login and deploy
railway login
railway new
railway up
```

Set environment variables in Railway dashboard (same as `.env`).  
Use Upstash Kafka free tier for managed Kafka in production.

## Reproducing Demand Validation

The questionnaire used to validate market demand is in `survey/questionnaire.md`.  
Distribute via Shopee seller Facebook groups. Results summary is in the PDF report.

## Technologies Used

| Layer | Technology | Course Concept |
|-------|-----------|---------------|
| Ingestion | Scrapy + APScheduler | Data collection at scale |
| Messaging | Apache Kafka | Stream processing / event queue |
| Processing | Apache Spark Streaming | Distributed batch & stream processing |
| Storage | PostgreSQL + Redis | SQL store + in-memory cache |
| Delivery | Flask + Chart.js | End-to-end pipeline delivery |
| Notification | Gmail SMTP | Alert system |
