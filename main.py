# Робот сеточной торговли (Grid Bot) для QUIK через QuikPy.
# Автор: Vitaliy Novozhilov
# Выставляет лимитные заявки по сетке вокруг базовой цены,
# обновляет базовую цену при исполнении уровней и хранит её в файле state.txt.
# Параметры робота задаются в файле settings.py.
import os
import time
import traceback
from datetime import datetime

from QuikPy import QuikPy
from settings import CLASS, SECCODE, BASE_ASSET_CODE, ACCOUNT, CLIENT_CODE, LOT_PER_LEVEL, LEVELS, GRID_STEP, MAX_LOTS_TOTAL, START_TIME, END_TIME, POLL_MS, REQUESTS_PORT, CALLBACKS_PORT


# Глобальные переменные состояния робота
# - trans_id: счётчик транзакций для QUIK
# - position: текущая позиция по инструменту (в лотах)
# - base_price: текущая базовая цена сетки
# - prev_position: предыдущая позиция (для отслеживания изменений)
# - is_orders_sent: флаг, что сетка заявок выставлена
# - count_exept: счётчик подряд возникших исключений в основном цикле
# - first_start: флаг первого запуска при непустой позиции для выравнивания
# - file_name: файл для хранения базовой цены между перезапусками
trans_id = 1
position = 0
base_price = 0
prev_position = 0
is_orders_sent = False
count_exept = 1
first_start = True
file_name = 'state.txt'


def get_current_price(qp):
    """Возвращает текущую последнюю цену инструмента из QUIK."""
    # Читаем параметр LAST и приводим к целому числу
    return int(float(qp.GetParamEx(CLASS, SECCODE, "LAST")['data']['param_value']))


# def get_price_by_grid(price):
#     return round(price / GRID_STEP + 0.5) * GRID_STEP


def get_current_position(qp):
    """Возвращает текущую совокупную позицию по выбранному базовому активу."""
    # Перебираем фьючерсные позиции и ищем позицию по конкретному инструменту
    all_position = qp.GetFuturesHoldings()['data']
    total_position = 0 # Инициализируем 0, если позиция не найдена
    for item in all_position:
        if item['sec_code'] == BASE_ASSET_CODE: # Ищем точное совпадение с BASE_ASSET_CODE
            total_position = int(item['totalnet'])
            break # Нашли нужный инструмент, выходим из цикла
    return total_position
        

def write_in_file(price):
    """Сохраняет базовую цену сетки и код инструмента в файл состояния."""
    global file_name
    # Записываем две строки: цена и код инструмента
    with open(file_name, 'w') as f:
        f.write(f"{price}\n{SECCODE}")


def read_from_file():
    """Читает базовую цену из файла состояния.

    Возвращает:
        int: сохранённая базовая цена; 0, если файл не существует, пуст, не содержит число,
             или если код инструмента не совпадает с текущим SECCODE.

    Примечание:
        Файл должен содержать две строки: цена и код инструмента.
    """
    global file_name
    if not os.path.exists(file_name):
        return 0
    with open(file_name, 'r') as f:
        lines = f.readlines()
        if len(lines) < 2:
            # Старый формат файла (только цена) или неполный файл — считаем невалидным
            return 0
        try:
            price = int(lines[0].strip())
            saved_seccode = lines[1].strip()
            # Проверяем, что инструмент не поменялся
            if saved_seccode != SECCODE:
                print(f"Предупреждение: инструмент изменился ({saved_seccode} → {SECCODE}). Цена из файла не используется.")
                return 0
            return price
        except (ValueError, IndexError):
            print(f"Предупреждение: файл {file_name} содержит некорректные данные. Используется 0.")
            return 0
        
    
def get_last_trade_price(qp):
    """Возвращает цену последней сделки по инструменту."""
    # Берём последний элемент из списка сделок и приводим цену к int
    trades = qp.GetTrades(CLASS, SECCODE)['data']
    if not trades or len(trades) == 0:
        return None  # Нет сделок
    last_trade = trades[-1]
    last_trade_price = int(float(last_trade['price']))
    return last_trade_price
        

