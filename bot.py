from telethon import TelegramClient
import asyncio

# --- Configuration ---
api_id = 36588825
api_hash = '2ee167d5a23effb6ab1719974855aaef'
client = TelegramClient('session_name', api_id, api_hash)

messages = ["Hi"]
interval = 3600

async def main_logic():
    await client.start()

    dialogs = await client.get_dialogs()
    groups = [d for d in dialogs if d.is_group ]

    while True:
        for group in groups:
            try:
                for msg in messages:
                    await client.send_message(group.id, msg)
                    await asyncio.sleep(1)
            except Exception:
                pass
        await asyncio.sleep(interval)

async def main():
    await client.start()
    client.loop.create_task(main_logic())
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
