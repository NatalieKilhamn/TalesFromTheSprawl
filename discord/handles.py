import finances
import players
import actors
import chats
import server
#import player_setup
import channels
import game
from common import coin
from custom_types import Handle, HandleTypes, ActionResult

from discord.ext import commands
from configobj import ConfigObj
from typing import List
from enum import Enum
import random
import re
import asyncio

### Module handles.py
# This module tracks and handles state related to handles, e.g. in-game names/accounts that
# players can create.

# TODO: use the same semaphore for handles and .join

class HandlesCog(commands.Cog, name='handles'):
    '''Commands related to handles. 
    Your handle is how you appear to other users in most other channels. 
    Each handle has its own separate finances (see \".help finances\").
    These commands can also be used in your chat hub channel.'''
    def __init__(self, bot):
        self.bot = bot
        self._last_member = None

    # Commands related to handles
    # These work in both cmd_line and chat_hub channels

    @commands.command(
        name='handle',
        brief='Show current handle or switch to another handle.',
        help=(
            'Show current handle, or switch to another handle.\n' +
            'To show current, use \".handle\"\n' +
            'To switch, use \".handle new_handle\"\n'
            'The new handle can either be one you already control, or an unused one which will then be registered to you.'
        )
        )
    async def handle_command(self, ctx, new_handle : str=None):
        await self.handle_command_internal(ctx, new_handle, burner=False)

    @commands.command(name='burner', help='Create a new burner handle or switch to existing burner.')
    async def create_burner_command(self, ctx, new_burner : str=None):
        await self.handle_command_internal(ctx, new_burner, burner=True)

    async def handle_command_internal(self, ctx, new_handle : str=None, burner : bool=False):
        allowed = await channels.pre_process_command(ctx, allow_chat_hub=True)
        if not allowed:
            return
        # Note: this command may edit handles but may also be read-only.
        # The below function will claim handles semaphore if editing is required.
        response = await process_handle_command(ctx, new_handle, burner=burner)
        await self.send_command_response(ctx, response)

    @commands.command(name='handles', help='Show all your handles.')
    async def handles_command(self, ctx):
        allowed = await channels.pre_process_command(ctx, allow_chat_hub=True)
        if not allowed:
            return
        response = await get_full_handles_report(ctx)
        await self.send_command_response(ctx, response)

    @commands.command(name='show_handles', help='Show all handles for another player.', hidden=True)
    @commands.has_role('gm')
    async def show_handles_command(self, ctx, handle_id :str=None):
        allowed = await channels.pre_process_command(ctx, allow_chat_hub=False)
        if not allowed:
            return
        response = await get_full_handles_report_for_handle(handle_id)
        await self.send_command_response(ctx, response)


    @commands.command(name='burn', help='Destroy a burner account forever.')
    async def burn_command(self, ctx, burner_name : str=None):
        allowed = await channels.pre_process_command(ctx, allow_chat_hub=False)
        if not allowed:
            return
        sem_id = await get_semaphore(f'burning_{burner_name}')
        if sem_id is None:
            return 'Failed: system is too busy. Wait a few minutes and try again.'
        response = await process_burn_command(ctx, burner_name)
        return_semaphore(sem_id)
        await self.send_command_response(ctx, response)

    async def send_command_response(self, ctx, response : str):
        if channels.is_cmd_line(ctx.channel.name):
            await ctx.send(response)
        elif channels.is_chat_hub(ctx.channel.name):
            await ctx.send(response, delete_after=10)
            await server.swallow(ctx.message, alert=False);

    @commands.command(
        name='clear_all_handles',
        brief='Admin-only.',
        help=('Admin-only. Remove all handles (including all financial info) ' +
            'and reset all users to their original handle uXXXX.'),
        hidden=True
        )
    async def clear_handles_command(self, ctx):
        allowed = await channels.pre_process_command(ctx)
        if not allowed:
            return
        sem_id = await get_semaphore('clear_all_handles')
        if sem_id is None:
            return 'Failed: system is too busy. Wait a few minutes and try again.'
        await clear_all_handles()
        await actors.init(ctx.guild, clear_all=False)
        return_semaphore(sem_id)
        await ctx.send('Done.')

    @commands.command(
        name='remove_handle',
        brief='Admin-only.',
        help=('Admin-only. Remove a handle (including all financial info) ' +
            'without a trace.'),
        hidden=True
        )
    async def remove_handle_command(self, ctx, handle_id : str=None):
        allowed = await channels.pre_process_command(ctx)
        if not allowed:
            return
        sem_id = await get_semaphore(f'removing_{handle_id}')
        if sem_id is None:
            return 'Failed: system is too busy. Wait a few minutes and try again.'
        report = await process_remove_handle_command(ctx, handle_id)
        return_semaphore(sem_id)
        await self.send_command_response(ctx, report)

