# -*- coding: utf-8 -*-
from telethon import TelegramClient, events
import asyncio
import logging
from telethon.tl.types import Channel, User, Chat
from telethon.errors import RPCError
# NEW IMPORT for date filtering
from datetime import datetime, timedelta, timezone 

# Set up logging for better visibility
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
# IMPORTANT: Replace with your actual credentials.
api_id = 36588825
api_hash = '2ee167d5a23effb6ab1719974855aaef'
client = TelegramClient('session_name', api_id, api_hash)

# --- Automated Task Settings ---
messages_to_send = ["Hi"]
interval_seconds = 900

# --- Control Variables ---
is_running = False
background_task = None

# --- CORE CHAT RESOLUTION LOGIC (MODIFIED FOR SELECTIVE DELETION) ---

async def get_all_user_chats():
    """
    Fetches the list of all private chats with other users.
    MODIFIED: Only includes NON-CONTACT chats whose last message is older than 2 days.
    """
    logger.info("Fetching all dialogs to identify user chats for selective deletion...")
    user_chats = []
    
    # Calculate the time threshold (2 days ago, using UTC for comparison reliability)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    
    try:
        dialogs = await client.get_dialogs(limit=None)
        current_user = await client.get_me()
        user_id_to_exclude = current_user.id if current_user else 0

        for d in dialogs:
            # Check 1: Is it a private User chat?
            if isinstance(d.entity, User) and d.entity.id != user_id_to_exclude:
                
                # Exclude official service accounts (IDs are low, like 777000)
                if d.entity.id < 1000000:
                    continue

                # Check 2: Is the user NOT a saved contact?
                is_contact = getattr(d.entity, 'contact', False)
                
                # Check 3: Is the last message older than 2 days?
                # Ensure d.date has timezone info (replace with UTC if missing) for accurate comparison
                is_old_chat = d.date and (d.date.replace(tzinfo=timezone.utc) < two_days_ago)

                # Only append if ALL deletion conditions (Non-Contact AND Old) are met
                if not is_contact and is_old_chat:
                    user_chats.append(d.entity)
            
    except Exception as e:
        logger.error(f"Error fetching all dialogs: {e}")
        return []

    return user_chats

# --- Background Messaging Logic (MODIFIED) ---

async def send_scheduled_messages():
    """
    The function that runs in the background when /start is active.
    MODIFIED: Filters for groups/channels with > 20 unread messages.
    """
    global is_running
    
    logger.info("Scheduled messaging task has started.")

    while is_running:
        try:
            logger.info("Fetching the latest list of groups and channels...")
            dialogs = await client.get_dialogs(limit=None)
            
            # --- MODIFIED FILTERING LOGIC (Requirement 1: > 20 unread) ---
            target_chats = [
                d.entity for d in dialogs 
                if (isinstance(d.entity, Channel) or d.is_group) and d.unread_count > 20
            ]
            # --------------------------------

            if not target_chats:
                logger.warning("No groups or channels with > 20 unread messages found to send messages to this cycle.")
            else:
                logger.info(f"Targeting {len(target_chats)} chats for messaging.")

        except Exception as e:
            logger.error(f"Error fetching dialogs: {e}")
            target_chats = []

        # --- Messaging Loop ---
        for chat in target_chats:
            try:
                chat_name = getattr(chat, 'title', f"Chat {chat.id}")
                for msg in messages_to_send:
                    await client.send_message(chat, msg)
                    logger.info(f"Sent message to: {chat_name} ({chat.id})")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Could not send message to {chat_name} ({chat.id}): {e}")
                pass
                
        # --- Interval Sleep and Stop Check ---
        logger.info(f"Scheduled cycle finished. Waiting for {interval_seconds} seconds...")
        for _ in range(interval_seconds):
            if not is_running:
                break
            await asyncio.sleep(1)
            
    logger.info("Scheduled messaging task stopped gracefully.")

