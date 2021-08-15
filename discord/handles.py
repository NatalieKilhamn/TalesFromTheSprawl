import finances
import players
from constants import forbidden_content, forbidden_content_print

from configobj import ConfigObj
import re

### Module handles.py
# This module tracks and handles state related to handles, e.g. in-game names/accounts that
# players can create.

# 'handles' is the config object holding each user's current handles.
handles = ConfigObj('handles.conf')
active_index = '___active'
last_regular_index = '___last_regular'

# TODO: should be able to remove a lot of on-demand initialization now that we init all users

# May contain lowercase letters, numbers and underscores
# Must start and end with letter or number
# Must be at least two characters (TODO: not necessary, but makes for an easier regex)
alphanumeric_regex = re.compile(f'^[a-z0-9][a-z0-9_]*[a-z0-9]$')
double_underscore = '__'

class HandleStatus:
    handle : str = ''
    exists : str = False
    player_id : str = ''
    handle_type : str = ''

def clear_all_handles():
	for player_id in handles:
		for handle in get_handles_for_player(player_id):
			finances.deinit_finances_for_handle(handle)
		del handles[player_id]
	handles.write()

def init_handles_for_player(player_id : str, first_handle : str):
    handles[player_id] = {}
    create_regular_handle(player_id, first_handle)
    switch_to_handle(player_id, first_handle)

def is_forbidden_handle(new_handle : str):
    matches = re.search(alphanumeric_regex, new_handle)
    if matches is None:
        return True
    elif double_underscore in new_handle:
        return True
    else:
        return False

def create_handle(player_id : str, new_handle : str, burner : bool):
	if is_forbidden_handle(new_handle):
		return False
	handles[player_id][new_handle] = 'burner' if burner else 'regular'
	finances.init_finances_for_handle(new_handle)
	handles.write()
	return True

def create_regular_handle(player_id : str, new_handle : str):
	return create_handle(player_id, new_handle, False)

def create_burner_handle(player_id : str, new_burner_handle : str):
	return create_handle(player_id, new_burner_handle, True)

# returns the amount of money (if any) that was transferred away from the burner
async def destroy_burner(guild, player_id : str, burner : str):
	balance = 0
	if burner in handles[player_id]:
	# If we burn the active handle, we must figure out the new active one
		active = handles[player_id][active_index]
		if active == burner:
			new_active = handles[player_id][last_regular_index]
			switch_to_handle(player_id, new_active)
		else:
			new_active = active

		# Rescue any money about to be burned
		balance = finances.get_current_balance(burner)
		if balance > 0:
			await finances.transfer_from_burner(guild, burner, new_active, balance)

		# Delete the burner
		del handles[player_id][burner]
		finances.deinit_finances_for_handle(burner)
	handles.write()
	return balance

def switch_to_handle(player_id : str, handle : str):
    handles[player_id][active_index] = handle
    if handles[player_id][handle] == 'regular':
        handles[player_id][last_regular_index] = handle
    handles.write()

def get_handle(player_id : str):
    return handles[player_id][active_index]

def get_handles_for_player(player_id : str):
    for handle in handles[player_id]:
        if handle != active_index and handle != last_regular_index:
            yield handle

def get_all_handles():
    for player_id in handles:
        for handle in handles[player_id]:
            if handle != active_index and handle != last_regular_index:
                yield handle

def handle_exists(handle : str):
    result = HandleStatus()
    for player_id in handles:
        if handle in handles[player_id]:
            return True
    return False

# Sanitize input -- special return on reserved values will protect many commands, including creating
def get_handle_status(handle : str):
    if handle.lower() != handle:
        raise RuntimeError(f'Unsanitized handle {handle} passed to get_handle_status.')
    result = HandleStatus()
    for player_id in handles:
        if handle in get_handles_for_player(player_id):
            result.exists = True
            result.player_id = player_id
            result.handle_type = handles[player_id][handle]
            break
    return result



### Async methods, directly related to commands

