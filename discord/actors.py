#module actors.py

### This module collects everything that is common to actors and shops.

import channels
import handles
import reactions
import finances
import common
import server
import shops
import players

from custom_types import Transaction, Actor, TransTypes
from common import emoji_cancel, emoji_open

import discord
import asyncio
from configobj import ConfigObj
import re

actors_conf_dir = 'actors'
finance_channel_mapping_index = '___finance_channels'

def get_actors_confobj():
	actors = ConfigObj(actors_conf_dir + '/__actors.conf')
	if not finance_channel_mapping_index in actors:
		actors[finance_channel_mapping_index] = {}
		actors.write()
	return actors

async def init(guild, clear_all=False):
	await shops.init(guild, clear_all=clear_all)
	await players.init(guild, clear_all=clear_all)
	get_actors_confobj() # ensures it's properly initialised
	if clear_all:
		for actor_id in get_all_actor_ids():
			await clear_actor(guild, actor_id)
		await channels.delete_all_personal_channels()
		await handles.clear_all_handles()
	else:
		for actor in get_all_actors():
			await handles.init_handles_for_actor(actor.actor_id, overwrite=False)
			# TODO: re-map all personal channels?
	await delete_all_actor_roles(guild, spare_used=(not clear_all))

async def clear_actor(guild, actor_id : str):
	if actor_exists(actor_id):
		# TODO: clear out/archive chat participants from all chats? Not required unless we expect to create and destroy actors during game
		actor = read_actor(actor_id)
		finance_channel_id = str(actor.finance_channel_id)
		actors = get_actors_confobj()
		if finance_channel_id in actors[finance_channel_mapping_index]:
			del actors[finance_channel_mapping_index][finance_channel_id]
		del actors[actor_id]
		actors.write()
		clear_trans_memory(actor_id)
		await channels.delete_all_personal_channels(channel_suffix=actor.actor_id)
		await handles.clear_all_handles_for_actor(actor_id)
		shops.delete_delivery_ids_for_actor(actor_id)
		await delete_all_actor_roles(guild, spare_used=True)
		return 'Done'
	else:
		return f'Could not find actor {actor_id}'


async def delete_all_actor_roles(guild, spare_used : bool):
	task_list = (asyncio.create_task(delete_if_actor_role(r, spare_used)) for r in guild.roles)
	await asyncio.gather(*task_list)

async def delete_if_actor_role(role, spare_used : bool):
	if await is_actor_role(role.name):
		in_use = actor_index_in_use(role.name) or len(role.members) > 0
		if not in_use or not spare_used:
			await role.delete()

async def is_actor_role(name :str):
	return common.is_player_role(name) or common.is_shop_role(name)

def get_actor_role(guild, actor_id : str):
	actor = read_actor(actor_id)
	if actor is not None:
		return discord.utils.find(lambda role: role.name == actor.role_name, guild.roles)



def get_all_actors():
	for actor_id in get_all_actor_ids():
		yield read_actor(actor_id)

def get_all_actor_ids():
	actors = get_actors_confobj()
	for actor_id in actors:
		if actor_id != finance_channel_mapping_index:
			yield actor_id


def actor_exists(actor_id : str):
	actors = get_actors_confobj()
	return actor_id in actors

def actor_index_in_use(actor_index : str):
	for actor in get_all_actors():
		if actor.role_name == actor_index:
			return True
	return False

def store_actor(actor : Actor):
	actors = get_actors_confobj()
	actors[actor.actor_id] = actor.to_string()
	actors[finance_channel_mapping_index][str(actor.finance_channel_id)] = actor.actor_id
	actors.write()

def read_actor(actor_id : str):
	if actor_id in get_all_actor_ids():
		actors = get_actors_confobj()
		return Actor.from_string(actors[actor_id])

def get_owner_of_finance_channel(channel_id : str):
	actors = get_actors_confobj()
	if channel_id in actors[finance_channel_mapping_index]:
		return actors[finance_channel_mapping_index][channel_id]




recent_transactions_suffix = '_recent_trans.conf'

def get_trans_mem(actor_id : str):
	trans_mem_file_name = f'{actor_id}{recent_transactions_suffix}'
	return ConfigObj(f'{actors_conf_dir}/{trans_mem_file_name}')

def get_all_recent_trans(actor_id : str):
	if actor_exists(actor_id):
		trans_mem = get_trans_mem(actor_id)
		for msg_id in trans_mem:
			yield read_transaction_from_memory(trans_mem, msg_id)

def store_transaction(actor_id : str, msg_id : str, transaction : Transaction):
	if actor_exists(actor_id):
		trans_mem = get_trans_mem(actor_id)
		trans_mem[msg_id] = transaction.to_string()
		trans_mem.write()

