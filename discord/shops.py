#shops.py

import discord
import asyncio
import simplejson
import datetime
import random
import os

from configobj import ConfigObj
from typing import Dict, List, Tuple
from copy import deepcopy
from enum import Enum
from discord.ext import commands
from dotenv import load_dotenv

# Custom imports
import common
import handles
import channels
import players
import actors
import finances
import server

from common import coin, emoji_unavail, shop_role_start, highest_ever_index, emoji_alert, emoji_accept, number_emojis
from custom_types import Transaction, TransTypes, ActionResult, Handle, HandleTypes, PostTimestamp


load_dotenv()
# Note: for the .table command to work, you must manually set up
# the in-game bar/restaurant as a shop, using .create_shop etc.
main_shop = os.getenv('MAIN_SHOP_NAME')


# TODO: add role check: GMs can do anything to any shop
# TODO: change so that a shop does not have to have an owner to function


class ShoppingCog(commands.Cog, name='shopping'):
	"""Commands related to buying and ordering at stores and restaurants.
	If you work at a store/restaurant, see \".help employee\" instead."""
	def __init__(self, bot):
		self.bot = bot
		self._last_member = None

	# Commands related to ordering
	# These only work in cmd_line channels

	@commands.command(
		name='order',
		brief='Order a product from a shop.',
		help=(
			'Order a product from a shop. Tip: if the shop has published their menu, it is much easier to order ' +
			f'from their storefront channel, which is found under the category {common.shops_category_name}'
			)
		)
	async def order_command(self, ctx, product_name : str=None, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await order_product_from_command(str(ctx.message.author.id), shop_name, product_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='order_other',
		help='Admin-only. Order a product from a shop for someone else.',
		hidden=True)
	@commands.has_role('gm')
	async def order_other_command(self, ctx, product_name : str=None, shop_name : str=None, buyer : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return

		buyer_handle : Handle = handles.get_handle(buyer)
		report = await order_product_for_buyer(shop_name, product_name, buyer_handle)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='set_delivery_id',
		brief='Set your delivery option at a shop.',
		help=(
			'Set your delivery option at a shop. ' +
			'This can be e.g. your table number, your delivery address, or your alias. ' +
			'If several items are ordered for the same delivery option (e.g. to the same ' +
			'table or same address) around the same time, they will likely be together.'
			)
		)
	async def set_delivery_id_command(self, ctx, delivery_id : str=None, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = set_delivery_id_from_command(str(ctx.message.author.id), delivery_id, shop_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='table',
		brief=f'Tell {main_shop} where to bring your order.',
		help=(f'Tell {main_shop} where to bring your order. ' +
			'Valid options are table numbers, \"bar\", and \"call\" (call out your handle).\n' +
			f'Note: \'.table 5\" is the same as typing \'.set_delivery_id {main_shop}\"Table 5\"\'.'
			)
		)
	async def set_delivery_id_command_table(self, ctx, option : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = set_delivery_table_from_command(str(ctx.message.author.id), option, main_shop)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='clear_all_shops',
		help='Admin-only: delete all shops.',
		hidden=True)
	@commands.has_role('gm')
	async def clear_shops_command(self, ctx):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		await init(clear_all=True)
		await ctx.send('Done.')



class EmployeeCog(commands.Cog, name='employee'):
	"""Commands related to working at a store or restaurant.
	For all of these commands, the "shop_name" argument is optional! The system will find the store you work at, as long as you don't work at more than one.
	If you want to order from a store/restaurant, see \".help shopping\" instead."""
	def __init__(self, bot):
		self.bot = bot
		self._last_member = None

	# Commands related to managing a shop
	# These only work in cmd_line channels

	@commands.command(
		name='create_shop',
		help='Admin-only: create a new shop, run by a certain player.',
		hidden=True)
	@commands.has_role('gm')
	async def create_shop_command(self, ctx, shop_name : str=None, player_id : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		async with handles.semaphore():
			result : ActionResult = await create_shop(shop_name, player_id, is_owner=True)
			if result.report is not None:
				await ctx.send(result.report)


	@commands.command(
		name='employ',
		brief='Add a new employee to your shop.',
		help=(
			'Add a new employee to your shop.\n' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def employ_command(self, ctx, handle_id : str=None, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await process_employ_command(str(ctx.message.author.id), handle_id, shop_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='fire',
		brief='Shop owner only: remove an employee from your shop.',
		help=(
			'Shop owner only: remove an employee from your shop.\n' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def fire_command(self, ctx, handle_id : str=None, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await process_fire_command(str(ctx.message.author.id), handle_id, shop_name)
		if report is not None:
			await ctx.send(report)


	@commands.command(
		name='add_product',
		brief='Add a new product to the shop.',
		help=(
			'Add a new product to the shop.\n' +
			'If you do not give a description, price or symbol, boring presets will be used but you can edit them afterwards.\n' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)		
		)
	async def add_product_command(
		self,
		ctx,
		product_name : str=None,
		description : str=None,
		price : int=0,
		symbol : str=None,
		shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await add_product(str(ctx.message.author.id), product_name, description, price, symbol, shop_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='edit_product',
		brief='Edit one of the shop\'s existing products.',
		help=(
			'Edit a product\'s properties. Examples:\n' +
			'.edit_product beer description \"A refreshing soybeer\"\n' +
			'.edit_product beer price 5\n' +
			'.edit_product beer symbol beer [some named symbols are avaialable]\n' +
			'.edit_product beer symbol 🥤 [any standard emoji can be used]\n' +
			'.edit_product beer available true [\"true\", \"t\" and \"1\" are equivalent]\n' +
			'.edit_product beer available false [\"false\", \"f\" and \"0\" are equivalent]\n' +
			'.edit_product beer in_stock true\n' +
			'\"available\" means the product will be visible in the shop. \"in_stock\" means it can be ordered.\n' +
			'Note: after editing a product, you must run \".publish_menu\" before the changes are visible to customers.' +
			'Note 2: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)				
		)
	async def edit_product_command(
		self,
		ctx,
		product_name : str=None,
		key : str=None,
		value : str=None,
		shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await edit_product_from_command(str(ctx.message.author.id), product_name, key, value, shop_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='remove_product',
		brief='Delete a product from the shop.',
		help=(
			'Delete a product from the shop.\n' +
			'After editing a product, you must run \".publish_menu\" before the changes are visible to customers.' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def remove_product_command(
		self,
		ctx,
		product_name : str=None,
		shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await remove_product(str(ctx.message.author.id), product_name, shop_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='in_stock',
		brief='Set a product to be in stock / out of stock.',
		help=(
			'Set a product to be in stock / out of stock. \".in_stock beer true\" is equivalent to \".edit_product beer in_stock true\".\n' +
			'After editing a product, you must run \".publish_menu\" before the changes are visible to customers.' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def in_stock_command(
		self,
		ctx,
		product_name : str=None,
		value : bool=True, # TODO
		shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await edit_product_from_command(str(ctx.message.author.id), product_name, 'in_stock', str(value), shop_name)
		if report is not None:
			await ctx.send(report)


	@commands.command(
		name='publish_menu',
		brief='Publish the current catalogue/menu.',
		help=(
			'Publish the current catalogue/menu. After editing a product, you must run this command for the updates to be visible to customers.\n' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def publish_menu_command(self, ctx, product_name : str=None, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		if product_name is not None:
			report = await post_catalogue_item(str(ctx.message.author.id), product_name, shop_name)
		else:
			report = await update_storefront(str(ctx.message.author.id), shop_name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='pm',
		help='Publish the current catalogue/menu. Alias for .publish_menu.',
		hidden=True
		)
	async def pm_command(self, ctx, product_name : str=None, shop_name : str=None):
		await self.publish_menu_command(ctx, product_name, shop_name)

	@commands.command(
		name='clear_orders',
		brief='Shop owner only: clear your shop\'s orders.',
		help=(
			'Remove all orders (both fulfilled and pending), and publish all product updates to the menu.\n' +
			'Note: all orders that are pre-paid will still be paid, and there will be no easy way to refund them!\n' +
			'Note 2: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def clear_orders_command(self, ctx, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		await reinitialize(str(ctx.message.author.id), shop_name)
		await self.publish_menu_command(ctx, shop_name=shop_name)

	@commands.command(
		name='set_tips',
		brief='Set which handle should get your tips.',
		help=(
			'Set the handle that is shown in the storefront and gets your tips.\n' +
			'If you just do \".set_tips\" without any handle, you will not be shown in the storefront at all.\n' +
			'Note: as long as you don\'t work at more than one shop, you can skip the \"shop_name\" argument.'
			)
		)
	async def set_tips_command(self, ctx, handle_id : str=None, shop_name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await set_tips_for_user(str(ctx.message.author.id), handle_id, shop_name)
		if report is not None:
			await ctx.send(report)

def setup(bot):
	bot.add_cog(ShoppingCog(bot))
	bot.add_cog(EmployeeCog(bot))



emoji_shopping = '🛒'
emoji_ramen = '🍜'

product_emojis = {
	'shopping' : emoji_shopping,
	'ramen' : emoji_ramen,
	'noodles' : emoji_ramen,
	'beer' : '🍺',
	'water' : '🥤',
	'cocktail' : '🍸',
	'beers' : '🍻',
	'plate' : '🍽️',
	'food' : '🍽️'
}

emoji_unchecked = '🟦'
emoji_checked = '☑️'
emoji_unlocked = '🔓'
emoji_locked = '🔒'
max_table_number = 10

# Order unchecked: 🟦
# Order checked: ☑️

#User reacted with 🛒
#User reacted with 🍿
#User reacted with 🍺
#User reacted with 🥤
#User reacted with 🍸
#User reacted with 🍻
#User reacted with 🍽️


### Module to allow one or more players to run a shop together.
# Having a shop grants:
# - A public storefront, where the menu/catalogue is presented as messages you can react to
# - An "orders" channel, showing what people have ordered recently
# - A "delivery ID" (e.g. table number) for each customer,
#   so that orders can be collected and delivered together
# - An "actor", with the functionality that comes with it (handles, financial reports, chats)
#   albeit restricted to a single handle

### Classes, init and utilities:

class Employee(object):
	def __init__(
		self,
		player_id : str,
		handle_for_tips : str = None,
		emoji : str = None):
		self.player_id = player_id
		self.handle_for_tips = handle_for_tips
		self.emoji = emoji

	@staticmethod
	def from_string(string : str):
		obj = Employee(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

class Shop(object):
	def __init__(
		self,
		name : str,
		actor_id : str,
		storefront_channel_ids : Dict[str, str],
		order_flow_channel_id : str,
		employees : List[Employee] = None,
		owner_id : str = None):
		self.name = name
		self.owner_id = owner_id
		self.shop_id = actor_id
		self.storefront_channel_ids = storefront_channel_ids
		self.order_flow_channel_id = order_flow_channel_id
		self.highest_order = 0
		self.employees = [] if employees is None else employees
		self.order_collection_limit = 2

	@staticmethod
	def from_string(string : str):
		obj = Shop(None, None, None, None)
		loaded_dict = simplejson.loads(string)
		obj.__dict__.update(loaded_dict)
		for i, employee_str in enumerate(loaded_dict['employees']):
			obj.employees[i] = Employee.from_string(employee_str)
		return obj

	def to_string(self):
		dict_to_save = deepcopy(self.__dict__)
		list_of_employees = [step.to_string() for step in dict_to_save['employees']]
		dict_to_save['employees'] = list_of_employees
		return simplejson.dumps(dict_to_save)

	def get_employee_ids(self):
		for employee in self.employees:
			yield employee.player_id

	def get_storefront_channel_id(self, guild):
		return None if guild is None else self.storefront_channel_ids.get(str(guild.id))

	def storefront_channels(self):
		return [channels.get_discord_channel(channel_id, int(guild_id))
				  for guild_id, channel_id in self.storefront_channel_ids.items()]

	def edit_tips_handle(self, player_id : str, handle_id : str):
		# Note: handle_id can be None, it is valid
		for employee in self.employees:
			if employee.player_id == player_id:
				employee.handle_for_tips = handle_id
				return True
		return False

	# TODO: store the mapping separately for the shop
	# TODO: store the shop.to_string() in a separate file for each shop
	def generate_tips_list(self):
		initials = []
		# Loop to check for initialism duplicates
		use_initials = True
		for employee in self.employees:
			if employee.handle_for_tips is not None:
				initial = employee.handle_for_tips[0]
				if initial in initials:
					use_initials = False
				initials.append(initial)
		# second loop to actually allocate emojis and construct the map
		tips_tuples = []
		index = 1
		for employee in self.employees:
			if employee.handle_for_tips is not None:
				emoji = (
					common.letter_emoji(employee.handle_for_tips)
					if use_initials
					else number_emojis[index]
					)
				tips_tuples.append((employee.handle_for_tips, emoji))
				employee.emoji = emoji
				if not use_initials:
					index += 1
					if index == len(number_emojis):
						print(
							f'Warning: shop {self.name} has too many employees, ' +
							f'all cannot be showed in the tipping menu. Including the first {index}.'
							)
						break
		store_shop(self)
		return tips_tuples



class FindShopResult(object):
	def __init__(self, shop : Shop=None, error_report : str=None):
		self.shop = shop
		self.error_report = error_report

class Product(object):
	def __init__(
		self,
		name : str,
		description : str,
		price : int,
		file_name : str=None,
		storefront_msg_ids : Dict[str, str]={},
		in_stock : bool=True,
		available : bool=True,
		emoji : str = emoji_shopping):
		self.name = name
		self.product_id = name.lower() if name is not None else None
		self.description = description
		self.price = price
		self.file_name = file_name
		self.storefront_msg_ids = storefront_msg_ids
		# If available is false, product will not appear at all
		# If in_stock is false, product will appear in menu but with "Out of stock!" and not possible to order
		self.in_stock = in_stock
		self.available = available
		self.emoji = emoji

	@staticmethod
	def from_string(string : str):
		obj = Product(None, None, None, None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_storefront_message_id(self, guild_id: int):
		return self.storefront_msg_ids.get(str(guild_id))

	def set_storefront_message_id(self, guild_id: int, msg_id):
		self.storefront_msg_ids[str(guild_id)] = msg_id

class OrderStatus(str, Enum):
	Active = 'a'
	Locked = 'l'
	Delivered = 'd'


# Used to represent an order: one or more items bought/reserved that will be delivered together
class Order(object):
	def __init__(
		self,
		order_id : str,
		delivery_id : str,
		price_total : int,
		paid_total : int = 0,
		order_flow_msg_id : str=None,
		time_created : PostTimestamp=None,
		undo_hooks : List[Tuple[str, str]]=None,
		items_ordered={}):
		self.order_id = order_id
		self.delivery_id = delivery_id
		self.price_total = price_total
		self.paid_total = paid_total
		self.order_flow_msg_id = order_flow_msg_id
		self.items_ordered = items_ordered
		self.time_created : PostTimestamp = time_created
		self.time_updated : PostTimestamp = time_created
		self.undo_hooks = [] if undo_hooks is None else undo_hooks
		self.updated : bool = False

	@staticmethod
	def from_string(string : str):
		obj = Order(None, None, None)
		loaded_dict = simplejson.loads(string)
		obj.__dict__.update(loaded_dict)
		obj.time_created : PostTimestamp = PostTimestamp.from_string(loaded_dict['time_created'])
		obj.time_updated : PostTimestamp = PostTimestamp.from_string(loaded_dict['time_updated'])
		return obj

	def to_string(self):
		dict_to_save = deepcopy(self.__dict__)
		dict_to_save['time_created'] = PostTimestamp.to_string(self.time_created)
		dict_to_save['time_updated'] = PostTimestamp.to_string(self.time_updated)
		return simplejson.dumps(dict_to_save)

	def add(self, product_name : str, product_price : str, timestamp : PostTimestamp, pre_paid : bool):
		if product_name in self.items_ordered:
			prev_number = int(self.items_ordered[product_name])
		else:
			prev_number = 0
		new_number = prev_number + 1
		self.items_ordered[product_name] = new_number
		self.time_updated = timestamp
		self.price_total += product_price
		self.paid_total += product_price if pre_paid else 0
		self.updated = True

	async def remove_undo_hooks(self):
		for (actor_id, msg_id) in self.undo_hooks:
			# These are IDs for messages that could until now be used to undo the transaction
			await actors.lock_tentative_transaction(actor_id, msg_id)
		self.undo_hooks = []

	def all_paid(self):
		return self.paid_total >= self.price_total



# Used to represent an order: one or more items bought/reserved that will be delivered together
class MsgOrderMapping(object):
	def __init__(
		self,
		identifier : str, # For active orders: delivery_id. For inactive orders: order_id
		status : OrderStatus):
		self.identifier = identifier
		self.status = status

	@staticmethod
	def from_string(string : str):
		obj = MsgOrderMapping(None, OrderStatus.Active)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)



# Used to represent an action that can be taken from the storefront:
# - Ordering a product
# - Choosing a delivery option TODO
# - Tipping a server TODO
# - Starting a chat with the shop TODO
class StorefrontActionTypes(str, Enum):
	Order = 'o'
	SetDeliveryOption = 'sdo'
	Tip = 't'
	Chat = 'c'

class StorefrontAction(object):
	def __init__(
		self,
		action_type : StorefrontActionTypes,
		data : str=None # for orders: product id
		):
		self.action_type = action_type
		self.data = data

	@staticmethod
	def from_string(string : str):
		obj = StorefrontAction(StorefrontActionTypes.Order)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)



# "Missing" class: ChannelMapping
# Used to store mapping from channel to shop
# No class necessary; just use shop_id : str as the "pointer", indexed by channel ID




### Init, getters, setters, deleters

# TODO: gm-only function to remove a single shop
# Necessary as fail-safe if we allow players to create their own shops


shops_conf_dir = 'shops'

shop_data_index = '__shop_data'
storefront_channel_map_index = '__storefront_channel_mapping'
orders_channel_map_index = '__order_flow_channel_mapping'

def get_shops_configobj():
	shops = ConfigObj(f'{shops_conf_dir}/__shops.conf')
	edited = False
	if shop_data_index not in shops:
		shops[shop_data_index] = {}
		edited = True
	if highest_ever_index not in shops[shop_data_index]:
		shops[shop_data_index][highest_ever_index] = str(shop_role_start)
		edited = True
	if storefront_channel_map_index not in shops:
		shops[storefront_channel_map_index] = {}
		edited = True
	if orders_channel_map_index not in shops:
		shops[orders_channel_map_index] = {}
		edited = True
	if edited:
		shops.write()
	return shops

async def init(clear_all=False):
	shops = get_shops_configobj()
	if clear_all:
		for shop_id in get_all_shop_ids():
			shop : Shop = read_shop(shop_id)
			for player_id in shop.get_employee_ids():
				players.remove_shop(player_id, shop.shop_id)
			await actors.clear_actor(shop_id)
			await clear_shop_contents(shop_id)
			del shops[shop_data_index][shop_id]
		for channel in shops[storefront_channel_map_index]:
			del shops[storefront_channel_map_index][channel]
		for channel in shops[orders_channel_map_index]:
			del shops[orders_channel_map_index][channel]
		shops.write()
		await channels.delete_all_shops()

	if clear_all:
		shops[shop_data_index][highest_ever_index] = str(shop_role_start)
	shops.write()

	await delete_all_shop_roles(spare_used=not clear_all)

async def delete_all_shop_roles(spare_used : bool):
	task_list = (asyncio.create_task(delete_if_shop_role(r, spare_used)) for guild in server.get_guilds() for r in guild.roles)
	await asyncio.gather(*task_list)

async def delete_if_shop_role(role, spare_used : bool):
	if common.is_shop_role(role.name):
		in_use = actors.actor_index_in_use(role.name) or len(role.members) > 0
		if not in_use or not spare_used:
			await role.delete()

async def reinitialize(user_id : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name, must_be_owner=True)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	order_flow_channel = channels.get_discord_channel(shop.order_flow_channel_id)
	tasks = [asyncio.create_task(order_flow_channel.purge())]
	tasks.extend((asyncio.create_task(ch.purge()) for ch in shop.storefront_channels()))
	await asyncio.gather(*tasks)
	delete_storefront_msg_mappings_for_shop(shop.shop_id)
	await clear_order_data(shop.shop_id)
	shop.highest_order = 1
	store_shop(shop)
	clear_order_semaphores_for_shop(shop.shop_id)
	return 'Done.'


# TODO: move all this into class Shop

def get_next_shop_index():
	shops = get_shops_configobj()
	prev_highest = int(shops[shop_data_index][highest_ever_index])
	shop_index = str(prev_highest + 1)
	shops[shop_data_index][highest_ever_index] = shop_index
	shops.write()
	return shop_index

def shop_exists(shop_name : str):
	return shop_name is not None and shop_name.lower() in get_all_shop_ids()

def get_all_shop_ids():
	shops = get_shops_configobj()
	for shop_id in shops[shop_data_index]:
		if shop_id != highest_ever_index:
			yield shop_id

def store_shop(shop : Shop):
	shops = get_shops_configobj()
	shops[shop_data_index][shop.shop_id] = shop.to_string()
	shops.write()

def read_shop(shop_name : str):
	shop_id = shop_name.lower()
	shops = get_shops_configobj()
	if shop_id in shops[shop_data_index]:
		return Shop.from_string(shops[shop_data_index][shop_id])

def record_new_order(shop_name : str):
	shop : Shop = read_shop(shop_name)
	new_order_id = int(shop.highest_order)
	shop.highest_order = new_order_id + 1
	store_shop(shop)
	return str(new_order_id)

def store_storefront_channel_mapping(channel_id : str, shop_name : str):
	shop_id = shop_name.lower()
	shops = get_shops_configobj()
	shops[storefront_channel_map_index][channel_id] = shop_id
	shops.write()

def read_storefront_channel_mapping(channel_id : str):
	shops = get_shops_configobj()
	if channel_id in shops[storefront_channel_map_index]:
		return shops[storefront_channel_map_index][channel_id]

def store_order_flow_channel_mapping(channel_id : str, shop_name : str):
	shop_id = shop_name.lower()
	shops = get_shops_configobj()
	shops[orders_channel_map_index][channel_id] = shop_id
	shops.write()

def read_order_flow_channel_mapping(channel_id : str):
	shops = get_shops_configobj()
	if channel_id in shops[orders_channel_map_index]:
		return shops[orders_channel_map_index][channel_id]


catalogue_suffix = '_catalogue.conf'
product_entries_index = '___products'

def get_catalogue(shop_name : str):
	shop_id = shop_name.lower()
	catalogue_file_name = f'{shop_id}{catalogue_suffix}'
	return ConfigObj(f'{shops_conf_dir}/{catalogue_file_name}')

def get_all_products(shop_name : str):
	catalogue = get_catalogue(shop_name)
	for product_id in catalogue[product_entries_index]:
		yield read_product_from_cat(catalogue, product_id)

def product_exists(shop_name : str, product_name : str):
	return read_product(shop_name, product_name) is not None


def store_product(shop_name : str, product : Product):
	if shop_exists(shop_name):
		catalogue = get_catalogue(shop_name)
		catalogue[product_entries_index][product.product_id] = product.to_string()
		catalogue.write()

def delete_product(shop_name : str, product_id : str):
	if shop_exists(shop_name):
		catalogue = get_catalogue(shop_name)
		if product_id in catalogue[product_entries_index]:
			del catalogue[product_entries_index][product_id]
			catalogue.write()

def read_product(shop_name : str, product_name : str):
	if shop_exists(shop_name):
		catalogue = get_catalogue(shop_name)
		return read_product_from_cat(catalogue, product_name)

def read_product_from_cat(catalogue, product_name : str):
	product_id = product_name.lower()
	if product_id in catalogue[product_entries_index]:
		return Product.from_string(catalogue[product_entries_index][product_id])

def clear_catalogue(shop_name : str):
	if shop_exists(shop_name):
		catalogue = get_catalogue(shop_name)
		catalogue[product_entries_index] = {}
		catalogue[msg_mapping_index] = {}
		catalogue.write()


storefront_suffix = '_storefront.conf'
msg_mapping_index = '___storefront_msg_mappings'
delivery_choice_msg_index = '___del_choice_msg'
tipping_msg_index = '___tipping_msg'

def get_storefront(shop_name : str):
	shop_id = shop_name.lower()
	storefront_file_name = f'{shop_id}{storefront_suffix}'
	return ConfigObj(f'{shops_conf_dir}/{storefront_file_name}')

def store_storefront_msg_mapping(shop_name : str, msg_id : str, action : StorefrontAction):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		storefront[msg_mapping_index][msg_id] = action.to_string()
		storefront.write()

def delete_storefront_msg_mapping(shop_name : str, msg_id : str):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		if msg_id in storefront[msg_mapping_index]:
			del storefront[msg_mapping_index][msg_id]
			storefront.write()

def read_storefront_msg_mapping(shop_name : str, msg_id : str):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		if msg_id in storefront[msg_mapping_index]:
			return StorefrontAction.from_string(storefront[msg_mapping_index][msg_id])

def delete_storefront_msg_mappings_for_shop(shop_name : str):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		for msg_id in storefront[msg_mapping_index]:
			del storefront[msg_mapping_index][msg_id]
		storefront.write()

def get_delivery_choice_message(shop_name : str, guild_id: int):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		if delivery_choice_msg_index in storefront:
			if str(guild_id) in storefront[delivery_choice_msg_index]:
				return storefront[delivery_choice_msg_index][str(guild_id)]

def store_delivery_choice_message(shop_name : str, msg_id : str, guild_id: int):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		if not delivery_choice_msg_index in storefront:
			storefront[delivery_choice_msg_index] = {}
		storefront[delivery_choice_msg_index][str(guild_id)] = msg_id
		action = StorefrontAction(StorefrontActionTypes.SetDeliveryOption)
		storefront[msg_mapping_index][msg_id] = action.to_string()
		storefront.write()

def get_tipping_message(shop_name : str, guild_id: int):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		if tipping_msg_index in storefront:
			if str(guild_id) in storefront[tipping_msg_index]:
				return storefront[tipping_msg_index][str(guild_id)]

def store_tipping_message(shop_name : str, msg_id : str, guild_id: int):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		if not tipping_msg_index in storefront:
			storefront[tipping_msg_index] = {}
		storefront[tipping_msg_index][str(guild_id)] = msg_id
		action = StorefrontAction(StorefrontActionTypes.Tip)
		storefront[msg_mapping_index][msg_id] = action.to_string()
		storefront.write()

def clear_storefront(shop_name : str):
	if shop_exists(shop_name):
		storefront = get_storefront(shop_name)
		storefront[msg_mapping_index] = {}
		if delivery_choice_msg_index in storefront:
			del storefront[delivery_choice_msg_index]
		if tipping_msg_index in storefront:
			del storefront[tipping_msg_index]
		storefront.write()



# The delivery ID of each player/actor is stored in a simple database

delivery_data_suffix = '_delivery_data.conf'
delivery_ids_index = '___delivery_ids'

def get_delivery_data(shop_name : str):
	shop_id = shop_name.lower()
	delivery_data_file_name = f'{shop_id}{delivery_data_suffix}'
	return ConfigObj(f'{shops_conf_dir}/{delivery_data_file_name}')

def player_has_delivery_id(shop_name : str, player_id : str):
	return get_delivery_id(shop_name, player_id) is not None

def store_delivery_id(shop_name : str, player_id : str, delivery_id : str):
	if shop_exists(shop_name):
		delivery_data = get_delivery_data(shop_name)
		delivery_data[delivery_ids_index][player_id] = delivery_id
		delivery_data.write()

def delete_delivery_id(shop_name : str, player_id : str):
	if shop_exists(shop_name):
		delivery_data = get_delivery_data(shop_name)
		if player_id in delivery_data[delivery_ids_index]:
			del delivery_data[delivery_ids_index][player_id]
			delivery_data.write()

def get_delivery_id(shop_name : str, player_id : str):
	if shop_exists(shop_name):
		delivery_data = get_delivery_data(shop_name)
		return read_delivery_id_from_del_data(delivery_data, player_id)

def read_delivery_id_from_del_data(delivery_data, player_id : str):
	if player_id in delivery_data[delivery_ids_index]:
		return delivery_data[delivery_ids_index][player_id]

def clear_delivery_data(shop_name : str):
	if shop_exists(shop_name):
		delivery_data = get_delivery_data(shop_name)
		delivery_data[delivery_ids_index] = {}
		delivery_data.write()

def delete_delivery_ids_for_actor(actor_id : str):
	for shop_id in get_all_shop_ids():
		delete_delivery_id(shop_id, actor_id)



async def clear_shop_contents(shop_name : str):
	clear_catalogue(shop_name)
	clear_delivery_data(shop_name)
	clear_storefront(shop_name)
	await clear_order_data(shop_name)

# The active orders are stored indexed on delivery ID, since there can only be
# one active order for each

# Each active order also stores a counter-mapping: msg_id -> delivery ID
# These are linked -- mapping must be added when order is stored
# Mapping must be removed when order is deleted (fetched)

order_data_suffix = '_order_data.conf'
active_orders_index = '___active_orders'
locked_orders_index = '___locked_orders'
msg_to_order_mapping_index = '___msg_to_order_mapping'

def get_order_data(shop_name : str):
	shop_id = shop_name.lower()
	order_data_file_name = f'{shop_id}{order_data_suffix}'
	return ConfigObj(f'{shops_conf_dir}/{order_data_file_name}')

def store_active_order(shop_name : str, order : Order):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		msg_id = str(order.order_flow_msg_id)
		msg_mapping = MsgOrderMapping(order.delivery_id, OrderStatus.Active)
		order_data[msg_to_order_mapping_index][msg_id] = msg_mapping.to_string()
		order_data[active_orders_index][order.delivery_id] = order.to_string()
		order_data.write()

def delete_active_order(shop_name : str, delivery_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		if delivery_id in order_data[active_orders_index]:
			del order_data[active_orders_index][delivery_id]
			order_data.write()

# Treat all output from this as read-only! If you need to edit the order, use fetch_order instead!
def get_active_order(shop_name : str, delivery_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		return read_active_order_from_order_data(order_data, delivery_id)

def fetch_all_active_orders(shop_name : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		for delivery_id in order_data[active_orders_index]:
			yield _fetch_active_order_from_order_data(order_data, delivery_id)

def fetch_active_order(shop_name : str, delivery_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		return _fetch_active_order_from_order_data(order_data, delivery_id)

def read_active_order_from_order_data(order_data, delivery_id : str):
	if delivery_id in order_data[active_orders_index]:
		return Order.from_string(order_data[active_orders_index][delivery_id])

def _fetch_active_order_from_order_data(order_data, delivery_id : str):
	if delivery_id in order_data[active_orders_index]:
		order = Order.from_string(order_data[active_orders_index][delivery_id])
		del order_data[active_orders_index][delivery_id]
		msg_id = str(order.order_flow_msg_id)
		if msg_id in order_data[msg_to_order_mapping_index]:
			del order_data[msg_to_order_mapping_index][msg_id]
		order_data.write()
		return order


# The locked orders are stored indexed on order number
def store_locked_order(shop_name : str, order : Order):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		msg_id = str(order.order_flow_msg_id)
		msg_mapping = MsgOrderMapping(order.order_id, OrderStatus.Locked)
		order_data[msg_to_order_mapping_index][msg_id] = msg_mapping.to_string()
		order_data[locked_orders_index][order.order_id] = order.to_string()
		order_data.write()

def delete_locked_order(shop_name : str, order_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		if order_id in order_data[locked_orders_index]:
			del order_data[locked_orders_index][order_id]
			order_data.write()

def get_locked_order(shop_name : str, order_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		return read_locked_order_from_order_data(order_data, order_id)

def fetch_locked_order(shop_name : str, order_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		return fetch_locked_order_from_order_data(order_data, order_id)

def read_locked_order_from_order_data(order_data, order_id : str):
	if order_id in order_data[locked_orders_index]:
		return Order.from_string(order_data[locked_orders_index][order_id])

def fetch_locked_order_from_order_data(order_data, order_id : str):
	if order_id in order_data[locked_orders_index]:
		order = Order.from_string(order_data[locked_orders_index][order_id])
		del order_data[locked_orders_index][order_id]
		msg_id = str(order.order_flow_msg_id)
		if msg_id in order_data[msg_to_order_mapping_index]:
			del order_data[msg_to_order_mapping_index][msg_id]
		order_data.write()
		return order

def get_order_mapping_from_msg(shop_name : str, msg_id : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		if msg_id in order_data[msg_to_order_mapping_index]:
			return MsgOrderMapping.from_string(order_data[msg_to_order_mapping_index][msg_id])


async def clear_order_data(shop_name : str):
	if shop_exists(shop_name):
		order_data = get_order_data(shop_name)
		if active_orders_index not in order_data:
			order_data[active_orders_index] = {}
		if locked_orders_index not in order_data:
			order_data[locked_orders_index] = {}
		if msg_to_order_mapping_index not in order_data:
			order_data[msg_to_order_mapping_index] = {}
		order_data.write()

		for order in fetch_all_active_orders(shop_name):
			await order.remove_undo_hooks()
		order_data[active_orders_index] = {}
		order_data[locked_orders_index] = {}
		order_data[msg_to_order_mapping_index] = {}
		order_data.write()



### Creating a new shop:

async def create_shop(shop_name : str, handle_id : str, is_owner : bool=False):
	main_guild = server.get_guild(None)
	result = ActionResult()
	if shop_name is None:
		result.report = 'Error: must give a shop name.'
		return result

	if shop_exists(shop_name):
		existing_shop = read_shop(shop_name)
		if existing_shop.name == shop_name:
			result.report = f'Error: the shop {shop_name} already exists.'
		else:
			result.report = (f'Error: cannot create **{shop_name}** because its internal ID '
				+ f'({shop_name.lower()}) clashes with existing shop **{existing_shop.name}**.)')
		return result

	shop_index = get_next_shop_index()
	actor : actors.Actor = await actors.create_new_actor(main_guild, actor_index=shop_index, actor_id=shop_name.lower())

	storefront_channel_ids = {}
	for guild in server.get_guilds():
		storefront_channel = await channels.create_shop_channel(guild, shop_name)
		store_storefront_channel_mapping(str(storefront_channel.id), shop_name)
		storefront_channel_ids[str(guild.id)] = str(storefront_channel.id)

	role = actors.get_actor_role(actor.actor_id)
	order_flow_channel = await channels.create_order_flow_channel(main_guild, role, shop_name)
	order_flow_channel_id = str(order_flow_channel.id)
	store_order_flow_channel_mapping(order_flow_channel_id, shop_name)

	# TODO: send welcome message in order_flow_channel

	if handle_id is None:
		player_id = None
	else:
		handle : Handle = handles.get_handle(handle_id)
		if handle.handle_type == HandleTypes.Unused:
			result.report = f'Error: handle {handle_id} does not exist.'
			return result
		player_id = handle.actor_id

	shop = Shop(shop_name, actor.actor_id, storefront_channel_ids, order_flow_channel_id)
	store_shop(shop)
	await clear_shop_contents(shop.shop_id)

	if player_id is not None:
		if is_owner:
			report = f'Created shop **{shop.name}**, run by {handle.handle_id} (player ID {handle.actor_id}).'
		else:
			report = f'Created shop **{shop.name}**, currently has no owner.'
		result = await employ(handle, shop, is_owner=is_owner)
		if result.success:
			result.report = report + '\n' + result.report
	else:
		result.report = f'Created shop **{shop.name}**, currently with no owner and no employees.'
		result.success = True

	return result


async def find_shop_for_command(user_id : str, shop_name : str, must_be_owner : bool=False):
	if user_id is None:
		raise RuntimeError('Tried to find a shop, but the action initiator user_id was not found.')

	result = FindShopResult()
	if shop_name is not None and not shop_exists(shop_name):
		result.error_report = f'Error: there is no shop named {shop_name}.'
		return result

	player_id = players.get_player_id(user_id)

	is_gm_or_admin = await players.is_gm_or_admin(player_id)

	shops_of_player = players.get_shops(player_id)
	if shop_name is None:
		# If no shop given, assume the player wants us to use their first one
		# If a player works at more than one shop, they will have to use the
		# full syntax of specifying which shop they mean
		if len(shops_of_player) == 0:
			if is_gm_or_admin:
				result.error_report = f'Error: no shop listed for {player_id}. Since you are GM/admin, you can edit any shop but you must specify which shop you mean.'
			else:
				result.error_report = f'Error: player {player_id} does not have access to any shops'
			return result
		shop_name = shops_of_player[0]
		if not shop_exists(shop_name):
			result.error_report = f'Error: there is no shop named {shop_name}.'
			return result
	elif shop_name.lower() not in shops_of_player and not is_gm_or_admin:
		result.error_report = f'Error: player {player_id} does not have access to shop {shop_name}.'
		return result

	shop : Shop = read_shop(shop_name)
	if must_be_owner and shop.owner_id != player_id and not is_gm_or_admin:
		result.error_report = f'Error: this action is only permitted for shop owner, which is {shop.owner_id}.'
		return result

	result.shop = shop
	return result



# Employees:

async def employ(handle : Handle, shop : Shop, is_owner : bool=False):
	result = ActionResult()
	player_id = handle.actor_id

	# TODO: encapsulate this in a "make player member of shop" method in players.py
	member = await server.get_member_from_nick(player_id)
	if not players.player_exists(player_id) or member is None:
		result.report = f'Error: handle {handle.handle_id} is not owned by a person, or they don\'t conform to the server nick scheme.'
		return result

	if player_id in shop.get_employee_ids():
		result.report = f'Error: {handle.handle_id} is controlled by {player_id} who already works at {shop.shop_id}.'
		return result

	role = actors.get_actor_role(shop.shop_id)
	if member.guild.id != role.guild.id:
		result.report = f'Error: Player {player_id} is not located in the same server as the shop. (we do not allow Work From Home here, duh)'
		return result
	await server.give_member_role(member, role)

	players.add_shop(player_id, shop.shop_id)
	shop.employees.append(Employee(player_id, handle_for_tips=handle.handle_id))
	if is_owner:
		shop.owner_id = player_id
	store_shop(shop)
	result.report = (f'Added {handle.handle_id} as an employee at {shop.name}. '
		+ 'They now have access to the shop\'s finances, chat and order channels, and can edit the product catalogue.')
	result.success = True
	return result

async def process_employ_command(user_id : str, handle_id : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	if handle_id is None:
		return 'Error: must give a a handle'
	handle : Handle = handles.get_handle(handle_id)
	if handle.handle_type == HandleTypes.Unused:
		return f'Error: handle {handle_id} does not exist.'

	result : ActionResult = await employ(handle, shop)
	if result.success:
		channel = players.get_cmd_line_channel(handle.actor_id)
		if channel is None:
			return result.report + '\nError: employee was added, but could not be notified; cmd_line channel not found.'
		else:
			await channel.send(
				f'Congratulations **{handle.handle_id}**—you have been added as an employee at **{shop.name}**! You now have access to its finances, chat, and order channels.\n'
				+ f'You can add products to the menu/catalogue:\n'
				+ f'> .add_product Beer "A description of the beer!" 10 :beer:\n'
				+ f'  (\"10\" is the cost in {coin})\n'
				+ f'You can edit products,:\n'
				+ f'> .edit_product Beer price 5\n'
				+ f'  The following fields can be edited: description, price, symbol, available, in_stock.\n'
				+ f'  \"available\" and \"in_stock\" can be set to \"0\" or \"1\". Available means the product is shown in the storefront channel; in_stock means it can be ordered.\n'
				+ f'To make your added/edited products appear in the public storefront channel:\n'
				+ f'> .publish_menu')
	return result.report

async def remove_employee(shop : Shop, player_id : str, handle_id : str=None):
	member = await server.get_member_from_nick(player_id)
	if not players.player_exists(player_id) or member is None:
		if handle_id is None:
			return f'Error: player {player_id} does not conform to the server nick scheme.'
		else:
			return f'Error: handle {handle_id} is not owned by a person, or they don\'t conform to the server nick scheme.'

	if player_id not in shop.get_employee_ids():
		initiator_id = handle_id if handle_id is not None else player_id
		return f'Error: {initiator_id} does not work at {shop.name}.'
	if player_id == shop.owner_id:
		if handle_id is None:
			return f'Error: {player_id} is the owner of {shop.name} and cannot be removed.'
		else:
			return f'Error: {handle_id} is controlled by {player_id} who is the owner of {shop.name} and cannot be removed.'

	# Revoke the discord role:
	role = actors.get_actor_role(shop.shop_id)
	await server.remove_role_from_member(member, role)
	# Update the shop's record:
	players.remove_shop(player_id, shop.shop_id)
	# Update the player's record:
	shop.employees = [e for e in shop.employees if e.player_id != player_id]

	store_shop(shop)

	ident_string = player_id if handle_id is None else f'{player_id} (controlling handle {handle_id})'
	return (f'Removed employee {ident_string} from {shop.name}. '
		+ 'They no longer have access to the shop\'s finances, chat or order channels, and can no longer edit the product catalogue.')

async def process_fire_command(user_id : str, handle_id : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name, must_be_owner=True)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	if handle_id is None:
		return 'Error: must give a a handle'
	handle : Handle = handles.get_handle(handle_id)
	if handle.handle_type == HandleTypes.Unused:
		return f'Error: handle {handle_id} does not exist.'

	return await remove_employee(shop, handle.actor_id, handle.handle_id)

async def remove_employee_player(player_id : str, shop_name : str):
	if not shop_exists(shop_name):
		return
	shop : Shop = read_shop(shop_name)
	await remove_employee(shop, player_id)


async def set_tips_for_user(user_id : str, handle_id : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	player_id = players.get_player_id(user_id)

	if handle_id is not None:
		handle : Handle = handles.get_handle(handle_id)
		if handle.handle_type == HandleTypes.Unused:
			return f'Error: handle {handle_id} does not exist.'
		if player_id != handle.actor_id:
			return f'Error: you do not control handle {handle_id}.'

	if shop.edit_tips_handle(player_id, handle_id):
		store_shop(shop)
		return f'Done.'
	else:
		return f'Error: could not update tip handle for {player_id} because they do not work at {shop.name}.'




## Adding and editing products for a shop


def get_emoji_for_new_product(symbol : str):
	if symbol is None:
		return emoji_shopping
	elif symbol in product_emojis:
		return product_emojis[symbol]
	else:
		# Hope that the symbol string itself contains an emoji
		return symbol


async def add_product(user_id : str, product_name : str, description : str, price : int, symbol : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	if product_name is None:
		return f'Error: must give a product name; use \".add_product <product_name> [Optional: description, price, type/symbol]\"'
	if product_exists(shop.shop_id, product_name):
		existing_product = read_product(shop.shop_id, product_name)
		if existing_product.name == product_name:
			return f'Error: the shop {shop.shop_id} already has a product called {product_name}.'
		else:
			return (f'Error: cannot create {product_name} at {shop.shop_id} because its internal ID '
				+ f'({product_name.lower()}) clashes with {existing_product.name}.)')
	if price < 0:
		return f'Error: {product_name} cannot have a negative price.'
	emoji = get_emoji_for_new_product(symbol)

	product = Product(
		name=product_name,
		description=description if description is not None else f'Order a {product_name}!',
		price=price,
		emoji=emoji)
	store_product(shop.shop_id, product)
	return (f'Added product {product_name} to {shop.shop_id}.')


async def remove_product(user_id : str, product_name : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	if product_name is None:
		return f'Error: must give a product name; use \".remove_product <product_name>\"'
	if not product_exists(shop.shop_id, product_name):
		return f'Error: shop {shop.shop_id} has no product called {product_name}.'

	product = read_product(shop.shop_id, product_name)
	# First, remove its listing:
	product.available = False
	product.in_stock = False

	tasks = (asyncio.create_task(update_catalogue_item_message(shop, ch, product)) for ch in shop.storefront_channels())
	await asyncio.gather(*tasks)

	# Then, remove it completely from database:
	delete_product(shop.shop_id, product.product_id)

	return (f'Removed product {product.name} from {shop.shop_id}.')


async def edit_product_from_command(user_id : str, product_name : str, key : str, value : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop
	return edit_product(shop, product_name, key, value)


def edit_product(shop : Shop, product_name : str, key : str, value : str):
	if product_name is None:
		return f'Error: must give a product name; use \".add_product {shop.shop_id} <product_name>. (Optional: add description, price, and type/symbol)\"'
	product = read_product(shop.shop_id, product_name)
	if product is None:
		return f'Error: no product called \"{product_name}\" at {shop.name}.'
	if key is None:
		return f'Error: must give the property to edit. usage: \".edit_product {shop.shop_id} {product_name} <property> <value>\"'

	key = key.lower()
	if key in ['available', 'in_stock'] and value is None:
		value = 'true'
	if value is None:
		return f'Error: must set the new value of property \"{key}\"'

	edited = False

	if key == 'description':
		product.description = value
		edited = True
	elif key in ['available', 'in_stock']:
		if value in ['true', 't', '1']:
			new_value = True
		elif value in ['false', 'f', '0']:
			new_value = False
		else:
			return f'Error: did not understand value \"{value}\" for property \"{key}\"'
		if key == 'available':
			product.available = new_value
		else:
			product.in_stock = new_value
		edited = True
	elif key == 'price':
		try:
			old_price = product.price
			new_price = int(value)
			product.price = new_price
			edited = old_price != new_price
		except ValueError:
			return f'Error: cannot set price to \"{value}\"; must be a number.'
	elif key in ['type', 'symbol', 'emoji']:
		emoji = get_emoji_for_new_product(value)
		edited = emoji != product.emoji
		product.emoji = emoji
	if edited:
		store_product(shop.shop_id, product)
		return 'Done.'
	else:
		return 'Your command resulted in no change.'



### The storefront: by reacting to the messages in this channel,
#   customers can perform actions at the shop (e.g. order products)

async def update_storefront(user_id : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	tasks = (asyncio.create_task(_update_storefront_channel(shop, ch)) for ch in shop.storefront_channels())
	await asyncio.gather(*tasks)

async def _update_storefront_channel(shop: Shop, channel):
	await update_storefront_delivery_choice_message(shop, channel)

	for product in get_all_products(shop.shop_id):
		await update_catalogue_item_message(shop, channel, product)

	await update_storefront_tipping_message(shop, channel)

	return 'Done.'


# Delivery choice message: a welcome message that allows customers to choose where to get their order delivered

bar_emoji = '🍸'
call_emoji = '📣'

async def update_storefront_delivery_choice_message(shop : Shop, channel):
	# TODO: track whether this shop is actually a restaurant, and otherwise edit this message
	content = (
		f'Please select your table using the buttons:\n' +
		f'{number_emojis[0]}–{number_emojis[max_table_number]}: serve at this table number\n' +
		f'{bar_emoji}: serve at the bar\n' +
		f'{call_emoji}: call out my current handle when the order is ready (note: you need to click this again if you switch handle)'
		)
	previous_message_exists = False
	prev_msg_id = get_delivery_choice_message(shop.shop_id, channel.guild.id)
	if prev_msg_id is not None:
		try:
			message = await channel.fetch_message(prev_msg_id)
			await message.edit(content=content)
			await message.clear_reactions()
			previous_message_exists = True
		except discord.errors.NotFound:
			# Reference to a message in storefront that is no longer available
			# Doesn't matter since the product should not be available anyway
			pass

	if not previous_message_exists:
		await channel.purge()
		message = await channel.send(content)
		await channel.send(
			f'{common.hard_space}\n' +
			'Use the buttons below to order! If you make a mistake, you can cancel the order from your **finance** channel (if you\'re fast enough).\n' +
			f'{common.hard_space}')
	if message is None:
		raise RuntimeError(f'Error: failed to find the delivery choice message in storefront, dump: {shop.to_string()}')
	else:
		await add_delivery_choice_reactions(message, max_table_number)
		store_delivery_choice_message(shop.shop_id, str(message.id), channel.guild.id)

async def add_delivery_choice_reactions(message, max_tables : int):
	for e in number_emojis[:(max_tables+1)]:
		await message.add_reaction(e)
	await message.add_reaction(bar_emoji)
	await message.add_reaction(call_emoji)

### The menu/catalogue: product information messages where players can order by pressing reactions

async def post_catalogue_item(user_id : str, product_name : str, shop_name : str):
	result : FindShopResult = await find_shop_for_command(user_id, shop_name)
	if result.error_report is not None or result.shop is None:
		return result.error_report
	shop : Shop = result.shop

	product = read_product(shop.shop_id, product_name)
	if product is None:
		return f'Error: there is no product called {product_name} at {shop.shop_id}'

	tasks = (asyncio.create_task(update_catalogue_item_message(shop, ch, product)) for ch in shop.storefront_channels())
	await asyncio.gather(*tasks)


async def update_catalogue_item_message(shop : Shop, channel, product : Product):
	if not product.available:
		msg_id = product.get_storefront_message_id(channel.guild.id)
		if msg_id is not None:
			delete_storefront_msg_mapping(shop.shop_id, msg_id)
			try:
				message = await channel.fetch_message(msg_id)
				await message.delete()
			except discord.errors.NotFound:
				# Reference to a message in storefront that is no longer available
				# Doesn't matter since the product should not be available anyway
				pass
		return

	# If we get here, the product is set to available, so we need to
	# either post the message or edit the existing one to updated description
	content = generate_catalogue_item_message(product)
	previous_msg = product.get_storefront_message_id(channel.guild.id)
	if previous_msg is not None:
		# Instead of sending a new message, update the existing one
		delete_storefront_msg_mapping(shop.shop_id, previous_msg)
		try:
			message = await channel.fetch_message(previous_msg)
			await asyncio.gather(
				*[asyncio.create_task(c)
				for c
				in [message.clear_reactions(), message.edit(content=content)]]
				)
		except discord.errors.NotFound:
			# Reference to a message in storefront that is no longer available
			# Either due to reinitialize(), or due to being removed by an admin
			previous_msg = None
	if previous_msg is None:
		# There is no previous message to update so we must send a new one
		message = await channel.send(content)

	if message is not None:
		product.set_storefront_message_id(channel.guild.id, str(message.id))
		if product.in_stock:
			await message.add_reaction(product.emoji)
		action = StorefrontAction(StorefrontActionTypes.Order, data=product.product_id)
		store_storefront_msg_mapping(shop.shop_id, str(message.id), action)
		store_product(shop.shop_id, product)
	else:
		raise RuntimeError(f'Error: failed to publish product, dump: {product.to_string()}')


def generate_catalogue_item_message(product):
	if product.in_stock:
		post = f'{product.emoji}   __**{product.name}**__\n'
	else:
		post = f'{emoji_unavail}   __**{product.name}**__ _!!! OUT OF STOCK !!!_\n'
	post += (f'> Price: {coin} **{product.price}**\n'
		+ f'> {product.description}\n'
		)
	return post


# The tipping message: reactions here will transfer some money to the staff

async def update_storefront_tipping_message(shop : Shop, channel):
	prev_msg_id = get_tipping_message(shop.shop_id, channel.guild.id)
	# The tipping message is at the bottom of the channel, so it needs to be re-posted every time to ensure the correct order
	#if msg_id is not None: #If there is no tipping data recorded, no need to do anything.
	#	store_tipping_message(shop.shop_id, msg_id)
	if prev_msg_id is not None:
		# Delete the previous message
		delete_storefront_msg_mapping(shop.shop_id, prev_msg_id)
		try:
			message = await channel.fetch_message(prev_msg_id)
			await message.delete()
		except discord.errors.NotFound:
			pass

	tipping_tuples = shop.generate_tips_list()
	if len(tipping_tuples) > 0:
		content = 'Don\'t forget to tip the servers and staff! Working right now:\n'
		for (handle_id, emoji) in tipping_tuples:
			content += f'{emoji}: **{handle_id}**\n'
		content += f'One reaction = **{coin} 1**!'
		message = await channel.send(content)
		if message is not None:
			store_tipping_message(shop.shop_id, str(message.id), channel.guild.id)
			for (_, emoji) in tipping_tuples:
				print(f'Adding reaction: {emoji}')
				await message.add_reaction(emoji)
		else:
			raise RuntimeError(f'Failed to post tipping message for shop, dump: {shop.to_string()}')
	else:
		# No employees with valid tipping handles -> no action
		pass


	





### Reactions:

### Reaction in storefront: select table, order a product, give a tip

async def process_reaction_in_storefront(message, user_id : str, emoji : str):
	result = ActionResult()
	shop_id = read_storefront_channel_mapping(str(message.channel.id))
	if shop_id is None:
		result.report = f'Error: tried to order {emoji} from shop but could not map channel {message.channel.id} to any shop.'
		return result		
	shop : Shop = read_shop(shop_id)
	if shop is None:
		result.report = f'Error: tried to order {emoji} from shop but could not find shop.'
		return result

	action : StorefrontAction = read_storefront_msg_mapping(shop.shop_id, str(message.id))
	if action is None:
		result.report = f'Error: tried to process {emoji} but could not map message id {message.id} to any action.'
	elif action.action_type == StorefrontActionTypes.Order:
		product_id = action.data
		if product_id is None:
			result.report = f'Error: tried to order {emoji} from {shop.name} but could not map the message to a product.'
			return result
		product : Product = read_product(shop_id, product_id)
		if product is None:
			result.report = f'Error: cannot find product {product_id} at shop {shop.name}.'
			return result
		if product.emoji != emoji:
			# TODO: add a reaction an employee can use to mark an item as out qof stock
			# Wrong reaction -- silently ignore it.
			return result

		player_id = players.get_player_id(user_id, expect_to_find=True)
		buyer_handle : Handle = handles.get_active_handle(player_id)

		result = await order_product(shop, product, buyer_handle)
	elif action.action_type == StorefrontActionTypes.SetDeliveryOption:
		player_id = players.get_player_id(user_id, expect_to_find=True)
		result = set_delivery_table_from_reaction(shop, player_id, emoji)
	elif action.action_type == StorefrontActionTypes.Tip:
		player_id = players.get_player_id(user_id, expect_to_find=True)
		result = await tip_staff_from_reaction(shop, player_id, emoji)
	else: # TODO: implement other action types
		result.report = f'Error: unsupported operation {action.action_type}.'
	return result


### Reaction in order_flow: will update orders

def get_actionable_emojis(status : OrderStatus):
	if status == OrderStatus.Active:
		return [emoji_accept, emoji_locked]
	elif status == OrderStatus.Locked:
		return [emoji_accept]
	else:
		return []

async def process_reaction_in_order_flow(channel_id : str, msg_id : str, emoji : str):
	result = ActionResult()
	shop_id = read_order_flow_channel_mapping(channel_id)
	if shop_id is None:
		result.report = f'Error: tried to edit order but could not map channel {channel_id} to any shop.'
		return result		
	shop : Shop = read_shop(shop_id)
	if shop is None:
		result.report = f'Error: tried to edit order, but could not find {shop_id} in database.'
		return result
	mapping : MsgOrderMapping = get_order_mapping_from_msg(shop.shop_id, msg_id)
	if mapping is None:
		result.report = f'Error: tried to edit order, but could not map the message to a recent order; it has been delivered or aborted.'
		return result

	if emoji not in get_actionable_emojis(mapping.status):
		# No action, but no report required either.
		return result

	async with get_order_semaphore(shop.shop_id, mapping.identifier):
		print(f'Trying to mark order {mapping.identifier}, {mapping.status} as {emoji}')
		order = None
		if mapping.status == OrderStatus.Active:
			order = fetch_active_order(shop.shop_id, mapping.identifier)
		elif mapping.status == OrderStatus.Locked:
			order = fetch_locked_order(shop.shop_id, mapping.identifier)
		if order is None:
			result.report = f'Error: tried to fetch order for {mapping.identifier} but could not find it. DB corrupt.'
			return result

		datetime_timestamp = datetime.datetime.today()
		timestamp = PostTimestamp(datetime_timestamp.hour, datetime_timestamp.minute)
		order.time_updated = timestamp

		if mapping.status == OrderStatus.Active and emoji == emoji_locked:
			result.report = await lock_active_order(shop, order)
		elif emoji == emoji_accept:
			result.report = await deliver_order(shop, order, mapping.status)

	# The above functions will only return something in the error case
	result.success = result.report is None
	return result



### Making an order:

# TODO: make this a class function
def generate_order_message(order : Order, status : OrderStatus):
	if status == OrderStatus.Active:
		if order.updated:
			content = f'**#{order.order_id}** for **{order.delivery_id}** {emoji_alert}{emoji_unlocked} updated at {order.time_updated.pretty_print()}\n'
		else:
			content = f'**#{order.order_id}** for **{order.delivery_id}**   {emoji_unlocked} created at {order.time_created.pretty_print()}\n'
	elif status == OrderStatus.Locked:
		content = f'**#{order.order_id}** for **{order.delivery_id}**	{emoji_locked} locked at {order.time_updated.pretty_print()}\n'
	elif status == OrderStatus.Delivered:
		content = f'**#{order.order_id}** for **{order.delivery_id}**	{emoji_accept} delivered at {order.time_updated.pretty_print()}\n'		
	for item, amount in order.items_ordered.items():
		# TODO: add the emoji for each product, as many times as the order, e.g. "4 Beer 🍺 🍺 🍺 🍺"
		content += f'> {amount} {item}\n'
	if order.all_paid():
		content += f'> Total: {coin} {order.price_total} (all paid)'
	else:
		content += f'> Total: {coin} {order.price_total} ({order.paid_total} paid)'
	return content

async def add_gui_reactions_to_order(message, status : OrderStatus):
	await message.clear_reactions()
	for emoji in get_actionable_emojis(status):
		await message.add_reaction(emoji)


async def order_product_from_command(user_id : str, shop_name : str, product_name : str):
	player_id = players.get_player_id(user_id)
	buyer_handle : Handle = handles.get_active_handle(player_id)
	return await order_product_for_buyer(shop_name, product_name, buyer_handle)

async def order_product_for_buyer(shop_name : str, product_name : str, buyer_handle : Handle):
	product = read_product(shop_name, product_name) # This implicitly checks that shop exists
	if product is None:
		print(f'Trying to order {product_name} from {shop_name}, found none')
		if product_name is None:
			return f'Error: no product name given. Use \".order <product_name> <shop_name>\"'
		elif shop_name is None:
			return f'Error: no shop name given. Use \".order {product_name} <shop_name>\"'
	else:
		print(f'Trying to order {product_name} from {shop_name}, found {product.to_string()}')

	if buyer_handle is None:
		return 'Error: no payer ID supplied.'
	if not buyer_handle.is_active():
		return f'Error: cannot find buyer handle {buyer_handle.handle_id}.'

	shop : Shop = read_shop(shop_name)
	result : ActionResult = await order_product(shop, product, buyer_handle)
	return result.report

# Semaphores for order, for when someone tries to add to order, lock/deliver order, and/or refund order at the same time

delivery_ids_semaphores = {}

def get_order_semaphore(shop_id : str, delivery_id : str):
	sem_id = shop_id + delivery_id
	if delivery_ids_semaphores.get(sem_id) is None:
		delivery_ids_semaphores[sem_id] = asyncio.Semaphore(1)
	return delivery_ids_semaphores[sem_id]

def clear_order_semaphores_for_shop(shop_id : str):
	global delivery_ids_semaphores
	for sem_id in delivery_ids_semaphores:
		if sem_id.startswith(shop_id):
			del delivery_ids_semaphores[sem_id]


async def order_product(shop : Shop, product : Product, buyer_handle : Handle):
	result = ActionResult()
	if not product.in_stock:
		return f'Sorry - {shop.name} is all out of {product.name}!'

	delivery_id = get_delivery_id(shop.shop_id, buyer_handle.actor_id)
	if delivery_id is None:
		# No delivery ID set for this player
		delivery_id = buyer_handle.handle_id

	must_be_pre_paid = True
	if buyer_handle.actor_id in shop.get_employee_ids():
		delivery_id = delivery_id + " [UNPAID]"
		must_be_pre_paid = False

	async with get_order_semaphore(shop.shop_id, delivery_id):
		# TODO: use "from_reaction" somehow to ensure not all transaction failures end up in cmd line?
		datetime_timestamp = datetime.datetime.today()
		timestamp = PostTimestamp(datetime_timestamp.hour, datetime_timestamp.minute)
		transaction = Transaction(
			payer=buyer_handle.handle_id,
			payer_actor=buyer_handle.actor_id,
			recip=shop.shop_id,
			recip_actor=shop.shop_id,
			amount=product.price,
			cause=TransTypes.ShopOrder,
			data=product.name,
			timestamp=timestamp)
		transaction.emoji = product.emoji
		if must_be_pre_paid:
			transaction = await finances.try_to_pay(transaction)
		if must_be_pre_paid and not transaction.success:
			result.report = transaction.report
		else:
			# Otherwise, we move on to create the order
			print(f'{transaction.payer} just bought {transaction.data} from {transaction.recip}!')
			await place_order_in_flow(shop, transaction, delivery_id, must_be_pre_paid)

			result.report = f'Successfully ordered {product.name} from {shop.name}'
			result.success = True
	return result

async def place_order_in_flow(shop : Shop, purchase : Transaction, delivery_id : str, pre_paid : bool):
	previous_order_updated = False
	order = fetch_active_order(shop.shop_id, delivery_id)
	if order is not None:
		# The previous order will have been deleted from active_orders
		time_diff = PostTimestamp.get_time_diff(order.time_created, purchase.timestamp)
		if time_diff <= shop.order_collection_limit:
			order = await add_to_active_order(shop, order, purchase, pre_paid)
			previous_order_updated = True
		else:
			# Lock the previous order
			order.time_updated = purchase.timestamp
			await lock_active_order(shop, order)

	if not previous_order_updated:
		order_flow_channel = channels.get_discord_channel(shop.order_flow_channel_id)
		order_id = str(record_new_order(shop.shop_id))
		order = Order(
			order_id,
			delivery_id,
			purchase.amount,
			paid_total = purchase.amount if pre_paid else 0,
			items_ordered = {purchase.data: 1},
			time_created = purchase.timestamp,
			undo_hooks = purchase.get_undo_hooks_list()
			)
		post = generate_order_message(order, OrderStatus.Active)
		message = await order_flow_channel.send(post)
		await add_gui_reactions_to_order(message, OrderStatus.Active)
		order.order_flow_msg_id = message.id
	store_active_order(shop.shop_id, order)



async def add_to_active_order(shop : Shop, order : Order, purchase : Transaction, pre_paid : bool):
	order.add(purchase.data, purchase.amount, purchase.timestamp, pre_paid)
	order_flow_channel = channels.get_discord_channel(shop.order_flow_channel_id)
	order_flow_message = await order_flow_channel.fetch_message(order.order_flow_msg_id)
	content = generate_order_message(order, OrderStatus.Active)
	await order_flow_message.delete()
	new_message = await order_flow_channel.send(content)
	await add_gui_reactions_to_order(new_message, OrderStatus.Active)
	# The mapping to the order message itself, for when we need to update it:
	order.order_flow_msg_id = new_message.id
	# The mapping to the messages in each player's respective finance channel, which
	# we need to find when we lock or complete the order, to take away the "undo" possibility
	for t in purchase.get_undo_hooks_list():
		order.undo_hooks.append(t)
	return order


async def lock_active_order(shop : Shop, order : Order):
	await order.remove_undo_hooks()
	content = generate_order_message(order, OrderStatus.Locked)

	try:
		order_flow_channel = channels.get_discord_channel(shop.order_flow_channel_id)
	except discord.errors.NotFound:
		return f'Error: could not edit order, {shop.name} database is corrupt.'
	try:
		order_flow_message = await order_flow_channel.fetch_message(order.order_flow_msg_id)
		await order_flow_message.edit(content=content)
		await add_gui_reactions_to_order(order_flow_message, OrderStatus.Locked)
	except discord.errors.NotFound:
		# Post a new message -- there may be an old one that we have lost track of, but this is better than nothing
		message = await order_flow_channel.send(content)
		await add_gui_reactions_to_order(message, OrderStatus.Locked)
		order.order_flow_msg_id = message.id
	
	store_locked_order(shop.shop_id, order)


async def deliver_order(shop : Shop, order : Order, status : OrderStatus):
	if status == OrderStatus.Active:
		await order.remove_undo_hooks()

	try:
		order_flow_channel = channels.get_discord_channel(shop.order_flow_channel_id)
	except discord.errors.NotFound:
		return f'Error: could not edit order, {shop.name} database is corrupt.'
	try:
		order_flow_message = await order_flow_channel.fetch_message(order.order_flow_msg_id)
	except discord.errors.NotFound:
		return f'Error: tried to mark order as delivered but the message in {order_flow_channel.name} could not be found.'
	
	content = generate_order_message(order, OrderStatus.Delivered)
	await order_flow_message.edit(content=content)
	await add_gui_reactions_to_order(order_flow_message, OrderStatus.Delivered)
	# No need to store the order now -- we hereby lose track of it in the backend
	# (The last message is left in the discord channel, but will disappear on the next clear_orders)


### Refunds

async def attempt_refund(transaction : Transaction, initiator_id : str):
	transaction.success = False
	transaction.cause = TransTypes.ShopRefund
	shop_id = transaction.recip_actor
	shop : Shop = read_shop(shop_id)
	if shop is None:
		transaction.report = f'Error: could not refund purchase becase shop no longer exists.'
		# Unsuccessful -- shop no longer exists!
		return

	datetime_timestamp = datetime.datetime.today()
	timestamp = PostTimestamp(datetime_timestamp.hour, datetime_timestamp.minute)
	time_diff = PostTimestamp.get_time_diff(transaction.timestamp, timestamp)
	# Update timestamp now that we got the info we needed from the old one
	transaction.timestamp=timestamp

	initiated_by_shop = initiator_id == shop_id

	if time_diff > shop.order_collection_limit and not initiated_by_shop:
		# Do not lock in the order automatically -- if the shop wants to refund, they can still do so
		# This means the player can go to the staff and ask for their help, even after trying for themselves first
		transaction.report = (f'Error: could not refund purchase becase too long time has passed (limit: {shop.order_collection_limit} minutes). '
			+ f'If it has not yet been delivered, you can still ask {shop_id} staff to refund it for you.')
		return

	buyer_player_id = transaction.payer_actor
	delivery_id = get_delivery_id(shop_id, buyer_player_id)
	if delivery_id is None:
		delivery_id = handles.get_active_handle_id(buyer_player_id)
		if delivery_id is None:
			if initiated_by_shop:
				transaction.report = (f'Error: could not find order to refund. If the buyer has switched their delivery option '
				+'(e.g. table, address, handle), they need to switch back in order to map the transaction to the order.')
			else:
				transaction.report = (f'Error: could not find order to refund. If you have switched your delivery option '
				+'(e.g. table, address, handle), try switching back to the one you had when you ordered. 1')
			return

	async with get_order_semaphore(shop.shop_id, delivery_id):
		order = fetch_active_order(shop_id, delivery_id)
		if order is None:
			if initiated_by_shop:
				transaction.report = (f'Error: could not find order to refund. Perhaps it has already been locked in or delivered. '
					+ 'Otherwise, if the buyer has switched their delivery option (e.g. table, address, handle), '
					'they need to switch back in order to map the transaction to the order.')
			else:
				transaction.report = (f'Error: could not find order to refund. If you have switched your delivery option '
					+'(e.g. table, address, handle), try switching back to the one you had when you ordered. 2')
			return

		product_name = transaction.data
		number_of_product_in_order = 0
		if product_name in order.items_ordered:
			number_of_product_in_order = int(order.items_ordered[product_name])
		if number_of_product_in_order <= 0:
			# This typically means the refund is too late -- perhaps it was clicked right at the same time when staff
			# marked the order as "locked" or "delivered". Both those options should remove the undo option from the
			# buyer's side, though.
			transaction.report = f'Error: could not refund. Order has been delivered, is in preparation, or this item has already been refunded.'
			return

		# attempt to transfer back money
		transaction.amount = -transaction.amount
		# Note: try_to_pay will turn any negative transaction into a positive one first, flipping payer and recip
		await finances.try_to_pay(transaction)

		if not transaction.success:
			# try_to_pay will have put in a good-enough error message
			transaction.report = 'Error: could not refund.\n' + transaction.report
			return

		await execute_refund_in_order_flow(shop, transaction, order)


async def execute_refund_in_order_flow(shop : Shop, refund : Transaction, order : Order):
	# Remove the item from the order:
	product_name = refund.data
	new_number = int(order.items_ordered[product_name]) - 1
	if new_number > 0:
		order.items_ordered[product_name] = new_number
	else:
		del order.items_ordered[product_name]

	order_empty = len(order.items_ordered) == 0

	# Remove the financial record entries for the refunded transaction
	# (also prevents the other party from trying to refund the same purchase a second time)
	undo_hook_message_ids_to_remove = [refund.payer_msg_id, refund.recip_msg_id]
	remaining_undo_hooks = []
	for (actor_id, msg_id) in order.undo_hooks:
		if msg_id in undo_hook_message_ids_to_remove:
			await actors.remove_tentative_transaction(actor_id, msg_id)
		elif order_empty:
			# If the order is empty, we don't expect any other undo hooks,
			# but we may as well remove the "undo" option if any are lingering
			await actors.lock_tentative_transaction(actor_id, msg_id)
		else:
			remaining_undo_hooks.append((actor_id, msg_id))
	order.undo_hooks = remaining_undo_hooks

	try:
		order_flow_channel = channels.get_discord_channel(shop.order_flow_channel_id)
	except discord.errors.NotFound:
		refund.success = False
		refund.report = f'Error: refund performed but {shop.name} database is corrupt -- order status may be shown wrong.'
		return
		# Either the channel or the message is missing.
	try:
		order_flow_message = await order_flow_channel.fetch_message(order.order_flow_msg_id)
	except discord.errors.NotFound:
		if not order_empty:
			refund.success = False
			refund.report = f'Error: refund performed but {shop.name} database is corrupt -- order status may be shown wrong.'
			# Post a new message -- there may be an old one that we have lost track of, but this is better than nothing
			content = generate_order_message(order, OrderStatus.Active)
			message = await order_flow_channel.send(content)
			order.order_flow_msg_id = message.id
			store_active_order(shop.shop_id, order)

	if order_empty:
		# There is nothing left, so we shall remove the order
		await order_flow_message.delete()
		alert = (f'Order #{order.order_id} for {order.delivery_id} has been cancelled. '
			+ f'The last item that was refunded was 1 {refund.data} {refund.emoji}.')
		await order_flow_channel.send(alert, delete_after=10)
	else:
		order.price_total -= refund.amount
		content = generate_order_message(order, OrderStatus.Active)
		await order_flow_message.edit(content=content)
		store_active_order(shop.shop_id, order)


### Tipping staff

async def tip_staff_from_reaction(shop : Shop, player_id : str, emoji : str):
	result = ActionResult()

	for employee in shop.employees:
		if employee.emoji == emoji:
			transaction = await finances.try_to_pay_from_actor(
				player_id,
				employee.handle_for_tips,
				amount=1,
				from_reaction=True
				)
			result.success = transaction.success
			if transaction.report != None:
				result.report = transaction.report
			break
	# If we do not find the employee, we just fail silently.
	# Most likely reason is that someone has added a reaction that does not correspond to any employee,
	# and we don't want any alerts from that.
	return result


### Delivery IDs -- where a player's order is to be delivered e.g. a table number

def check_delivery_id_input(delivery_id :str, shop_name : str):
	if delivery_id is None:
		return 'Error: must give a delivery ID.'
	if shop_name is None:
		return 'Error: must give a shop name.'
	if not shop_exists(shop_name):
		return f'Error: There is no shop called {shop_name}.'

def set_delivery_id_from_command(user_id : str, delivery_id :str, shop_name : str):
	report = check_delivery_id_input(delivery_id, shop_name)
	if report is not None:
		return report
	player_id = players.get_player_id(user_id, expect_to_find=True)
	store_delivery_id(shop_name, player_id, delivery_id)	
	return f'Done. All orders made by {player_id} (using any handle!) at {shop_name} will be delivered to {delivery_id}.'



# A special version of set_delivery_id 


def set_delivery_table_from_command(user_id : str, option :str, shop_name : str):
	report = check_delivery_id_input(option, shop_name)
	if report is not None:
		return report

	player_id = players.get_player_id(user_id, expect_to_find=True)
	action : ActionResult = set_delivery_table(player_id, option, shop_name)
	return action.report

def set_delivery_table_from_reaction(shop : Shop, player_id : str, emoji : str):
	result = ActionResult()
	if emoji in number_emojis:
		e_dict = dict(zip(number_emojis, range(len(number_emojis))))
		option = str(e_dict[emoji])
	elif emoji == bar_emoji:
		option = 'bar'
	elif emoji == call_emoji:
		option = 'call'
	else:
		result.report = f'Error: {emoji} does not correspond to a valid delivery option.'
		return result
	return set_delivery_table(player_id, option, shop.name)

def set_delivery_table(player_id : str, option :str, shop_name : str):
	result = ActionResult()
	if option == 'bar':
		delivery_id = 'the bar'
		delivery_str = f'served at the **bar**'
	elif option == 'call':
		# Call out the order for their current handle
		handle_id = handles.get_active_handle_id(player_id)
		if handle_id is None:
			result.report = f'Error: Tried to set delivery option to \"call out my name\", but could not determine your current handle!'
			return result
		delivery_id = f'{handle_id} (call out)'
		delivery_str = f'called out to **{handle_id}**'
	else:
		try:
			table_number = int(option)
			if table_number < 0 or table_number > max_table_number:
				result.report = f'Error: there is no table {option} at {shop_name}.'
				return result
			delivery_id = f'Table {table_number}'
			delivery_str = f'delivered to **{delivery_id}**'
		except ValueError:
			result.report = f'Error: \"{option}\" is not a valid table number (0–{max_table_number}) or delivery option.'
			return result

	store_delivery_id(shop_name, player_id, delivery_id)
	result.report = f'Done. All orders made by {player_id} (using any handle!) at {shop_name} will be {delivery_str}.'
	result.success = True
	return result





