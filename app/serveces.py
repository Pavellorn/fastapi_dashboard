# app/services.py
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os
from datetime import datetime, timedelta


class DataService:
    """Сервис для получения данных из OZON API"""
    
    @staticmethod
    def get_sales(client_id: str, headers: dict, period: int = 30) -> pd.DataFrame:  # ← исправил perid на period
        """Получить данные о продажах"""
        print(f"📦 Получение продаж для {client_id}...")
        
        # 1. Создаем отчет
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period)  # ← исправил perid на period
        
        body = {
            "filter": {
                "processed_at_from": start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "processed_at_to": end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
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
        
        response = requests.post(
            'https://api-seller.ozon.ru/v1/report/postings/create',
            headers=headers,
            json=body
        )
        code = response.json()['result']['code']
        
        # 2. Ждем готовности файла
        print(f"⏳ Ожидание отчета...")
        for _ in range(30):
            response = requests.post(
                "https://api-seller.ozon.ru/v1/report/info",
                headers=headers,
                json={"code": code}
            )
            result = response.json()['result']
            
            if result['status'] == 'success':
                file_url = result['file']
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("Превышено время ожидания отчета")
        
        # 3. Скачиваем CSV
        os.makedirs('data', exist_ok=True)
        csv_file = f'data/orders_{client_id}.csv'
        
        with requests.get(file_url, stream=True) as r:
            with open(csv_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        # 4. Парсим данные
        df = pd.read_csv(csv_file, sep=';', encoding='utf-8')
        df['Принят в обработку'] = pd.to_datetime(df['Принят в обработку'])
        df['date'] = df['Принят в обработку'].dt.date
        
        daily = df.groupby('date').agg({
            'Сумма отправления': 'sum',
            'Номер заказа': 'count'
        }).reset_index()
        daily.columns = ['date', 'sum', 'count']
        
        print(f"✅ Получено {len(daily)} дней продаж")
        if os.path.exists(csv_file):
            os.remove(csv_file)
        return daily
    
    @staticmethod  # ← ВАЖНО! Этот метод должен быть с отступом внутри класса DataService
    def get_defects(headers: dict) -> dict:
        """Получить данные об ошибках (API возвращает фиксированный период ~14 дней)"""
        print(f"⚠️ Получение индекса ошибок...")
        
        # API ошибок не принимает период, возвращает данные за последние ~14 дней
        response = requests.post(
            "https://api-seller.ozon.ru/v1/rating/index/fbs/info",
            headers=headers
        )
        data = response.json()
        
        # Проверяем наличие данных
        if not data.get('defects'):
            print("⚠️ Нет данных об ошибках")
            return {
                'dates': [],
                'index_values': [],
                'costs_values': [],
                'period_from': datetime.now().strftime("%Y-%m-%d"),
                'period_to': datetime.now().strftime("%Y-%m-%d"),
                'total_index': 0,
                'total_costs': 0
            }
        
        result = {
            'dates': [d['date'] for d in data['defects']],
            'index_values': [d['index_by_date'] * 100 for d in data['defects']],
            'costs_values': [d['processing_costs_sum_by_date'] for d in data['defects']],
            'period_from': data['period_from'],
            'period_to': data['period_to'],
            'total_index': data['index'] * 100,
            'total_costs': data['processing_costs_sum']
        }
        
        print(f"✅ Индекс ошибок: {result['total_index']:.2f}%")
        print(f"   Период: {result['period_from']} — {result['period_to']}")
        return result


class ChartService:
    """Создание графиков"""
    
    @staticmethod
    def create_dashboard(sales_df: pd.DataFrame, defects: dict, 
                        client_id: str, client_name: str) -> go.Figure:
        """Создать дашборд"""
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        sales_dates = [str(d) for d in sales_df['date']]
        sales_text = [f"{val:,.0f} ₽" for val in sales_df['sum']]
        
        # Столбцы продаж
        fig.add_trace(
            go.Bar(
                x=sales_dates,
                y=sales_df['sum'].tolist(),
                name="Продажи (₽)",
                marker_color='#2ecc71',
                opacity=0.7,
                text=sales_text,
                textposition='outside',
                textfont=dict(size=18, color='#27ae60', family='Arial Black'),
                hovertemplate='<b>%{x}</b><br>Сумма: %{y:,.0f} ₽<extra></extra>'
            ),
            secondary_y=False
        )
        
        # Линия ошибок (если есть данные)
        if defects['dates'] and defects['index_values']:
            error_text = [f"{val:.1f}%" for val in defects['index_values']]
            
            fig.add_trace(
                go.Scatter(
                    x=defects['dates'],
                    y=defects['index_values'],
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
            max_index = max(defects['index_values'])
        else:
            # Если нет данных об ошибках, добавляем пустой trace
            fig.add_trace(
                go.Scatter(
                    x=[],
                    y=[],
                    name="Индекс ошибок (нет данных)",
                    mode='lines+markers',
                    line=dict(color='#e74c3c', width=3),
                ),
                secondary_y=True
            )
            max_index = 1
        
        # Настройки осей
        max_sales = sales_df['sum'].max()
        
        fig.update_yaxes(
            title_text="<b>Продажи (₽)</b>",
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
        
        # Заголовок с информацией
        title_text = (
            f"<b>{client_name} (ID: {client_id})</b><br>"
            f"<b>Продажи и Индекс ошибок</b><br>"
        )
        
        if defects['dates']:
            title_text += (
                f"<sub>Индекс: {defects['total_index']:.2f}% | "
                f"Обработка: {defects['total_costs']:,.2f} ₽ | "
                f"Период ошибок: {defects['period_from']} — {defects['period_to']}</sub>"
            )
        else:
            title_text += "<sub>⚠️ Нет данных об ошибках</sub>"
        
        fig.update_layout(
            title=dict(
                text=title_text,
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
            margin=dict(t=140, b=60, l=80, r=50)
        )
        
        os.makedirs('outputs', exist_ok=True)
        fig.write_html(f'outputs/dashboard_{client_id}.html')
        
        return fig