def delete_transaction(actor_id : str, msg_id : str):
	if actor_exists(actor_id):
		trans_mem = get_trans_mem(actor_id)
		if msg_id in trans_mem:
			del trans_mem[msg_id]
			trans_mem.write()

def read_transaction(actor_id : str, msg_id : str):
	if actor_exists(actor_id):
		trans_mem = get_trans_mem(actor_id)
		return read_transaction_from_memory(trans_mem, msg_id)

def read_transaction_from_memory(trans_mem, msg_id : str):
	if msg_id in trans_mem:
		return Transaction.from_string(trans_mem[msg_id])

def clear_trans_memory(actor_id : str):
	if actor_exists(actor_id):
		trans_mem = get_trans_mem(actor_id)
		for entry in trans_mem:
			del trans_mem[entry]
		trans_mem.write()



async def give_actor_access(guild, channel, actor_id : str):
	role = get_actor_role(guild, actor_id)
	await server.give_role_access(channel, role)

async def create_new_actor(guild, actor_index : str, actor_id : str, existing_role_name : str=None):
	if existing_role_name is None:
		# Create role for this actor:
		role = await guild.create_role(name=actor_index)
	else:
		role = discord.utils.find(lambda role: role.name == existing_role_name, guild.roles)

	return await create_new_actor_with_role(guild, role, actor_id)

# TODO: change GM handles to a special handle type that cannot handle money
#       and remove the GM's financial channel completely
async def create_gm_actor(guild, role_name : str, actor_id : str):
	role = discord.utils.find(lambda role: role.name == role_name, guild.roles)
	return await create_new_actor_with_role(guild, role, actor_id, is_gm=True)

async def create_new_actor_with_role(guild, role, actor_id : str, is_gm : bool=False):
	# Create personal channels for user:
	chat_hub_creation = asyncio.create_task(channels.create_personal_channel(
		guild,
		role,
		channels.get_chat_hub_name(actor_id),
		actor_id
	))

	finances_creation = asyncio.create_task(channels.create_personal_channel(
		guild,
		role,
		channels.get_finance_name(actor_id),
		actor_id,
		read_only=True
	))

	[chat_hub_channel, finances_channel] = (
		await asyncio.gather(chat_hub_creation, finances_creation)
	)

	# Send welcome messages to the channels (no-one has the role to see it yet)
	chat_hub_welcome = asyncio.create_task(send_startup_message_chat_hub(chat_hub_channel, actor_id, is_gm))
	finance_welcome = asyncio.create_task(send_startup_message_finance(finances_channel, actor_id))
	init_handles = asyncio.create_task(handles.init_handles_for_actor(actor_id))
	await asyncio.gather(chat_hub_welcome, finance_welcome, init_handles)

	actor = Actor(
		role_name=role.name,
		actor_id=actor_id,
		finance_channel_id=finances_channel.id,
		finance_stmt_msg_id=0,
		chat_channel_id=chat_hub_channel.id)
	store_actor(actor)
	clear_trans_memory(actor_id)
	return actor

async def send_startup_message_finance(channel, actor_id : str):
	content = f'This is the financial record for {actor_id}.\n'
	content = content + 'A record of every transaction—involving any handle you control—will appear here. You cannot send anything in this channel.'
	await channel.send(content)

async def send_startup_message_chat_hub(channel, actor_id : str, is_gm : bool):
	if is_gm:
		content = 'This is the GM chat hub. The GM handles are shared between all GMs and you cannot start new chats from them.\n'
		content += 'When other players want to chat with GM, they will show up here. You can open and close those chats just like your personal ones.\n'
		content += 'Remember: all of the GMs can see and respond to all these chats! Communicate with each other to avoid chaos!'
	else:
		content = f'This is the chat hub for {actor_id}. '
		content += 'You can start new chats by typing \"**.chat** *handle*\", for example \".chat gm\".\n' # or [NOT IMPLEMENTED YET] \".room <room_name>\".'
		content += f'Once you have started a chat, you will see it below, and you can close and re-open it by clicking the {emoji_cancel} and {emoji_open} below the message.\n '
	await channel.send(content)

def get_actor_for_handle(handle_id : str):
	handle : handles.Handle = handles.get_handle(handle_id)
	if handle.actor_id is not None:
		return read_actor(handle.actor_id)

def get_finance_channel_for_handle(handle : str):
	actor : Actor = get_actor_for_handle(handle)
	if actor is not None:
		return channels.get_discord_channel(actor.finance_channel_id)

