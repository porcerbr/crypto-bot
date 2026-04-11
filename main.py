def check_signal(symbol, prices):

    global last_states
    global last_signal_time
    global last_warning_time

    if len(prices) < EMA_LONG + 2:
        return

    # EMA atual
    ema9 = calculate_ema(prices, EMA_SHORT)
    ema21 = calculate_ema(prices, EMA_LONG)

    # EMA anterior
    ema9_prev = calculate_ema(prices[:-1], EMA_SHORT)
    ema21_prev = calculate_ema(prices[:-1], EMA_LONG)

    if None in [ema9, ema21, ema9_prev, ema21_prev]:
        return

    now_time = time.time()

    state = "BUY" if ema9 > ema21 else "SELL"

    # Distâncias
    dist_now = abs(ema9 - ema21)
    dist_prev = abs(ema9_prev - ema21_prev)

    # Velocidade EMA
    speed_ema9 = ema9 - ema9_prev
    speed_ema21 = ema21 - ema21_prev

    # 🟡 PREVISÃO REAL
    approaching = dist_now < dist_prev

    strong_movement = (
        abs(speed_ema9) > 0.01
        or abs(speed_ema21) > 0.01
    )

    if approaching and strong_movement:

        if now_time - last_warning_time[symbol] > 120:

            now = (
                datetime.now(timezone.utc)
                - timedelta(hours=3)
            ).strftime("%H:%M:%S")

            msg = (
                f"⏳ <b>POSSÍVEL CRUZAMENTO</b>\n\n"
                f"<b>Cripto:</b> {symbol}\n"
                f"<b>EMAs se aproximando</b>\n"
                f"<b>Preparar entrada</b>\n"
                f"<b>Hora:</b> {now}"
            )

            send_telegram(msg)

            last_warning_time[symbol] = now_time

    # 🔵 CRUZAMENTO REAL

    previous = last_states[symbol]

    if now_time - last_signal_time[symbol] < 60:
        return

    if previous is None:
        last_states[symbol] = state
        return

    if state != previous:

        now = (
            datetime.now(timezone.utc)
            - timedelta(hours=3)
        ).strftime("%H:%M:%S")

        emoji = "🟢" if state == "BUY" else "🔴"

        msg = (
            f"{emoji} <b>{state} CONFIRMADO</b>\n\n"
            f"<b>Cripto:</b> {symbol}\n"
            f"<b>Hora:</b> {now}"
        )

        send_telegram(msg)

        last_states[symbol] = state
        last_signal_time[symbol] = now_time
