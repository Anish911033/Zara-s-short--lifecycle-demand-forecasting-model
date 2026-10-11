# Zara new-style replenishment forecast (Render deploy)

A small FastAPI service that serves the notebook's forecast for new styles:
weekly units by size, next 4 weeks, per store, plus the style total for DC dispatch.

## Run locally
    pip install -r requirements.txt
    uvicorn app:app --reload
https://zara-s-short-lifecycle-demand-y9l2.onrender.com/

## Endpoints
- `/`                         simple page: pick a style, see DC dispatch and store detail
- `/health`                   health check (used by Render)
- `/api/styles`               list of new styles
- `/api/forecast?sku=ZSK00200`  store x week x size forecast
- `/api/dispatch?sku=ZSK00200`  style total per week and size
- `/api/forecast.csv`         full forecast file
- `/api/blend?own_avg=7&weeks_seen=1&store_id=ZR001`  one store's blended forecast

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render dashboard > New > Blueprint > pick the repo > Apply (reads render.yaml).
   Or: New > Web Service, Build `pip install -r requirements.txt`,
   Start `uvicorn app:app --host 0.0.0.0 --port $PORT`, Health check `/health`.
3. Open the `.onrender.com` URL.

Prophet and the EDA stay in the notebook. They are not needed to serve forecasts.
