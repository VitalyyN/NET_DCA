-- ==========================================================
-- GridBot v2.1 — tracked orders, safe sync, correct grid logic
-- - respects existing open positions (state.trades)
-- - does not re-place open orders on already-opened levels
-- - cancels only necessary orders sequentially
-- ==========================================================

CONFIG = {
    CLASS = "SPBFUT",
    SECCODE = "SRZ5",
    ACCOUNT = "SPBFUT000e8",
    CLIENT_CODE = "",
    LOT_PER_LEVEL = 3,
    LEVELS = 3,
    GRID_STEP = 5,
    MAX_LOTS_TOTAL = 30,
    START_TIME = "10:00",
    END_TIME = "23:45",
    POLL_MS = 1000,
    PRICE_STEP = 0,
}

-- STATE
local state = {
    base_price = nil,
    last_price_in_deal = 0,
    direction = nil,            -- "B" or "S" or nil
    last_trades_in_first_level = {},        -- array of last trades in first level { {price, qty, dir}, ... } 
    changed = true,
    position = 0,
    orders = {},                -- {order_num, price}
}

local isRunning = true
local trans_id = 0
local tbl_id = nil

-- ================= UTIL =================

local function log(msg)
    message("[GridBot_" .. CONFIG.SECCODE .. "] " .. tostring(msg))
end

local function get_price_step()
    if tonumber(CONFIG.PRICE_STEP) and CONFIG.PRICE_STEP > 0 then return CONFIG.PRICE_STEP end
    local res = getParamEx(CONFIG.CLASS, CONFIG.SECCODE, "SEC_PRICE_STEP")
    if res and res.param_value and tonumber(res.param_value) then
        CONFIG.PRICE_STEP = tonumber(res.param_value)
        return CONFIG.PRICE_STEP
    end
    CONFIG.PRICE_STEP = tonumber(CONFIG.GRID_STEP) or 1
    return CONFIG.PRICE_STEP
end

local function round_price_to_tick(price)
    local tick = get_price_step() or 1
    if not price or tick == 0 then return price end
    return math.floor(price / tick + 0.5) * tick
end

local function round_to_grid(price)
    local step = tonumber(CONFIG.GRID_STEP) or 1
    if not price then return nil end
    return math.floor(price / step + 0.5) * step
end

local function get_last_price()
    local p = getParamEx(CONFIG.CLASS, CONFIG.SECCODE, "LAST")
    if p and p.param_value and p.param_value ~= "" then
        local v = tonumber(p.param_value)
        if v and v > 0 then return v end
    end
    local b = getParamEx(CONFIG.CLASS, CONFIG.SECCODE, "BID")
    local a = getParamEx(CONFIG.CLASS, CONFIG.SECCODE, "OFFER")
    local bid = (b and b.param_value and tonumber(b.param_value)) or 0
    local ask = (a and a.param_value and tonumber(a.param_value)) or 0
    if bid > 0 and ask > 0 then return (bid + ask) / 2 end
    return nil
end

local function in_trading_time()
    local t = os.date("*t")
    local now = string.format("%02d:%02d", t.hour, t.min)
    return now >= CONFIG.START_TIME and now <= CONFIG.END_TIME
end

local function price_key(p) return string.format("%.0f", tonumber(p) or 0) end


-- ================= TRANSACTIONS =================

local function sendLimitOrder(operation, price, lot)
    trans_id = trans_id + 1
    local price_ok = tostring(round_price_to_tick(price))
    local lot_ok = math.floor(tonumber(lot) or 0)
    if lot_ok <= 0 then return nil, "lot==0" end

    local tr = {
        ['TRANS_ID']   = tostring(trans_id),
        ['ACCOUNT']    = CONFIG.ACCOUNT,
        ['CLASSCODE']  = CONFIG.CLASS,
        ['SECCODE']    = CONFIG.SECCODE,
        ['ACTION']     = 'NEW_ORDER',
        ['TYPE']       = 'L',
        ['OPERATION']  = operation,
        ['PRICE']      = string.format("%.0f", price_ok),
        ['QUANTITY']   = tostring(lot_ok),
        ['CLIENT_CODE']= tostring("")
    }

    local res = sendTransaction(tr)
    if res and res ~= "" then
        message("sendLimitOrder(): Error: " .. tostring(res))
        return nil, res
    end
