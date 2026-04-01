# main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import os

app = FastAPI(title="Sales & Defects Dashboard")

# Конфигурация заголовков
HEAD_SELLS = {{
    "Client-Id": "482702",
    "Api-Key": "7ae789b7-93ff-4ca7-aae0-4f47f48ffdec",
    "Content-Type": "application/json"},
    {
    "Client-Id": "370459",
    "Api-Key": "419643b0-8150-4ba5-b5b7-32767f6b860f",
    "Content-Type": "application/json"},
    {
    "Client-Id": "1303860",
    "Api-Key": "887ced9a-7ada-4678-8349-fd5edd421571",
    "Content-Type": "application/json"},
}

HEAD_ERRORS = {
    "Client-Id": "482702",
    "Api-Key": "33b925bb-50af-4a2c-87e1-c7d66e36c3ea",
    "Content-Type": "application/json"
}


# ══════════════════════════════════════════════════════════
# ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ОШИБОК
# ══════════════════════════════════════════════════════════
def get_defects_data(head_errors):
    """Получает данные индекса ошибок"""
    url_method = "https://api-seller.ozon.ru/v1/rating/index/fbs/info"
    response = requests.post(url_method, headers=head_errors)
    data = response.json()

    dates = [d['date'] for d in data['defects']]
    index_values = [d['index_by_date'] * 100 for d in data['defects']]
    costs_values = [d['processing_costs_sum_by_date'] for d in data['defects']]

    return {
        'dates': dates,
        'index_values': index_values,
        'costs_values': costs_values,
        'period_from': data['period_from'],
        'period_to': data['period_to'],
        'total_index': data['index'] * 100,
        'total_costs': data['processing_costs_sum']
    }


# ══════════════════════════════════════════════════════════
# ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ПРОДАЖ
# ══════════════════════════════════════════════════════════
def warehouse_body(url_met, head):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=14)
    processed_at_from = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    processed_at_to = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    body = {
        "filter": {
            "processed_at_from": processed_at_from,
            "processed_at_to": processed_at_to,
            "delivery_schema": ["fbs"],
        },
        "language": "DEFAULT",
        "with": {
            "additional_data": False,
            "analytics_data": False,
            "customer_data": False,
            "jewelry_codes": False
        }
    }

    response = requests.post(url_met, headers=head, json=body)
    response = response.json()
    code_value = response['result']['code']
    return code_value


def file_info_body(value, url_met, head):
    file_info_body = {"code": value}
    while True:
        response_info = requests.post(url_met, headers=head, json=file_info_body)
        response_info = response_info.json()
        if response_info['result']['status'] == 'success':
            return response_info['result']['file']
        time.sleep(2)


def download_file(url, filename):
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def get_sales_data(csv_file="orders.csv"):
    """Получает данные продаж из CSV"""
    df = pd.read_csv(csv_file, sep=';', encoding='utf-8')
    df['Принят в обработку'] = pd.to_datetime(df['Принят в обработку'])
    df['date'] = df['Принят в обработку'].dt.date

    daily = df.groupby('date').agg({
        'Сумма отправления': 'sum',
        'Номер заказа': 'count'
    }).reset_index()
    daily.columns = ['date', 'sum', 'count']
    
    return daily


def fetch_and_download(head_sells):
    """Полный цикл получения данных продаж"""
    url_method = 'https://api-seller.ozon.ru/v1/report/postings/create'
    url_info = "https://api-seller.ozon.ru/v1/report/info"

    res = warehouse_body(url_method, head_sells)
    url_for_download = file_info_body(res, url_info, head_sells)
    download_file(url_for_download, 'orders.csv')

    return get_sales_data('orders.csv')


