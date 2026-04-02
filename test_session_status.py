#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тестовый скрипт для проверки статуса торговой сессии инструмента"""

from datetime import datetime
from QuikPy import QuikPy

# Настройки инструмента
CLASS = "FUTSPREAD"
SECCODE = "CRM6CRU6"
BASE_ASSET_CODE = "CRU6"  # Базовый актив (нога спреда)

if __name__ == '__main__':
    qp = QuikPy(requests_port=34132, callbacks_port=34133)
    
    print("=" * 70)
    print(f"Статус торговой сессии для {SECCODE}")
    print("=" * 70)
    print(f"Время проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. Серверное время
    print("1. СЕРВЕРНОЕ ВРЕМЯ:")
    try:
        server_time = qp.GetInfoParam('SERVERTIME')['data']
        trade_date = qp.GetInfoParam('TRADEDATE')['data']
        print(f"   Дата: {trade_date}")
        print(f"   Время: {server_time}")
    except Exception as e:
        print(f"   Ошибка: {e}")
    print()
    
    # 2. TRADINGPHASE для спреда
    print(f"2. TRADINGPHASE для спреда {SECCODE} ({CLASS}):")
    try:
        result = qp.GetParamEx(CLASS, SECCODE, 'TRADINGPHASE')
        print(f"   Полный ответ: {result}")
        if result and 'data' in result:
            data = result['data']
            print(f"   param_value: {data.get('param_value', 'N/A')}")
            print(f"   param_image: {data.get('param_image', 'N/A')}")
            print(f"   param_type: {data.get('param_type', 'N/A')}")
            print(f"   result: {data.get('result', 'N/A')}")
            
            # Интерпретация
            param_value = data.get('param_value')
            param_image = data.get('param_image', '')
            
            if param_image:
                print(f"   → Статус: {param_image.upper()}")
                if param_image == 'открыта':
                    print(f"   → Робот будет торговать: ✅ ДА")
                elif param_image == 'закрыта':
                    print(f"   → Робот будет торговать: ❌ НЕТ (клиринг/перерыв)")
            
            if param_value:
                try:
                    phase = int(float(param_value))
                    phases = {
                        0: "Торг не идет",
                        1: "Период открытия",
                        2: "Основная сессия",
                        3: "Период закрытия"
                    }
                    print(f"   → Фаза по значению: {phase} ({phases.get(phase, 'Неизвестно')})")
                except:
                    pass
    except Exception as e:
        print(f"   Ошибка: {e}")
    print()
    
    # 3. TRADINGPHASE для базового актива (ноги)
    print(f"3. TRADINGPHASE для базового актива {BASE_ASSET_CODE} (FUT):")
    try:
        result = qp.GetParamEx('FUT', BASE_ASSET_CODE, 'TRADINGPHASE')
        print(f"   Полный ответ: {result}")
        if result and 'data' in result:
            data = result['data']
            print(f"   param_value: {data.get('param_value', 'N/A')}")
            print(f"   param_image: {data.get('param_image', 'N/A')}")
            
            param_image = data.get('param_image', '')
            if param_image:
                print(f"   → Статус: {param_image.upper()}")
    except Exception as e:
        print(f"   Ошибка: {e}")
    print()
    
    # 4. Другие параметры сессии
    print("4. ДРУГИЕ ПАРАМЕТРЫ СЕССИИ:")
    session_params = ['SESSION', 'DURATION', 'STARTTIME', 'ENDTIME', 'LIMUP', 'LIMDOWN']
    for param in session_params:
        try:
            result = qp.GetParamEx(CLASS, SECCODE, param)
            if result and 'data' in result:
                value = result['data'].get('param_value', 'N/A')
                print(f"   {param}: {value}")
        except Exception as e:
            print(f"   {param}: Ошибка - {e}")
    print()
    
    # 5. Параметры инструмента
    print("5. ПАРАМЕТРЫ ИНСТРУМЕНТА:")
    instrument_params = ['LAST', 'BID', 'OFFER', 'HIGH', 'LOW', 'QTY', 'STEP', 'PRICE_PRECISION']
    for param in instrument_params:
        try:
            result = qp.GetParamEx(CLASS, SECCODE, param)
            if result and 'data' in result:
                value = result['data'].get('param_value', 'N/A')
                print(f"   {param}: {value}")
        except Exception as e:
            print(f"   {param}: Ошибка - {e}")
    print()
    
    # 6. Проверка логики робота
    print("6. ПРОВЕРКА ЛОГИКИ РОБОТА:")
    try:
        # Проверка по param_image
        result = qp.GetParamEx(CLASS, SECCODE, 'TRADINGPHASE')
        param_image = result['data'].get('param_image', '') if result and 'data' in result else ''
        
        if param_image == 'открыта':
            session_open = True
        elif param_image == 'закрыта':
            session_open = False
        else:
            # Fallback к param_value
            param_value = result['data'].get('param_value') if result and 'data' in result else None
            if param_value:
                phase = int(float(param_value))
                session_open = phase in (1, 2)
            else:
                session_open = True
        
        print(f"   check_session_status() вернёт: {session_open}")
        print(f"   → Робот {'будет' if session_open else 'НЕ будет'} торговать")
    except Exception as e:
        print(f"   Ошибка проверки: {e}")
    print()
    
    # 7. Стакан (BID/OFFER)
    print("7. СТАКАН (BID/OFFER):")
    try:
        bid_result = qp.GetParamEx(CLASS, SECCODE, "BID")
        offer_result = qp.GetParamEx(CLASS, SECCODE, "OFFER")
        
        if bid_result and 'data' in bid_result:
            bid_price = bid_result['data'].get('param_value', 'N/A')
            print(f"   BID: {bid_price}")
        
        if offer_result and 'data' in offer_result:
            offer_price = offer_result['data'].get('param_value', 'N/A')
            print(f"   OFFER: {offer_price}")
        
        if bid_price != 'N/A' and offer_price != 'N/A':
            try:
                spread = float(offer_price) - float(bid_price)
                print(f"   Спред: {spread:.6f}")
            except:
                pass
    except Exception as e:
        print(f"   Ошибка: {e}")
    print()
    
    print("=" * 70)
    print("Тест завершён")
    print("=" * 70)
    
    qp.CloseConnectionAndThread()