def check_position_change_and_update(cur_pos):
    """Проверяет изменение позиции и обновляет глобальную переменную.

    Параметры:
        cur_pos (int | None): текущая позиция.

    Возвращает:
        bool: True, если позиция изменилась и обновлена; иначе False.
    """
    global position
    if position != cur_pos:
        position = cur_pos
        return True
    return False


def check_levels_executed(cur_pos, qp):
    """Определяет, выполнен ли очередной уровень сетки.

    При достижении кратности позиции `LOT_PER_LEVEL` обновляет базовую цену
    по последней сделке, обновляет `prev_position` и сохраняет цену в файл.
    При закрытии позиции (cur_pos == 0) обновляет базовую цену по текущей рыночной цене.

    Параметры:
        cur_pos (int): текущая позиция.
        qp: экземпляр QuikPy.

    Возвращает:
        bool: True, если уровень считается выполненным; иначе False.
    """
    global first_price_buy, first_price_sell, base_price, prev_position
    # Проверяем, изменилась ли позиция с последней проверки
    if cur_pos == prev_position:
        return False  # Позиция не изменилась — уровень не исполнен
    # Проверяем кратность позиции LOT_PER_LEVEL
    if cur_pos % LOT_PER_LEVEL == 0 and abs(cur_pos) <= MAX_LOTS_TOTAL:
        # Если позиция закрылась — обновляем базовую цену по текущей рыночной цене
        if cur_pos == 0:
            base_price = get_current_price(qp)
            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Позиция закрыта. Новая базовая цена: {base_price}")
            time.sleep(2)  # Задержка 2 секунды после закрытия позиции
        elif cur_pos > 0:
            trade_price = get_last_trade_price(qp)
            if trade_price is not None:
                base_price = trade_price
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Уровень исполнен. Новая базовая цена: {base_price}")
        elif cur_pos < 0:
            trade_price = get_last_trade_price(qp)
            if trade_price is not None:
                base_price = trade_price
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Уровень исполнен. Новая базовая цена: {base_price}")
        # Фиксируем новую базовую цену и сохраняем её на диск
        prev_position = cur_pos
        write_in_file(base_price)
        return True
    return False


def check_time(qp):
    """Проверяет, находится ли текущее серверное время в торговом окне.

    Возвращает:
        bool: True, если текущее время между START_TIME и END_TIME.
    """
    server_time = str(qp.GetInfoParam('SERVERTIME')['data']).strip()
    parts = server_time.split(':')
    if len(parts) < 2:
        return False
    current_time = parts[0] + ':' + parts[1]
    return START_TIME <= current_time <= END_TIME


def check_session_status(qp):
    """Проверяет статус торговой сессии QUIK через параметр TRADINGPHASE.

    Возвращает:
        bool: True, если основная сессия (торги идут); False, если клиринг/перерыв/открытие/закрытие.

    Значения TRADINGPHASE:
        0 - Торг не идет
        1 - Период открытия
        2 - Основная сессия (торги идут)
        3 - Период закрытия
    """
    try:
        result = qp.GetParamEx(CLASS, SECCODE, 'TRADINGPHASE')
        if not result or 'data' not in result or not result['data'].get('param_value'):
            # Параметр недоступен (например, для спредов) — считаем сессию активной
            return True
        trading_phase = int(float(result['data']['param_value']))
        # Торгуем только в основной сессии (фаза 2)
        return trading_phase == 2
    except (KeyError, ValueError, TypeError):
        # Если параметр недоступен, считаем сессию активной (для совместимости)
        return True