# ══════════════════════════════════════════════════════════
# СОЗДАНИЕ ГРАФИКА
# ══════════════════════════════════════════════════════════
def create_combined_chart(sales_data, defects_data, output_name="dashboard"):
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Конвертируем даты в строки для JSON
    sales_dates = [str(d) for d in sales_data['date']]
    
    # Подписи
    sales_text = [f"{val:,.0f} ₽" for val in sales_data['sum']]
    error_text = [f"{val:.1f}%" for val in defects_data['index_values']]

    # Столбцы продаж
    fig.add_trace(
        go.Bar(
            x=sales_dates,
            y=sales_data['sum'].tolist(),
            name="Сумма продаж (₽)",
            marker_color='#2ecc71',
            opacity=0.7,
            text=sales_text,
            textposition='outside',
            textfont=dict(size=18, color='#27ae60', family='Arial Black'),
            hovertemplate='<b>%{x}</b><br>Сумма: %{y:,.0f} ₽<extra></extra>'
        ),
        secondary_y=False
    )

    # Линия ошибок
    fig.add_trace(
        go.Scatter(
            x=defects_data['dates'],
            y=defects_data['index_values'],
            name="Индекс ошибок (%)",
            mode='lines+markers+text',
            line=dict(color='#e74c3c', width=3),
            marker=dict(size=10, color='#e74c3c'),
            text=error_text,
            textposition='top center',
            textfont=dict(size=18, color="#d13625", family='Arial Black'),
            hovertemplate='<b>%{x}</b><br>Индекс: %{y:.2f}%<extra></extra>'
        ),
        secondary_y=True
    )

    # Настройки осей
    max_sales = sales_data['sum'].max()
    max_index = max(defects_data['index_values'])

    fig.update_yaxes(
        title_text="<b>Сумма продаж (₽)</b>",
        title_font=dict(size=14, color='#27ae60'),
        range=[0, max_sales * 1.3],
        secondary_y=False
    )

    fig.update_yaxes(
        title_text="<b>Индекс ошибок (%)</b>",
        title_font=dict(size=20, color='#e74c3c'),
        range=[0, max_index * 1.3],
        secondary_y=True
    )

    fig.update_xaxes(
        title_text="Дата",
        title_font=dict(size=14),
        tickfont=dict(size=12)
    )

    fig.update_layout(
        title=dict(
            text=(
                f"<b>Продажи и Индекс ошибок</b><br>"
                f"<sub>Индекс ошибок: {defects_data['total_index']:.2f}% | "
                f"Сумма обработки: {defects_data['total_costs']:,.2f} ₽ | "
                f"Период: {defects_data['period_from']} — {defects_data['period_to']}</sub>"
            ),
            font=dict(size=30)
        ),
        height=700,
        template='plotly_white',
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.9,
            xanchor="center",
            x=0.5,
            font=dict(size=12),
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='#ddd',
            borderwidth=1
        ),
        margin=dict(t=120, b=60, l=80, r=50)
    )

    # Сохранение
    fig.write_html(f"{output_name}.html")
    return fig


# ══════════════════════════════════════════════════════════
# ЭНДПОИНТЫ FASTAPI
# ══════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def get_dashboard_html(client_id: int):
    """
    Эндпоинт 1: Возвращает HTML с графиком
    """
    try:
        print("📦 Загрузка данных продаж...")
        sales_data = fetch_and_download(HEAD_SELLS['Client-Id'])

        print("⚠️ Загрузка данных ошибок...")
        defects_data = get_defects_data(HEAD_ERRORS)

        print("📊 Создание dashboard...")
        create_combined_chart(sales_data, defects_data, "dashboard")

        # Читаем созданный HTML файл
        with open("dashboard.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        return HTMLResponse(content=html_content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/api/data")
async def get_dashboard_data():
    """
    Эндпоинт 2: Возвращает данные в JSON формате
    """
    try:
        print("📦 Загрузка данных продаж...")
        sales_data = fetch_and_download(HEAD_SELLS)

        print("⚠️ Загрузка данных ошибок...")
        defects_data = get_defects_data(HEAD_ERRORS)

        # Формируем JSON ответ
        response_data = {
            "sales": {
                "dates": [str(d) for d in sales_data['date'].tolist()],
                "sums": sales_data['sum'].tolist(),
                "counts": sales_data['count'].tolist()
            },
            "defects": {
                "dates": defects_data['dates'],
                "index_values": defects_data['index_values'],
                "costs_values": defects_data['costs_values'],
                "period_from": defects_data['period_from'],
                "period_to": defects_data['period_to'],
                "total_index": defects_data['total_index'],
                "total_costs": defects_data['total_costs']
            },
            "summary": {
                "total_sales": float(sales_data['sum'].sum()),
                "total_orders": int(sales_data['count'].sum()),
                "avg_order_value": float(sales_data['sum'].sum() / sales_data['count'].sum()),
                "period_from": defects_data['period_from'],
                "period_to": defects_data['period_to']
            }
        }

        return response_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ══════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)