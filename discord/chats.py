from typing import Optional
import discord
import asyncio
import simplejson
from configobj import ConfigObj
from enum import Enum
from discord.ext import commands

import actors
import players
import handles
import channels
import server
import posting
import gm
import game
from common import emoji_cancel, emoji_open, emoji_green, emoji_red, emoji_green_book, emoji_red_book, emoji_unread
from custom_types import Handle, PostTimestamp



### Module chats.py
# This module handles chats between handles

class ChatsCog(commands.Cog, name='chats'):
	"""Commands related to chats.
	These are private conversations between two different handles."""
	def __init__(self, bot):
		self.bot = bot
		self._last_member = None

	# TODO: swallow messages (and post alerts) when trying to use commands in chat channel

	# Commands related to chats
	# These only work in cmd_line channels

	@commands.command(
		name='chat',
		brief='Open a chat session with another user.',
		help=(
			'Open a chat session between you (using your current handle) and another user. ' +
			'If you have never had a chat between those two handles before, one will be created. ' +
			'All your active chats are shown in your personal chat_hub channel, where you can open and ' +
			'close the connections as needed.\n' +
			'You can close a chat and re-open it and all the chat history will be stored, except for file attachments. ' +
			'Note: you cannot change your handle in an existing chat, so make sure to start the chat from the correct one! ' +
			'If you switch handles and open a new chat, the other person can see that two handles have tried to contact them, ' +
			'but they will not see that they belong to the same person.'
		)
		)
	async def chat_command(self, ctx, handle : str=None):
		allowed = await channels.pre_process_command(ctx, allow_chat_hub=True)
		if not allowed:
			return

		response = None
		if handle is None:
			response = f'Error: you must say who you want to chat with. Example: \".chat shadow_weaver\"'
		else:
			handle = handle.lower()
			response = await create_chat_from_command(str(ctx.message.author.id), handle)
		if response is not None:
			await self.send_command_response(ctx, response)

	@commands.command(
		name='chat_other',
		help='Admin only. Open a chat session for someone else.',
		hidden=True)
	@commands.has_role('gm')
	async def chat_other_command(self, ctx,  my_handle : str=None, other_handle : str=None):
		allowed = await channels.pre_process_command(ctx, allow_chat_hub=False)
		if not allowed:
			return
		if my_handle is None:
			await ctx.send('Error: you must give two handles to start a chat.')
			return
		elif other_handle is None:
			report = f'Error: you must give the second handle that should chat with {my_handle}.'
			await ctx.send(report)
			return

		my_handle = my_handle.lower()
		other_handle = other_handle.lower()
		report = await create_2party_chat_from_handle_id(my_handle, other_handle)
		if report != None:
			await ctx.send(report)

	@commands.command(
		name='gm_chat',
		help='GM only. Open a chat session from the shared GM account.',
		hidden=True)
	@commands.has_role('gm')
	async def gm_chat_command(self, ctx,  other_handle : str=None):
		allowed = await channels.pre_process_command(ctx, allow_chat_hub=False)
		if not allowed:
			return
		if other_handle is None:
			report = f'Error: you must give the handle to chat with.'
			await ctx.send(report)
			return

		my_handle = gm.get_gm_active_handle()
		other_handle = other_handle.lower()
		report = await create_2party_chat_from_handle_id(my_handle, other_handle)
		if report != None:
			await ctx.send(report)

	@commands.command(
		name='close_chat',
		brief='Close a chat session from your end.',
		help=(
			'Close a chat session from your end. This will not affect how the other participant sees the chat. ' +
			f'You can re-open the chat at any time using \".chat\", or by clicking the {emoji_open} in your chat_hub.'
			)
		)
	async def close_chat_command(self, ctx, handle : str=None):
		allowed = await channels.pre_process_command(ctx, allow_chat_hub=True)
		if not allowed:
			return
		if handle is None:
			response = f'Error: you must say which chat you want to close. Example: \".close_chat shadow_weaver\"'
		else:
			handle = handle.lower()
			response = await close_chat_session_from_command(ctx, handle)
		if response is not None:
			await self.send_command_response(ctx, response)

	@commands.command(
		name='close_chat_other',
		help='Admin-only. Close a chat session for someone else.',
		hidden=True)
	@commands.has_role('gm')
	async def close_chat_other_command(self, ctx, my_handle : str, other_handle : str):
		allowed = await channels.pre_process_command(ctx, allow_chat_hub=False)
		if not allowed:
			return
		my_handle = my_handle.lower()
		other_handle = other_handle.lower()
		report = await close_2party_chat_session_from_handle_id(my_handle, other_handle)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='clear_all_chats',
		help='Admin-only. Delete all chats and chat channels for all users.',
		hidden=True)
	@commands.has_role('gm')
	async def clear_all_chats_command(self, ctx):
		allowed = await channels.pre_process_command(ctx, allow_chat_hub=False)
		if not allowed:
			return
		await init(clear_all=True)
		await ctx.send('Done.')

	async def send_command_response(self, ctx, response : str):
		if channels.is_cmd_line(ctx.channel.name):
			await ctx.send(response)
		elif channels.is_chat_hub(ctx.channel.name):
			await ctx.send(response, delete_after=10)
			await server.swallow(ctx.message, alert=False, delay=10);


chats_dir = 'chats'
chats = ConfigObj(f'{chats_dir}/chats.conf')

def setup(bot):
	global chats
	bot.add_cog(ChatsCog(bot))
	chats = ConfigObj(f'{chats_dir}/chats.conf')

channel_limit_per_actor = 5

