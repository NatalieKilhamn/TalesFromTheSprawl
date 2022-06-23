from configobj import ConfigObj
import datetime
import discord

from custom_types import PostTimestamp, ChannelIdentifier
from common import all_categories, personal_category_base, shops_category_name, chats_category_base, off_category_name, public_open_category_name, shadowlands_category_name, groups_category_name, announcements_category_name, gm_announcements_name, setup_category_name, testing_category_name

import actors
import server
import asyncio
import players

### Module channels.py
# This module tracks and handles state related to channels

public_anon_channel_name = 'anon'

channel_id_index = '___channel_id'
last_poster_index = '___last_poster'
last_full_post_index = '___last_full_post_time'
post_counter_index = '___post_counter'

slowmode_delay : int = 2

# Channel state: this is the state of the channel, independent of the handles used in it.

channel_states = ConfigObj('channel_states.conf')


### Utilities:

def clickable_channel_ref(discord_channel):
    return clickable_channel_id_ref(discord_channel.id)

def clickable_channel_id_ref(channel_id : str):
    return f'<#{channel_id}>'

def is_offline_channel(discord_channel):
    if discord_channel.category == None:
        return True
    else:
        return discord_channel.category.name == off_category_name

def is_public_channel(discord_channel):
    if discord_channel.category == None:
        return False
    else:
        return discord_channel.category.name == public_open_category_name

def is_announcement_channel(discord_channel):
    if discord_channel.category == None:
        return False
    else:
        return discord_channel.category.name == announcements_category_name

def is_chat_channel(discord_channel):
    if discord_channel.category == None:
        return False
    else:
        return discord_channel.category.name.startswith(chats_category_base)

def is_personal_channel(discord_channel, channel_suffix : str=None):
    return is_category_channel(discord_channel, personal_category_base, channel_suffix)

def is_group_channel(discord_channel, channel_suffix : str=None):
    return is_category_channel(discord_channel, groups_category_name, channel_suffix)

def is_category_channel(discord_channel, category_name : str, channel_suffix : str=None):
    if discord_channel.category == None:
        return False
    else:
        if discord_channel.category.name.startswith(category_name):
            if channel_suffix is None:
                return True
            else:
                return discord_channel.name.endswith(channel_suffix)



# TODO: allow for "manual shops",
# e.g. channels under shops_category_name that are nonetheless handled just like public_open_category_name

def is_shop_channel(discord_channel):
    if discord_channel.category == None:
        return False
    else:
        return discord_channel.category.name == shops_category_name

def is_pseudonymous_channel(discord_channel):
    if discord_channel.category == None:
        return False
    else:
        return discord_channel.category.name in [public_open_category_name, shadowlands_category_name, groups_category_name]

def is_anonymous_channel(discord_channel):
    return discord_channel.name == public_anon_channel_name

def set_channel_id(channel_name : str, ident : ChannelIdentifier):
    channel_states[channel_name][channel_id_index] = ident.to_string()
    channel_states.write()

def get_channel_id(channel_name : str):
    return ChannelIdentifier.from_string(channel_states[channel_name][channel_id_index])

def get_discord_channel_from_name(guild, channel_name : str):
    ident : ChannelIdentifier = get_channel_id(channel_name)
    if ident.discord_channel_id != None:
        return guild.get_channel(ident.discord_channel_id)
    else:
        raise RuntimeError(f'Tried to find discord channel but channel_id missing: {ident.to_string()}')

def get_discord_channel(channel_id : str):
    guild = server.get_guild()
    return guild.get_channel(int(channel_id))


async def delete_discord_channel(channel_id : str):
    guild = server.get_guild()
    channel = guild.get_channel(int(channel_id))
    if channel is not None:
        await channel.delete()


# TODO: idea: a "do actions muted" function, that would remove all non-system permissions, do action (callable?) and then re-add them
# To avoid notifications

### Common init functions:


async def init():
    for elem in channel_states:
        del channel_states[elem]
    channel_states.write()

    task_list_categories = (asyncio.create_task(verify_category_exists(cat, channels)) for cat, channels in all_categories)
    await asyncio.gather(*task_list_categories)

    channel_list = await server.get_all_channels()

    for c in channel_list:
        print("Setting roles for %s" % c.name)
        await init_discord_channel(c)


