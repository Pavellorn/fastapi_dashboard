# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import CLIENTS, get_headers
from app.services import DataService, ChartService
import os

# ═══════════════════════════════════════════════════════════
# СОЗДАЁМ ПРИЛОЖЕНИЕ
# ═══════════════════════════════════════════════════════════
app = FastAPI(
    title="OZON Dashboard",
    description="Дашборды для нескольких кабинетов OZON",
    version="1.0"
)

# ═══════════════════════════════════════════════════════════
# CORS - ВАЖНО! Добавляем ДО всех роутов
# ═══════════════════════════════════════════════════════════
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Временно разрешаем всё для теста
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)


# ═══════════════════════════════════════════════════════════
# РОУТЫ
# ═══════════════════════════════════════════════════════════

@app.get("/")
def home():
    """Главная"""
    return {
        "message": "OZON Dashboard API",
        "clients": {cid: info["name"] for cid, info in CLIENTS.items()},
        "cors": "enabled",
        "usage": {
            "dashboard": "/{client_id}/dashboard - HTML график",
            "data": "/{client_id}/data - JSON данные"
        }
    }


@app.get("/health")
def health():
    """Проверка здоровья"""
    return {
        "status": "ok", 
        "clients": len(CLIENTS),
        "cors": "enabled"
    }


@app.get("/{client_id}/dashboard", response_class=HTMLResponse)
def get_dashboard(client_id: str, period: int = 14):
    """HTML дашборд"""
    try:
        if client_id not in CLIENTS:
            raise HTTPException(404, f"Клиент {client_id} не найден")
        
        client_name = CLIENTS[client_id]["name"]
        print(f"\n📊 Дашборд для: {client_name} ({client_id}) за {period} дней\n")
        
        sales_headers = get_headers(client_id, "sells")
        errors_headers = get_headers(client_id, "errors")
        
        sales = DataService.get_sales(client_id, sales_headers, period)
        defects = DataService.get_defects(errors_headers)
        
        fig = ChartService.create_dashboard(sales, defects, client_id, client_name)
        
        return HTMLResponse(fig.to_html())
        
    except Exception as e:
        raise HTTPException(500, f"Ошибка: {str(e)}")


@app.get("/{client_id}/data")
def get_data(client_id: str, period: int = 14):
    """JSON данные"""
    try:
        if client_id not in CLIENTS:
            raise HTTPException(404, f"Клиент {client_id} не найден")
        
        client_name = CLIENTS[client_id]["name"]
        print(f"\n📦 Данные для: {client_name} ({client_id}) за {period} дней\n")
        
        sales_headers = get_headers(client_id, "sells")
        errors_headers = get_headers(client_id, "errors")
        
        sales = DataService.get_sales(client_id, sales_headers, period)
        defects = DataService.get_defects(errors_headers)
        
        return {
            "client_id": client_id,
            "client_name": client_name,
            "sales": {
                "dates": [str(d) for d in sales['date'].tolist()],
                "sums": sales['sum'].tolist(),
                "counts": sales['count'].tolist()
            },
            "defects": defects,
            "summary": {
                "total_sales": float(sales['sum'].sum()),
                "total_orders": int(sales['count'].sum()),
                "avg_order": float(sales['sum'].sum() / sales['count'].sum()) if sales['count'].sum() > 0 else 0,
                "period": f"{defects.get('period_from', '')} — {defects.get('period_to', '')}"
            }
        }
        
    except Exception as e:
        raise HTTPException(500, f"Ошибка: {str(e)}")


# ═══════════════════════════════════════════════════════════
# EVENTS
# ═══════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup_event():
    print("🚀 API запущено")
    print("🌐 CORS включен для всех источников")