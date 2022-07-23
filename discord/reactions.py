import datetime
import random
import asyncio
import discord

import posting
import channels
import finances
import players
import actors
import custom_types
import chats
import shops
import game

from custom_types import ActionResult
from common import coin

# good-to-have emojis:
# ✅
# ❇️
# ❌
# 🟥
# 🔥

reactions_worth_money = {'💴' : 1, '💸' : 1, '💰' : 1, '🍺' : 1, '💯' : 100, '🪙' : 1}
chat_reactions = ['📧', '💬', '🗨️', '❔', '❓', '❕', '❗']

def init():
	clear_reaction_semaphores()

async def remove_reaction(message, emoji, user_id : int):
	member = await message.channel.guild.fetch_member(user_id)
	if member == None:
		print(f'Error: tried to remove reaction but member not found, user_id is {user_id}')
	else:
		await message.remove_reaction(emoji, member)

def get_common_reactions_summary_string():
	tipping_emojis = dict()
	for emoji, amount in reactions_worth_money.items():
		if amount in tipping_emojis:
			tipping_emojis[amount].append(emoji)
		else:
			tipping_emojis[amount] = [emoji]
	report = ''
	for amount, emojis in tipping_emojis.items():
		emojis_commas = ', '.join(emojis)
		report += f'{emojis_commas}: give author {coin} {str(amount)}\n'
	#report += f'{', '.join(chat_reactions)}: start a chat with author'
	return report



class ReactionRecipientSearchResult:
    message = None
    recipient : str = None

async def find_reaction_recipient_and_message(message_id : int, channel):
	result = ReactionRecipientSearchResult()
	partial_message = channel.get_partial_message(message_id)

	epsilon = datetime.timedelta(milliseconds=500)
	timestamp = partial_message.created_at + epsilon
	message_history = await channel.history(limit=20, before=timestamp).flatten()
	for message in message_history:
		if message.id == message_id:
			result.message = message
		if result.message == None:
			# We fetched a few messages that actually came after the original one (within 500 ms)
			continue
		match = posting.read_handle_from_post(message.content)
		if match != None:
			#print(f'Recorded reaction on post by {match}')
			result.recipient = match
			break
	return result

async def process_reaction_on_other_handle(message_id : int, user_id : int, channel, emoji):
	search_result : ReactionRecipientSearchResult = await find_reaction_recipient_and_message(message_id, channel)
	if search_result.recipient is None:
		print(f'Error! Could not find recipient for message in channel {channel.name}.')
		return

	# Currently only one use case for reading reactions, and that is for paying money
	emoji_str = str(emoji)
	if emoji_str in reactions_worth_money:
		payment_amount = reactions_worth_money[emoji_str]
		if payment_amount > 0:
			player_id = players.get_player_id(str(user_id))
			transaction : custom_types.Transaction = await finances.try_to_pay_from_actor(
				player_id,
				search_result.recipient,
				payment_amount,
				from_reaction=True
			)
			if not transaction.success:
				await remove_reaction(search_result.message, emoji, user_id)
			await send_report_to_cmd_line(str(user_id), transaction.report)
	#elif emoji_str in chat_reactions:


async def process_reaction_in_chat_hub(message_id : int, user_id : int, channel, emoji):
	message = await channel.fetch_message(message_id)
	report = await chats.process_reaction_in_chat_hub(message, str(emoji))
	await send_report_to_cmd_line(str(user_id), report)

async def process_reaction_in_storefront(message_id : int, user_id : int, channel, emoji):
	message = await channel.fetch_message(message_id)
	result : ActionResult = await shops.process_reaction_in_storefront(message, str(user_id), str(emoji))
	if not result.success:
		await send_report_to_cmd_line(str(user_id), result.report)

async def send_report_to_cmd_line(user_id : str, report : str):
	if report is not None:
		player_id = players.get_player_id(str(user_id), expect_to_find=False)
		if player_id is not None:
			cmd_line_channel = players.get_cmd_line_channel(player_id)
			if cmd_line_channel is not None:
				await cmd_line_channel.send(report)	


async def process_reaction_in_finance_channel(message_id : int, user_id : int, channel, emoji):
	await actors.process_reaction_in_finance_channel(str(channel.id), str(message_id), str(emoji))

async def process_reaction_in_order_flow(message_id : int, user_id : int, channel, emoji):
	message = await channel.fetch_message(message_id)
	result : ActionResult = await shops.process_reaction_in_order_flow(str(channel.id), str(message_id), str(emoji))
	if not result.success and result.report is not None:
		await channel.send(content=result.report, delete_after=5)


reactions_semaphores = {}

def get_reaction_semaphore(user_id : str):
	if reactions_semaphores.get(user_id) is None:
		reactions_semaphores[user_id] = asyncio.Semaphore(1)
	return reactions_semaphores[user_id]

def clear_reaction_semaphores():
	global reactions_semaphores
	for sem_id in reactions_semaphores:
		del reactions_semaphores[sem_id]



async def process_reaction_add(message_id : int, user_id : int, channel, emoji):
	if not game.can_process_reactions() and not channels.is_chat_hub(channel.name):
		# Remove the reaction
		message = await channel.fetch_message(message_id)
		await remove_reaction(message, emoji, user_id)
		return

	# Semaphore handling to ensure we only process one action per player at a time:
	async with get_reaction_semaphore(user_id):
		print(f'User reacted with {emoji}')
		should_remove_reaction = True
		try:
			if channels.is_anonymous_channel(channel):
				# Reactions are allowed in anonymous channels, but trigger no effects
				should_remove_reaction = False
			elif channels.is_cmd_line(channel.name):
				# Reactions in cmd_line are silently swallowed
				pass
			elif channels.is_chat_hub(channel.name):
				await process_reaction_in_chat_hub(message_id, user_id, channel, emoji)
				should_remove_reaction = False # Not needed after this
			elif channels.is_shop_channel(channel):
				await process_reaction_in_storefront(message_id, user_id, channel, emoji)
			elif channels.is_finance(channel.name):
				await process_reaction_in_finance_channel(message_id, user_id, channel, emoji)
			elif channels.is_order_flow(channel.name):
				await process_reaction_in_order_flow(message_id, user_id, channel, emoji)
			else:
				await process_reaction_on_other_handle(message_id, user_id, channel, emoji)
				should_remove_reaction = False # Reaction should stay unless removed by above function
		except discord.errors.NotFound:
			# If the message has already been removed, processing will fail and we just move on
			pass

	if should_remove_reaction:
		try:
			message = await channel.fetch_message(message_id)
			await remove_reaction(message, emoji, user_id)
		except discord.errors.NotFound:
			# If the processing above has removed the message or the reaction, we just ignore it
			pass



