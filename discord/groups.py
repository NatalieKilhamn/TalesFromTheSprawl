# module groups.py

### This module collects storage and utilities for groups, which are essentially access roles that
# more than one player can share.
# TODO: a shop could be implemented with a group as a base, to represent the employees and access part of it
# Possible refactoring: split "actor" into "access role" (which groups, players and shops all share)
# and "finance and chat capabilities", which only players and shops have
# (this would avoid the double-implementation of access roles that currently exists between groups and actors)

import discord
import asyncio
import simplejson

from configobj import ConfigObj
from typing import List, Tuple
from copy import deepcopy
from enum import Enum

# Custom imports
import common
import channels
import actors
import server
import players
import handles

from common import emoji_alert, emoji_accept, group_role_start, highest_ever_index
from custom_types import ActionResult, Handle, HandleTypes


# TODO: show members?

groups_conf_dir = 'groups'
groups_file_name = groups_conf_dir + '/groups.conf'

class Group(object):
	def __init__(
		self,
		group_index : str,
		group_id : str,
		main_channel_id : str,
		members : List[str] = None # player_ids
		):
		self.group_index = group_index
		self.group_id = group_id
		self.members = [] if members is None else members
		self.main_channel_id = main_channel_id

	@staticmethod
	def from_string(string : str):
		obj = Group(None, None, None)
		obj.__dict__ = simplejson.loads(string)
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def store(self):
		groups = ConfigObj(groups_file_name)
		groups[self.group_id] = self.to_string()
		groups.write()

	async def add_member(self, member, player_id : str):
		self.members.append(player_id)
		self.store()

		players.add_group(player_id, self.group_id)

		role = self.get_role()
		if role is not None:
			await server.give_member_role(member, role)
		else:
			print(f'Error: could not find the role belonging to group {self.group_id}')

	async def remove_member(self, player_id : str):
		self.members = [m for m in self.members if m != player_id]
		self.store()

		member = await server.get_member_from_nick(player_id)
		if member is None:
			return f'Error: actor {player_id} is not a player, or does not follow the server nick scheme.'
		
		role = self.get_role()
		await server.remove_role_from_member(member, role)

	def get_role(self):
		guild = server.get_guild()
		return discord.utils.find(lambda role: role.name == self.group_index, guild.roles)

	@staticmethod
	def exists(group_name : str):
		if group_name is not None:
			groups = ConfigObj(groups_file_name)
			return group_name.lower() in groups

	@staticmethod
	def read(group_name : str):
		if group_name is not None:
			group_id = group_name.lower()
			if group_id in get_all_group_ids():
				groups = ConfigObj(groups_file_name)
				return Group.from_string(groups[group_id])

	@staticmethod
	def get_next_index():
		groups = ConfigObj(groups_file_name)
		prev_highest = int(groups[highest_ever_index])
		group_index = str(prev_highest + 1)
		groups[highest_ever_index] = group_index
		groups.write()
		return group_index


# Init and utils

async def init(guild, clear_all=False):
	for group_id in get_all_group_ids():
		await clear_group(guild, group_id, spare_used=not clear_all)
	clear_all = clear_all or not any_groups()
	if clear_all:
		await channels.delete_all_group_channels()
	await delete_all_group_roles(guild, spare_used=(not clear_all))	

	groups = ConfigObj(groups_file_name)
	if highest_ever_index not in groups or clear_all:
		groups[highest_ever_index] = str(group_role_start)		
		groups.write()
	

async def clear_group(guild, group_id : str, spare_used : bool):
	if Group.exists(group_id):
		group = Group.read(group_id)
		if len(group.members) > 0 and spare_used:
			return f'Did not remove group {group_id} because it has members.'
		for player_id in group.members:
			players.remove_group(player_id, group.group_id)
		groups = ConfigObj(groups_file_name)
		del groups[group_id]
		groups.write()
		await delete_all_group_roles(guild, spare_used=True)
		return 'Done'
	else:
		return f'Could not find group {group_id}'

async def delete_all_group_roles(guild, spare_used : bool):
	task_list = (asyncio.create_task(delete_if_group_role(r, spare_used)) for r in guild.roles)
	await asyncio.gather(*task_list)

async def delete_if_group_role(role, spare_used : bool):
	if await is_group_role(role.name):
		if not spare_used or len(role.members) == 0:
			await role.delete()

async def is_group_role(name :str):
	return common.is_group_role(name)

def get_group_role(group_id : str):
	group = Group.read(group_id)
	if group is not None:
		return group.get_role()


