import actors
import players
import groups
import channels
import server
import handles
import common

from discord.ext import commands
from discord import app_commands, Interaction
import discord

### Module admin.py
# This module holds the admin cog, which is used to


# TODO: change these to be admin-only (currently they are actually GM-only)
# TODO: grab the name of the admin role from env file

class AdminCog(commands.Cog, name='admin'):
	"""Admin-only commands, hidden by default. To view documentation, use \"help <command>\". The commands are:
	init_all_players, fake_join, fake_join_name, fake_join_nick, clear_all_players, clear_all_actors, clear_actor, ping"""
	def __init__(self, bot):
		self.bot = bot
		self._last_member = None

	# Admin-only commands for testing etc.

	#This command is not safe right now.
	@app_commands.command(
		name='init_all_players',
		description='Admin-only. Initialise all current members of the server as players.'
		)
	@app_commands.checks.has_role('gm')
	async def init_all_players_command(self, interaction: Interaction):
		await interaction.response.defer(ephemeral=True)
		await players.initialise_all_users()
		await interaction.followup.send('Done.', ephemeral=True)

	@app_commands.command(
		name='fake_join',
		description='Admin-only. Initialise a user as a player.')
	@app_commands.checks.has_role('gm')
	async def fake_join_command(self, interaction: Interaction, user_id: int, handle: str):
		await interaction.response.defer(ephemeral=True)
		member_to_fake_join = await interaction.guild.fetch_member(user_id)
		if member_to_fake_join is None:
			await interaction.followup.send(f'Failed: member with user_id {user_id} not found.', ephemeral=True)
		elif handle is None:
			await interaction.followup.send(f'Failed: you must give the player\'s main handle.', ephemeral=True)
		else:
			async with handles.semaphore():
				report = await players.create_player(member_to_fake_join, handle)
				if report is None:
					report = "Done."
			await interaction.followup.send(report, ephemeral=True)

	@app_commands.command(
		name='fake_join_name',
		description='Admin-only. Initialise a user as a player (based on discord name).')
	@app_commands.checks.has_role('gm')
	async def fake_join_name_command(self, interaction: Interaction, name: str, handle: str):
		await interaction.response.defer(ephemeral=True)
		member_to_fake_join = None
		async for member in interaction.guild.fetch_members(limit=100):
			if member.name == name:
				member_to_fake_join = member
				break
		if member_to_fake_join is None:
			await interaction.followup.send(f'Failed: member with name {name} not found.', ephemeral=True)
		elif handle is None:
			await interaction.followup.send(f'Failed: you must give the player\'s main handle.', ephemeral=True)
		else:
			async with handles.semaphore():
				report = await players.create_player(member_to_fake_join, handle)
				if report is None:
					report = "Done."
			await interaction.followup.send(report, ephemeral=True)

	@app_commands.command(
		name='fake_join_nick',
		description='Admin-only. Initialise a user as a player (based on server nick).')
	@app_commands.checks.has_role('gm')
	async def fake_join_nick_command(self, interaction: Interaction, nick: str, handle: str):
		await interaction.response.defer(ephemeral=True)
		member_to_fake_join = await server.get_member_from_nick(nick)
		if member_to_fake_join is None:
			await interaction.followup.send(f'Failed: member with nick {nick} not found.', ephemeral=True)
		elif handle is None:
			await interaction.followup.send(f'Failed: you must give the player\'s main handle.', ephemeral=True)
		else:
			async with handles.semaphore():
				report = await players.create_player(member_to_fake_join, handle)
				if report is None:
					report = "Done."
			await interaction.followup.send(report, ephemeral=True)

	# This command ONLY works in the landing page channel.
	# Note: no other commands work in the landing page channel!
	# TODO: semaphore for joining
	@app_commands.command(
		name='join',
		description='Claim a handle and join the game. Only for players who have not yet joined.')
	@app_commands.checks.has_role(common.new_player_role_name)
	async def join_command(self, interaction: Interaction, handle: str):
		await interaction.response.defer(ephemeral=True)
		member = await interaction.guild.fetch_member(interaction.user.id)
		if member is None:
			await interaction.followup.send('Failed: member not found.', ephemeral=True)
		elif handle is None or handle == 'handle' or handle == '<handle>':
			await interaction.followup.send('You must say which handle is yours! Example: \"/join shadow_weaver\"', ephemeral=True)
		else:
			async with handles.semaphore():
				# TODO give player some sort of warning about using lower-case only
				handle_id = handle.lower()
				report = await players.create_player(member, handle_id)
			if report is not None:
				await interaction.followup.send(f'Failed: invalid starting handle \"{handle_id}\" (or handle is already taken).', ephemeral=True)
			else:
				await interaction.followup.send('Success! Now have a look at all your new channels 🥳', ephemeral=True)

	@app_commands.command(
		name='clear_all_players',
		description='Admin-only. De-initialise all players.')
	@app_commands.checks.has_role('gm')
	async def clear_all_players_command(self, interaction: Interaction):
		await interaction.response.defer(ephemeral=True)
		await players.init(clear_all=True)
		try:
			await interaction.followup.send('Done.', ephemeral=True)
		except discord.errors.NotFound:
			print('Cleared all players. Could not send report because channel is missing – '
				+'the command was probably given in a player-only command line that was deleted.')

	@app_commands.command(
		name='clear_all_actors',
		description='Admin-only: de-initialise all actors (players and shops).')
	@app_commands.checks.has_role('gm')
	async def clear_all_actors_command(self, interaction: Interaction):
		await interaction.response.defer(ephemeral=True)
		await actors.init(clear_all=True)
		try:
			await interaction.followup.send('Done.', ephemeral=True)
		except discord.errors.NotFound:
			print('Cleared all actors. Could not send report because channel is missing – '
				+'the command was probably given in a player-only command line that was deleted.')

	@app_commands.command(
		name='clear_actor',
		description='Admin-only: de-initialise an actor (player or shop).')
	@app_commands.checks.has_role('gm')
	async def clear_actor_command(self, interaction: Interaction, actor_id: str):
		await interaction.response.defer(ephemeral=True)
		report = await actors.clear_actor(actor_id)
		try:
			await interaction.followup.send(report, ephemeral=True)
		except discord.errors.NotFound:
			print(f'Cleared actor {actor_id}. Could not send report because channel is missing – '
				+'the command was probably given in a player-only command line that was deleted.')
	
	@app_commands.command(
		name='ping',
		description='Admin-only. Send a ping to a player\'s cmd_line channel.')
	@app_commands.checks.has_role('gm')
	async def ping_command(self, interaction: Interaction, player_id : str):
		await interaction.response.defer(ephemeral=True)
		channel = players.get_cmd_line_channel(player_id)
		if channel is not None:
			await channel.send(f'Testing ping for {player_id}')
			await interaction.followup.send('OK', ephemeral=True)
		else:
			await interaction.followup.send(f'Error: could not find the command line channel for {player_id}', ephemeral=True)

	@app_commands.command(
		name='add_member',
		description='Admin-only. Add a member to a group.')
	@app_commands.checks.has_role('gm')
	async def add_member_command(self, interaction: Interaction, handle_id: str, group_id: str):
		await interaction.response.defer(ephemeral=True)
		report = await groups.add_member_from_handle(interaction.guild, group_id, handle_id)
		if report is not None:
			await interaction.followup.send(report, ephemeral=True)
		else:
			await interaction.followup.send('Failed to add member from handle', ephemeral=True)

	@app_commands.command(
		name='create_group',
		description='Admin-only. Create a group with yourself as initial member.')
	@app_commands.checks.has_role('gm')
	async def create_group_command(self, interaction: Interaction, group_name: str):
		await interaction.response.defer(ephemeral=True)
		report = await groups.create_group_from_command(interaction.user.id, group_name)
		if report is not None:
			await interaction.followup.send(report, ephemeral=True)

	@app_commands.command(
		name='clear_all_groups',
		description='Admin-only. Delete all groups.')
	@app_commands.checks.has_role('gm')
	async def clear_all_groups_command(self, interaction: Interaction):
		await interaction.response.defer(ephemeral=True)
		await groups.init(clear_all=True)
		await interaction.followup.send('Done.', ephemeral=True)



async def setup(bot):
	await bot.add_cog(AdminCog(bot))