def setup(bot):
    bot.add_cog(HandlesCog(bot))


handles_semaphore = None

async def get_semaphore(user_id : str):
    global handles_semaphore
    sem_id = user_id + '_' + str(random.randrange(10000))
    number_iterations = 0
    while True:
        if handles_semaphore is None:
            handles_semaphore = sem_id
            await asyncio.sleep(0.5)
            if handles_semaphore == sem_id:
                break
        await asyncio.sleep(0.5)
        number_iterations += 1
        if number_iterations > 120:
            print(f'Error: semaphore probably stuck! Resetting semaphore for {sem_id}.')
            handles_semaphore = None
            return None
    return sem_id

def return_semaphore(sem_id : str):
    global handles_semaphore
    if handles_semaphore == sem_id:
        handles_semaphore = None
    else:
        print(f'Semaphore error for \"handle edit\": tried to return semaphore for {sem_id} but it was already free!')



# 'handles' is the config object holding each user's current handles.
handles_conf_dir = 'handles'

handles_to_actors = '___handle_to_actor_mapping'
actors_index = '___all_actors'

# Each actor gets their own file, containing all their handles, along with record of their
# current active one and their most recently active regular (non-burner, non-NPC) handles
active_index = '___active'
last_regular_index = '___last_regular'
handles_index = '___all_handles'


def get_handles_confobj():
    handles = ConfigObj(handles_conf_dir + '/__handles.conf')
    if not handles_to_actors in handles:
        handles[handles_to_actors] = {}
        handles.write()
    if not actors_index in handles:
        handles[actors_index] = {}
        handles.write()
    return handles


# May contain letters, numbers and underscores
# Must start and end with letter or number
alphanumeric_regex = re.compile(f'^[a-zA-Z0-9][a-zA-Z0-9_]*$')
double_underscore = '__'

class HandleAllowedResult(str, Enum):
    Allowed = 'a'
    Invalid = 'i'
    Reserved = 'r'

def is_forbidden_handle(new_handle : str):
    handle_to_check = new_handle.lower()
    matches = re.search(alphanumeric_regex, handle_to_check)
    if matches is None:
        return HandleAllowedResult.Invalid
    elif double_underscore in handle_to_check or handle_to_check.startswith('_') or handle_to_check.endswith('_'):
        return HandleAllowedResult.Invalid
    elif game.is_handle_reserved(handle_to_check):
        return HandleAllowedResult.Reserved
    else:
        return HandleAllowedResult.Allowed

async def init(clear_all : bool=False):
    handles = get_handles_confobj()
    if handles_to_actors not in handles:
        handles[handles_to_actors] = {}
    if actors_index not in handles:
        handles[actors_index] = {}
    handles.write()
    if clear_all:
        await clear_all_handles()

async def clear_all_handles():
    handles = get_handles_confobj()
    for actor_id in handles[actors_index]:
        await clear_all_handles_for_actor(actor_id)
    handles[actors_index] = {}
    handles[handles_to_actors] = {}
    handles.write()

async def clear_all_handles_for_actor(actor_id : str):
    handles = get_handles_confobj()
    for handle in get_handles_for_actor(actor_id, include_burnt=True):
        await clear_handle(handle)
    if actor_id in handles[actors_index]:
        del handles[actors_index][actor_id]
    handles.write()