def get_all_groups():
	for group_id in get_all_group_ids():
		yield Group.read(group_id)

def get_all_group_ids():
	groups = ConfigObj(groups_file_name)
	for group_id in groups:
		if group_id != highest_ever_index:
			yield group_id

def any_groups():
	groups = ConfigObj(groups_file_name)
	for group_id in groups:
		if group_id != highest_ever_index:
			return True
	return False


def get_main_channel(group_name : str):
	if group_name is not None:
		group_id = group_name.lower()
		group : Group = Group.read(group_id)
		if group is not None:
			return channels.get_discord_channel(group.main_channel_id)



# Create group

async def create_group_from_command(ctx, group_name : str):
	if group_name is None:
		return f'Error: must give a group name.'

	player_id = players.get_player_id(str(ctx.message.author.id))
	if player_id is not None:
		members = [player_id]
		members_report = f' The first member is {player_id}'
	else:
		members = []
		members_report = ''
	if Group.exists(group_name):
		return f'Error: group {group_name} already exists, or its internal ID ({group_name.lower()}) would clash with existing group.'
	group = await create_new_group(ctx.guild, group_name, initial_members=members)
	return f'Created group \"{group.group_id}\".' + members_report

async def create_new_group(guild, group_name : str, initial_members : List[str] = None, has_channel : bool=True):
	initial_members = [] if initial_members is None else initial_members
	print(f'Creating new group {group_name} with players {initial_members}')
	group_id = group_name.lower()
	group_index = Group.get_next_index()

	# Create role for this group:
	role = await guild.create_role(name=group_index)

	# Create channel for the group:
	channel_id = None
	if has_channel:
		channel = await channels.create_group_channel(guild, role, group_id)
		channel_id = str(channel.id)

	for player_id in initial_members:
		players.add_group(player_id, group_id)
		member = await server.get_member_from_nick(player_id)
		if member is not None:
			await server.give_member_role(member, role)

	group = Group(
		group_index=group_index,
		group_id=group_id,
		main_channel_id=channel_id,
		members=initial_members)
	group.store()
	return group


# Edit groups

async def add_member_from_handle(guild, group_id : str, handle_id : str):
	if handle_id is None:
		return f'Error: you must give a handle ID and group name. Use \".add_member <handle> <group>\"'
	handle : Handle = handles.get_handle(handle_id)
	if handle.handle_type == HandleTypes.Unused:
		return f'Error: handle {handle_id} does not exist.'
	member = await server.get_member_from_nick(handle.actor_id)
	if member is None:
		return f'Error: actor {handle.actor_id} is not a player, or does not follow the server nick scheme.'
	if group_id is None:
		return f'Error: you must give a group name. Use \".add_member {handle_id} <group>\"'
	group : Group = Group.read(group_id)
	if group is None:
		return f'Error: could not find group {group_id}.'

	if handle.actor_id in group.members:
		return f'Player {handle.actor_id} (owner of handle {handle.handle_id}) is already a member of {group.group_id}.'

	error_report = await group.add_member(member, handle.actor_id)
	if error_report is None:
		return f'Added {handle.handle_id} to group {group.group_id}.'
	else:
		return error_report

async def add_member_from_player_id(group_id : str, player_id : str):
	if player_id is None:
		return f'Error: you must give a player ID.'
	member = await server.get_member_from_nick(player_id)
	if member is None:
		return f'Error: actor {player_id} is not a player, or does not follow the server nick scheme.'
	if group_id is None:
		return f'Error: you must give a group name.'
	group : Group = Group.read(group_id)
	if group is None:
		return f'Error: could not find group {group_id}.'

	if player_id in group.members:
		return f'Player {player_id} is already a member of {group.group_id}.'

	error_report = await group.add_member(member, player_id)
	if error_report is None:
		return f'Added {player_id} to group {group.group_id}.'
	else:
		return error_report


async def remove_member_from_player_id(group_id : str, player_id : str):
	group : Group = Group.read(group_id)
	if group is None:
		return f'Error: could not find group {group_id}.'
	await group.remove_member(player_id)


# Use groups

async def give_group_access(channel, group_id : str):
	role = get_group_role(group_id)
	await server.give_role_access(channel, role)


def get_members_of_groups(group_ids : List[str]):
	members = []
	for group_id in group_ids:
		group : Group = Group.read(group_id)
		if group is not None:
			for player_id in group.members:
				if player_id not in members:
					members.append(player_id)
	print(f'Found members {members} in groups {group_ids}')
	return members
