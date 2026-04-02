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
# - count_exept: счётчик подряд возникших исключений в основном цикле
# - first_start: флаг первого запуска при непустой позиции для выравнивания
# - file_name: файл для хранения базовой цены между перезапусками
trans_id = 1
position = 0
base_price = 0
prev_position = 0
count_exept = 1
first_start = True
file_name = 'state.txt'


def get_current_price(qp):
    """Возвращает текущую последнюю цену инструмента из QUIK."""
    # Читаем параметр LAST и приводим к float для поддержки дробных цен
    return float(qp.GetParamEx(CLASS, SECCODE, "LAST")['data']['param_value'])


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
            price = float(lines[0].strip())
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
    # Берём последний элемент из списка сделок и приводим цену к float
    trades = qp.GetTrades(CLASS, SECCODE)['data']
    if not trades or len(trades) == 0:
        return None  # Нет сделок
    last_trade = trades[-1]
    last_trade_price = float(last_trade['price'])
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
        # Если позиция закрылась — обновляем базовую цену по цене последней сделки
        if cur_pos == 0:
            trade_price = get_last_trade_price(qp)
            base_price = trade_price if trade_price is not None else base_price
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
    try:
        server_time_data = qp.GetInfoParam('SERVERTIME')['data']
        if not server_time_data:
            return False
        server_time = str(server_time_data).strip()
        parts = server_time.split(':')
        if len(parts) < 2:
            return False
        # Нормализуем формат: добавляем ведущий ноль (9:58 → 09:58)
        current_time = f"{int(parts[0]):02d}:{parts[1]}"
        return START_TIME <= current_time <= END_TIME
    except Exception:
        return False


def check_quik_connection(qp):
    """Проверяет соединение QUIK с сервером.

    Возвращает:
        bool: True, если QUIK подключен к серверу; False, если отключен.
    """
    try:
        result = qp.IsConnected()
        if not result or 'data' not in result:
            return False
        return result['data'] == 1
    except (KeyError, ValueError, TypeError):
        # Если проверка недоступна, считаем соединение активным
        return True


def check_session_status(qp):
    """Проверяет статус торговой сессии QUIK через параметр TRADINGPHASE.

    Возвращает:
        bool: True, если торги идут (сессия открыта); False, если клиринг/перерыв/закрытие.

    Примечание:
        Для спредов FUTSPREAD параметр TRADINGPHASE может возвращать:
        - param_image: 'открыта' или 'закрыта'
        - param_value: '1.000000' (может быть и при открытой, и при закрытой сессии)
        
        Поэтому проверяем param_image, а не param_value.
    """
    try:
        result = qp.GetParamEx(CLASS, SECCODE, 'TRADINGPHASE')
        if result and 'data' in result:
            param_image = result['data'].get('param_image', '')
            # Проверяем по изображению параметра (более надёжно для спредов)
            if param_image == 'открыта':
                return True
            elif param_image == 'закрыта':
                return False
            # Если param_image не определён, пробуем проверить по param_value
            param_value = result['data'].get('param_value')
            if param_value:
                trading_phase = int(float(param_value))
                # Торгуем в фазе 1 (открытие) и 2 (основная сессия)
                return trading_phase in (1, 2)
        # Если параметр недоступен — считаем сессию активной
        return True
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
    # Округляем цену до 6 знаков после запятой для избежания проблем с float
    price = round(float(price), 6)
    # Форматируем цену: убираем лишние нули после запятой (249.0 -> 249, 0.230000 -> 0.23)
    price_str = f'{price:g}'
    # Формируем словарь транзакции. Все значения должны быть строками
    transaction = {  # Все значения должны передаваться в виде строк
        'TRANS_ID': str(trans_id),  # Номер транзакции задается клиентом
        'CLIENT_CODE': CLIENT_CODE,  # Код клиента. Для фьючерсов его нет
        'ACCOUNT': ACCOUNT,  # Счет
        'ACTION': 'NEW_ORDER',  # Тип заявки: Новая лимитная/рыночная заявка
        'CLASSCODE': CLASS,  # Код площадки
        'SECCODE': SECCODE,  # Код тикера
        'OPERATION': side,  # B = покупка, S = продажа
        'PRICE': price_str,  # Цена исполнения. Для рыночных фьючерсных заявок наихудшая цена в зависимости от направления. Для остальных рыночных заявок цена = 0
        'QUANTITY': str(volume),  # Кол-во в лотах
        'TYPE': 'L'}  # L = лимитная заявка (по умолчанию), M = рыночная заявка
    qp.SendTransaction(transaction)["data"]