# TODO: remove old chats?
async def clear_handle(handle : Handle):
    await finances.deinit_finances_for_handle(handle, record=False)
    handles = get_handles_confobj()
    if handle.handle_id in handles[handles_to_actors]:
        del handles[handles_to_actors][handle.handle_id]
        handles.write()
        file_name = f'{handles_conf_dir}/{handle.actor_id}.conf'
        actor_handles_conf = ConfigObj(file_name)
        if handles_index in actor_handles_conf:
            if handle.handle_id in actor_handles_conf[handles_index]:
                del actor_handles_conf[handles_index][handle.handle_id]
                actor_handles_conf.write()


async def init_handles_for_actor(actor_id : str, first_handle : str=None, overwrite=True):
    if first_handle is None:
        first_handle = actor_id
    handles = get_handles_confobj()
    if overwrite or actor_id not in handles[actors_index]:
        handles[actors_index][actor_id] = {}
        handles.write()
        file_name = f'{handles_conf_dir}/{actor_id}.conf'
        actor_handles_conf = ConfigObj(file_name)
        for entry in actor_handles_conf:
            del actor_handles_conf[entry]
        actor_handles_conf[handles_index] = {}
        actor_handles_conf.write()
        handle : Handle = await create_handle(actor_id, first_handle, HandleTypes.Regular, force_reserved=True)
        switch_to_handle(handle)

def store_handle(handle : Handle):
    handles = get_handles_confobj()
    handles[actors_index][handle.actor_id] = {}
    handles[handles_to_actors][handle.handle_id] = handle.actor_id
    handles.write()

    file_name = f'{handles_conf_dir}/{handle.actor_id}.conf'
    actor_handles_conf = ConfigObj(file_name)
    actor_handles_conf[handles_index][handle.handle_id] = handle.to_string()
    actor_handles_conf.write()


async def create_handle(actor_id : str, handle_id : str, handle_type : HandleTypes, force_reserved : bool=False):
    handle = Handle(handle_id, handle_type = handle_type, actor_id = actor_id)
    result : HandleAllowedResult = is_forbidden_handle(handle_id)
    if result == HandleAllowedResult.Allowed:
        store_handle(handle)
        finances.init_finances_for_handle(handle)
    elif result == HandleAllowedResult.Reserved:
        if force_reserved:
            store_handle(handle)
            finances.init_finances_for_handle(handle)
        else:
            handle.handle_type = HandleTypes.Reserved
    else:
        handle.handle_type = HandleTypes.Invalid
    return handle


def read_handle(actor_handles, handle_id : str):
    handles = get_handles_confobj()
    # Unprotected -- only use for handles that you know exist
    return Handle.from_string(actor_handles[handles_index][handle_id])

def get_active_handle_id(actor_id : str):
    handles = get_handles_confobj()
    if actor_id in handles[actors_index]:
        file_name = f'{handles_conf_dir}/{actor_id}.conf'
        actor_handles_conf = ConfigObj(file_name)
        if active_index in actor_handles_conf:
            return actor_handles_conf[active_index]
            
def get_active_handle(actor_id : str):
    handles = get_handles_confobj()
    if actor_id in handles[actors_index]:
        file_name = f'{handles_conf_dir}/{actor_id}.conf'
        actor_handles_conf = ConfigObj(file_name)
        if active_index in actor_handles_conf:
            active_id = actor_handles_conf[active_index]
            if active_id in actor_handles_conf[handles_index]:
                handle = read_handle(actor_handles_conf, active_id)
                return handle

def get_last_regular_id(actor_id : str):
    handles = get_handles_confobj()
    if actor_id in handles[actors_index]:
        file_name = f'{handles_conf_dir}/{actor_id}.conf'
        actor_handles_conf = ConfigObj(file_name)
        if last_regular_index in actor_handles_conf:
            return actor_handles_conf[last_regular_index]

def get_last_regular(actor_id : str):
    handles = get_handles_confobj()
    if actor_id in handles[actors_index]:
        file_name = f'{handles_conf_dir}/{actor_id}.conf'
        actor_handles_conf = ConfigObj(file_name)
        if last_regular_index in actor_handles_conf:
            last_regular_id = actor_handles_conf[last_regular_index]
            if last_regular_id in actor_handles_conf[handles_index]:
                return read_handle(actor_handles_conf, last_regular_id)


