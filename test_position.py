# test_position.py
import time
from QuikPy import QuikPy
from settings import POLL_MS # Импортируем только POLL_MS, так как остальные не нужны для этой задачи

# Инициализация QuikPy
qp = QuikPy()

print("\n=============================================")
print("Отображение всех фьючерсных позиций по клиентским счетам.")
print(f"Обновление каждые {POLL_MS} секунд. Нажмите Ctrl+C для выхода.")
print("---------------------------------------------")

try:
    while True:
        # Получаем все фьючерсные позиции
        # 'data' содержит список словарей, каждый из которых представляет позицию по инструменту
        all_positions = qp.GetFuturesHoldings()['data']
        
        if all_positions:
            print(f"\n--- Время: {time.strftime('%H:%M:%S')} ---")
            for item in all_positions:
                # Выводим код инструмента (sec_code) и совокупную позицию (totalnet)
                print(f"  Инструмент: {item['sec_code']}, Позиция: {item['totalnet']}")
        else:
            print(f"\n--- Время: {time.strftime('%H:%M:%S')}: Активных фьючерсных позиций не найдено. ---")
        
        time.sleep(POLL_MS)
        
except KeyboardInterrupt:
    print("\nТестирование завершено.")
finally:
    # Закрываем соединение с QUIK при завершении работы
    qp.CloseConnectionAndThread()