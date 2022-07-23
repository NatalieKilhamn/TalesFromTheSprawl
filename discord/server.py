import asyncio
import discord
from typing import List

from common import system_role_name, admin_role_name, all_players_role_name, gm_role_name, new_player_role_name

guilds = []
guild_roles = {}

# TODO: restrict reactions to only the channels where they actually do anything.
# This is a third category I think:
# private with emoji: yes, chats
# private without emoji: yes cmd_line
# private read-only with emoji: yes, order flow (although they might not be "private", more like "groups")
# private read-only without emoji: yes, finance
# public with emoji: yes, all
# public read-only with emoji: yes, shops
# public without emoji: perhaps none?
#
# Easiest would be to just pass in a separate parameter

no_access = discord.PermissionOverwrite(read_messages=False, send_messages=False)
normal_access = discord.PermissionOverwrite(read_messages=True) # Will get send access depending on all_players_role settings for this channel
super_access = discord.PermissionOverwrite(read_messages=True, send_messages=True)

private_read_only_base = no_access
# A little weird to set read=False send=True,
# but it means that anyone who does get read access will automatically also have send access
private_normal_base = discord.PermissionOverwrite(read_messages=False, send_messages=True)
public_read_only_base = discord.PermissionOverwrite(read_messages=True, send_messages=False)
public_normal_base = super_access

async def init(connected_guilds):
	for guild in connected_guilds:
		guilds.append(guild)
		guild_roles[guild.id] = {}
		for role_name in [system_role_name, admin_role_name, gm_role_name, all_players_role_name, new_player_role_name]:
			guild_roles[guild.id][role_name] = await _init_role(guild, role_name)

async def _init_role(guild, role_name: str):
	role = discord.utils.find(lambda role: role.name == role_name, guild.roles)
	if role is None:
		print(f'Creating role with name {role_name}')
		role = await guild.create_role(name=role_name)
	return role

def get_guild(guild_id=None):
	for guild in guilds:
		if guild.id == guild_id:
			return guild
	return guilds[0]	# Fallback solution

def get_guilds():
	return guilds

async def give_role_access(channel, role):
	if channel.guild.id != role.guild.id:
		print(f'Warning: Trying to set role permissions on a channel from a different guild')
	await channel.set_permissions(role, overwrite=normal_access)

async def give_member_role(member, role):
	if member.guild.id != role.guild.id:
		print(f'Warning: Trying to give member a role from a different guild')
	new_roles = member.roles
	if role not in member.roles:
		new_roles.append(role)
	await member.edit(roles=new_roles)

async def remove_role_from_member(member, role):
	if role is None:
		return
	new_roles = member.roles
	new_roles = [r for r in member.roles if r.name != role.name]
	await member.edit(roles=new_roles)

def check_member_has_role(member, role_names : List[str]):
	if member is not None:
		for role_name in role_names:
			if role_name in [r.name for r in member.roles]:
				return True
	return False

async def set_user_as_new_player(member):
	new_player_role = get_new_player_role(member.guild)
	await give_member_role(member, new_player_role)

def get_all_players_role(guild):
	return guild_roles[guild.id][all_players_role_name]

def get_system_role(guild):
	return guild_roles[guild.id][system_role_name]

def get_admin_role(guild):
	return guild_roles[guild.id][admin_role_name]

def get_gm_role(guild):
	return guild_roles[guild.id][gm_role_name]

def get_new_player_role(guild):
	return guild_roles[guild.id][new_player_role_name]

def _generate_overwrites_own_private_channel(player_role):
	return {player_role: normal_access}

def generate_overwrites_own_new_private_channel(player_role, read_only : bool=False, gm_extra_access : bool=False):
	return (
		{**generate_base_overwrites(player_role.guild, private=True, read_only=read_only, gm_extra_access=gm_extra_access),
		**_generate_overwrites_own_private_channel(player_role)
		})

def generate_base_overwrites(guild, private : bool, read_only : bool, gm_extra_access : bool=False):
	if private:
		access_level = private_read_only_base if read_only else private_normal_base
	else:
		access_level = public_read_only_base if read_only else public_normal_base	
	return (
		{guild.default_role: no_access,
		get_all_players_role(guild): access_level,
		get_system_role(guild): super_access,
		get_admin_role(guild): super_access,
		get_gm_role(guild): normal_access if (gm_extra_access or not private) else no_access
		})

def generate_setup_channel_overwrites(guild):
	return (
		{guild.default_role: no_access,
		get_all_players_role(guild): no_access,
		get_system_role(guild): super_access,
		get_admin_role(guild): super_access,
		get_gm_role(guild): super_access,
		get_new_player_role(guild): super_access
		})

async def get_member_from_nick(nick : str):
	if nick is not None:
		for guild in guilds:
			members = await guild.fetch_members(limit=100).flatten()
			member = discord.utils.find(lambda m: m.nick == nick, members)
			if member:
				return member

async def get_all_channels_in(guild):
	return await guild.fetch_channels()

async def get_all_channels():
	task_list = (asyncio.create_task(guild.fetch_channels()) for guild in guilds)
	channels_per_guild = await asyncio.gather(*task_list)
	return [channel for channels in channels_per_guild for channel in channels]

async def get_mirrored_channels(channel):
	result = []
	for guild in guilds:
		channels = await get_all_channels_in(guild)
		channel_in_guild = discord.utils.find(lambda c: c.name == channel.name, channels)
		if channel_in_guild:
			result.append(channel_in_guild)
	return result

async def swallow(message, alert=True, delay : int=0):
	if delay > 0:
		await message.delete(delay=delay)
	else:
		await message.delete()
	if alert:
		await message.channel.send(
			'```You cannot use that command here. Use your #cmd_line instead.```',
			delete_after=5)
