# bot.py
import os
import discord
import asyncio
import re

from discord.ext import commands
from dotenv import load_dotenv

# Custom imports
import handles
import channels
import posting
import reactions
import actors
import players
import finances
import chats
import server
import shops
import groups
import game
import artifacts
import gm
import logger


load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
guild_name = os.getenv('GUILD_NAME')

intents = discord.Intents.default()
intents.members = True

logger.setup_command_logger()

# Change only the no_category default string
help_command = commands.DefaultHelpCommand(
    no_category = 'Commands'
)
bot = commands.Bot(
    command_prefix='.',
    intents=intents,
    help_command = help_command
)

# Below cogs represents our folder our cogs are in. Following is the file name. So 'meme.py' in cogs, would be cogs.meme
# Think of it like a dot path import
initial_extensions = ['handles', 'finances', 'admin', 'chats', 'shops', 'gm', 'artifacts']

# Here we load our extensions(cogs) listed above in [initial_extensions].
if __name__ == '__main__':
    for extension in initial_extensions:
        bot.load_extension(extension)

@bot.event
async def on_ready():
    global guild_name
    clear_all = (os.getenv('CLEAR_ALL') == 'true')
    # TODO: move some of the initialisation to the cogs instead
    await server.init(bot.guilds)
    await handles.init(clear_all)
    await actors.init(clear_all=clear_all)
    await players.init(clear_all=clear_all)
    await channels.init()
    finances.init_finances()
    await chats.init(clear_all=clear_all)
    await shops.init(clear_all=clear_all)
    await groups.init(clear_all=clear_all)
    reactions.init()
    artifacts.init(clear_all=clear_all)
    await gm.init(clear_all=clear_all)
    game.init()
    print('Initialization complete.')
    report = game.start_game()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.BadArgument) and 'Converting to "int" failed for parameter "amount"' in str(error):
        await ctx.send("Error: amount must be an integer greater than 0.")
    elif isinstance(error, commands.errors.BadArgument) and 'Converting to "int" failed for parameter "price"' in str(error):
        await ctx.send("Error: price must be an integer greater than 0.")
    elif isinstance(error, commands.errors.CommandNotFound):
        await ctx.send("Error: that is not a known command.")
    else:
        await ctx.send("Error: unknown system error. Contact administrator.")
        raise(error)

# General message processing (reposting for anonymity/pseudonymity)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        # Never react to bot's own message to avoid loops
        return

    if channels.is_offline_channel(message.channel):
        # No bot shenanigans in the off channel
        return

    try:
        player_name = players.get_player_id(message.author.id, False)
        logger.log_command(message.author.id, player_name, message.channel.name, message.content)
    except:
        print("Failed to log command to file")

    # "Off messages" means starting and replying to chats with GM and similar
    only_off_messages = not game.can_process_messages()
    #await server.swallow(message, alert=False)
    #return

    if channels.is_cmd_line(message.channel.name):
        if only_off_messages and not has_chat_command(message):
                await server.swallow(message, alert=False)
                return
        await bot.process_commands(message)
        return

    if channels.is_chat_hub(message.channel.name) or channels.is_landing_page(message.channel.name):
        if only_off_messages and not has_chat_command(message):
                await server.swallow(message, alert=False)
                return
        # TODO: fix custom help command to avoid this hack
        # The .help command does not discern between channels, so we must check for it specifically since
        # we want it to work in cmd_line but not in chat_hub
        if has_help_command(message):
            should_alert = not channels.is_landing_page(message.channel.name)
            await server.swallow(message, alert=should_alert)
        else:
            # All our commands know if they are usable in chat hub or not, and will handle the message accordingly
            # TODO: not all commands actually know this
            await bot.process_commands(message)
        return

    # Trying a command in any other channel gets it swallowed:
    if has_any_command(message):
        await server.swallow(message, alert=True)
        return

    if only_off_messages:
        # Only chats with certain handles are okay
        allowed = channels.is_chat_channel(message.channel) and game.is_out_of_game_chat(message.channel)
        if not allowed:
            await server.swallow(message, alert=False)
            return

    alert_checking = asyncio.create_task(game.check_alerts(message.content, message.channel, str(message.author.id)))
    processing = asyncio.create_task(process_message(message))
    await asyncio.gather(alert_checking, processing)



async def process_message(message):
    if channels.is_anonymous_channel(message.channel):
        await posting.process_open_message(message, True)
        return

    if channels.is_pseudonymous_channel(message.channel):
        await posting.process_open_message(message)

    if channels.is_chat_channel(message.channel):
        await chats.process_message(message)   


def has_any_command(message):
    alphanumeric_regex = re.compile(f'^\.[a-z]+')
    matches = re.search(alphanumeric_regex, message.content)
    return matches is not None

def has_help_command(message):
    help_regex = re.compile(f'^\.help')
    matches = re.search(help_regex, message.content)
    return matches is not None

def has_chat_command(message):
    chat_regex = re.compile(f'^\.chat')
    matches = re.search(chat_regex, message.content)
    if matches is not None:
        return True
    chat_regex = re.compile(f'^\.gm_chat')
    matches = re.search(chat_regex, message.content)
    return matches is not None

# General reaction handling

@bot.event
async def on_raw_reaction_add(payload):
    channel = await bot.fetch_channel(payload.channel_id)
    if payload.user_id == bot.user.id:
        # Don't act on bot's own reactions to avoid loops
        return

    if channels.is_offline_channel(channel):
        # No bot shenanigans in the off channels
        return

    await reactions.process_reaction_add(payload.message_id, payload.user_id, channel, payload.emoji)

# New players

@bot.event
async def on_member_join(member):
    # TODO: put the player in a special setup area, and force them to join (claim a handle) before they can continue
    await server.set_user_as_new_player(member)
    #return await players.create_player(member)



bot.run(TOKEN)
