# FIFA World Cup 2026 Sports Forecasting & Analytics Engine

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18.x-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![Astro](https://img.shields.io/badge/Astro-4.x-BC52EE?style=for-the-badge&logo=astro&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Cloudflare](https://img.shields.io/badge/Cloudflare-CDN_--_WAF-F38020?style=for-the-badge&logo=cloudflare&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)

A high-performance sports analytics platform engineered for the **FIFA World Cup 2026**. Features real-time match tracking, probabilistic quantitative forecasting models (Poisson Engine), interactive Telegram Mini-App (TMA), real-time community chat, and programmatically generated static web pages.

---

## Key Features

- **Quant Poisson Forecasting Engine**: Mathematical model calculating win/draw probabilities, goal distributions, and expected scores for all 104 World Cup matches.
- **Real-Time Live Score Engine**: Low-latency polling architecture (15s interval) with failover chain across multiple sports data feeds and Playwright scraping fallbacks.
- **Telegram Mini-App (TMA)**: Interactive React 18 frontend native to Telegram with seamless Telegram Stars payment integration and real-time user predictions.
- **Programmatic Web Architecture**: High-speed Astro 4.x static page generation for all 104 matches, 48 national team profiles, and group standings.
- **Real-Time Chat Infrastructure**: High-throughput message streaming buffer with batched SQLite WAL persistence.
- **Telegram Bot Integration**: Multi-functional bot supporting deep-linking authentication, live updates, and match analytics commands.

---

## System Architecture

```text
               ┌─────────────────────────────────────────┐
               │    Client Interfaces (Web / TMA / Bot)   │
               └────────────────────┬────────────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │ Cloudflare CDN / WAF │
                         └──────────┬──────────┘
                                    │
                        ┌───────────┴───────────┐
                        │  Nginx Reverse Proxy  │
                        └─────┬───────────┬─────┘
                              │           │
                     ┌────────┴──┐     ┌──┴──────────┐
                     │ Astro Web │     │ FastAPI App │
                     │  (/web)   │     │   (/api)    │
                     └───────────┘     └─────┬───────┘
                                             │
                                    ┌────────┴────────┐
                                    │ SQLite (WAL) DB │
                                    └─────────────────┘
```

---

## Project Structure

```text
.
├── api/                   # FastAPI backend services
│   ├── auth.py            # JWT authentication & Telegram Login validation
│   ├── chat.py            # Real-time chat & message buffer system
│   ├── live.py            # Low-latency live scores API
│   ├── main.py            # Main FastAPI application & route mounting
│   └── posts.py           # Community posts & user prediction endpoints
├── bot/                   # Telegram Bot daemon (/start, /live, /predict, /stats)
│   └── main.py
├── core/                  # Core analytics & quantitative modeling
│   ├── config.py          # Central environment configuration
│   ├── database.py        # SQLite WAL schema definitions & database helpers
│   ├── poisson.py         # SciPy/NumPy Poisson probability calculation engine
│   └── ingestion/         # Multi-source live score & data ingestion pipelines
├── tma/                   # Telegram Mini-App (React 18 + Vite)
│   └── src/               # Application UI & Telegram WebApp SDK integrations
├── web/                   # Static SEO Website (Astro 4.x)
│   └── src/pages/         # Dynamic Astro routes & match templates
├── ops/                   # Nginx config, deployment scripts & systemd service units
├── generate_content.py    # Match preview generator
├── indexnow-submit.mjs    # IndexNow protocol submission script
├── player_ids.json        # Wikidata player dataset
└── requirements.txt       # Python backend dependencies
```

---

## Quick Start & Installation

### Prerequisites
- Python 3.12+
- Node.js 18+
- SQLite 3.35+

### 1. Backend Setup
```bash
# Clone the repository
git clone https://github.com/mahimalam/llm-sports-forecasting-engine.git
cd llm-sports-forecasting-engine

# Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env

# Run FastAPI server
uvicorn api.main:app --reload --port 8000
```

### 2. Website Setup (Astro)
```bash
cd web
npm install
npm run dev
```

### 3. Telegram Mini-App Setup (React)
```bash
cd tma
npm install
npm run dev
```

---

## API Endpoint Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/matches` | Returns dataset of all 104 World Cup matches |
| `GET` | `/api/matches/live` | Low-latency live scores, clock, events & statistics |
| `GET` | `/api/predictions/{id}`| Quantitative score probabilities & tactical breakdown |
| `GET` | `/api/teams` | Team rating matrices & historical strength metrics |
| `POST` | `/api/auth/telegram` | Telegram OAuth Login widget → JWT session exchange |
| `GET` | `/api/chat/messages` | Fetches active chat room messages |
| `POST` | `/api/chat/send` | Submits chat message with authenticated payload |

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