def get_all_handles():
    handles = get_handles_confobj()
    for actor_id in handles[actors_index]:
        for handle in get_handles_for_actor(actor_id, include_burnt=True):
            yield handle


def get_handle(handle_name : str):
    handle_id = handle_name.lower()
    handles = get_handles_confobj()
    for actor_id in handles[actors_index]:
        for handle in get_handles_for_actor(actor_id, include_burnt=True):
            if handle.handle_id == handle_id:
                return handle
    return Handle(handle_id, handle_type=HandleTypes.Unused)

def switch_to_handle(handle : Handle):
    file_name = f'{handles_conf_dir}/{handle.actor_id}.conf'
    actor_handles_conf = ConfigObj(file_name)
    actor_handles_conf[active_index] = handle.handle_id
    if handle.handle_type == HandleTypes.Regular:
        actor_handles_conf[last_regular_index] = handle.handle_id
    actor_handles_conf.write()

def get_handles_for_actor(actor_id : str, include_burnt : bool=False, include_npc : bool=True):
    types_list = [HandleTypes.Regular, HandleTypes.Burner]
    if include_burnt:
        types_list.append(HandleTypes.Burnt)
    if include_npc:
        types_list.append(HandleTypes.NPC)
    return get_handles_for_actor_of_types(actor_id, types_list)

def get_handles_for_actor_of_types(actor_id : str, types_list : List[HandleTypes]):
    file_name = f'{handles_conf_dir}/{actor_id}.conf'
    actor_handles_conf = ConfigObj(file_name)
    for handle_id in actor_handles_conf[handles_index]:
        handle = read_handle(actor_handles_conf, handle_id)
        if handle.handle_type in types_list:
            yield handle





### Methods directly related to commands


async def process_remove_handle_command(ctx, handle_id : str):
    if handle_id is None:
        return 'Error: you must say which handle you want to clear.'
    handle : Handle = get_handle(handle_id)
    if handle.handle_id == handle.actor_id:
        return f'Error: cannot destroy this user\'s base handle.'
    elif handle.handle_type == HandleTypes.Unused:
        return f'Error: cannot clear handle {handle_id} because it does not exist.'
    else:
        active : Handle = get_active_handle(handle.actor_id)
        if active.handle_id == handle.handle_id:
            new_active : Handle = get_handle(handle.actor_id)
            switch_to_handle(new_active)

        await clear_handle(handle)
        return f'Removed handle {handle_id}. Warning: if the handle is re-created in the future, some things might not work since old chats etc may linger in the database.'

def current_handle_report(actor_id : str):
    current_handle : Handle = get_active_handle(actor_id)
    if current_handle.handle_type == HandleTypes.Burner:
        response = f'Your current handle is **{current_handle.handle_id}**. It\'s a burner handle – to destroy it, use \".burn {current_handle.handle_id}\". To switch handle, type \".handle <new_name>\".'
    elif current_handle.handle_type == HandleTypes.NPC:
        response = f'Your current handle is **{current_handle.handle_id}**. [OFF: It\'s an NPC handle, so it cannot be directly linked to your other handles, unless they interact with it]'
    elif current_handle.handle_type == HandleTypes.Regular:
        response = f'Your current handle is **{current_handle.handle_id}**. To switch handle, type \".handle <new_name>\".'
    else:
        raise RuntimeError(f'Unexpected handle type of active handle. Dump: {current_handle.to_string()}')
    return response

def all_handles_report(actor_id : str, third_person : bool=False):
    current_handle : Handle = get_active_handle(actor_id)
    if third_person:
        report = 'The following handles are all connected:\n'
    else:
        report = 'Here are all your connected handles:\n'
    any_burner = False
    for handle in get_handles_for_actor(actor_id, include_npc=False):
        if handle.handle_id == current_handle.handle_id:
            report = report + f'> **{handle.handle_id}**'
        else:
            report = report + f'> {handle.handle_id}'
        if handle.handle_type == HandleTypes.Burner:
            any_burner = True
            report += '  🔥'
        report += '\n'

    any_npc_found = False
    for handle in get_handles_for_actor_of_types(actor_id, [HandleTypes.NPC]):
        if not any_npc_found:
            any_npc_found = True
            if third_person:
                report += '\n[OFF: The same player also control these NPC accounts:]\n'
            else:
                report += '\n[OFF: You also control these NPC accounts:]\n'
        if handle.handle_id == current_handle.handle_id:
            report = report + f'> **{handle.handle_id}**\n'
        else:
            report = report + f'> {handle.handle_id}\n'

    report += '\nYou can switch to another handle (any type), or create a new one, by using \".handle\".\n'
    if any_burner:
        report += 'Create new burner handles (🔥) using \".burner\". They can be deleted forever using \".burn\". Regular handles cannot be deleted.\n'
    report += 'To see how much money each handle has, use \".balance\" or check your \"finances\" channel.\n'

    return report