def get_finance_channel(actor_id : str):
	actor : Actor = read_actor(actor_id)
	if actor is not None:
		return channels.get_discord_channel(actor.finance_channel_id)

def get_chat_hub_channel_for_handle(handle : str):
	actor : Actor = get_actor_for_handle(handle)
	if actor is not None:
		return channels.get_discord_channel(actor.chat_channel_id)

def get_chat_hub_channel(actor_id : str):
	actor : Actor = read_actor(actor_id)
	if actor is not None:
		return channels.get_discord_channel(actor.chat_channel_id)


async def get_financial_statement(channel, actor : Actor):
	if actor.finance_stmt_msg_id > 0:
		try:
			return await channel.fetch_message(actor.finance_stmt_msg_id)
		except discord.errors.NotFound:
			pass

async def update_financial_statement(channel, actor : Actor):
	message = await get_financial_statement(channel, actor)
	if message is not None:
		await message.delete()

	report = finances.get_all_handles_balance_report(actor.actor_id)
	content = '========================\n' + report

	new_message = await channel.send(content)
	actor.finance_stmt_msg_id = new_message.id
	store_actor(actor)

async def refresh_financial_statement(actor_id : str):
	actor = read_actor(actor_id)
	if actor is None:
		raise RuntimeError(f'Trying to write financial record but could not find which actor it belongs to.')
	channel = channels.get_discord_channel(actor.finance_channel_id)
	await update_financial_statement(channel, actor)

async def write_financial_record(transaction : Transaction, payer_record : str=None, recip_record : str=None):
	def send_record_task(actor_id : str, record : str):
		return asyncio.create_task(send_financial_record_for_actor(actor_id, record, transaction.last_in_sequence))

	task_list = (
		send_record_task(a, r)
		for (a, r)
		in [(transaction.payer_actor, payer_record), (transaction.recip_actor, recip_record)]
	)
	[payer_message, sender_message] = await asyncio.gather(*task_list)

	if transaction.cause == TransTypes.ShopOrder:
		if payer_message is not None:
			await payer_message.add_reaction(emoji_cancel)
			transaction.payer_msg_id = str(payer_message.id)
		if sender_message is not None:
			await sender_message.add_reaction(emoji_cancel)
			transaction.recip_msg_id = str(sender_message.id)
		# After completing both, the transaction object is complete and can be stored
		if payer_message is not None:
			store_transaction(transaction.payer_actor, transaction.payer_msg_id, transaction)
		if sender_message is not None:
			store_transaction(transaction.recip_actor, transaction.recip_msg_id, transaction)


async def send_financial_record_for_actor(actor_id : str, record : str, last_in_sequence):
	if record is not None:
		actor = read_actor(actor_id)
		if actor is None:
			raise RuntimeError(f'Trying to write financial record but could not find which actor it belongs to.')
		channel = channels.get_discord_channel(actor.finance_channel_id)
		message = await channel.send(record)
		if last_in_sequence:
			await update_financial_statement(channel, actor)
		return message

async def lock_tentative_transaction(actor_id : str, msg_id : str):
	delete_transaction(actor_id, msg_id)
	channel = get_finance_channel(actor_id)
	if channel is None:
		raise RuntimeError(f'Error: trying to edit financial record but could not find the channel for {actor_id}.')
		return
	try:
		message = await channel.fetch_message(int(msg_id))
		await message.clear_reactions()
	except discord.errors.NotFound:
		print(f'Tried to lock in transaction with msg_id {msg_id} for {actor_id}, but message has been removed.')
		return


async def remove_tentative_transaction(actor_id : str, msg_id : str):
	delete_transaction(actor_id, msg_id)
	channel = get_finance_channel(actor_id)
	if channel is None:
		raise RuntimeError(f'Trying to edit financial record but could not find the channel for {actor_id}.')
	message = await channel.fetch_message(int(msg_id))
	if message is None:
		print(f'Tried to remove transaction record with msg_id {msg_id} for {actor_id}, but message has already been removed.')
		return
	await message.delete()




## Reactions:

async def process_reaction_in_finance_channel(channel_id : str, msg_id : str, emoji : str):
	actor_id = get_owner_of_finance_channel(channel_id)

	transaction : Transaction = read_transaction(actor_id, msg_id)
	if transaction is None or emoji != emoji_cancel:
		# Either this message cannot trigger any actions based on emoji, or the wrong emoji was used
		return

	await shops.attempt_refund(transaction, actor_id)
	if transaction is not None:
		print(f'Attempted refund, success: {transaction.success}, report: {transaction.report}')
		if not transaction.success and transaction.report is not None:
			channel = channels.get_discord_channel(channel_id)
			await channel.send(content=transaction.report, delete_after=10)
		