end

local function sendKillOrder(order_key)
    if not order_key then return false, "no_key" end
    trans_id = trans_id + 1
    local tr = {
        ['TRANS_ID'] = tostring(trans_id),
        ['ACTION'] = "KILL_ORDER",
        ['CLASSCODE'] = CONFIG.CLASS,
        ['SECCODE'] = CONFIG.SECCODE,
        ['ORDER_KEY'] = tostring(order_key)
    }
    local res = sendTransaction(tr)
    if res and res ~= "" then
        message("sendKillOrder(): Error: " .. tostring(res))
        return false, res
    end
    return true, nil
end

-- cancel provided keys sequentially, remove from local map immediately to avoid repeated kills
local function cancel_orders(delete_order_last)
    if delete_order_last then
        for i = #state.orders, 1, -1 do
            local order = state.orders[i]
            local success, err = pcall(sendKillOrder, order.order_num)
            if not success then
                log("sendKillOrder() threw: " .. tostring(err))
                -- remove local tracking immediately to avoid repeated attempts
            end
            table.remove(state.orders, i)
        end
    else
        for i = #state.orders, 1, -1 do
            local order = state.orders[i]
            local price = order.price
            if price ~= state.last_price_in_deal then
                local success, err = pcall(sendKillOrder, order.order_num)
                if not success then
                    log("sendKillOrder() threw: " .. tostring(err))
                    -- remove local tracking immediately to avoid repeated attempts
                end
                table.remove(state.orders, i)
            end
        end
    end
end

-- ================= CORE: desired-building & sync =================

local function set_orders_by_table(orders)
    for _, order in ipairs(orders) do
        message("set_orders_by_table(): " .. order.operation .. " " .. order.price .. " " .. order.qty)
        sendLimitOrder(order.operation, order.price, order.qty)
    end
end

local function set_grid_orders_initial()
    if #state.last_trades_in_first_level == 0 then
        local last = get_last_price()
        state.base_price = round_to_grid(last)
    end
    for i=1, CONFIG.LEVELS do
        local price_buy = state.base_price - CONFIG.GRID_STEP * i
        local price_sell = state.base_price + CONFIG.GRID_STEP * i
        local qty = CONFIG.LOT_PER_LEVEL
        sendLimitOrder("B", price_buy, qty)
        sendLimitOrder("S", price_sell, qty)
    end
end

local function set_grid_orders_on_trades()
    -- Определяем направление из первой позиции
    local dir = state.direction
    local orders = {}

    if dir == "B" then
        for i=1, CONFIG.LEVELS do
            if i == 1 and #state.last_trades_in_first_level > 0 then
                local price_sell = state.last_trades_in_first_level[1].price + CONFIG.GRID_STEP
                local qty = state.last_trades_in_first_level[1].qty
                table.insert(orders, { operation = "S", price = price_sell, qty = qty })
                local price_buy = state.base_price - CONFIG.GRID_STEP * i
                table.insert(orders, { operation = "B", price = price_buy, qty = qty })
            else
                local price_sell = state.base_price + CONFIG.GRID_STEP * i
                table.insert(orders, { operation = "S", price = price_sell, qty = CONFIG.LOT_PER_LEVEL })
                local price_buy = state.base_price - CONFIG.GRID_STEP * i
                table.insert(orders, { operation = "B", price = price_buy, qty = CONFIG.LOT_PER_LEVEL })
            end
        end

    elseif dir == "S" then
        for i=1, CONFIG.LEVELS do
            if i == 1 and #state.last_trades_in_first_level > 0 then
                local price_buy = state.last_trades_in_first_level[1].price - CONFIG.GRID_STEP
                local qty = state.last_trades_in_first_level[1].qty
                table.insert(orders, { operation = "B", price = price_buy, qty = qty })
                local price_sell = state.base_price + CONFIG.GRID_STEP * i
                table.insert(orders, { operation = "S", price = price_sell, qty = qty })
            else
                local price_buy = state.base_price - CONFIG.GRID_STEP * i
                table.insert(orders, { operation = "B", price = price_buy, qty = CONFIG.LOT_PER_LEVEL })
                local price_sell = state.base_price + CONFIG.GRID_STEP * i
                table.insert(orders, { operation = "S", price = price_sell, qty = CONFIG.LOT_PER_LEVEL })
            end
        end
    end
    set_orders_by_table(orders)
