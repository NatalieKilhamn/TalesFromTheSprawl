#module actors.py

### This module collects everything that is common to actors and shops.

import channels
import handles
import reactions
import finances
import common
import server

from custom_types import Transaction, Actor

import discord
import asyncio
from configobj import ConfigObj
import re


actors = ConfigObj('actors.conf')
actors_input = ConfigObj('actors_input.conf')


finance_statement_index = '___finance_statement_msg_id'

# TODO: loop through all users, find their actor_ids and re-map personal channels if not available
async def init(bot, guild, clear_all=False):
	if clear_all:
		for actor_id in actors:
			del actors[actor_id]
		await channels.delete_all_personal_channels(bot)
		await handles.clear_all_handles()
	await delete_all_actor_roles(guild, spare_used=(not clear_all))

	actors.write()


async def delete_all_actor_roles(guild, spare_used : bool):
	task_list = (asyncio.create_task(delete_if_actor_role(r, spare_used)) for r in guild.roles)
	await asyncio.gather(*task_list)

async def delete_if_actor_role(role, spare_used : bool):
	if common.is_personal_role(role.name):
		if not spare_used or len(role.members) == 0:
			print(f'Deleting unused role with name {role.name}')
			await role.delete()

def get_actor_role(guild, actor_id : str):
	return discord.utils.find(lambda role: role.name == actor_id, guild.roles)


def get_all_actors():
	for actor_id in actors:
		yield read_actor(actor_id)

def actor_exists(actor_id : str):
	return actor_id in get_all_actors()

def store_actor(actor : Actor):
	actors[actor.actor_id] = actor.to_string()
	actors.write()

def read_actor(actor_id : str):
	if actor_id in actors:
		return Actor.from_string(actors[actor_id])


async def give_actor_access(guild, channel, actor_id : str):
	role = get_actor_role(guild, actor_id)
	await server.give_role_access(channel, role)

async def create_new_actor(guild, actor_id : str, internal_name : str=None):
	# Create role for this actor:
	role = await guild.create_role(name=actor_id)

	# Create personal channels for user:
	chat_overwrites = server.generate_overwrites_own_new_private_channel(role)
	overwrites_finance = server.generate_overwrites_own_new_private_channel(role, read_only=True)

	chat_hub_creation = asyncio.create_task(channels.create_personal_channel(
		guild,
		chat_overwrites,
		channels.get_chat_hub_name(actor_id)
	))

	finances_creation = asyncio.create_task(channels.create_personal_channel(
		guild,
		overwrites_finance,
		channels.get_finance_name(actor_id)
	))

	[chat_hub_channel, finances_channel] = (
		await asyncio.gather(chat_hub_creation, finances_creation)
	)

	# Send welcome messages to the channels (no-one has the role to see it yet)
	chat_hub_welcome = asyncio.create_task(send_startup_message_chat_hub(chat_hub_channel, internal_name))
	finance_welcome = asyncio.create_task(send_startup_message_finance(finances_channel, internal_name))
	await asyncio.gather(chat_hub_welcome, finance_welcome)

	actor = Actor(
		actor_id=actor_id,
		finance_channel_id=finances_channel.id,
		finance_stmt_msg_id=0,
		chat_channel_id=chat_hub_channel.id)
	store_actor(actor)
	return actor

async def send_startup_message_finance(channel, name : str=None):
	if name is None:
		content = 'This is your financial record.\n'
	else:
		content = f'This is the financial record for {name}.\n'
	content = content + 'A record of every transaction will appear here. You cannot send anything in this channel.'
	await channel.send(content)

async def send_startup_message_chat_hub(channel, name : str=None):
	if name is None:
		content = 'This is your chat hub.'
	else:
		content = f'This is the chat hub for {name}.'
	content += ' All your chat connections will be visible here. If you close a chat, you can find it here to re-open it.\n '
	content += 'You can start new chats by typing \".chat <handle>\" or [NOT IMPLEMENTED YET] \".room <room_name>\".'
	await channel.send(content)

async def get_financial_statement(channel, actor : Actor):
	if actor.finance_stmt_msg_id > 0:
		return await channel.fetch_message(actor.finance_stmt_msg_id)

async def update_financial_statement(channel, actor : Actor):
	message = await get_financial_statement(channel, actor)
	if message is not None:
		await message.delete()

	report = finances.get_all_handles_balance_report(actor.actor_id)
	content = '========================\n' + report

	new_message = await channel.send(content)
	actor.finance_stmt_msg_id = new_message.id
	store_actor(actor)

async def record_transaction(transaction : Transaction):
	payer_status : handles.HandleStatus = handles.get_handle_status(transaction.payer)
	recip_status : handles.HandleStatus = handles.get_handle_status(transaction.recip)
	if payer_status.exists:
		# Special case: recip is a collector account
		if transaction.recip == common.transaction_collector:
			await write_financial_record(
				payer_status.actor_id,
				finances.generate_record_collected(transaction),
				transaction.last_in_sequence
			)
		elif recip_status.exists:
			# Both payer and recip are normal handles
			if payer_status.actor_id == recip_status.actor_id:
				# Special case: payer and recip are the same
				await write_financial_record(
					payer_status.actor_id,
					finances.generate_record_self_transfer(transaction),
					transaction.last_in_sequence
				)
			else:
				await asyncio.create_task(
					write_financial_record(
						payer_status.actor_id,
						finances.generate_record_payer(transaction),
						transaction.last_in_sequence
					)
				)
				await asyncio.create_task(
					write_financial_record(
						recip_status.actor_id,
						finances.generate_record_recip(transaction),
						transaction.last_in_sequence
					)
				)
		else:
			# Only payer exists, not recip:
			await write_financial_record(
				payer_status.actor_id,
				finances.generate_record_payer(transaction),
				transaction.last_in_sequence
			)
	elif recip_status.exists:
		# Only recip exists, not payer
		# Special case: payer is the collection from other accounts
		if transaction.payer == common.transaction_collected:
			await write_financial_record(
				recip_status.actor_id,
				finances.generate_record_collector(transaction),
				transaction.last_in_sequence
			)
		else:
			await write_financial_record(recip_status.actor_id, finances.generate_record_recip(transaction), transaction.last_in_sequence)


async def write_financial_record(actor_id : str, content : str, last_in_sequence : bool, handle : str = None):
	if actor_id is None:
		if handle is not None:
			actor_status : handles.HandleStatus = handles.get_handle_status(handle)
			if actor_status.exists:
				actor_id = actor_status.actor_id
	actor = read_actor(actor_id)
	if actor is None:
		raise RuntimeError(f'Trying to write financial record but could not find which actor it belongs to.')
	channel = channels.get_discord_channel(actor.finance_channel_id)
	if content is not None:
		await channel.send(content)
	if last_in_sequence:
		await update_financial_statement(channel, actor)

def get_actor_for_handle(handle : str):
	actor_status : handles.HandleStatus = handles.get_handle_status(handle)
	if actor_status.exists:
		return read_actor(actor_status.actor_id)

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
