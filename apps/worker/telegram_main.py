"""Dedicated Telegram updates listener entrypoint."""
from worker.telegram_bot import start_telegram_bot_listener


if __name__ == "__main__":
    start_telegram_bot_listener()