handle_index = '___handle'
chat_channel_data_index = '___chat_channel_data'
chat_hub_msg_data_index = '___chat_hub_msg_data'
chat_content_index = '___chat_content'
chats_with_logs_index = '___chat_log_length'
chat_participants_index = '___chat_participants'

session_status_active = '___active'
session_status_inactive = '___inactive'
session_status_unread = '___inactive_unread'
session_status_closed_archive = '___inactive_archive'
session_status_open_archive = '___open_archive'

### Classes, init and basic utilities

# This is stored indexed by handle, and points out the various connections that handle has to the chat
class ChatParticipant(object):
	def __init__(
		self,
		chat_name : str,
		session_status : str,
		channel_name : str,
		actor_id : str,
		handle : str, # TODO: rename handle_id
		chat_hub_msg_id : str,
		channel_id : str=None):
		self.chat_name = chat_name
		self.session_status = session_status
		# Regardless of whether the channel currently exists or not
		# it shall have the same name every time it's re-created
		self.channel_name = channel_name
		self.actor_id = actor_id
		self.handle = handle
		self.chat_hub_msg_id = chat_hub_msg_id
		# Set to None when the channel is temporarily closed
		self.channel_id = channel_id

	@staticmethod
	def from_string(string : str):
		obj = ChatParticipant(None, None, None, None, None, None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)