def current_handle_report(player_id : str):
    current_handle = get_handle(player_id)
    handle_status : HandleStatus = get_handle_status(current_handle)
    if (handle_status.handle_type == 'burner'):
        response = 'Your current handle is **' + current_handle + '**. It\'s a burner handle – to destroy it, use \".burn ' + current_handle + '\". To switch handle, type \".handle <new_name>\".'
    else:
        response = 'Your current handle is **' + current_handle + '**. To switch handle, type \".handle <new_name>\".'
    return response

def switch_to_own_existing_handle(player_id : str, new_handle : str, handle_status : HandleStatus, new_shall_be_burner):
    if (handle_status.handle_type == 'burner'):
        # We can switch to a burner handle using both .handle and .burner
        response = 'Switched to burner handle **' + new_handle + '**. Remember to burn it when done, using \".burn ' + new_handle + '\".'
        switch_to_handle(player_id, new_handle)
    elif new_shall_be_burner:
        # We cannot switch to a non-burner using .burner
        response = 'Handle **' + new_handle + '** already exists but is not a burner handle. Use \".handle ' + new_handle + '\" to switch to it.'
    else:
        response = 'Switched to handle **' + new_handle + '**.'
        switch_to_handle(player_id, new_handle)
    return response

def create_handle_and_switch(player_id : str, new_handle : str, new_shall_be_burner):
	success = create_handle(player_id, new_handle, new_shall_be_burner)
	if success:
		switch_to_handle(player_id, new_handle)
		if new_shall_be_burner:
			# TODO: note about possibly being hacked until destroyed?
			response = f'Switched to new burner handle **{new_handle}** (created now). To destroy it, use \".burn {new_handle}\".'
		else:
			response = f'Switched to new handle **{new_handle}** (created now).'
	else:
		response = (f'Error: cannot create handle {new_handle}. '
            + 'Handles can only contain letters a-z (lowercase), numbers 0-9, and \_ (underscore). '
            + 'May not start or end with \_, may not have more than one \_ in a row.'
        )
	return response

async def process_handle_command(ctx, new_handle : str=None, burner=False):
    player_id = players.get_player_id(str(ctx.message.author.id))
    if new_handle == None:
        response = current_handle_report(player_id)
        if burner:
        	response += ' To create a new burner, use \".burner <new_name>\".'
    else:
        new_handle_lower = new_handle.lower()
        handle_status : HandleStatus = get_handle_status(new_handle_lower)
        if (handle_status.exists and handle_status.player_id == player_id):
            response = switch_to_own_existing_handle(player_id, new_handle_lower, handle_status, burner)
        elif (handle_status.exists):
            response = f'Error: the handle {new_handle} is currently registered by someone else.'
        else:
            response = create_handle_and_switch(player_id, new_handle_lower, burner)
        if (new_handle_lower != new_handle):
            response += f'\nNote that handles are lowercase only: {new_handle} -> **{new_handle_lower}**.'
    return response

async def process_burn_command(ctx, burner_id : str=None):
    if burner_id == None:
        response = 'Error: No burner handle specified. Use \".burn <handle>\"'
    else:
        burner_id = burner_id.lower()
        player_id = players.get_player_id(str(ctx.message.author.id))
        handle_status : handles.HandleStatus = handles.get_handle_status(burner_id)
        if (not handle_status.exists):
            response = 'Error: the handle ' + burner_id + ' does not exist'
        elif (handle_status.player_id != player_id):
            response = 'Error: you do not have access to ' + burner_id
        elif (handle_status.handle_type == 'regular'):
            response = 'Error: **' + burner_id + '** is not a burner handle, cannot be destroyed. To stop using it, simply switch to another handle.'
        elif (handle_status.handle_type == 'burner'):
            amount = await handles.destroy_burner(ctx.guild, player_id, burner_id)
            current_handle = handles.get_handle(player_id)
            response = 'Destroyed burner handle **' + burner_id + '**.\n'
            response = response + 'If you or someone else uses that name, it may be confusing but cannot be traced to the previous use.\n'
            if amount > 0:
                response = response + f'Your current handle is **{current_handle}**; the remaining ¥ {amount} from {burner_id} was transferred there.'
            else:
                response = response + 'Your current handle is **' + current_handle + '**.'
    return response