end

local function set_grid_orders()
    message(tostring(#state.trades))
    if #state.trades == 0 then
        if #state.orders > 0 then cancel_orders(true) end
        set_grid_orders_initial()
        return
    end
    if #state.orders > 0 then cancel_orders(false) end
    set_grid_orders_on_trades()
end

-- ================= TRADES AND ORDERS MANAGEMENT =================

local function delete_orders_from_table(price)
    for i = #state.orders, 1, -1 do
        if state.orders[i].price == price then
            table.remove(state.orders, i)
        end
    end
end

local function add_open_trade(price, qty)
    price = math.floor(tonumber(price) or 0)
    qty = math.floor(tonumber(qty) or 0)

    if qty >= CONFIG.LOT_PER_LEVEL then
        delete_orders_from_table(price)
        state.base_price = price
        state.last_trades_in_first_level = {}
    else
        if #state.last_trades_in_first_level >= 0 then
            if math.abs(state.last_trades_in_first_level[1].price - price) < 1e-6 then
                state.last_trades_in_first_level[1].qty = state.last_trades_in_first_level[1].qty + qty
                if state.last_trades_in_first_level[1].qty >= CONFIG.LOT_PER_LEVEL then
                    delete_orders_from_table(price)
                    state.last_trades_in_first_level = {}
                    state.base_price = price
                end
            end
        else
            table.insert(state.last_trades_in_first_level, { price = price, qty = qty})
        end
    end
end

local function reduce_or_remove_open_trades(close_price, close_qty, close_side)
    close_price = math.floor(tonumber(close_price) or 0)
    close_qty = math.floor(tonumber(close_qty) or 0)

    local step = CONFIG.GRID_STEP
    local target_open_price = (close_side == "B") and (close_price + step) or (close_price - step)
    
    for i = #state.trades, 1, -1 do
        local t = state.trades[i]
        if math.abs(t.price - target_open_price) < 1e-6 and t.dir ~= close_side then
            t.qty = t.qty - close_qty
            if t.qty <= 0 then
                state.base_price = t.price
                table.remove(state.trades, i)
                delete_orders_from_table(t.price)
            end  -- выходим после обработки одной позиции
            return
        end
    end
end

-- ================= CALLBACKS =================

local band = require("bit").band

local function get_trade_side(flags)
    if not flags then return nil end
    if band(flags, 4) ~= 0 then
        return "S"  -- продажа
    else
        return "B"  -- покупка
    end
end

local function check_order_in_table(order_num)
    for _, order in ipairs(state.orders) do
        if order.order_num == order_num then
            return true
        end
    end
    return false
end

local function add_position(qty, dir)
    if dir == "B" then
        state.position = state.position + qty
    else
        state.position = state.position - qty
    end
end

local function reduce_position(qty, dir)
    if dir == "B" then
        state.position = state.position - qty
    else
        state.position = state.position + qty
    end
end

function OnInit()
    init_table()
    log("GridBot_" .. CONFIG.SECCODE .. " Started")
    return 1
end

function OnOrder(order)
    if not order then return end
    if order.seccode ~= CONFIG.SECCODE then return end

    local order_num = order.order_num
    local price = tonumber(order.price)
    if not price then return end
    if check_order_in_table(order_num) then return end
    table.insert(state.orders, {order_num = order_num, price = price})
end

function OnTrade(trade)
    if not trade then return end
    if trade.seccode ~= CONFIG.SECCODE then return end

    local qty = tonumber(trade.qty)
    local price = tonumber(trade.price)
    if not price or price == 0 or qty == 0 then return end

    local flags = tonumber(trade.flags)
    local side = get_trade_side(flags)

    if not state.direction then  -- если первая сделка, запоминаем направление
        state.direction = side
        state.last_price_in_deal = price
        add_open_trade(price, qty)
        add_position(qty, side)
    elseif state.direction ~= side then  -- если сделка звкрывающая, уменьшаем размер позиции на уровне или удаляем уровень
        reduce_or_remove_open_trades(price, qty, side)
        if #state.trades == 0 then state.direction = nil end
        reduce_position(qty, side)
    else -- если сделка открывающая
        add_open_trade(price, qty)
        state.last_price_in_deal = price
        add_position(qty, side)
    end
    state.changed = true
end

function OnStop()
    isRunning = false
    log("Stopping GridBot — cancelling active orders")
    -- cancel only tracked orders sequentially
    cancel_orders(true)
    if tbl_id and not IsWindowClosed(tbl_id) then DestroyTable(tbl_id) end
    log("GridBot stopped")
    return 1
end

-- ================= TABLE =================

function init_table()
    if tbl_id and not IsWindowClosed(tbl_id) then DestroyTable(tbl_id) end
    tbl_id = AllocTable()
    AddColumn(tbl_id, 0, "Param", true, QTABLE_STRING_TYPE, 18)
    AddColumn(tbl_id, 1, "Value", true, QTABLE_STRING_TYPE, 48)
    CreateWindow(tbl_id)
    SetWindowCaption(tbl_id, "GridBot_" .. CONFIG.SECCODE)
    SetWindowPos(tbl_id, 20, 130, 230, 350)

    local params = { "Time", "Instrument", "BasePrice", "Direction", "OpenLevels", "Position", "GridStep", "Levels", "LotPerLevel", "Num_Orders_In_Tbl" }
    for i = 1, #params do
        InsertRow(tbl_id, -1)
        SetCell(tbl_id, i-1, 0, tostring(params[i]))
        SetCell(tbl_id, i-1, 1, "")
    end
end

local function format_trades()
    if not state.trades or #state.trades == 0 then return "-" end
    local parts = {}
    for _, t in ipairs(state.trades) do
        parts[#parts+1] = string.format("%.0f(%s,%d)", t.price, t.dir, t.qty)
    end
    return table.concat(parts, "; ")
end

local function draw_table()
    if not tbl_id then return end
    SetCell(tbl_id, 0, 1, os.date("%H:%M:%S"))
    SetCell(tbl_id, 1, 1, tostring(CONFIG.SECCODE))
    SetCell(tbl_id, 2, 1, tostring(state.base_price or "-"))
    SetCell(tbl_id, 3, 1, tostring(state.direction or "-"))
    SetCell(tbl_id, 4, 1, tostring(format_trades()))
    SetCell(tbl_id, 5, 1, tostring(state.position or 0))
    SetCell(tbl_id, 6, 1, tostring(CONFIG.GRID_STEP))
    SetCell(tbl_id, 7, 1, tostring(CONFIG.LEVELS))
    SetCell(tbl_id, 8, 1, tostring(CONFIG.LOT_PER_LEVEL))
    SetCell(tbl_id, 9, 1, tostring(#state.orders))
end

-- ================= MAIN =================

function main()
    math.randomseed(os.time())
    message("GridBot " .. CONFIG.SECCODE .. " Is Running")

    -- align GRID_STEP to tick
    get_price_step()

    local last = get_last_price()
    if not last then
        message("GridBot: cannot read instrument price")
        return
    end

    if not state.base_price then
        state.base_price = round_to_grid(last)
        state.initial_base = state.base_price
        log("Initial base set to " .. tostring(state.base_price))
    end

    while isRunning do
        if in_trading_time() then
            if state.changed then
                set_grid_orders()
                state.changed = false
            end
            pcall(draw_table)
        end
        sleep(CONFIG.POLL_MS)
    end
end