# This is stored per channel/msg ID, and maps back to the chat
class ChatConnectionMapping(object):
	def __init__(self, chat_name : str, actor_id : str, handle : str):
		self.chat_name = chat_name
		self.actor_id = actor_id
		self.handle = handle # TODO: rename handle_id

	@staticmethod
	def from_string(string : str):
		obj = ChatConnectionMapping(None, None, None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

class ChatLogEntry(object):
	def __init__(
		self,
		message : str,
		header : bool=False,
		closed_handle_id : str=None,
		archived_handle_id : str=None
		):
		self.message = message
		self.header = header
		self.closed_handle_id = closed_handle_id
		self.archived_handle_id = archived_handle_id

	@staticmethod
	def from_string(string : str):
		obj = ChatLogEntry(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

# This represent everything in discord that can currently be used to interface with the chat:
# - Channel for messages
# - The chat hub message with open/close commands
# This is not meant to be stored in any configobj
class ChatUI(object):
	def __init__(
		self,
		chat_name : str,
		channel,
		chat_hub_message,
		session_status : str,
		handle : str,
		actor_id : str):
		self.chat_name = chat_name
		self.channel = channel # Can be None, if the channel is closed (session_status_inactive)
		self.chat_hub_message = chat_hub_message
		self.session_status = session_status
		self.handle = handle # TODO: rename handle_id, or replace with handle
		self.actor_id = actor_id

class Activation(str, Enum):
	No = 'no'
	Msg = 'msg'
	Open = 'open'


def init_chats_confobj():
	global chats
	chats = ConfigObj(f'{chats_dir}/chats.conf')
	if not chat_channel_data_index in chats:
		chats[chat_channel_data_index] = {}
	if not chat_hub_msg_data_index in chats:
		chats[chat_hub_msg_data_index] = {}
	if not chats_with_logs_index in chats:
		chats[chats_with_logs_index] = {}
	chats.write()

def get_channel_budget():
	return ConfigObj(f'{chats_dir}/channel_budget.conf')


def dump():
	for cat in chats:
		print(f'Dumping category {cat}:')
		for entry in chats[cat]:
			print(f'Entry {entry}: {chats[cat][entry]}')

async def init(clear_all : bool=False):
	init_chats_confobj()
	# Loop through all chats that are supposed to exist according to conf files
	for chat_name in chats[chats_with_logs_index]:
		chat_state = get_chat_state(chat_name)
		if clear_all:
			del chat_state[chat_participants_index]
			del chat_state[chat_content_index]
			chat_state.write()
		else:
			# Re-init the chats (posting-wise) like any open channel
			channels.init_chat_channel(chat_name)
			# Keep the participants data but reset the channel IDs, to indicate that all discord channels are deleted
			if not chat_participants_index in chat_state:
				init_chat_state(chat_state)
			for participant in get_participants(chat_state):
				# Close all chat sessions. If the discord and config files are still in sync,
				# this will update all chat hub messages so that chats can be easily re-opened
				await close_chat_session(participant)
	# Remove all channel mappings
	chats[chat_channel_data_index] = {}
	if clear_all:
		chats[chat_hub_msg_data_index] = {}
		chats[chats_with_logs_index] = {}
		channel_list = await channels.get_all_chat_hub_channels()
		await asyncio.gather(
			*[asyncio.create_task(c.purge())
			for c
			in channel_list])

	# Any left-over channels after this should be deleted
	await channels.delete_all_chats()

	chat_channel_budget = get_channel_budget()
	for actor_id in chat_channel_budget:
		del chat_channel_budget[actor_id]
		chat_channel_budget.write()

	chats.write()


def create_2party_chat_name(handle1 : Handle, handle2 : Handle):
	handles_ordered = sorted([handle1.handle_id, handle2.handle_id])
	return f'{handles_ordered[0]}_{handles_ordered[1]}'

def _get_chat_connection_key(guild_id: int, channel_id: str):
	return f'{guild_id}#{channel_id}'

def read_chat_connection_from_channel(guild_id: int, channel_id : str):
	init_chats_confobj()
	chats = ConfigObj(f'{chats_dir}/chats.conf')

	key = _get_chat_connection_key(guild_id, channel_id)
	if key in chats[chat_channel_data_index]:
		string = chats[chat_channel_data_index][key]
		chat_connection : ChatConnectionMapping = ChatConnectionMapping.from_string(string)
		return chat_connection
	else:
		return None

def store_chat_connection_for_channel(guild_id: int, channel_id : str, chat_connection : ChatConnectionMapping):
	init_chats_confobj()
	key = _get_chat_connection_key(guild_id, channel_id)
	chats[chat_channel_data_index][key] = chat_connection.to_string()
	chats.write()

def clear_channel_connection_mappings(guild_id: int, channel_id: str):
	init_chats_confobj()
	key = _get_chat_connection_key(guild_id, channel_id)
	if key in chats[chat_channel_data_index]:
		del chats[chat_channel_data_index][key]
		chats.write()


def read_chat_connection_from_hub_msg(msg_id : str):
	init_chats_confobj()
	# TODO: Guard msg_id with guild_id too?
	if msg_id in chats[chat_hub_msg_data_index]:
		string = chats[chat_hub_msg_data_index][msg_id]
		chat_connection : ChatConnectionMapping = ChatConnectionMapping.from_string(string)
		return chat_connection
	else:
		return None

def store_chat_connection_for_hub_msg(msg_id : str, chat_connection : ChatConnectionMapping):
	init_chats_confobj()
	chats[chat_hub_msg_data_index][msg_id] = chat_connection.to_string()
	chats.write()

def clear_hub_msg_connection_mapping(msg_id):
	init_chats_confobj()
	if msg_id in chats[chat_hub_msg_data_index]:
		del chats[chat_hub_msg_data_index][msg_id]
		chats.write()



def chat_exists(chat_name : str):
	init_chats_confobj()
	return chat_name in chats[chats_with_logs_index]

def get_chat_state(chat_name : str):
	chat_file_name = f'{chat_name}.conf'
	return ConfigObj(f'{chats_dir}/{chat_file_name}')

def get_chats_for_handle(handle : Handle):
	init_chats_confobj()
	for msg_id in chats[chat_hub_msg_data_index]:
		chat_connection : ChatConnectionMapping = read_chat_connection_from_hub_msg(msg_id)
		if chat_connection.handle == handle.handle_id:
			yield (chat_connection.chat_name, get_chat_state(chat_connection.chat_name))

def get_participants(chat_state):
	for participant_id in chat_state[chat_participants_index]:
		yield read_participant(chat_state, participant_id)

def read_participant(chat_state, handle_id : str):
	if handle_id in chat_state[chat_participants_index]:
		string = chat_state[chat_participants_index][handle_id]
		participant : ChatParticipant = ChatParticipant.from_string(string)
		return participant
	else:
		return None

def store_participant(chat_name : str, participant : ChatParticipant):
	chat_state = get_chat_state(chat_name)
	chat_state[chat_participants_index][participant.handle] = participant.to_string()
	chat_state.write()


def get_log_length(chat_name : str):
	init_chats_confobj()
	return int(chats[chats_with_logs_index][chat_name])

def increment_log_length(chat_name : str):
	init_chats_confobj()
	prev_length = int(chats[chats_with_logs_index][chat_name])
	chats[chats_with_logs_index][chat_name] = str(prev_length + 1)
	chats.write()

# TODO: move the chat log to a separate file, so that writing an entry
# and opening/closing a sesson don't need to interfere

def read_chat_log_entry(chat_state, index : int):
	string = chat_state[chat_content_index][str(index)]
	return ChatLogEntry.from_string(string)

def get_chat_log_iterable(chat_state, chat_name : str):
	log_length = get_log_length(chat_name)
	for index in range(log_length):
		index_str = str(index)
		if index_str in chat_state[chat_content_index]:
			yield (index, read_chat_log_entry(chat_state, index))

def store_chat_log_entry(chat_name : str, index : int, entry : ChatLogEntry):
	chat_state = get_chat_state(chat_name)
	chat_state[chat_content_index][str(index)] = entry.to_string()
	chat_state.write()

def remove_entry_from_chat_log(chat_name : str, index : int):
	# Re-read the log (minimize time between read and write)
	chat_state = get_chat_state(chat_name)
	index_str = str(index)
	if index_str in chat_state[chat_content_index]:
		del chat_state[chat_content_index][index_str]
		chat_state.write()

def write_new_chat_log_entry(chat_name : str, entry : ChatLogEntry):
	next_index = get_log_length(chat_name)
	store_chat_log_entry(chat_name, next_index, entry)
	increment_log_length(chat_name)

def get_participant_handle_ids(channel):
	chat_channel_data : ChatConnectionMapping = read_chat_connection_from_channel(channel.guild.id, str(channel.id))
	if chat_channel_data is not None:
		chat_state = get_chat_state(chat_channel_data.chat_name)
		for participant in get_participants(chat_state):
			yield participant.handle


# Returns True if the chat was newly created, False if it already existed
def init_chat_log(chat_name : str):
	init_chats_confobj()
	if not chat_name in chats[chats_with_logs_index]:
		chats[chats_with_logs_index][chat_name] = 0
		chats.write()
		chat_state = get_chat_state(chat_name)
		init_chat_state(chat_state)
		return True
	else:
		return False
	
def init_chat_state(chat_state):
	if not chat_participants_index in chat_state:
		chat_state[chat_participants_index] = {}
		chat_state[chat_content_index] = {}
		chat_state.write()
	else:
		print(f'Overwriting existing chat log file - the record did not indicate that chat {chat_state.filename} would exist.')

def get_chat_log_length(chat_name):
	init_chats_confobj()
	return int(chats[chats_with_logs_index][chat_name])


### The channel budget

def try_to_add_active_chat(actor_id : str):
	chat_channel_budget = get_channel_budget()
	if actor_id in chat_channel_budget:
		prev_number = int(chat_channel_budget[actor_id])
		if prev_number < channel_limit_per_actor:
			chat_channel_budget[actor_id] = str(prev_number + 1)
			chat_channel_budget.write()
			return True
		else:
			return False
	else:
		chat_channel_budget[actor_id] = 1
		chat_channel_budget.write()
		return True

def decrease_num_active_chats(actor_id : str):
	chat_channel_budget = get_channel_budget()
	if actor_id in chat_channel_budget:
		prev_number = int(chat_channel_budget[actor_id])
		if prev_number > 0:
			chat_channel_budget[actor_id] = str(prev_number - 1)
			chat_channel_budget.write()
	else:
		chat_channel_budget[actor_id] = 0
		chat_channel_budget.write()


### Creating a new chat

async def create_chat_from_command(user_id : str, partner_handle_id : str):
	creator_actor_id = players.get_player_id(user_id, expect_to_find=True)
	creator_handle = handles.get_active_handle(creator_actor_id)
	if not creator_handle.is_active():
		return f'Error: tried to open chat but could not find active handle for initiator {creator_actor_id}.'
	return await create_2party_chat(creator_handle, partner_handle_id)

async def create_2party_chat_from_handle_id(my_handle_id : str, partner_handle_id : str):
	my_handle : Handle = handles.get_handle(my_handle_id)
	if not my_handle.is_active():
		return f'Tried to open chat but initiator handle {my_handle_id} does not exist.'
	return await create_2party_chat(my_handle, partner_handle_id)

# TODO: Split this into create_2party_chat and create_chat, where the latter takes my_handle and [other_handles]
async def create_2party_chat(my_handle : Handle, partner_handle_id : str):
	if not game.is_2party_chat_possible(my_handle.handle_id, partner_handle_id):
		return '```[OFF: network unavailable -- right now you can chat with gm and similar but not others]```'

	if my_handle.handle_id == partner_handle_id:
		return f'Error: {partner_handle_id} is your current handle – cannot open chat with yourself.'

	partner_handle : Handle = handles.get_handle(partner_handle_id)
	if not partner_handle.is_active():
		return f'Error: could not open chat with {partner_handle_id}; recipient does not exist.'

	# data common to both participants:
	chat_name = create_2party_chat_name(my_handle, partner_handle)
	# Chat-specific config: will hold all history, but also actors' active handles and channels
	newly_created_chat = init_chat_log(chat_name)
	if newly_created_chat:
		channels.init_chat_channel(chat_name)

	chat_state = get_chat_state(chat_name)

	# Always activate my own session:
	task_add_me = asyncio.create_task(
		add_participant_to_chat(
			chat_state,
			chat_name,
			my_handle,
			port_name = partner_handle.handle_id,
			activation = Activation.Open
		)
	)

	# For the partner, the session will not be activated.
	# We will get a reference to the UI from the partner's side as well, but it will
	# only contain a channel if we are re-opening a chat that was already open in their end
	task_add_partner = asyncio.create_task(
		add_participant_to_chat(
			chat_state,
			chat_name,
			partner_handle,
			port_name = my_handle.handle_id
		)
	)

	[my_ui, partner_ui] = await asyncio.gather(task_add_me, task_add_partner)
	if my_ui.channel is None:
		clickable_chat_hub = channels.clickable_channel_ref(actors.get_chat_hub_channel(my_handle.actor_id))
		report = (f'Created chat {chat_name}, but it is currently closed since you have too many chat sessions open. '
			+ f'You can access the chat from {clickable_chat_hub}, if you close another chat first.')
		return report
	my_clickable_ref = channels.clickable_channel_ref(my_ui.channel)
	partner_clickable_ref = channels.clickable_channel_ref(partner_ui.channel) if partner_ui.channel is not None else None

	if not newly_created_chat:
		report = f'Re-opened chat between {my_handle.handle_id} and {partner_handle.handle_id}: {my_clickable_ref}'
		if partner_clickable_ref is not None:
			# TODO: this is only here during testing
			# non-admins should not see their partner's channel even if it does exist.
			report += f'(Other channel is available at {partner_clickable_ref})'
	elif my_handle.actor_id == partner_handle.actor_id:
		report = (f'Opened chat between {my_handle.handle_id} and {partner_handle.handle_id}. '
			+ 'Note that both handles are controlled by you, so you will be chatting with yourself. '
			)
		if partner_clickable_ref is not None:
			report += f'Channels are available at {my_clickable_ref} and {partner_clickable_ref}.'
		else:
			report += f'Channel is available at {my_clickable_ref}.'
	else:
		report = f'Opened chat between {my_handle.handle_id} and {partner_handle.handle_id}: {my_clickable_ref}'
	return report



### Common method used both when creating and re-opening chats

async def add_participant_to_chat(
	chat_state,
	chat_name : str,
	handle : Handle,
	port_name : str,
	activation : Activation=Activation.No
	):
	channel_name = f'{handle.handle_id}_to_{port_name}'
	
	guild = actors.get_guild_for_actor(handle.actor_id)
	participant : ChatParticipant = read_participant(chat_state, handle.handle_id)
	if participant == None:
		# This is a newly added participant
		participant = create_new_participant(chat_name, channel_name, session_status_inactive, handle)
	return await get_chat_ui(guild, chat_state, participant, activation)

def create_new_participant(chat_name : str, channel_name : str, session_status : str, handle : Handle):
	return ChatParticipant(
		chat_name,
		session_status,
		channel_name,
		handle.actor_id,
		handle.handle_id,
		chat_hub_msg_id=None,
		channel_id=None)

async def get_chat_ui(guild, chat_state, participant : ChatParticipant, activation : Activation=Activation.No):
	# Chat already exists
	if participant.session_status in [session_status_active, session_status_open_archive]:
		# Chat not only exists, but is already open
		return await get_chat_ui_for_active_session(guild, participant)
	else:
		# Chat exists but channel has been closed
		return await get_chat_ui_for_inactive_session(
			guild,
			chat_state,
			participant,
			activation
		)


async def get_chat_ui_for_active_session(guild, participant):
	if participant.channel_id is None or participant.chat_hub_msg_id is None:
		raise RuntimeError(f'Chat session {participant.handle} : {participant.chat_name} is listed as active, '
			+ 'but missing either channel_id or chat_hub_msg_id'
		)
	chat_channel = channels.get_discord_channel(participant.channel_id, guild.id)

	chat_hub_channel = actors.get_chat_hub_channel(participant.actor_id)
	chat_hub_message = await chat_hub_channel.fetch_message(participant.chat_hub_msg_id)

	return ChatUI(
		participant.chat_name,
		chat_channel,
		chat_hub_message,
		participant.session_status,
		participant.handle,
		participant.actor_id)


async def get_chat_ui_for_inactive_session(guild, chat_state, participant : ChatParticipant, activation : Activation):
	if (participant.session_status in [session_status_active, session_status_open_archive]
		or participant.channel_id is not None):
		raise RuntimeError(f'Instructed to open session but it appears to be active. Dump: {participant.to_string()}')

	channel = None

	status_change = False
	valid_activation_reason = (
		activation == Activation.Open
		or (activation == Activation.Msg
			and participant.session_status in [session_status_inactive, session_status_unread]
		)
	)
	if valid_activation_reason:
		can_be_activated = try_to_add_active_chat(participant.actor_id)
		if can_be_activated:
			if participant.session_status == session_status_closed_archive:
				participant.session_status = session_status_open_archive
			else:
				participant.session_status = session_status_active
			channel = await create_channel_for_chat_session(guild, chat_state, participant)
			participant.channel_id = str(channel.id)
			# channel ID -> chat mapping
			chat_connection = ChatConnectionMapping(participant.chat_name, participant.actor_id, participant.handle)
			store_chat_connection_for_channel(guild.id, participant.channel_id, chat_connection)
			status_change = True

	chat_hub_message = await update_chat_hub_message(channel, participant, has_changed=status_change)
	participant.chat_hub_msg_id = str(chat_hub_message.id)

	# chat -> actor, channel ID, msg ID mapping
	# 'participant' may have been updated: 
	store_participant(participant.chat_name, participant)

	return ChatUI(
		participant.chat_name,
		channel,
		chat_hub_message,
		participant.session_status,
		participant.handle,
		participant.actor_id
	)

async def create_channel_for_chat_session(guild, chat_state, participant : ChatParticipant):
	archived = participant.session_status in [session_status_open_archive, session_status_closed_archive]
	if players.is_player(participant.actor_id):
		category_index = players.get_player_category_index(participant.actor_id)
	else:
		category_index = 6
	channel = await channels.create_chat_session_channel_no_role(guild, participant.channel_name, read_only=archived, category_index=category_index)
	await channel.send(
		(
			f'```This is the start of {participant.channel_name}. '
			+ f'In this chat, you will always appear as \"{participant.handle}\", even if you switch handles elsewhere.```'
		)
	)

	await repost_message_history(channel, chat_state, participant)

	# At this point we want to give permissions (prevent unread from before)
	await actors.give_actor_access(channel, participant.actor_id)
	return channel

async def open_chat_from_reaction(chat_state, participant : ChatParticipant):
	guild = actors.get_guild_for_actor(participant.actor_id)
	# activate the session:
	chat_ui = await get_chat_ui(guild, chat_state, participant, activation=Activation.Open)
	return chat_ui.session_status in [session_status_active, session_status_open_archive]


### The messages in the chat_hub channel, which are linked to and from the chat state itself

def generate_hub_msg_active_session(discord_channel, handle_id : str):
	clickable_ref = channels.clickable_channel_ref(discord_channel)
	content = (f'> Chat name: {clickable_ref}\n'
		+ f'> Your identity: **{handle_id}**\n'
		+ f'> Status: {emoji_green}  **connected**\n'
		+ f'> To close connection, click on the {emoji_cancel} below.'
	)
	return content

def generate_hub_msg_inactive_session(chat_title : str, handle_id : str):
	content = (f'> Chat name: **{chat_title}**\n'
		+ f'> Your identity: **{handle_id}**\n'
		+ f'> Status: {emoji_red}  **not connected** (no unread messages)\n' # TODO
		+ f'> To open connection, click on the {emoji_open} below.'
	)
	return content

def generate_hub_msg_unread_session(chat_title : str, handle_id : str):
	content = (f'> Chat name: **{chat_title}**\n'
		+ f'> Your identity: **{handle_id}**\n'
		+ f'> Status: {emoji_red} {emoji_unread} **not connected – unread messages** \n' # TODO
		+ f'> To open connection, click on the {emoji_open} below.'
	)
	return content

def generate_hub_msg_open_archived_session(discord_channel, handle_id : str):
	clickable_ref = channels.clickable_channel_ref(discord_channel)
	content = (f'> Chat name: {clickable_ref}\n'
		+ f'> Your identity: **{handle_id}**\n'
		+ f'> Status: {emoji_green_book}  **archived** – **connected** to log server\n'
		+ f'> To close archive, click on the {emoji_cancel} below.'
	)
	return content

def generate_hub_msg_closed_archived_session(chat_title : str, handle_id : str):
	content = (f'> Chat name: **{chat_title}**\n'
		+ f'> Your identity: **{handle_id}**\n'
		+ f'> Status: {emoji_red_book}  **archived** – **not connected** to log server\n'
		+ f'> To read archive, click on the {emoji_open} below.'
	)
	return content

def generate_hub_msg(handle_id : str, session_status : str, chat_title : str=None, discord_channel=None):
	if session_status == session_status_active:
		if discord_channel is None:
			raise RuntimeError(f'Attempted to write chat hub msg for active session, but there is no channel. Dump: {handle_id}')
		return generate_hub_msg_active_session(discord_channel, handle_id)
	elif session_status == session_status_inactive:
		return generate_hub_msg_inactive_session(chat_title, handle_id)
	elif session_status == session_status_unread:
		return generate_hub_msg_unread_session(chat_title, handle_id)
	elif session_status == session_status_open_archive:
		return generate_hub_msg_open_archived_session(discord_channel, handle_id)
	elif session_status == session_status_closed_archive:
		return generate_hub_msg_closed_archived_session(chat_title, handle_id)
	else:
		return "Archived chat -- not implemented yet!"

async def update_chat_hub_message(chat_channel, participant, has_changed : bool=False, repost : bool=False):
	message = None
	chat_hub_channel = actors.get_chat_hub_channel(participant.actor_id)
	if participant.chat_hub_msg_id is not None:
		try:
			message = await chat_hub_channel.fetch_message(participant.chat_hub_msg_id)
		except discord.errors.NotFound:
			# No message found -- we will create a new one
			pass

	if message is None or has_changed:
		# TODO: with multi-part chats, the title should be the chat name
		# but for 2party ones it should be the channel name
		new_content = generate_hub_msg(participant.handle, participant.session_status, participant.channel_name, chat_channel)
		if message is None:
			message = await chat_hub_channel.send(new_content)
		elif repost:
			# Delete the message and post a new one -- will make sure it shows up as unread
			clear_hub_msg_connection_mapping(str(message.id))
			await message.delete()
			message = await chat_hub_channel.send(new_content)
		else:
			# Pre-existing message, but we must update it
			edit_task = asyncio.create_task(message.edit(content=new_content))
			clear_reactions_task = asyncio.create_task(message.clear_reactions())
			await asyncio.gather(edit_task, clear_reactions_task)
	await add_initial_reaction_chat_hub_msg(message, participant.session_status)

	chat_connection = ChatConnectionMapping(participant.chat_name, participant.actor_id, participant.handle)
	store_chat_connection_for_hub_msg(str(message.id), chat_connection)

	return message

async def add_initial_reaction_chat_hub_msg(message, session_status : str):
	initial_emoji = (
		emoji_cancel
		if session_status in [session_status_active, session_status_open_archive]
		else emoji_open)
	await message.add_reaction(initial_emoji)

async def process_reaction_in_chat_hub(message, emoji : str):
	await message.clear_reaction(emoji)

	message_id = str(message.id)

	chat_connection : ChatConnectionMapping = read_chat_connection_from_hub_msg(message_id)
	if chat_connection == None:
		# Error: reacted to old message in chat hub, not connected to any active chat.
		return f'Error: reacted on msg {message_id} chat hub, but it was not connected to any existing chat.'

	chat_state = get_chat_state(chat_connection.chat_name)
	participant : ChatParticipant = read_participant(chat_state, chat_connection.handle)

	if (participant.session_status in [session_status_active, session_status_open_archive]
		and emoji == emoji_cancel
		):
		# Ignore return value -- it's not worth the effort to send it to actor's command line
		# (and they may not even have one)
		await close_chat_session(participant)
	elif (participant.session_status in [session_status_inactive, session_status_unread, session_status_closed_archive]
		and emoji == emoji_open
		):
		success = await open_chat_from_reaction(chat_state, participant)
		if not success:
			warning = f'Cannot open {chat_connection.chat_name} -- you have too many open chats! Close one before opening another.'
			await message.channel.send(content = warning, delete_after=6)
	return None


### Closing chats

async def close_chat_session_from_command(ctx, partner_handle_id : str):
	my_user_id = str(ctx.message.author.id)
	my_actor_id = players.get_player_id(my_user_id)
	my_handle = handles.get_handle(my_actor_id)
	return await close_2party_chat_session(my_handle, partner_handle_id)

async def close_2party_chat_session_from_handle_id(my_handle_id : str, partner_handle_id : str):
	my_handle : Handle = handles.get_handle(my_handle_id)
	if not my_handle.is_active():
		return f'Error: Tried to close chat but initiator handle {my_handle_id} does not exist.'
	return await close_2party_chat_session(my_handle, partner_handle_id)


async def close_2party_chat_session(my_handle : Handle, partner_handle_id : str):
	if my_handle.handle_id == partner_handle_id:
		return f'Error: {partner_handle_id} is your current handle – there is no chat.'

	partner_handle : Handle = handles.get_handle(partner_handle_id)
	if not partner_handle.is_active():
		return f'Error: no chat with {partner_handle.handle_id} found; recipient does not exist. Check the spelling.'

	chat_name = create_2party_chat_name(my_handle, partner_handle)
	if not chat_exists(chat_name):
		return f'Error: there is no record of any chat between {my_handle.handle_id} and {partner_handle.handle_id}.'

	chat_state = get_chat_state(chat_name)
	participant : ChatParticipant = read_participant(chat_state, my_handle.handle_id)

	failure_report = await close_chat_session(participant)
	if failure_report is None:
		return f'Closed chat session with {partner_handle.handle_id}. To re-open, use \".chat {partner_handle.handle_id}\".'
	else:
		return failure_report


async def close_chat_session(participant : ChatParticipant):
	print(f'Trying to close {participant.chat_name}, for {participant.handle}')

	# update chat -> channel ID mapping
	should_log = True
	if participant.session_status == session_status_active:
		participant.session_status = session_status_inactive
	elif participant.session_status == session_status_open_archive:
		participant.session_status = session_status_closed_archive
		should_log = False
	else:
		return f'Tried to close {participant.chat_name} for {participant.handle} but the session was not open.'

	if participant.channel_id is None:
		raise RuntimeError(f'Attempted to close {participant.chat_name} for {participant.handle}, recorded as active, '
			+'but channel ID is missing. Dump: {participant.to_string()}'
		)

	decrease_num_active_chats(participant.actor_id)
	channel_id_to_close = participant.channel_id
	guild_id = actors.get_guild_for_actor(participant.actor_id).id

	# Update participant
	participant.channel_id = None

	# Remove channel ID -> chat mapping
	clear_channel_connection_mappings(guild_id, channel_id_to_close)

	# TODO: we could put the channel closing and the chat hub update in an asyncio.gather if we wanted

	# Close the session, i.e. delete the actor's discord channel
	await channels.delete_discord_channel(channel_id_to_close, guild_id)

	chat_hub_message = await update_chat_hub_message(None, participant, has_changed=True)
	participant.chat_hub_msg_id = str(chat_hub_message.id)

	# 'participant' is the chat -> actor, channel ID, msg ID mapping
	store_participant(participant.chat_name, participant)

	if should_log:
		# Add chat log entry for this event
		entry = ChatLogEntry(None, closed_handle_id=participant.handle)
		write_new_chat_log_entry(participant.chat_name, entry)


### Archiving chats -- currently only happens when burning burner handles

async def archive_all_chats_for_handle(handle : Handle):
	task_list = []
	for (chat_name, chat_state) in get_chats_for_handle(handle):
		task_list.append(asyncio.create_task(archive_chat_for_handle(handle, chat_name, chat_state)))
	await asyncio.gather(*task_list)

def participant_is_handle(handle : Handle, participant : ChatParticipant):
	return participant.handle == handle.handle_id

def is_archived(participant : ChatParticipant):
	return participant.session_status in [session_status_open_archive, session_status_closed_archive]

async def archive_chat_for_handle(handle: Handle, chat_name : str, chat_state):
	participants = list(get_participants(chat_state))
	participant_to_archive = next(p for p in participants if participant_is_handle(handle, p))
	archived_participant = await archive_chat_for_participant(chat_state, participant_to_archive)
	store_participant(chat_name, archived_participant)

	other_participants = [p for p in participants if not participant_is_handle(handle, p)]
	is_non_archived = [1 for p in other_participants if not is_archived(p)]

	archive_for_remaining = len(is_non_archived) <= 1

	print(f'Archiving chat for {handle.handle_id}. Other participant is {other_participants[0].to_string()}. is_non_archived: {is_non_archived}, archive_for_remaining: {archive_for_remaining}')
	task_list = (
		asyncio.create_task(
			update_other_participant_after_archiving(p, handle, chat_state, archive_for_remaining)
		) for p in other_participants
	)
	await asyncio.gather(*task_list)


async def archive_chat_for_participant(chat_state, participant : ChatParticipant):
	guild = actors.get_guild_for_actor(participant.actor_id)
	chat_ui = await get_chat_ui(guild, chat_state, participant)
	if chat_ui.session_status == session_status_active:
		participant.session_status = session_status_open_archive
		await chat_ui.channel.send(get_archived_alert(participant.handle))
		await channels.make_read_only(participant.channel_id, guild.id)
	elif chat_ui.session_status in [session_status_inactive, session_status_unread]:
		participant.session_status = session_status_closed_archive
	elif chat_ui.session_status in [session_status_open_archive, session_status_closed_archive]:
		# No need to do anything
		return
	else:
		raise RuntimeError(f'Unexpected session status {chat_ui.session_status}. Dump: {participant.to_string()}')

	entry = ChatLogEntry(None, archived_handle_id=participant.handle)
	write_new_chat_log_entry(participant.chat_name, entry)

	await update_chat_hub_message(chat_ui.channel, participant, has_changed=True)
	return participant

async def update_other_participant_after_archiving(
	participant : ChatParticipant,
	archived_handle : Handle,
	chat_state,
	should_be_archived : bool):
	guild = actors.get_guild_for_actor(participant.actor_id)
	if should_be_archived:
		participant = await archive_chat_for_participant(chat_state, participant)
		store_participant(participant.chat_name, participant)
	else:
		chat_ui = await get_chat_ui(guild, chat_state, participant)
		if chat_ui.session_status == session_status_active:
			await chat_ui.channel.send(get_other_unreachable_alert(archived_handle.handle_id))



### Messages in chat

async def post_to_participant(chat_state, msg_data : posting.MessageData, participant : ChatParticipant, poster_id : str, full_post : bool):
	if participant.session_status != session_status_active:
		# A new channel may be created => we should always include the full header on the first message
		full_post = True

	# Try to activate the session for the recipient
	guild = actors.get_guild_for_actor(participant.actor_id)
	chat_ui = await get_chat_ui(guild, chat_state, participant, activation=Activation.Msg)
	if chat_ui.session_status == session_status_active:
		if chat_ui.channel is None:
			print(f'Failed to reach participant of chat. Dump: {participant.to_string()}')
		else:
			# Send the message to the open channel
			poster_id = poster_id if full_post else None
			await posting.repost_message_to_channel(chat_ui.channel, msg_data, poster_id)
	elif chat_ui.session_status == session_status_inactive:
		# The channel was not opened when requested -- recipient must be at their chat session limit
		participant.session_status = session_status_unread
		# Update and repost the chat hub message:
		chat_hub_message = await update_chat_hub_message(chat_ui.channel, participant, has_changed=True, repost=True)
		participant.chat_hub_msg_id = str(chat_hub_message.id)
		# chat -> (actor, channel ID, msg ID mapping) has been updated
		store_participant(participant.chat_name, participant)
	elif chat_ui.session_status == session_status_unread:
		# Chat already has unread messages -- nothing changes when we add one more
		pass
	elif chat_ui.session_status in [session_status_open_archive, session_status_closed_archive]:
		print(f'Just for logging: posting message in chat with archived participant {participant.handle}')
	else:
		raise RuntimeError(f'Unexpected case! Dump: {participant.to_string()}, {chat_ui.session_status}')


def create_reposting_tasks(chat_name : str, msg_data: posting.MessageData, poster_id : str, full_post : bool):
	chat_state = get_chat_state(chat_name)
	for participant in get_participants(chat_state):
		yield asyncio.create_task(post_to_participant(chat_state, msg_data, participant, poster_id, full_post))

async def process_message(message):
	await message.delete()

	sender_channel = message.channel
	chat_channel_data : ChatConnectionMapping = read_chat_connection_from_channel(sender_channel.guild.id, str(sender_channel.id))
	if chat_channel_data is None:
		return
	await process_message_data(chat_channel_data, posting.MessageData.load_from_discord_message(message))
	await auto_respond_if_needed(chat_channel_data, message)

async def auto_respond_if_needed(chat_channel_data: ChatConnectionMapping, message: discord.Message):
	chat_state = get_chat_state(chat_channel_data.chat_name)
	for participant in get_participants(chat_state):
		handle = handles.get_handle(participant.handle)
		if handle.auto_respond_message:
			actor = actors.read_actor(participant.actor_id)
			chat_channel_data_2 : ChatConnectionMapping = read_chat_connection_from_channel(actor.guild_id, participant.channel_id)
			if chat_channel_data_2:
				print("Sending auto respond message for %s" % participant.handle)
				await process_message_data(chat_channel_data_2, posting.MessageData(content=handle.auto_respond_message, created_at=message.created_at))
				break

async def process_message_data(chat_channel_data: ChatConnectionMapping, msg_data: posting.MessageData):
	poster_id = chat_channel_data.handle
	chat_name = chat_channel_data.chat_name

	# With timestamps from discord, we must apply the DST diff compared to the python env timestamps
	post_time = PostTimestamp.from_datetime(msg_data.created_at, dst_diff=2)
	full_post = channels.record_new_post(chat_channel_data.chat_name, poster_id, post_time)
	tasks = create_reposting_tasks(chat_name, msg_data, poster_id, full_post)

	await asyncio.gather(*tasks)

	# Write to the persistent log:
	# TODO: also add header if it is the first message after someone disconnected
	poster_id = poster_id if full_post else None
	post = posting.create_post(msg_data, poster_id, attachments_supported=False)
	entry = ChatLogEntry(post, full_post)
	chat_state = get_chat_state(chat_name)
	write_new_chat_log_entry(chat_name, entry)

async def repost_string_buffer(channel, string_buffer : str):
	if string_buffer != '':
		await channel.send(string_buffer)
		string_buffer = ''
	return string_buffer

def get_archived_alert(handle_id : str):
	return f'```Cannot connect to any of the recipients from {handle_id}. This chat is archived in read-only form.```'

def get_other_unreachable_alert(handle_id : str):
	return f'```====== connection lost to {handle_id} ======```'

def get_last_session_closed_alert():
	return '```====== last chat session was closed here ======```'

def get_reopened_chat_alert(chat_name : str):
	return f'```====== re-opened chat {chat_name} ======```'

async def repost_message_history(channel, chat_state, participant : ChatParticipant):
	any_history = False
	index_to_remove : int = -1
	# each entry is a ChatLogEntry
	string_buffer = ''
	for (index, entry) in get_chat_log_iterable(chat_state, participant.chat_name):
		if (entry.closed_handle_id is not None
			and entry.closed_handle_id == participant.handle
			and any_history):
			# This entry denotes the point where closed_handle_id stopped listening
			# and there has been history before this point.
			# Empty the current buffer:
			string_buffer = await repost_string_buffer(channel, string_buffer)
			# Print delimiter:
			await channel.send(get_last_session_closed_alert())
			# We don't need to remember every time someone has closed a chat, just the last one:
			index_to_remove = index
		elif (entry.archived_handle_id is not None):
			if (entry.archived_handle_id != participant.handle
			and any_history):
				# This entry denotes the point where connection was lost to another participant
				# Empty the current buffer:
				string_buffer = await repost_string_buffer(channel, string_buffer)
				# Print delimiter:
				await channel.send(get_other_unreachable_alert(entry.archived_handle_id))
			elif entry.archived_handle_id == participant.handle:
				# This denotes the point where connection was lost to us
				# We shall not read any histoy past this point
				break
		elif entry.message is not None:
			any_history = True
			if entry.header:
				# Send the buffer we have built up so far
				string_buffer = await repost_string_buffer(channel, string_buffer)
			if string_buffer == '':
				string_buffer = entry.message
			else:
				string_buffer += f'\n{entry.message}'
	# Finish by sending anything that is left over
	await repost_string_buffer(channel, string_buffer)
	if participant.session_status in [session_status_open_archive, session_status_closed_archive]:
		await channel.send(get_archived_alert(participant.handle))
	elif any_history:
		await channel.send(get_reopened_chat_alert(participant.channel_name))

	# Remove the entry that denoted last time session was closed
	# TODO: chat_log_length_at_last_close could also be tracked on a participant level
	# would probably be cleaner
	if index_to_remove != -1:
		remove_entry_from_chat_log(participant.chat_name, index_to_remove)
		
