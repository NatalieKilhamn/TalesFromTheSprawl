import actors
import player_setup
import scenarios
import artifacts
import channels
import server
import handles

from discord.ext import commands
from dotenv import load_dotenv
import os


### Module gm.py
# This module holds the gm cog, which is used to set up in-game content and track resources shared by all GMs

load_dotenv()
gm_role_name = os.getenv('GM_ROLE_NAME')
gm_actor_id = gm_role_name

class GmCog(commands.Cog, name=gm_role_name):
	"""GM-only commands, hidden by default. To view documentation, use \"help <command>\". The commands are:
	add_known_handle, create_scenario, run_scenario, create_artifact"""
	def __init__(self, bot):
		self.bot = bot
		self._last_member = None

	# GM-only commands for setting up in-game content.

	@commands.command(
		name='add_known_handle',
		brief='GM-only. Add a player\'s handle.',
		help=(
			'Add a player\'s handle before they join the server. ' +
			'When a player claims the given handle, their initial data ' +
			'(aliases, money, groups etc) will be set up automatically.'
			),
		hidden=True
		)
	@commands.has_role(gm_role_name)
	async def add_known_handle_command(self, ctx, handle_id : str):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		if handle_id is None:
			await ctx.send('Error: provide a handle')
		else:
			player_setup.add_known_handle(handle_id)
			await ctx.send(f'Added entry for {handle_id}. Please update its contents manually by editing the file.')



	@commands.command(
		name='run_scenario',
		help='GM-only. Run a scenario.',
		hidden=True)
	@commands.has_role(gm_role_name)
	async def run_scenario_command(self, ctx, name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await scenarios.run_scenario(name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='create_scenario',
		help='GM-only. Create a basic scenario.',
		hidden=True)
	@commands.has_role(gm_role_name)
	async def create_scenario_command(self, ctx, name : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = await scenarios.create_scenario(name)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='create_artifact',
		brief='GM-only. Create an artifact.',
		help=(
			'Create an artifact, which is any sort of digital content that players can access ' +
			'using some sort of username/password setup. Examples include encrypted cloud storage ' +
			'(where the player finds the user/pw) and physical devices that the player \"connects\" to ' +
			'(by entering a device ID, \"port number\" or similar which is printed on the physical thing).'
			),
		hidden=True
		)
	@commands.has_role(gm_role_name)
	async def create_artifact_command(self, ctx, name : str=None, content : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = artifacts.create_artifact(name, content)
		if report is not None:
			await ctx.send(report)

	@commands.command(
		name='init_gm',
		brief='GM-only. Reinitialise the GM context and handles.',
		hidden=True
		)
	@commands.has_role(gm_role_name)
	async def init_gm_command(self, ctx):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		sem_id = await handles.get_semaphore('init_gm')
		if sem_id is None:
			await ctx.send('Failed: system is too busy. Wait a few minutes and try again.')
		else:
			await init(clear_all=True)
			await ctx.send('Done.')
			handles.return_semaphore(sem_id)


def setup(bot):
	bot.add_cog(GmCog(bot))

async def init(clear_all : bool=False):
	exists = actors.actor_exists(gm_actor_id)
	if exists and clear_all:
		await actors.clear_actor(server.get_guild(), gm_actor_id)
	if not exists or clear_all:
		await create_gm_actor()

async def create_gm_actor():
	actor : actors.Actor = await actors.create_gm_actor(
		server.get_guild(),
		role_name=gm_role_name,
		actor_id=gm_actor_id)
	response = await player_setup.setup_handles_no_welcome_new_player(gm_actor_id, gm_actor_id)
	if response:
		print(response)

def get_gm_active_handle():
	handle = handles.get_active_handle(gm_actor_id)
	return handle.handle_id