import simplejson
from configobj import ConfigObj
from typing import List

import handles
import channels
import server
import finances
import groups
import reactions
from groups import Group
import shops
import actors
from shops import Shop
from custom_types import Handle, HandleTypes, Actor, ActionResult, PlayerData
from common import coin, emoji_accept


# Known_handles is meant to be read-only during the event
# It can be edited manually

# TODO: re-write this to integrate the output with the general welcome message!

class PlayerSetupInfo(object):
	def __init__(
		self,
		handle_id : str):
		self.handles = [(handle_id, 0), ('__example_handle1', 0), ('__example_handle2', 0)]
		self.npc_handles = [('__example_npc1', 0), ('__example_npc1', 0)]
		self.burners = [('__example_burner1', 0), ('__example_burner1', 0)]
		self.groups = ['__example_group1', '__example_group2']
		self.shops_owner = ['__example_shop1']
		self.shops_employee = ['__example_shop1']
		self.starting_money = 10

	@staticmethod
	def from_string(string : str):
		obj = PlayerSetupInfo(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_all_reserved(self):
		for handle_id in only_firsts_no_examples(self.handles):
			yield handle_id
		for handle_id in only_firsts_no_examples(self.npc_handles):
			yield handle_id
		for handle_id in only_firsts_no_examples(self.burners):
			yield handle_id
		for group_name in remove_examples(self.groups):
			yield group_name
		for shop_name in remove_examples(self.shops_owner):
			yield shop_name
		for shop_name in remove_examples(self.shops_employee):
			yield shop_name


double_underscore = '__'

def remove_examples(entries : List[str]):
	for entry in entries:
		if double_underscore not in entry:
			yield entry

def remove_examples_from_firsts(entries : List):
	for entry in entries:
		if double_underscore not in entry[0]:
			yield entry

def only_firsts_no_examples(entries):
	for entry in entries:
		if double_underscore not in entry[0]:
			yield entry[0]

def add_known_handle(handle_id : str):
	known_handles = ConfigObj('known_handles.conf')
	if handle_id not in known_handles:
		known_handles[handle_id] = PlayerSetupInfo(handle_id).to_string()
		known_handles.write()
	else:
		print(f'Trying to edit player setup info for a handle that is already in the database. Please edit the file manually instead.')

def get_known_handles_configobj():
	return ConfigObj('known_handles.conf')

def read_player_setup_info(handle_id : str):
	known_handles = get_known_handles_configobj()
	if handle_id in known_handles:
		return PlayerSetupInfo.from_string(known_handles[handle_id])
	else:
		return None
		# To allow players to join with unannounced handles, switch the above line to the below:
		# Return a new object, containing only the one handle we know we want
		#return PlayerSetupInfo(handle_id)


def get_all_reserved():
	known_handles = get_known_handles_configobj()
	for handle_id in known_handles:
		info = PlayerSetupInfo.from_string(known_handles[handle_id])
		for entry in info.get_all_reserved():
			yield entry

def can_setup_new_player_with_handle(main_handle : str):
	info = read_player_setup_info(main_handle)
	if info is None:
		return False
	handle = handles.get_handle(main_handle)
	return handle.handle_type == HandleTypes.Unused

async def setup_handles_and_welcome_new_player(player : PlayerData, main_handle : str):
	guild = actors.get_guild_for_actor(player.player_id)
	channel = channels.get_discord_channel(str(player.cmd_line_channel_id), guild.id)
	if channel is None:
		print(f'Error: Failed to welcome player {player.player_id} -- no cmd line channel found!')
		return False
	result : ActionResult = await handles.create_handle_and_switch(player.player_id, main_handle, force_reserved=True)
	if not result.success:
		report = f'Error: Failed to claim main handle {main_handle} for player {player.player_id}! Please contact administrator.'
		await channel.send(report)
		return False

	info = read_player_setup_info(main_handle)

	content = f'Welcome to the matrix_client, **{main_handle}**. This is your command line. To see all commands, type \"**.help**\"\n'
	content += f'Your account ID is {player.player_id}. All channels ending with {player.player_id} are only visible to you.\n'
	content += f'In all other channels, your posts will be shown under your current **handle** ({main_handle}).'
	await channel.send(content)

	content = '=== **HANDLES** ===\n'
	content += 'You can create and switch handles freely using the following commands:\n'
	content += '\n'
	content += '> **.handle** *new_handle*\n'
	content += '  Switch to handle - if it does not already exist, it will be created for you.\n'
	content += '  Regular handles cannot be deleted, but you can just abandon it if you don\'t need it.\n'
	content += '\n'
	content += '> **.handle** / **.handles**\n'
	content += '  Show you what your current handle is / show all your handles.\n'
	content += '\n'
	content += '> **.burner** *new_handle*\n'
	content += '  Switch to a burner handle - if it does not already exist, it will be created for you.\n'
	content += '\n'
	content += '> **.burn** *burner_handle*\n'
	content += '  Destroy a burner handle forever.\n'
	content += '  While a burner handle is active, it can possibly be traced.\n'
	content += '  After burning it, its ownership cannot be traced.\n'
	content += '\n '
	await channel.send(content)

	content = 'You currently have the following handles:\n'
	any_handles = False
	for (handles_list, handle_type) in (
		[(info.handles, HandleTypes.Regular),
		(info.burners, HandleTypes.Burner),
		(info.npc_handles, HandleTypes.NPC)]):
		result = await setup_alternate_handles(player.player_id, handles_list, handle_type)
		if result.success:
			any_handles = True
			content += result.report
	if any_handles:
		await channel.send(content)

	content = '=== **MONEY** ===\n'
	content += 'Each handle has its own balance (money). Commands related to money:\n'
	content += '\n'
	content += '> **.balance**\n'
	content += '  Show the current balance of all handles you control.\n'
	content += '\n'
	content += '> **.collect**\n'
	content += '  Transfer all money from all handles you control to the one you are currently using.\n'
	content += '\n'
	content += '> **.pay** *recipient* *amount*\n'
	content += '  Transfer money from your current handle to the recipient.\n'
	content += '  You can of course use this to transfer money to another handle that you also own.\n'
	content += '\n'
	content += '  Note: when a burner handle is destroyed, any money on it will be transferred to your active handle.\n'
	content += '  Money transfer can be traced, even from burners.\n'
	content += '\n'
	await channel.send(content)

	content = await setup_groups(player.player_id, info.groups)
	if content != '':
		await channel.send(content)

	for (shops_list, is_owner) in [(info.shops_owner, True), (info.shops_employee, False)]:
		async for content in setup_shops(player.player_id, shops_list, is_owner):
			await channel.send(content)

	content = '=== **REACTIONS** ===\n'
	content += 'In many cases, you can do things by using **reactions**.\n'
	content += f'They look like little buttons under the message -- for example like the {emoji_accept} under this one. Try clicking it!'
	message = await channel.send(content)
	await message.add_reaction(emoji_accept)
	content = f'Here in {channels.clickable_channel_ref(channel)}, reactions don\'t do anything.\n\n'
	content += 'In the chat hub channel, financial channel, and storefronts, you can use them to perform various actions.\n\n'
	content += 'In any discussion, you can use the following reactions to interact with the author of a message:\n\n'
	content += reactions.get_common_reactions_summary_string()
	await channel.send(content)
	return True


async def setup_handles_no_welcome_new_player(actor_id : str, main_handle : str):
	info = read_player_setup_info(main_handle)
	if info is None:
		return

	for (handles_list, handle_type) in (
		[(info.handles, HandleTypes.Regular),
		(info.burners, HandleTypes.Burner),
		(info.npc_handles, HandleTypes.NPC)]):
		result = await setup_alternate_handles(actor_id, handles_list, handle_type)
		if not result.success:
			print(result.report)

	await setup_groups(actor_id, info.groups)

	for (shops_list, is_owner) in [(info.shops_owner, True), (info.shops_employee, False)]:
		async for _ in setup_shops(actor_id, shops_list, is_owner):
			pass


async def setup_alternate_handles(actor_id : str, aliases, alias_type : HandleTypes):
	result = ActionResult()
	result.report = ''
	for handle_data in remove_examples_from_firsts(aliases):
		other_handle_id = handle_data[0]
		amount = handle_data[1]
		auto_respond_msg = handle_data[2] if len(handle_data) > 2 else None

		# TODO: check if handle already exists and throw error
		other_handle = await handles.create_handle(
			actor_id,
			other_handle_id,
			alias_type,
			force_reserved=True,
			auto_respond_message=auto_respond_msg
			)
		if other_handle.handle_type != HandleTypes.Unused:
			result.report += get_connected_alias_report(other_handle_id, alias_type, int(amount))
			await finances.add_funds(other_handle, int(amount))
			result.success = True
	if result.success:
		result.report += get_all_connected_aliases_of_type_report(alias_type, other_handle_id)
	return result

def get_connected_alias_report(handle_id : str, handle_type : HandleTypes, amount : int):
	ending = '' if amount == 0 else f' with {coin} **{amount}**'
	if handle_type == HandleTypes.Regular:
		return f'- Regular handle **{handle_id}**{ending}\n'
	elif handle_type == HandleTypes.Burner:
		return f'- Burner handle **{handle_id}**{ending}\n'
	elif handle_type == HandleTypes.NPC:
		return f'  [OFF: NPC handle **{handle_id}**{ending}.]\n'

def get_all_connected_aliases_of_type_report(handle_type : HandleTypes, last_example : str=None):
	if handle_type == HandleTypes.Regular:
		return ''
	elif handle_type == HandleTypes.Burner:
		example_burner = 'burner_name' if last_example is None else last_example
		return f'  (Use for example \".burn {example_burner}\" to destroy a burner and erase its tracks)\n'
	elif handle_type == HandleTypes.NPC:
		return '  [OFF: NPC handles let you act as someone else, and cannot be traced to your other handles.]\n'


async def setup_groups(actor_id : str, group_names : List[str]):
	any_found = False
	report = ''
	guild = actors.get_guild_for_actor(actor_id)
	for group_name in remove_examples(group_names):
		any_found = True
		await setup_group_for_new_member(group_name, actor_id)
		channel = groups.get_main_channel(guild, group_name)
		report += f'- **{group_name}**: {channels.clickable_channel_ref(channel)}\n'
	if any_found:
		report = ('=== **COMMUNITIES** ===\nEach community has a private chat room that is invisible to outsiders:\n' +
			report +
			'  Keep in mind that you can access these channels using any of your handles!')
	return report

async def setup_group_for_new_member(group_name : str, actor_id : str):
	if Group.exists(group_name):
		report = await groups.add_member_from_player_id(group_name, actor_id)
	else:
		await groups.create_new_group(group_name, [actor_id])


async def setup_shops(actor_id : str, shop_names : List[str], is_owner : bool):
	handle : Handle = handles.get_active_handle(actor_id)
	if handle is None:
		return
	guild = actors.get_guild_for_actor(actor_id)
	for shop_name in remove_examples(shop_names):
		shop : Shop = await setup_shop_for_member(shop_name, handle, is_owner)
		if shop is None:
			report = f'Error: failed to gain access to **{shop_name}**. Most likely the player data entry for {handle.actor_id} is corrupt.\n\n'
		else:
			report = f'=== **{shop_name.upper()}** ===\n'
			if is_owner:
				if shop.owner_id != handle.actor_id:
					report += f'Error: according to the database {handle.actor_id} should be the owner of the shop **{shop_name}**, but it is owned by {shop.owner_id}.\n'
				else:
					report += f'You are the owner of the shop **{shop_name}**.\n'
			else:
				report += f'You are employed at **{shop_name}**.\n'
			report += f'Use \".help employee\" to see the commands you can use to manage the business.\n'
			report += f'  Public storefront: {channels.clickable_channel_id_ref(shop.get_storefront_channel_id(guild))}.\n'
			report += f'  Order status: {channels.clickable_channel_id_ref(shop.order_flow_channel_id)}.\n'
			shop_actor : Actor = actors.read_actor(shop.shop_id)
			report += f'  Financial status: {channels.clickable_channel_id_ref(shop_actor.finance_channel_id)}.\n'
			report += f'  Business chat hub: {channels.clickable_channel_id_ref(shop_actor.chat_channel_id)}.\n'
			report += f'  Note: customers will see you as **{handle.handle_id}** unless you change it with \".set_tips\"!'
		yield report


async def setup_shop_for_member(shop_name : str, handle : Handle, is_owner : bool):
	if shops.shop_exists(shop_name):
		shop : Shop = shops.read_shop(shop_name)
		await shops.employ(handle, shop, is_owner=is_owner)
		return shop
	else:
		result : ActionResult = await shops.create_shop(shop_name, handle.actor_id, is_owner=is_owner)
		if result.success:
			return shops.read_shop(shop_name)
		else:
			print(f'Failed to setup shop for member: {result.report}')
			return None