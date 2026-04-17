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
    def get_sales(client_id: str, headers: dict, period: int = 30) -> pd.DataFrame:
        """Получить данные о продажах"""
        print(f"📦 Получение продаж для {client_id}...")
        
        # 1. Создаем отчет
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period)
        
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
        for _ in range(300):
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
    
    @staticmethod
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
    """Создание графиков в стиле Bootstrap"""
    
    @staticmethod
    def create_dashboard(sales_df: pd.DataFrame, defects: dict, 
                        client_id: str, client_name: str) -> go.Figure:
        
        # Палитра Bootstrap
        BS_PRIMARY = "#0d6efd"
        BS_SUCCESS = "#198754"
        BS_DANGER = "#dc3545"
        BS_INFO = "#0dcaf0"
        BS_GRAY = "#6c757d"
        BS_LIGHT_GRAY = "#f8f9fa"

        # Итоги
        total_sales = sales_df['sum'].sum()
        total_orders = sales_df['count'].sum()
        total_defects_cost = defects.get('total_costs', 0)
        avg_index = defects.get('total_index', 0)

        # Создаем сетку
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=(
                f'<span style="color:{BS_GRAY}">📊 Продажи и заказы</span>',
                f'<span style="color:{BS_GRAY}">⚠️ Ошибки и штрафы</span>'
            ),
            vertical_spacing=0.12,
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
        )

        # --- ГРАФИК 1: ПРОДАЖИ (SUCCESS) ---
        dates = [str(d) for d in sales_df['date']]
        
        # Столбцы (Выручка)
        fig.add_trace(
            go.Bar(
                x=dates, y=sales_df['sum'],
                name="Выручка",
                marker=dict(color=BS_SUCCESS, opacity=0.8, line=dict(width=0)),
                text=[f"{v/1000:.1f}k" if v > 0 else "" for v in sales_df['sum']],
                textposition='outside',
                hovertemplate='%{y:,.0f} ₽'
            ), row=1, col=1, secondary_y=False
        )
        
        # Линия (Кол-во шт)
        fig.add_trace(
            go.Scatter(
                x=dates, y=sales_df['count'],
                name="Заказы (шт)",
                mode='lines+markers',
                line=dict(color=BS_INFO, width=3),
                marker=dict(size=8, symbol='circle', line=dict(width=2, color='white')),
                hovertemplate='%{y} шт'
            ), row=1, col=1, secondary_y=True
        )

        # --- ГРАФИК 2: ОШИБКИ (DANGER) ---
        if defects['dates']:
            # Столбцы (Штрафы)
            fig.add_trace(
                go.Bar(
                    x=defects['dates'], y=defects['costs_values'],
                    name="Штрафы (₽)",
                    marker=dict(color=BS_DANGER, opacity=0.6),
                    hovertemplate='%{y:,.2f} ₽'
                ), row=2, col=1, secondary_y=False
            )
            
            # Линия (Индекс %)
            fig.add_trace(
                go.Scatter(
                    x=defects['dates'], y=defects['index_values'],
                    name="Индекс (%)",
                    mode='lines+markers+text',
                    text=[f"{v:.1f}%" for v in defects['index_values']],
                    textposition="top center",
                    line=dict(color="#842029", width=2),
                    marker=dict(size=6),
                    hovertemplate='%{y:.2f}%'
                ), row=2, col=1, secondary_y=True
            )

        # --- ОБЩЕЕ ОФОРМЛЕНИЕ (BOOTSTRAP STYLE) ---
        
        # Заголовок как в Bootstrap Header
        header_title = (
            f"<span style='font-family:Segoe UI, sans-serif; font-weight:bold; font-size:28px; color:#212529'>"
            f"{client_name}</span><br>"
            f"<span style='font-family:Segoe UI, sans-serif; font-size:16px; color:{BS_GRAY}'>"
            f"💰 Выручка: <b>{total_sales:,.0f} ₽</b> | 📦 Заказов: <b>{total_orders} шт</b> | "
            f"🚫 Штрафы: <b>{total_defects_cost:,.0f} ₽</b> | 📉 Индекс: <b>{avg_index:.2f}%</b>"
            f"</span>"
        )

        fig.update_layout(
            title=dict(text=header_title, x=0.05, y=0.95, xanchor='left'),
            template='plotly_white',
            height=900,
            margin=dict(t=140, b=80, l=60, r=60),
            font=dict(family="Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif", size=13),
            hovermode="x unified",
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top", y=-0.05,
                xanchor="center", x=0.5,
                bgcolor='rgba(255,255,255,0)',
                bordercolor=BS_LIGHT_GRAY,
                borderwidth=1
            )
        )

        # Настройка осей (тонкие линии и сетка)
        axis_config = dict(
            showline=True, linecolor="#dee2e6",
            showgrid=True, gridcolor="#f0f0f0",
            tickfont=dict(color=BS_GRAY)
        )
        
        fig.update_xaxes(**axis_config)
        fig.update_yaxes(**axis_config)

        # Кастомные настройки для каждой оси Y
        fig.update_yaxes(title_text="₽ Выручка", row=1, col=1, secondary_y=False, title_font_color=BS_SUCCESS)
        fig.update_yaxes(title_text="Шт. Заказы", row=1, col=1, secondary_y=True, title_font_color=BS_INFO, showgrid=False)
        fig.update_yaxes(title_text="₽ Штрафы", row=2, col=1, secondary_y=False, title_font_color=BS_DANGER)
        fig.update_yaxes(title_text="% Индекс", row=2, col=1, secondary_y=True, title_font_color="#842029", showgrid=False)

        # Стилизация подзаголовков (Subtitle)
        fig.update_annotations(font=dict(size=18, color="#495057"), x=0.05, xanchor='left')

        # Сохранение
        os.makedirs('outputs', exist_ok=True)
        fig.write_html(f'outputs/dashboard_{client_id}.html', include_plotlyjs='cdn')
        
        return fig