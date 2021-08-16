#shops.py

import discord
import asyncio
import simplejson

from configobj import ConfigObj

# Custom imports
import handles
import channels
import players
import finances
import server


catalogues_dir = 'shops'

shops = ConfigObj(f'shops.conf')

### Module to set certain player to have a shop.
# Having a shop grants:
# - A public storefront, where the "meny" is presented as messages you can react to
# - An "orders" channel, showing what people have ordered recently
# - A "delivery ID" (e.g. table number) for each customer,
#   so that orders can be collected and delivered together

### Classes, init and utilities:

class Shop(object):
	def __init__(
		self,
		shop_name : str,
		player_id : str,
		storefront_channel_id : str,
		order_flow_channel_id : str):
		self.shop_name = shop_name
		self.player_id = player_id
		self.shop_id = shop_name.lower() if shop_name is not None else None
		self.storefront_channel_id = storefront_channel_id
		self.order_flow_channel_id = order_flow_channel_id

	@staticmethod
	def from_string(string : str):
		obj = Shop(None, None, None, None)
		obj.__dict__ = simplejson.loads(string)
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

class Product(object):
	def __init__(
		self,
		name : str,
		description : str,
		price : int,
		file_name : str=None,
		storefront_msg_id : str=None,
		available : bool=False):
		self.name = name
		self.description = description
		self.price = price
		self.file_name = file_name
		self.storefront_msg_id = storefront_msg_id
		self.available = available

	@staticmethod
	def from_string(string : str):
		obj = Product(None, None, None, None)
		obj.__dict__ = simplejson.loads(string)
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)





async def init(bot, clear_all=False):
	if clear_all:
		for shop_name in shops:
			del shops[shop_name]
		shops.write()
		await channels.delete_all_shops(bot)
		# TODO: clear order flow channels


def shop_exists(shop_name : str):
	return shop_name.lower() in shops

def store_shop(shop : Shop):
	shops[shop.shop_id] = shop.to_string()
	shops.write()

def read_shop(shop_name : str):
	shop_id = shop_name.lower()
	if shop_id in shops:
		return Shop.from_string(shops[shop_id])


def get_catalogue(shop_name : str):
	shop_id = shop_name.lower()
	catalogue_file_name = f'{shop_id}.conf'
	return ConfigObj(f'{catalogues_dir}/{catalogue_file_name}')


def store_product(shop_name : str, product : Product):
	if shop_exists(shop_name):
		catalogue = get_catalogue(shop_name)
		catalogue[product.name] = product.to_string()
		catalogue.write()

def read_product(shop_name : str, product_name):
	if shop_exists(shop_name):
		catalogue = get_catalogue(shop_name)
		if product_name in catalogue:
			return Product.from_string(catalogue[product_name])



### Creating a new shop:

async def create_shop(guild, shop_name : str, player_id : str):
	if shop_name is None:
		return 'Error: must give a shop name'
	if player_id is None:
		return f'Error: must give a player id; use \".create_shop {shop_name} <player_id>\"'
	if not players.player_exists(player_id):
		return f'Error: player {player_id} does not exist.'
	if shop_exists(shop_name):
		existing_shop = read_shop(shop_name)
		if existing_shop.shop_name == shop_name:
			return f'Error: the shop {shop_name} already exists.'
		else:
			return (f'Error: cannot create {shop_name} because its internal ID '
				+ f'({shop_name.lower()}) clashes with {existing_shop.shop_name}.)')


	storefront_channel = await channels.create_shop_channel(guild, shop_name)
	storefront_channel_id = str(storefront_channel.id)

	order_flow_channel = await channels.create_order_flow_channel(guild, player_id, shop_name)
	order_flow_channel_id = str(order_flow_channel.id)

	# TODO: send welcome message

	shop = Shop(shop_name, player_id, storefront_channel_id, order_flow_channel_id)
	store_shop(shop)
	report = f'Created store {shop_name}, run by {player_id}'
	return report


# TODO: command to add products
async def add_product(guild, shop_name : str, product_name : str):
	if shop_name is None:
		return 'Error: must give a shop name'
	if product_name is None:
		return 'Error: must give a product name; use \".add_product {shop_name} <product_name>\"'
	if not shop_exists(shop_name):
		return 'Error: shop {shop_name} does not exist'

	product = Product(name=product_name, description=f'Buy a {product_name}!', price=0)
	store_product(shop_name, product)