async def init_discord_channel(discord_channel):
    if discord_channel.type in [discord.ChannelType.category, discord.ChannelType.voice]:
        # No need to do anything for the categories themselves or the voice channels
        return

    if discord_channel.category != None:
        if discord_channel.category.name.startswith(personal_category_base):
            await init_private_channel(discord_channel)
        elif discord_channel.category.name == public_open_category_name:
            await init_public_open_channel(discord_channel)
        elif discord_channel.category.name == shops_category_name:
            await init_common_read_only_channel(discord_channel)
        elif discord_channel.category.name == groups_category_name:
            await init_group_channel(discord_channel)
        elif discord_channel.category.name == announcements_category_name:
            if discord_channel.name == gm_announcements_name:
                await init_private_channel(discord_channel, gm_extra_access=True)
            else:
                await init_common_read_only_channel(discord_channel)
        elif discord_channel.category.name == setup_category_name:
            await init_setup_channel(discord_channel)
        elif discord_channel.category.name == testing_category_name:
            await init_private_channel(discord_channel, gm_extra_access=True)


    else:
        print(f'Will not create channel state for channel {discord_channel.name} which has no category')


async def verify_category_exists(category_name: str, channels: list):
    guild = server.get_guild()
    if not category_name in [cat.name for cat in guild.categories]:
        print("Did not find category %s, will create it" % category_name)
        await guild.create_category(category_name)

    category = next((cat for cat in guild.categories if cat.name == category_name), None)
    channels_tasks = (
        asyncio.create_task(verify_channel_exists(category, channel))
        for channel in channels)
    await asyncio.gather(*channels_tasks)

async def verify_channel_exists(category, channel_name: str):
    if not channel_name in [ch.name for ch in category.channels]:
        await category.create_text_channel(channel_name)


async def init_channel_state(discord_channel):
    await discord_channel.edit(slowmode_delay=slowmode_delay)
    channel_name = discord_channel.name
    channel_states[channel_name] = {}
    channel_states.write()
    ident = ChannelIdentifier(discord_channel_id=discord_channel.id)
    set_channel_id(discord_channel.name, ident)    

async def set_base_permissions(discord_channel, private : bool, read_only : bool, gm_extra_access : bool=False):
    add_roles_tasks = (
        [asyncio.create_task(discord_channel.set_permissions(role, overwrite=overwrites))
        for (role, overwrites)
        in server.generate_base_overwrites(private, read_only, gm_extra_access).items()])
    await asyncio.gather(*add_roles_tasks)

async def init_common_read_only_channel(discord_channel, gm_only : bool=False):
    await set_base_permissions(discord_channel, private=gm_only, read_only=True, gm_extra_access=gm_only)
    await init_channel_state(discord_channel)
    init_pseudonymous_channel(discord_channel.name)

async def init_public_open_channel(discord_channel):
    await set_base_permissions(discord_channel, private=False, read_only=False)
    await init_channel_state(discord_channel)
    init_pseudonymous_channel(discord_channel.name)

async def init_private_channel(discord_channel, gm_extra_access : bool=False):
    read_only = is_read_only_private_channel(discord_channel)
    await set_base_permissions(discord_channel, private=True, read_only=read_only, gm_extra_access=gm_extra_access)
    await init_channel_state(discord_channel)

async def init_group_channel(discord_channel):
    await set_base_permissions(discord_channel, private=True, read_only=False, gm_extra_access=True)
    await init_channel_state(discord_channel)
    init_pseudonymous_channel(discord_channel.name)

async def init_setup_channel(discord_channel):
    add_roles_tasks = (
        [asyncio.create_task(discord_channel.set_permissions(role, overwrite=overwrites))
        for (role, overwrites)
        in server.generate_setup_channel_overwrites().items()])
    await asyncio.gather(*add_roles_tasks)
    await init_channel_state(discord_channel)
    await discord_channel.purge()
    await discord_channel.send(generate_setup_channel_welcome_msg())


async def make_read_only(channel_id : str):
    channel = get_discord_channel(channel_id)
    await set_base_permissions(channel, private=True, read_only=True)


### Processing commands in channels
async def pre_process_command(
    ctx,
    allow_cmd_line : bool=True,
    allow_chat_hub : bool=False,
    allow_landing_page : bool=False):
    if is_cmd_line(ctx.channel.name) and allow_cmd_line:
        return True
    if is_chat_hub(ctx.channel.name) and allow_chat_hub:
        return True
    if is_landing_page(ctx.channel.name) and allow_landing_page:
        return True
    await server.swallow(ctx.message, alert=allow_cmd_line);
    return False