def send_limit_order(qp, price, volume, side):
    """Отправляет лимитную заявку в QUIK.

    Параметры:
        qp: экземпляр QuikPy.
        price (int | float): цена заявки.
        volume (int): объём в лотах.
        side (str): направление операции ('B' — покупка, 'S' — продажа).
    """
    global trans_id
    trans_id += 1
    # Формируем словарь транзакции. Все значения должны быть строками
    transaction = {  # Все значения должны передаваться в виде строк
        'TRANS_ID': str(trans_id),  # Номер транзакции задается клиентом
        'CLIENT_CODE': CLIENT_CODE,  # Код клиента. Для фьючерсов его нет
        'ACCOUNT': ACCOUNT,  # Счет
        'ACTION': 'NEW_ORDER',  # Тип заявки: Новая лимитная/рыночная заявка
        'CLASSCODE': CLASS,  # Код площадки
        'SECCODE': SECCODE,  # Код тикера
        'OPERATION': side,  # B = покупка, S = продажа
        'PRICE': str(price),  # Цена исполнения. Для рыночных фьючерсных заявок наихудшая цена в зависимости от направления. Для остальных рыночных заявок цена = 0
        'QUANTITY': str(volume),  # Кол-во в лотах
        'TYPE': 'L'}  # L = лимитная заявка (по умолчанию), M = рыночная заявка
    qp.SendTransaction(transaction)["data"]


def cancel_order(qp, order_num):
    """Отменяет заявку по её номеру.

    Параметры:
        qp: экземпляр QuikPy.
        order_num (int | str): номер заявки (ORDER_KEY).
    """
    global trans_id, is_orders_sent
    trans_id += 1
    # Формируем транзакцию на снятие заявки
    transaction = {
        'TRANS_ID': str(trans_id),  # Номер транзакции задается клиентом
        'ACTION': 'KILL_ORDER',  # Тип заявки: Удаление существующей заявки
        'CLASSCODE': CLASS,  # Код площадки
        'SECCODE': SECCODE,  # Код тикера
        'ORDER_KEY': str(order_num)}  # Номер заявки
    qp.SendTransaction(transaction)["data"]
    is_orders_sent = False


def find_active_orders(qp):
    """Возвращает список номеров активных заявок по инструменту.

    Параметры:
        qp: экземпляр QuikPy.

    Возвращает:
        list[int]: список номеров активных заявок.
    """
    orders = qp.GetOrders(CLASS, SECCODE)['data']  # Все заявки по классу и тикеру
    active_orders = [order for order in orders if order['flags'] & 0b1 == 0b1]  # Активные заявки
    active_orders_nums = [order['order_num'] for order in active_orders]
    return active_orders_nums


def cancel_all_orders(qp):
    """Снимает все активные заявки по инструменту."""
    active_orders_nums = find_active_orders(qp)
    for order_num in active_orders_nums:
        cancel_order(qp, order_num)


def set_grid(qp, price):
    """Выставляет сетку лимитных заявок вокруг заданной цены.

    Логика:
        - Если позиция нулевая — строит симметричную сетку от заданной цены.
        - Если позиция не нулевая — учитывает ограничение MAX_LOTS_TOTAL.

    Параметры:
        qp: экземпляр QuikPy.
        price (int): базовая цена сетки.
    """
    global is_orders_sent, position, base_price
    qty = position
    if qty == 0:
        # При нулевой позиции используем переданную цену для построения сетки
        for i in range(1, LEVELS+1):
            send_limit_order(qp, price - i * GRID_STEP, LOT_PER_LEVEL, "B")
            send_limit_order(qp, price + i * GRID_STEP, LOT_PER_LEVEL, "S")
        is_orders_sent = True
        base_price = price
        return
    for i in range(1, LEVELS+1):
        if abs(qty) < MAX_LOTS_TOTAL:
            # Пока общий объём меньше лимита — добавляем заявки в обе стороны
            send_limit_order(qp, price - i * GRID_STEP, LOT_PER_LEVEL, "B")
            send_limit_order(qp, price + i * GRID_STEP, LOT_PER_LEVEL, "S")
            qty += LOT_PER_LEVEL if qty > 0 else -LOT_PER_LEVEL
            is_orders_sent = True
        else:
            if qty > 0:
                # При перегруженной длинной позиции добавляем только продажи
                send_limit_order(qp, price + i * GRID_STEP, LOT_PER_LEVEL, "S")
                is_orders_sent = True
            elif qty < 0:
                # При перегруженной короткой позиции добавляем только покупки
                send_limit_order(qp, price - i * GRID_STEP, LOT_PER_LEVEL, "B")
                is_orders_sent = True