def switch_to_own_existing_handle(actor_id : str, handle : Handle, expected_type : HandleTypes):
    if handle.handle_type == HandleTypes.Burner:
        if expected_type in [HandleTypes.Regular, HandleTypes.Burner]:
            # We can switch to a burner handle using both .handle and .burner
            response = f'Switched to burner handle **{handle.handle_id}**. Remember to burn it when done, using \".burn {handle.handle_id}\".'
            switch_to_handle(handle)
        else:
            response = f'Attempted to switch to {expected_type} handle {handle.handle_id}, but {handle.handle_id} is in fact a burner.'
    elif handle.handle_type == HandleTypes.Burnt:
        # We cannot switch to a burnt handle
        response = f'Error: handle {handle.handle_id} is no longer available.'
    elif handle.handle_type == HandleTypes.Regular:
        if expected_type == HandleTypes.Regular:
            response = f'Switched to handle **{handle.handle_id}**.'
            switch_to_handle(handle)
        else:
            # We cannot switch to a non-burner using .burner
            response = f'Handle **{handle.handle_id}** already exists but is not a {expected_type} handle. Use \".handle {handle.handle_id}\" to switch to it.'
    elif handle.handle_type == HandleTypes.NPC:
        response = f'Switched to NPC handle **{handle.handle_id}**.'
        switch_to_handle(handle)
    else:
        raise RuntimeError(f'Unexpected handle type of active handle. Dump: {handle.to_string()}')
    return response

async def create_handle_and_switch(
    actor_id : str,
    new_handle_id : str,
    handle_type : HandleTypes=HandleTypes.Regular,
    force_reserved : bool=False):
    result = ActionResult()
    handle : Handle = await create_handle(actor_id, new_handle_id, handle_type, force_reserved)
    if handle.handle_type == HandleTypes.Invalid:
        result.report = (f'Error: cannot create handle {handle.handle_id}. '
            + 'Handles can only contain letters a-z, numbers 0-9, and \_ (underscore). '
            + 'May not start or end with \_, may not have more than one \_ in a row.')
    elif handle.handle_type == HandleTypes.Reserved:
        result.report = (f'Error: cannot create handle {handle.handle_id}. '
            + 'That name is used by the system or reserved for a user who has not connected their main handle yet.')
    elif handle.handle_type == handle_type and handle.is_active():
        switch_to_handle(handle)
        #report = await player_setup.player_setup_for_new_handle(handle)
        #if report is not None:
            # If something happened in player_setup_for_new_handle(), that report will be enough
        #    return report
        result.success = True
        if handle_type == HandleTypes.Burner:
            # TODO: note about possibly being hacked until destroyed?
            result.report = (f'Switched to new burner handle **{handle.handle_id}** (created now). '
                + f'To destroy it, use \".burn {handle.handle_id}\".')
        elif handle_type == HandleTypes.NPC:
            result.report = (f'Switched to new handle **{handle.handle_id}** (created now). '
                + '[OFF: it\'s an NPC handle, meaning it cannot be linked to your regular handles unless it interacts with them.]')
        else:
            result.report = f'Switched to new handle **{handle.handle_id}** (created now).'
    else:
        result.report = (f'Error: failed to create {handle.handle_id}; reason unknown.')
    return result

