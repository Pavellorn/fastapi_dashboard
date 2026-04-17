import os
import json
import logging
from datetime import datetime
from threading import Thread

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import CLIENTS, get_headers
from app.services import DataService, ChartService

# Настройка логов, чтобы видеть процесс в консоли
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════
app = FastAPI(
    title="OZON Dashboard Pro",
    description="Система мониторинга Ozon с фоновым обновлением данных",
    version="2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Папки для хранения кэша
CACHE_DIR = "cache"
OUTPUTS_DIR = "outputs"
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════
# ФОНОВЫЙ РОБОТ (WORKER)
# ═══════════════════════════════════════════════════════════

def update_all_data():
    """
    Функция обходит все кабинеты Ozon, скачивает данные 
    и обновляет файлы на диске.
    """
    logger.info("🔄 Запуск планового обновления данных для всех клиентов...")
    
    for client_id, info in CLIENTS.items():
        try:
            client_name = info["name"]
            logger.info(f"⚙️ Обработка: {client_name} (ID: {client_id})")
            
            # 1. Подготовка заголовков
            sales_headers = get_headers(client_id, "sells")
            errors_headers = get_headers(client_id, "errors")
            
            # 2. Получение данных (тяжелые запросы к Ozon)
            # Берем период 14 дней для скорости и наглядности
            sales = DataService.get_sales(client_id, sales_headers, period=14)
            defects = DataService.get_defects(errors_headers)
            
            # 3. Генерация HTML Дашборда (сохраняется внутри сервиса)
            ChartService.create_dashboard(sales, defects, client_id, client_name)
            
            # 4. Сохранение JSON данных для роута /data
            # Превращаем DataFrame в список словарей для JSON
            json_data = {
                "client_id": client_id,
                "client_name": client_name,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "summary": {
                    "total_sales": float(sales['sum'].sum()),
                    "total_orders": int(sales['count'].sum()),
                    "total_defects": defects.get('total_count', 0),
                    "total_fines": float(defects.get('total_costs', 0))
                },
                "raw_defects": defects # Здесь уже лежат counts_values и т.д.
            }
            
            with open(f"{CACHE_DIR}/data_{client_id}.json", "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
                
            logger.info(f"✅ Данные для {client_name} успешно обновлены.")
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при обновлении {client_id}: {str(e)}")

# ═══════════════════════════════════════════════════════════
# ПЛАНИРОВЩИК (SCHEDULER)
# ═══════════════════════════════════════════════════════════
scheduler = BackgroundScheduler()

@app.on_event("startup")
async def startup_event():
    # 1. Добавляем задачу: выполнять раз в 60 минут
    scheduler.add_job(update_all_data, 'interval', minutes=60, id='ozon_update_job')
    scheduler.start()
    logger.info("⏰ Планировщик запущен: интервал 60 минут.")
    
    # 2. Запускаем обновление ПЕРВЫЙ раз в отдельном потоке, 
    # чтобы не блокировать запуск самого сервера FastAPI
    Thread(target=update_all_data).start()

# ═══════════════════════════════════════════════════════════
# РОУТЫ (ОТДАЮТ ГОТОВЫЙ КЭШ)
# ═══════════════════════════════════════════════════════════

@app.get("/")
def home():
    """Список всех доступных кабинетов"""
    return {
        "status": "online",
        "update_interval": "60 min",
        "clients": {cid: info["name"] for cid, info in CLIENTS.items()},
        "endpoints": {
            "dashboard": "/{client_id}/dashboard",
            "json_data": "/{client_id}/data"
        }
    }

@app.get("/{client_id}/dashboard", response_class=HTMLResponse)
def get_dashboard(client_id: str):
    """Отдает предзагруженный HTML график"""
    if client_id not in CLIENTS:
        raise HTTPException(404, "Клиент не найден в базе")
    
    file_path = f"{OUTPUTS_DIR}/dashboard_{client_id}.html"
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        # Если файла еще нет (первый запуск), показываем загрузку
        return f"""
        <html>
            <head><meta charset="utf-8"><meta http-equiv="refresh" content="10"></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 100px; color: #666;">
                <div style="font-size: 50px;">🔄</div>
                <h2>Данные для {CLIENTS[client_id]['name']} подготавливаются...</h2>
                <p>Обычно это занимает 1-2 минуты при первом запуске. Страница обновится сама.</p>
                <div style="color: #ccc; margin-top: 20px;">ID запроса: {client_id}</div>
            </body>
        </html>
        """

@app.get("/{client_id}/data")
def get_json_data(client_id: str):
    """Отдает предзагруженные данные в формате JSON"""
    file_path = f"{CACHE_DIR}/data_{client_id}.json"
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    raise HTTPException(202, "Данные еще собираются, попробуйте через минуту.")

@app.get("/system/force_update")
def force_update():
    """Ручной запуск обновления (для тестов)"""
    Thread(target=update_all_data).start()
    return {"message": "Обновление запущено вручную в фоновом режиме"}

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}