def check_base_price_by_grid(qp, price):
    """Проверяет необходимость перестройки сетки и выполняет выравнивание на старте.

    На первом запуске при ненулевой позиции пытается выставить заявку на её выравнивание.
    Также инициирует перестановку сетки при смещении цены от базовой больше половины шага.

    Параметры:
        qp: экземпляр QuikPy.
        price (int): текущая рыночная цена.

    Возвращает:
        bool: True, если требуется/выполнено действие по перестройке; иначе False.
    """
    global base_price, first_start, prev_position
    cur_pos = get_current_position(qp)
    if cur_pos == 0:
        prev_position = cur_pos
        return False
    else:
        if first_start:
            if cur_pos > 0:
                begin_grid_price = (cur_pos // LOT_PER_LEVEL) * GRID_STEP + base_price
                if price >= begin_grid_price:
                    # Выставляем лимит на продажу для выравнивания длинной позиции
                    price_to_order = int(float(qp.GetParamEx(CLASS, SECCODE, "BID")['data']['param_value'])) + 1
                    if price_to_order >= begin_grid_price:
                        send_limit_order(qp, price_to_order, abs(cur_pos),  "S")
                        first_start = False
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Выставлена заявка на закрытие позиции: {abs(cur_pos)} лотов по {price_to_order}")
                        return True
            elif cur_pos < 0:
                begin_grid_price = base_price - (abs(cur_pos) // LOT_PER_LEVEL) * GRID_STEP
                if price <= begin_grid_price:
                    # Выставляем лимит на покупку для выравнивания короткой позиции
                    price_to_order = int(float(qp.GetParamEx(CLASS, SECCODE, "OFFER")['data']['param_value'])) - 1
                    if price_to_order <= begin_grid_price:
                        send_limit_order(qp, price_to_order, abs(cur_pos),  "B")
                        first_start = False
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Выставлена заявка на закрытие позиции: {abs(cur_pos)} лотов по {price_to_order}")
                        return True
        if abs(price - base_price) >= GRID_STEP / 2:
            return True
        else:
            cancel_all_orders(qp)
            return False


if __name__ == "__main__":
    # Подключаемся к QUIK через QuikPy
    qp = QuikPy(requests_port=REQUESTS_PORT, callbacks_port=CALLBACKS_PORT)
    print("\n\n=============================================")
    print(f"Grid bot is running for {SECCODE}")
    print(f"Connected to QuikPy on ports {REQUESTS_PORT}/{CALLBACKS_PORT}")

    try:
        # Ждём наступления торгового окна START_TIME..END_TIME
        last_status = None
        while not check_time(qp) or not check_session_status(qp):
            status_msg = "торговое время" if check_time(qp) else "клиринг/перерыв"
            if status_msg != last_status:
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Ожидание: {status_msg}...")
                last_status = status_msg
            time.sleep(POLL_MS)
        print()  # Новая строка после ожидания
        # Инициализация текущих значений цены и позиции
        current_price = get_current_price(qp)
        local_base_price = read_from_file()
        cur_pos = get_current_position(qp)
        # Используем позицию как исходную для prev_position
        prev_position = cur_pos
        if cur_pos is None:
            cur_pos = 0
            prev_position = cur_pos
            print(f"Current position: {cur_pos}")
        # Если есть базовая цена в файле — восстановим сетку относительно неё
        if local_base_price != 0:
            base_price = local_base_price
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Базовая цена восстановлена из файла: {base_price}")
            # Если позиция не нулевая, то корректируем базовую цену
            if cur_pos != 0:
                last_wait_status = None
                wait_printed = False
                while check_base_price_by_grid(qp, current_price):
                    # Проверяем статус сессии и выводим сообщение
                    if not check_session_status(qp):
                        wait_status = "клиринг"
                    else:
                        wait_status = f"Ожидание возврата цены к {base_price} для построения сетки"
                    if wait_status != last_wait_status:
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {wait_status}...")
                        last_wait_status = wait_status
                        wait_printed = True
                    current_price = get_current_price(qp)
                    time.sleep(POLL_MS)
                if wait_printed:
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Цена вернулась к базовой — строим сетку\n")
        else: # Если восстановление не требуется (файл пуст/0)
            base_price = get_current_price(qp) # Устанавливаем текущую рыночную цену как базовую
            # Если цена по LAST равна 0, попробуем использовать BID/OFFER
            if base_price == 0:
                print("Параметр LAST вернул 0. Попытка получить цену по BID/OFFER...")
                try:
                    bid_price_data = qp.GetParamEx(CLASS, SECCODE, "BID")
                    offer_price_data = qp.GetParamEx(CLASS, SECCODE, "OFFER")

                    bid_price = int(float(bid_price_data['data']['param_value'])) if 'param_value' in bid_price_data['data'] else 0
                    offer_price = int(float(offer_price_data['data']['param_value'])) if 'param_value' in offer_price_data['data'] else 0

                    if bid_price != 0 and offer_price != 0:
                        base_price = (bid_price + offer_price) // 2 # Средняя между BID и OFFER
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Базовая цена установлена по BID/OFFER: {base_price}")
                    elif bid_price != 0:
                        base_price = bid_price
                        print(f"Базовая цена установлена по BID: {base_price}")
                    elif offer_price != 0:
                        base_price = offer_price
                        print(f"Базовая цена установлена по OFFER: {base_price}")
                    else:
                        print("Не удалось получить актуальную цену из BID/OFFER. Base price останется 0.")
                except Exception as e:
                    print(f"Ошибка при получении BID/OFFER цен: {e}. Base price останется 0.")

            if base_price != 0:
                print(f"Базовая цена установлена по рынку: {base_price}")
            else:
                print("Внимание: Не удалось установить базовую цену по рынку. Используется 0.")

        set_grid(qp, base_price)
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка выставлена. Базовая цена: {base_price}\n")
        # Сохраняем базовую цену на диск для последующих перезапусков
        write_in_file(base_price)
        time.sleep(POLL_MS * 2)

        # Основной цикл работы робота: следим за временем, состоянием позиций и активными заявками
        in_session_wait = False
        while True:
            try:
                # Проверяем статус сессии — если закрыта (клиринг), ждём
                if not check_session_status(qp):
                    if not in_session_wait:
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сессия закрыта (клиринг/перерыв). Ожидание...")
                        in_session_wait = True
                    time.sleep(POLL_MS)
                    continue
                if in_session_wait:
                    in_session_wait = False
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сессия открыта — возобновляем торговлю...")

                if check_time(qp):
                    cur_pos = get_current_position(qp)
                    current_price = get_current_price(qp)
                    orders = find_active_orders(qp)

                    # Проверяем, должна ли быть сетка при текущей позиции
                    should_have_grid = True
                    if cur_pos != 0:
                        # При позиции проверяем, должна ли быть сетка или ждём
                        if abs(current_price - base_price) >= GRID_STEP / 2:
                            should_have_grid = False  # Ждём возврата цены или закрытия

                    # Если активных заявок нет и сетка должна быть — восстанавливаем после клиринга
                    if len(orders) == 0 and should_have_grid:
                        set_grid(qp, base_price)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка восстановлена после клиринга")
                    # При изменении позиции и выполнении уровня — отменяем старые заявки и переставляем сетку
                    if check_position_change_and_update(cur_pos) and check_levels_executed(cur_pos, qp):
                        cancel_all_orders(qp)
                        set_grid(qp, base_price)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка переставлена. Базовая цена: {base_price}")
                time.sleep(POLL_MS)
                
            except Exception as e:
                print("\n❗ Exception occurred:")
                print(traceback.format_exc())
                # Ограничиваем число подряд возникших исключений
                count_exept += 1
                if count_exept >= 3:
                    break
                time.sleep(POLL_MS)
                continue
        raise Exception("Max count of exceptions")
    except Exception as e:
        print(e)
    except KeyboardInterrupt:
        print('Робот остановлен пользователем')
    finally:
        # Перед выходом снимаем все заявки и закрываем соединение с QUIK
        cancel_all_orders(qp)
        qp.CloseConnectionAndThread()