async def process_handle_command(ctx, new_handle_id : str=None, burner : bool=False, npc : bool=False):
    actor_id = players.get_player_id(str(ctx.message.author.id))
    if new_handle_id == None:
        response = current_handle_report(actor_id)
        if burner:
            response += ' To create a new burner, use \".burner <new_name>\".'
    else:
        # Entry point for possibly editing handles:
        sem_id = await get_semaphore(f'switching_to_{new_handle_id}')
        if sem_id is None:
            return 'Failed: system is too busy. Wait a few minutes and try again.'

        existing_handle : Handle = get_handle(new_handle_id)
        handle_type = HandleTypes.Regular
        if burner:
            handle_type = HandleTypes.Burner
        elif npc:
            handle_type = HandleTypes.NPC

        if existing_handle.handle_type != HandleTypes.Unused:
            if existing_handle.actor_id == actor_id:
                response = switch_to_own_existing_handle(actor_id, existing_handle, handle_type)
            elif existing_handle.handle_id != new_handle_id:
                response = f'Error: cannot create handle {new_handle_id} because its internal ID ({existing_handle.handle_id}) clashes with an existing handle.'
            else:
                response = f'Error: the handle {new_handle_id} not available.'
        else:
            result = await create_handle_and_switch(actor_id, new_handle_id, handle_type)
            response = result.report
        if existing_handle.handle_id != new_handle_id:
            response += f'\nNote that handles are lowercase only: {new_handle_id} -> **{existing_handle.handle_id}**.'
        return_semaphore(sem_id)

    return response


async def get_full_handles_report(ctx):
    actor_id = players.get_player_id(str(ctx.message.author.id))
    return all_handles_report(actor_id)

async def get_full_handles_report_for_handle(handle_id : str):
    if handle_id is None:
        return 'Error: you must give a handle to search for.'
    handle = get_handle(handle_id)
    if handle.handle_type == HandleTypes.Unused:
        return f'Handle {handle_id} has never been used.'
    report = ''
    if handle.handle_type == HandleTypes.Burnt:
        report += (f'Handle **{handle_id}** was a burner handle and it has been burnt. ' +
            'It should be untraceable, even for a good hacker!\n' +
            'For GM eyes only, the player\'s current handles are given below.\n\n')
    report += all_handles_report(handle.actor_id, third_person=True)
    return report


#Burners

# returns the amount of money (if any) that was transferred away from the burner
async def destroy_burner(guild, burner : Handle):
    balance = 0
    # If we burn the active handle, we must figure out the new active one
    active : Handle = get_active_handle(burner.actor_id)
    if active.handle_id == burner.handle_id:
        new_active = get_last_regular(burner.actor_id)
        switch_to_handle(new_active)
    else:
        new_active = active

    # Rescue any money about to be burned
    balance = finances.get_current_balance(burner)
    if balance > 0:
        await finances.transfer_from_burner(burner, new_active, balance)

    # archive any chats for the burner
    await chats.archive_all_chats_for_handle(burner)

    # Destroy the burner
    burner.handle_type = HandleTypes.Burnt
    store_handle(burner)
    await finances.deinit_finances_for_handle(burner, record=True)
    return balance

async def process_burn_command(ctx, burner_id : str=None):
    if burner_id == None:
        response = 'Error: No burner handle specified. Use \".burn <handle>\"'
    else:
        actor_id = players.get_player_id(str(ctx.message.author.id))
        burner : Handle = get_handle(burner_id)
        if not burner.is_active():
            response = f'Error: the handle {burner_id} does not exist.'
        elif burner.actor_id != actor_id:
            response = f'Error: you do not have access to {burner_id}.'
        elif burner.handle_type in [HandleTypes.Regular, HandleTypes.NPC]:
            response = f'Error: **{burner_id}** is not a burner handle, cannot be destroyed. To stop using it, simply switch to another handle.'
        elif burner.handle_type == HandleTypes.Burner:
            amount = await destroy_burner(ctx.guild, burner)
            current_handle_id = get_active_handle_id(actor_id)
            response = 'Destroyed burner handle **' + burner_id + '**.\n'
            response = response + 'It will not be possible to use again, for anyone. Its previous use cannot be traced to you.\n'
            if amount > 0:
                response = response + f'Your current handle is **{current_handle_id}**; the remaining {coin} {amount} from {burner.handle_id} was transferred there.'
            else:
                response = response + f'Your current handle is **{current_handle_id}**.'
    return response