def cancel_order(qp, order_num):
    """Отменяет заявку по её номеру.

    Параметры:
        qp: экземпляр QuikPy.
        order_num (int | str): номер заявки (ORDER_KEY).
    """
    global trans_id
    trans_id += 1
    # Формируем транзакцию на снятие заявки
    transaction = {
        'TRANS_ID': str(trans_id),  # Номер транзакции задается клиентом
        'ACTION': 'KILL_ORDER',  # Тип заявки: Удаление существующей заявки
        'CLASSCODE': CLASS,  # Код площадки
        'SECCODE': SECCODE,  # Код тикера
        'ORDER_KEY': str(order_num)}  # Номер заявки
    qp.SendTransaction(transaction)["data"]


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
        - Перед выставлением сетки отменяет все активные заявки.
        - Если позиция нулевая — строит симметричную сетку от заданной цены.
        - Если позиция не нулевая — учитывает ограничение MAX_LOTS_TOTAL.

    Параметры:
        qp: экземпляр QuikPy.
        price (float): базовая цена сетки.
    """
    global base_price
    # Получаем актуальную позицию из QUIK
    qty = get_current_position(qp)
    
    # Перед выставлением сетки отменяем все заявки
    cancel_all_orders(qp)
    
    if qty == 0:
        # При нулевой позиции используем переданную цену для построения сетки
        for i in range(1, LEVELS+1):
            send_limit_order(qp, price - i * GRID_STEP, LOT_PER_LEVEL, "B")
            send_limit_order(qp, price + i * GRID_STEP, LOT_PER_LEVEL, "S")
        base_price = price
        return
    for i in range(1, LEVELS+1):
        if abs(qty) < MAX_LOTS_TOTAL:
            # Пока общий объём меньше лимита — добавляем заявки в обе стороны
            send_limit_order(qp, price - i * GRID_STEP, LOT_PER_LEVEL, "B")
            send_limit_order(qp, price + i * GRID_STEP, LOT_PER_LEVEL, "S")
            qty += LOT_PER_LEVEL if qty > 0 else -LOT_PER_LEVEL
        else:
            if qty > 0:
                # При перегруженной длинной позиции добавляем только продажи
                send_limit_order(qp, price + i * GRID_STEP, LOT_PER_LEVEL, "S")
            elif qty < 0:
                # При перегруженной короткой позиции добавляем только покупки
                send_limit_order(qp, price - i * GRID_STEP, LOT_PER_LEVEL, "B")


def check_base_price_by_grid(qp, price):
    """Проверяет необходимость перестройки сетки и выполняет выравнивание на старте.

    Логика:
        1. Если позиция в плюсе (цена >= begin_grid_price) и заявок нет — выставляем заявку на закрытие.
        2. Если цена вне канала (±GRID_STEP) — ждём возврата.
        3. Если цена в канале — нужна сетка.

    Параметры:
        qp: экземпляр QuikPy.
        price (float): текущая рыночная цена.

    Возвращает:
        tuple: (need_grid, close_position, position_closed) — нужна ли сетка, закрыли ли позицию, позиция закрыта.
    """
    global base_price, prev_position
    cur_pos = get_current_position(qp)
    if cur_pos == 0:
        prev_position = cur_pos
        return (True, False, True)  # Позиция нулевая — нужна сетка

    # 1. Проверка на закрытие прибыльной позиции
    if cur_pos > 0:
        # Длинная позиция: закрываем, если цена выше begin_grid_price
        begin_grid_price = (cur_pos // LOT_PER_LEVEL) * GRID_STEP + base_price
        if price >= begin_grid_price:
            # Проверяем, есть ли уже активные заявки
            orders = find_active_orders(qp)
            if len(orders) == 0:
                # Заявок нет — выставляем на закрытие
                bid_result = qp.GetParamEx(CLASS, SECCODE, "BID")
                if bid_result and 'data' in bid_result:
                    bid_price = float(bid_result['data'].get('param_value', 0))
                    # Получаем шаг цены для корректного расчёта цены заявки
                    step_result = qp.GetParamEx(CLASS, SECCODE, "STEP")
                    price_step = float(step_result['data'].get('param_value', GRID_STEP)) if step_result and 'data' in step_result else GRID_STEP
                    # Цена заявки = BID + шаг цены (чтобы заявка исполнилась сразу)
                    price_to_order = round(bid_price + price_step, 6)
                    if price_to_order >= begin_grid_price and bid_price > 0:
                        send_limit_order(qp, price_to_order, abs(cur_pos),  "S")
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Выставлена заявка на закрытие позиции: {abs(cur_pos)} лотов по {price_to_order}")
                        return (False, True, False)  # Заявка выставлена, ждём исполнения
            # Заявка уже есть — ждём исполнения
            return (False, True, False)
    elif cur_pos < 0:
        # Короткая позиция: закрываем, если цена ниже begin_grid_price
        begin_grid_price = base_price - (abs(cur_pos) // LOT_PER_LEVEL) * GRID_STEP
        if price <= begin_grid_price:
            # Проверяем, есть ли уже активные заявки
            orders = find_active_orders(qp)
            if len(orders) == 0:
                # Заявок нет — выставляем на закрытие
                offer_result = qp.GetParamEx(CLASS, SECCODE, "OFFER")
                if offer_result and 'data' in offer_result:
                    offer_price = float(offer_result['data'].get('param_value', 0))
                    # Получаем шаг цены для корректного расчёта цены заявки
                    step_result = qp.GetParamEx(CLASS, SECCODE, "STEP")
                    price_step = float(step_result['data'].get('param_value', GRID_STEP)) if step_result and 'data' in step_result else GRID_STEP
                    # Цена заявки = OFFER - шаг цены (чтобы заявка исполнилась сразу)
                    price_to_order = round(offer_price - price_step, 6)
                    if price_to_order <= begin_grid_price and offer_price > 0:
                        send_limit_order(qp, price_to_order, abs(cur_pos),  "B")
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Выставлена заявка на закрытие позиции: {abs(cur_pos)} лотов по {price_to_order}")
                        return (False, True, False)  # Заявка выставлена, ждём исполнения
            # Заявка уже есть — ждём исполнения
            return (False, True, False)

    # 2. Позиция в минусе или в плюсе, но не достигла уровня закрытия
    if abs(price - base_price) > GRID_STEP:
        # Цена за пределами канала — ждём возврата, сетка не нужна
        return (False, False, False)
    else:
        # Цена в канале (±GRID_STEP) — нужна сетка
        return (True, False, False)


if __name__ == "__main__":
    # Подключаемся к QUIK через QuikPy
    qp = QuikPy(requests_port=REQUESTS_PORT, callbacks_port=CALLBACKS_PORT)
    print("\n\n=============================================")
    print(f"Grid bot is running for {SECCODE}")
    print(f"Connected to QuikPy on ports {REQUESTS_PORT}/{CALLBACKS_PORT}")

    try:
        # Даём QUIK время на получение актуальных данных после подключения
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Получение данных от QUIK...")
        time.sleep(3)
        
        # Проверяем, что QUIK возвращает актуальные данные
        try:
            server_time = qp.GetInfoParam('SERVERTIME')['data']
            trade_date = qp.GetInfoParam('TRADEDATE')['data']
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Серверное время QUIK: {trade_date} {server_time}")
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Предупреждение: не удалось получить время QUIK: {e}")
        
        # Ждём наступления торгового окна START_TIME..END_TIME
        last_status = None
        while not check_time(qp) or not check_session_status(qp):
            # Проверяем каждое условие отдельно для корректного сообщения
            is_time_ok = check_time(qp)
            is_session_ok = check_session_status(qp)
            
            if not is_session_ok:
                status_msg = "клиринг/перерыв"
            elif not is_time_ok:
                status_msg = "внерабочее время"
            else:
                break  # Оба условия выполнены
            
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
                position_closed = False  # Флаг закрытия позиции
                while True:
                    # Проверяем режим работы
                    need_grid, close_position, pos_closed = check_base_price_by_grid(qp, current_price)
                    
                    # Если позиция закрылась — выходим
                    if pos_closed:
                        position_closed = True
                        break
                    
                    # Если нужна сетка (цена в канале) — выходим
                    if need_grid:
                        break
                    
                    # Цена вне канала — ждём возврата
                    # Проверяем соединение с QUIK
                    if not check_quik_connection(qp):
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} QUIK отключен от сервера. Ожидание подключения...")
                        while not check_quik_connection(qp):
                            time.sleep(POLL_MS * 15)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} QUIK подключен к серверу — возобновляем работу...")
                        time.sleep(3)  # Даём время на обновление данных
                        # После подключения проверяем актуальную цену
                        current_price = get_current_price(qp)
                        continue

                    # Проверяем, не закрылась ли позиция (заявка исполнилась)
                    current_cur_pos = get_current_position(qp)
                    if current_cur_pos == 0:
                        # Позиция закрылась — обновляем базовую цену
                        position_closed = True
                        trade_price = get_last_trade_price(qp)
                        if trade_price is not None:
                            base_price = trade_price
                            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Позиция закрыта. Новая базовая цена: {base_price}")
                        break  # Выход из цикла ожидания

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

                if position_closed:
                    # Позиция закрыта — выставляем сетку с новой базовой ценой
                    pass  # Базовая цена уже обновлена
                elif wait_printed:
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Цена вернулась к базовой — строим сетку\n")
        else: # Если восстановление не требуется (файл пуст/0)
            base_price = get_current_price(qp) # Устанавливаем текущую рыночную цену как базовую
            # Если цена по LAST равна 0, попробуем использовать BID/OFFER
            if base_price == 0:
                print("Параметр LAST вернул 0. Попытка получить цену по BID/OFFER...")
                try:
                    bid_price_data = qp.GetParamEx(CLASS, SECCODE, "BID")
                    offer_price_data = qp.GetParamEx(CLASS, SECCODE, "OFFER")

                    bid_price = float(bid_price_data['data']['param_value']) if bid_price_data and 'data' in bid_price_data and 'param_value' in bid_price_data['data'] else 0
                    offer_price = float(offer_price_data['data']['param_value']) if offer_price_data and 'data' in offer_price_data and 'param_value' in offer_price_data['data'] else 0

                    if bid_price != 0 and offer_price != 0:
                        # Получаем шаг цены для приведения базовой цены
                        step_result = qp.GetParamEx(CLASS, SECCODE, "STEP")
                        price_step = float(step_result['data'].get('param_value', GRID_STEP)) if step_result and 'data' in step_result else GRID_STEP
                        # Средняя между BID и OFFER, приведённая к шагу цены
                        base_price = round((bid_price + offer_price) / 2 / price_step) * price_step
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
        connection_lost = False
        time_check_failures = 0  # Счётчик неудачных проверок времени
        
        while True:
            try:
                # Проверяем соединение QUIK с сервером
                if not check_quik_connection(qp):
                    if not connection_lost:
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} QUIK отключен от сервера. Ожидание подключения...")
                        connection_lost = True
                    time.sleep(POLL_MS * 15)
                    continue
                if connection_lost:
                    connection_lost = False
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} QUIK подключен к серверу — возобновляем работу...")
                    # После подключения даем время на получение актуальных данных (15 секунд)
                    time.sleep(15)
                    # Сбрасываем счётчик ошибок времени
                    time_check_failures = 0
                    # Проверяем, не закрылась ли позиция во время разрыва
                    cur_pos_after_connect = get_current_position(qp)
                    if cur_pos_after_connect == 0 and position != 0:
                        # Позиция закрылась во время разрыва — обновляем базовую цену
                        trade_price = get_last_trade_price(qp)
                        if trade_price is not None:
                            base_price = trade_price
                            write_in_file(base_price)
                            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Позиция закрыта во время разрыва. Новая базовая цена: {base_price}")
                        set_grid(qp, base_price)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка выставлена после закрытия позиции")
                    prev_position = cur_pos_after_connect
                    position = cur_pos_after_connect
                    # Не проверяем время сразу после подключения — даём QUIK время на обновление
                    continue

                # Проверяем торговое время — если вне окна, останавливаемся
                # Проверяем только при активном соединении
                is_time_ok = check_time(qp)
                if not is_time_ok:
                    time_check_failures += 1
                    # Выходим только после 3 неудачных проверок (защита от ложных срабатываний)
                    if time_check_failures >= 3:
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Торговое время завершено. Остановка робота.")
                        break
                    else:
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Предупреждение: не удалось проверить время (попытка {time_check_failures}/3). Ожидание...")
                        time.sleep(POLL_MS * 5)
                        continue
                else:
                    # Время проверено успешно — сбрасываем счётчик
                    time_check_failures = 0

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
                    continue

                if check_time(qp):
                    cur_pos = get_current_position(qp)
                    current_price = get_current_price(qp)
                    orders = find_active_orders(qp)

                    # Если базовая цена равна 0 — не торгуем, ждём установки корректной цены
                    if base_price == 0:
                        time.sleep(POLL_MS)
                        continue

                    # Проверяем режим работы: закрытие прибыли или сетка
                    need_grid, close_position, pos_closed = check_base_price_by_grid(qp, current_price)
                    
                    if pos_closed:
                        # Позиция закрыта (только при запуске) — выставляем сетку
                        set_grid(qp, base_price)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка выставлена после закрытия позиции")
                    elif close_position:
                        # Заявка на закрытие выставлена — проверяем исполнение
                        if cur_pos == 0:
                            # Позиция закрылась — обновляем базовую цену и выставляем сетку
                            trade_price = get_last_trade_price(qp)
                            if trade_price is not None:
                                base_price = trade_price
                                write_in_file(base_price)
                                print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Заявка на закрытие исполнилась. Новая базовая цена: {base_price}")
                            set_grid(qp, base_price)
                            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка выставлена после исполнения заявки")
                        # else: продолжаем ждать исполнения
                    elif need_grid:
                        # Цена в канале — проверяем, есть ли заявки
                        if len(orders) == 0:
                            # Заявок нет — выставляем сетку
                            set_grid(qp, base_price)
                            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка выставлена/восстановлена")
                        # else: заявки уже есть — ничего не делаем
                    # else: цена вне канала — ждём возврата, ничего не делаем
                        
                    # Проверяем, не изменилась ли позиция (уровень сетки исполнился)
                    if check_position_change_and_update(cur_pos) and check_levels_executed(cur_pos, qp):
                        # Уровень сетки исполнился — переставляем сетку
                        set_grid(qp, base_price)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Сетка переставлена. Базовая цена: {base_price}\n")
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