### Anonymous channels:

def get_public_anon_channel(guild):
    return get_discord_channel_from_name(guild, public_anon_channel_name)


### Utilities related to pseudonymous channels, i.e. ones where all messages are reposted using handle

def init_pseudonymous_channel(channel_name : str):
    set_last_poster(channel_name, '')
    timestamp : PostTimestamp = PostTimestamp.from_datetime(datetime.datetime.today())
    set_last_full_post(channel_name, timestamp)
    reset_post_counter(channel_name)

def set_last_poster(channel_name : str, poster_id : str):
    channel_states[channel_name][last_poster_index] = poster_id;
    channel_states.write()

def get_last_poster(channel_name : str):
    if not last_poster_index in channel_states[channel_name]:
        return ''
    else:
        return channel_states[channel_name][last_poster_index];

def get_last_post_time(channel_name : str):
    return PostTimestamp.from_string(channel_states[channel_name][last_full_post_index])

def set_last_full_post(channel_name : str, timestamp : PostTimestamp):
    channel_states[channel_name][last_full_post_index] = timestamp.to_string()
    channel_states.write()

def time_has_passed_since_last_full_post(channel_name : str, timestamp):
    post_time = PostTimestamp(timestamp.hour, timestamp.minute)
    old_time = get_last_post_time(channel_name)
    if post_time != old_time:
        return True
    else:
        return False

def increment_post_counter(channel_name : str):
    count = int(channel_states[channel_name][post_counter_index])
    count += 1
    channel_states[channel_name][post_counter_index] = str(count)
    channel_states.write()
    return count >= 10

def reset_post_counter(channel_name : str):
    channel_states[channel_name][post_counter_index] = str(0)
    channel_states.write()

# Returns True if the new post should be a full post (with sender and timestamp header)
# Returns False if the new post should only include the content itself
def record_new_post(channel_name : str, poster_id : str, timestamp : PostTimestamp):
    last_poster = get_last_poster(channel_name)
    time_has_passed = time_has_passed_since_last_full_post(channel_name, timestamp)
    counter_has_passed_limit = increment_post_counter(channel_name)

    if last_poster != poster_id or time_has_passed or counter_has_passed_limit:
        set_last_poster(channel_name, poster_id)
        set_last_full_post(channel_name, timestamp)
        reset_post_counter(channel_name)
        return True
    else:
        return False


### Private channels:
# Only visible to some players

async def create_discord_channel(guild, overwrites, channel_name : str, category_name : str):
    category = discord.utils.find(lambda cat: cat.name == category_name, guild.channels)
    channel = await guild.create_text_channel(
        channel_name,
        overwrites=overwrites,
        category=category,
        slowmode_delay=slowmode_delay
    )
    await init_channel_state(channel)
    return channel


### Personal channels: completely belonging to and owned by one player

cmd_line_base = 'cmd_line_'
finance_base = 'finance_'
daemon_base = 'daemon_'
chat_hub_base = 'chat_hub_'
order_flow_base = 'orders_'

# TODO: some sort of dictionary for these, with an enum type

async def delete_all_personal_channels(channel_suffix : str=None):
    channels_list = await get_all_personal_channels(channel_suffix)
    task_list = (asyncio.create_task(c.delete()) for c in channels_list)
    await asyncio.gather(*task_list)

async def get_all_personal_channels(channel_suffix : str=None):
    channel_list = await server.get_all_channels()
    return [c for c in channel_list if is_personal_channel(c, channel_suffix)]

async def get_all_chat_hub_channels(channel_suffix : str=None):
    channel_list = await server.get_all_channels()
    def is_match(channel_name : str):
        return is_chat_hub(channel_name) and (channel_suffix is None or channel_name.endswith(channel_suffix))
    return [c for c in channel_list if is_match(c.name)]

async def create_personal_channel(guild, role, channel_name : str, actor_id : str, read_only : bool=False):
    overwrites = server.generate_overwrites_own_new_private_channel(role, read_only)
    if actor_id.startswith("u27"):
        category_index = players.get_player_category_index(actor_id)
    else:
        print("Using default category index 6 for non-player %s" % actor_id)
        category_index = 6
    category_name = "%s%d" % (personal_category_base, category_index)
    return await create_discord_channel(guild, overwrites, channel_name, category_name)

