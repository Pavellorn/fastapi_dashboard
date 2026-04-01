# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .config import CLIENTS, get_headers
from .serveces import DataService, ChartService

app = FastAPI(
    title="OZON Dashboard",
    description="Дашборды для нескольких кабинетов OZON",
    version="1.0"
)


@app.get("/")
def home():
    """Главная страница со списком кабинетов"""
    return {
        "message": "OZON Dashboard API",
        "clients": {
            cid: info["name"] 
            for cid, info in CLIENTS.items()
        },
        "usage": {
            "dashboard": "/{client_id}/dashboard - HTML график",
            "data": "/{client_id}/data - JSON данные"
        }
    }


@app.get("/{client_id}/dashboard", response_class=HTMLResponse)
def get_dashboard(client_id: str):
    """HTML дашборд"""
    try:
        if client_id not in CLIENTS:
            raise HTTPException(404, f"Клиент {client_id} не найден")
        
        client_name = CLIENTS[client_id]["name"]
        print(f"\n{'='*60}")
        print(f"📊 Дашборд для: {client_name} ({client_id})")
        print(f"{'='*60}\n")
        
        # Получаем данные
        sales_headers = get_headers(client_id, "sells")
        errors_headers = get_headers(client_id, "errors")
        
        sales = DataService.get_sales(client_id, sales_headers, period=14)
        defects = DataService.get_defects(errors_headers)
        
        # Создаем график
        fig = ChartService.create_dashboard(sales, defects, client_id, client_name)
        
        return HTMLResponse(fig.to_html())
        
    except Exception as e:
        raise HTTPException(500, f"Ошибка: {str(e)}")


@app.get("/{client_id}/data")
def get_data(client_id: str):
    """JSON данные"""
    try:
        if client_id not in CLIENTS:
            raise HTTPException(404, f"Клиент {client_id} не найден")
        
        client_name = CLIENTS[client_id]["name"]
        print(f"\n{'='*60}")
        print(f"📦 Данные для: {client_name} ({client_id})")
        print(f"{'='*60}\n")
        
        # Получаем данные
        sales_headers = get_headers(client_id, "sells")
        errors_headers = get_headers(client_id, "errors")
        
        sales = DataService.get_sales(client_id, sales_headers)
        defects = DataService.get_defects(errors_headers)
        
        # Формируем ответ
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
                "avg_order": float(sales['sum'].sum() / sales['count'].sum()),
                "period": f"{defects['period_from']} — {defects['period_to']}"
            }
        }
        
    except Exception as e:
        raise HTTPException(500, f"Ошибка: {str(e)}")


@app.get("/health")
def health():
    """Проверка работы"""
    return {
        "status": "ok",
        "clients": len(CLIENTS)
    }