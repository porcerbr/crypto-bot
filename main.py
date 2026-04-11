def calculate_rsi(prices, period=14):

    if len(prices) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):

        diff = prices[i] - prices[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


def check_signal(prices):

    global last_state
    global last_signal_time
    global last_warning_time

    if len(prices) < EMA_LONG + 15:
        return

    ema9 = calculate_ema(prices, EMA_SHORT)
    ema21 = calculate_ema(prices, EMA_LONG)

    ema9_prev = calculate_ema(prices[:-1], EMA_SHORT)
    ema21_prev = calculate_ema(prices[:-1], EMA_LONG)

    rsi = calculate_rsi(prices[-15:])
    rsi_prev = calculate_rsi(prices[-16:-1])

    if None in [ema9, ema21, ema9_prev, ema21_prev, rsi, rsi_prev]:
        return

    now_time = time.time()

    # Distância entre EMAs
    dist_now = abs(ema9 - ema21)
    dist_prev = abs(ema9_prev - ema21_prev)

    # Velocidade de aproximação
    speed = dist_prev - dist_now

    # 🧠 PREVISÃO 2 CANDLES
    if speed > 0:

        candles_to_cross = dist_now / speed

        if 1 <= candles_to_cross <= 2.5:

            if now_time - last_warning_time > 120:

                now = (
                    datetime.now(timezone.utc)
                    - timedelta(hours=3)
                ).strftime("%H:%M:%S")

                msg = (
                    f"⏳ <b>PREPARAR ENTRADA</b>\n\n"
                    f"Cripto: ETHUSDT\n"
                    f"RSI: {rsi:.1f}\n"
                    f"Cruzamento em ~{candles_to_cross:.1f} candles\n"
                    f"Hora: {now}"
                )

                send_telegram(msg)

                last_warning_time = now_time

    # 🎯 CRUZAMENTO REAL

    state = "BUY" if ema9 > ema21 else "SELL"

    if last_state is None:
        last_state = state
        return

    if now_time - last_signal_time < 60:
        return

    rsi_buy_ok = rsi > 50 and rsi > rsi_prev
    rsi_sell_ok = rsi < 50 and rsi < rsi_prev

    if state != last_state:

        # FILTRO RSI
        if state == "BUY" and not rsi_buy_ok:
            return

        if state == "SELL" and not rsi_sell_ok:
            return

        now = (
            datetime.now(timezone.utc)
            - timedelta(hours=3)
        ).strftime("%H:%M:%S")

        emoji = "🟢" if state == "BUY" else "🔴"

        msg = (
            f"{emoji} <b>{state} CONFIRMADO</b>\n\n"
            f"Cripto: ETHUSDT\n"
            f"RSI: {rsi:.1f}\n"
            f"Hora: {now}"
        )

        send_telegram(msg)

        last_state = state
        last_signal_time = now_time