async def create_group_channel(guild, role, channel_name : str, read_only : bool=False):
    overwrites = server.generate_overwrites_own_new_private_channel(role, read_only)
    channel = await create_discord_channel(guild, overwrites, channel_name, groups_category_name)
    await init_group_channel(channel)
    return channel

async def create_order_flow_channel(guild, role, shop_name : str):
    discord_channel_name = get_order_flow_name(shop_name)
    return await create_personal_channel(guild, role, discord_channel_name, shop_name)


def get_cmd_line_name(player_id : str):
    return cmd_line_base + player_id

def is_cmd_line(channel_name : str):
    return channel_name.startswith(cmd_line_base)


def get_finance_name(actor_id : str):
    return finance_base + actor_id

def is_finance(channel_name : str):
    return channel_name.startswith(finance_base)


def get_chat_hub_name(actor_id : str):
    return chat_hub_base + actor_id

def is_chat_hub(channel_name : str):
    return channel_name.startswith(chat_hub_base)


def get_order_flow_name(shop_name : str):
    return order_flow_base + shop_name

def is_order_flow(channel_name : str):
    return channel_name.startswith(order_flow_base)

def is_announcement(channel_name : str):
    return channel_name.endswith(order_flow_base)

# Some of the private channels (not available to all players) are read-only
def is_read_only_private_channel(channel):
    return is_finance(channel.name) or is_order_flow(channel.name) or is_announcement_channel(channel)


### Group channels:

async def delete_all_group_channels(channel_suffix : str=None):
    channels_list = await get_all_groups_channels(channel_suffix)
    task_list = (asyncio.create_task(c.delete()) for c in channels_list)
    await asyncio.gather(*task_list)

async def get_all_groups_channels(channel_suffix : str=None):
    channel_list = await server.get_all_channels()
    return [c for c in channel_list if is_group_channel(c, channel_suffix)]



### Chat channels:
# These are weird: the "channel" is not the discord channel, but rather a name that can be used to fetch one or more channels
# from the chats.py module

def init_chat_channel(channel_name : str):
    channel_states[channel_name] = {}
    channel_states.write()
    init_pseudonymous_channel(channel_name)
    ident = ChannelIdentifier(chat_channel_name=channel_name)
    set_channel_id(channel_name, ident)

async def create_chat_session_channel_no_role(guild, discord_channel_name : str, read_only : bool=False, category_index : int=0):
    base_overwrites = server.generate_base_overwrites(private = True, read_only = read_only)
    return await create_discord_channel(guild, base_overwrites, discord_channel_name, "%s%d" % (chats_category_base, category_index))

async def delete_all_chats():
    channel_list = await get_all_chat_channels()
    task_list = (asyncio.create_task(c.delete()) for c in channel_list)
    await asyncio.gather(*task_list)

async def get_all_chat_channels():
    channel_list = await server.get_all_channels()
    return [c for c in channel_list if is_chat_channel(c)]


### Shop channels:
# These are public (open to all players) but read-only
# The idea is that the channel holds the menu items as messages, and players can react to place their orders

async def create_shop_channel(guild, channel_name : str):
    overwrites = server.generate_base_overwrites(private = False, read_only = True)
    return await create_discord_channel(guild, overwrites, channel_name, shops_category_name)

async def delete_all_shops():
    channel_list = await get_all_shop_related_channels()
    task_list = (asyncio.create_task(c.delete()) for c in channel_list)
    await asyncio.gather(*task_list)

async def get_all_shop_related_channels():
    channel_list = await server.get_all_channels()
    return [c for c in channel_list if is_shop_channel(c) or is_order_flow(c.name)]


### Landing page channel

landing_page = 'landing_page'

def is_landing_page(channel_name : str):
    return channel_name == landing_page

def generate_setup_channel_welcome_msg():
    content = 'Welcome to the in-game matrix system! In order to join the game, you must select your first **handle**. '
    content += 'Your starting money, access to private networks etc. are tied to this.\n\n'
    content += 'To select your handle, type \"**.join** *handle*\" below.\n'
    content += 'For example, if you are shadow_weaver, type \".join shadow_weaver\"\n\n'
    content += 'If you are not sure what your main handle is, please contact the organizers.\n'
    content += '==============================='
    return content