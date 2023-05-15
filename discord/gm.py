import actors
import player_setup
import scenarios
import artifacts
import channels
import server
import handles

from discord.ext import commands
from discord import app_commands, Interaction
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

	@app_commands.command(
		name='add_known_handle',
		description='GM-only. Add a player\'s handle before they join the server.',
#		help=(
#			'Add a player\'s handle before they join the server. ' +
#			'When a player claims the given handle, their initial data ' +
#			'(aliases, money, groups etc) will be set up automatically.'
#			),
		)
	@app_commands.checks.has_role(gm_role_name)
	async def add_known_handle_command(self, interaction: Interaction, handle_id: str):
		if handle_id is None:
			await interaction.response.send_message('Error: provide a handle', ephemeral=True)
		else:
			player_setup.add_known_handle(handle_id)
			await interaction.response.send_message(f'Added entry for {handle_id}. Please update its contents manually by editing the file.', ephemeral=True)


	@app_commands.command(name='run_scenario', description='GM-only. Run a scenario.')
	@app_commands.checks.has_role(gm_role_name)
	async def run_scenario_command(self, interaction: Interaction, name: str):
		report = await scenarios.run_scenario(name)
		if report is None:
			report = "Command finished without any output"
		await interaction.response.send_message(report, ephemeral=True)

	@app_commands.command(name='create_scenario', description='GM-only. Create a basic scenario.')
	@app_commands.checks.has_role(gm_role_name)
	async def create_scenario_command(self, interaction: Interaction, name: str):
		report = await scenarios.create_scenario(name)
		if report is None:
			report = "Command ended without any output"
		await interaction.response.send_message(report, ephemeral=True)

	@app_commands.command(name='create_artifact', description='GM-only. Create an artifact.',
#		help=(
#			'Create an artifact, which is any sort of digital content that players can access ' +
#			'using some sort of username/password setup. Examples include encrypted cloud storage ' +
#			'(where the player finds the user/pw) and physical devices that the player \"connects\" to ' +
#			'(by entering a device ID, \"port number\" or similar which is printed on the physical thing).'
#			),
		)
	@app_commands.checks.has_role(gm_role_name)
	async def create_artifact_command(self, interaction: Interaction, name: str, content: str):
		report = artifacts.create_artifact(name, content)
		if report is None:
			report = "Unknown error. Contact system admin."
		await interaction.response.send_message(report, ephemeral=True)

	@app_commands.command(name='init_gm', description='GM-only. Reinitialise the GM context and handles.')
	@app_commands.checks.has_role(gm_role_name)
	async def init_gm_command(self, interaction: Interaction):
		await interaction.response.defer(ephemeral=True)
		async with handles.semaphore():
			await init(clear_all=True)
		await interaction.followup.send('Done.', ephemeral=True)


async def setup(bot):
	await bot.add_cog(GmCog(bot))

async def init(clear_all : bool=False):
	exists = actors.actor_exists(gm_actor_id)
	if exists and clear_all:
		await actors.clear_actor(gm_actor_id)
	if not exists or clear_all:
		await create_gm_actor()

async def create_gm_actor():
	actor : actors.Actor = await actors.create_gm_actor(
		server.get_guild(),			# always use the first guild for gm
		role_name=gm_role_name,
		actor_id=gm_actor_id)
	response = await player_setup.setup_handles_no_welcome_new_player(gm_actor_id, gm_actor_id)
	if response:
		print(response)

def get_gm_active_handle():
	handle = handles.get_active_handle(gm_actor_id)
	return handle.handle_id