# --- Command Handlers ---

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Handles the /start command."""
    global is_running, background_task
    
    if is_running:
        await event.reply('✅ The scheduled messaging is already *running*.')
        return

    is_running = True
    background_task = client.loop.create_task(send_scheduled_messages())
    
    await event.reply('🚀 *Scheduled messaging started!* Messages will be sent periodically to active Groups/Channels.')
    
@client.on(events.NewMessage(pattern='/stop'))
async def stop_handler(event):
    """Handles the /stop command."""
    global is_running, background_task

    if not is_running:
        await event.reply('🛑 The scheduled messaging is already *stopped*.')
        return

    is_running = False
    await asyncio.sleep(2) # Give background task time to finish its sleep cycle
    
    if background_task and not background_task.done():
        background_task.cancel()
    
    await event.reply('⏸ *Scheduled messaging stopped.*')

@client.on(events.NewMessage(pattern='/delete'))
async def delete_all_user_chats_handler(event):
    """
    Handles the /delete command to remove old, non-contact private user chats.
    Now uses revoke=True for two-sided deletion attempt.
    """
    
    # --- SECURITY CHECK ---
    if not event.is_private:
        await event.reply("🚫 **Deletion failed.** The `/delete` command (to delete specific user chats) can only be run in a private chat for security reasons.")
        return
    
    # The string must be fully readable by the interpreter
    await event.reply("**Searching for NON-CONTACT user chats older than 2 days...** Confirm with `/delete confirm` if you are sure to delete these filtered chats. **(Attempting two-sided deletion)**")
    
    # Require a second command for confirmation of mass deletion
    if event.raw_text.lower() != '/delete confirm':
        return

    await event.reply('🔥 **SELECTIVE DELETION INITIATED!** This may take a while...')
    
    # Get the list of filtered user chats (Non-Contact & Old)
    chats_to_delete = await get_all_user_chats()

    if not chats_to_delete:
        await event.reply("🛑 **No user chats found** that meet the criteria (non-contact and older than 2 days).")
        return

    deleted_count = 0
    failed_chats = []
    total_to_delete = len(chats_to_delete)

    await event.reply(f'🗑️ Found **{total_to_delete}** user chats meeting the criteria. Starting **two-sided** deletion...')

    for chat in chats_to_delete:
        chat_name = getattr(chat, 'first_name', f"User {chat.id}")
        
        try:
            # VITAL CHANGE: Added revoke=True to attempt deletion on the other user's side
            await client.delete_dialog(chat.id, revoke=True) 
            logger.info(f"Successfully deleted (revoke=True): {chat_name} ({chat.id})")
            deleted_count += 1
            await asyncio.sleep(0.5) 
        except RPCError as e:
            # Catch specific errors like insufficient permissions
            logger.error(f"RPC Error (Revoke Failed) deleting {chat_name}: {e}")
            failed_chats.append(f"{chat_name} (RPC Error)")
        except Exception as e:
            logger.error(f"Failed to delete chat with {chat_name} ({chat.id}): {e}")
            failed_chats.append(chat_name)
            pass

    # --- Final Report ---
    if failed_chats:
        fail_list = "\n".join(failed_chats)
        report = (
            f'✅ **Selective Deletion Complete!**\n\n'
            f'**Deleted:** {deleted_count}/{total_to_delete} filtered user chats.\n'
            f'**Failed:** {len(failed_chats)} chats. (Often due to Telegram restrictions on two-sided deletion).\n\n'
            f'Failed Chats:\n`{fail_list}`'
        )
    else:
        report = f'🎉 **All Done!** Successfully deleted **{deleted_count}** filtered private user chats (attempted two-sided deletion).'
        
    await event.reply(report)


@client.on(events.NewMessage(pattern='/delete groups'))
async def delete_all_non_user_chats_handler(event):
    """
    Handles the /delete groups command to remove ALL non-user chats (Groups/Channels/Bots) 
    permanently on both sides.
    """
    
    if not event.is_private:
        await event.reply("🚫 **Deletion failed.** This command can only be run in a private chat for security reasons.")
        return

    await event.reply('🔥 **MASS NON-USER CHAT DELETION INITIATED!** This will try to delete Groups/Channels/Bots permanently on both sides (`revoke=True`).')
    
    deleted_count = 0
    failed_chats = []
    
    try:
        dialogs = await client.get_dialogs(limit=None)
        
        # Filter for non-user chats (Channels and Groups)
        chats_to_delete = [
            d.entity for d in dialogs 
            # We target Channels (supergroups/channels) and Chats (basic groups/some bots/service msgs)
            if isinstance(d.entity, (Channel, Chat)) 
        ]
        
        total_to_delete = len(chats_to_delete)
        if total_to_delete == 0:
            await event.reply("🛑 **No non-user chats found** to delete.")
            return

        await event.reply(f'🗑️ Found **{total_to_delete}** non-user chats. Starting permanent deletion...')

        for chat in chats_to_delete:
            # Get title for channels/groups, first_name for bots/users, or a default
            chat_name = getattr(chat, 'title', getattr(chat, 'first_name', f"Chat {chat.id}"))
            
            try:
                # Use revoke=True for permanent, two-sided deletion attempt
                await client.delete_dialog(chat.id, revoke=True)
                logger.info(f"Successfully deleted (revoke=True): {chat_name} ({chat.id})")
                deleted_count += 1
                await asyncio.sleep(0.5) 
            except RPCError as e:
                # Catch specific errors like insufficient permissions to delete for others
                logger.error(f"RPC Error (No Permission/Revoke Failed) deleting {chat_name}: {e}")
                failed_chats.append(f"{chat_name} (RPC Error)")
            except Exception as e:
                logger.error(f"Failed to delete non-user chat {chat_name}: {e}")
                failed_chats.append(chat_name)

        # --- Final Report ---
        if failed_chats:
            fail_list = "\n".join(failed_chats)
            report = (
                f'✅ **Non-User Chat Deletion Complete!**\n\n'
                f'**Deleted:** {deleted_count}/{total_to_delete} non-user chats.\n'
                f'**Failed:** {len(failed_chats)} chats. (Often due to no "delete/revoke" permission).\n\n'
                f'Failed Chats:\n`{fail_list}`'
            )
        else:
            report = f'🎉 **All Done!** Successfully deleted **{deleted_count}** non-user chats.'
            
        await event.reply(report)
        
    except Exception as e:
        logger.critical(f"A fatal error during group deletion occurred: {e}")
        await event.reply(f"❌ **FATAL ERROR:** Check logs. Error: `{e}`")


# --- Main Execution ---
async def main():
    print("Connecting to Telegram...")
    await client.start()
    print("Client is running and listening for commands...")
    # Get the username of the running userbot
    me = await client.get_me()
    print(f"Logged in as: @{me.username} (ID: {me.id})")
    print("Use /start, /stop, /delete confirm, or /delete groups in any chat to control the bot.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shut down by user.")
    except Exception as e:
        logger.critical(f"A fatal error occurred: {e}")