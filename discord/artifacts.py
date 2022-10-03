# module artifacts.py

# This module handles the creation and execution of in-game artifacts, which are items that can be accessed through
# logging in with codes.

import simplejson
from configobj import ConfigObj
from typing import List
from copy import deepcopy
from discord.ext import commands

import channels

#TODO: reinitialise?

class ArtifactsCog(commands.Cog, name='network'):
	"""Commands for connecting to devices and accessing files."""
	def __init__(self, bot):
		self.bot = bot
		self._last_member = None

	@commands.command(name='connect', help='Connect to device or remote server. Aliases: .login, .access')
	async def connect_command(self, ctx, name : str=None, code : str=None):
		allowed = await channels.pre_process_command(ctx)
		if not allowed:
			return
		report = access_artifact(name, code)
		if report is not None:
			await ctx.send(report)

	@commands.command(name='login', help='Connect to device or remote server. Same as .connect.', hidden=True)
	async def login_command(self, ctx, name : str=None, code : str=None):
		await self.connect_command(ctx, name, code)

	@commands.command(name='access', help='Connect to device or remote server. Same as .connect.', hidden=True)
	async def access_command(self, ctx, name : str=None, code : str=None):
		await self.connect_command(ctx, name, code)

	@commands.command(name='ACCESS', help='Connect to device or remote server. Same as .connect.', hidden=True)
	async def access_upper_command(self, ctx, name : str=None, code : str=None):
		await self.connect_command(ctx, name, code)

	@commands.command(name='LOGIN', help='Connect to device or remote server. Same as .connect.', hidden=True)
	async def login_upper_command(self, ctx, name : str=None, code : str=None):
		await self.connect_command(ctx, name, code)

	@commands.command(name='CONNECT', help='Connect to device or remote server. Same as .connect.', hidden=True)
	async def connect_upper_command(self, ctx, name : str=None, code : str=None):
		await self.connect_command(ctx, name, code)


def setup(bot):
	bot.add_cog(ArtifactsCog(bot))



artifacts_conf_dir = 'artifacts'
main_index = '___main'

def init(clear_all : bool=False):
	with open(f'{artifacts_conf_dir}/__artifacts.conf', "r", encoding='utf-8') as read_file:
		artifacts_main_conf = ConfigObj(read_file, encoding='UTF8')
	for art_name in artifacts_main_conf:
		if clear_all:
			del artifacts_main_conf[art_name]
		else:
			artifact = Artifact.from_string(artifacts_main_conf[art_name])
			artifact.store()

class FileArea(object):
	def __init__(
		self,
		content : str,
		codes : List[str] = None):
		# TODO: also add a list of handles to alert on access
		self.content = content
		self.codes = [] if codes is None else codes

	@staticmethod
	def from_string(string : str):
		obj = FileArea(None, None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)


class Artifact(object):
	def __init__(
		self,
		name : str,
		areas : List[FileArea] = None):
		self.name = name
		self.areas = [] if areas is None else areas

	@staticmethod
	def from_string(string : str):
		obj = Artifact(None)
		loaded_dict = simplejson.loads(string)
		obj.__dict__.update(loaded_dict)
		for i, area_str in enumerate(loaded_dict['areas']):
			obj.areas[i] = FileArea.from_string(area_str)
		return obj

	def to_string(self):
		dict_to_save = deepcopy(self.__dict__)
		list_of_areas = [step.to_string() for step in dict_to_save['areas']]
		dict_to_save['areas'] = list_of_areas
		return simplejson.dumps(dict_to_save)

	def store(self):
		artifacts_main_conf = ConfigObj(f'{artifacts_conf_dir}/__artifacts.conf', encoding='UTF8')
		artifacts_main_conf[self.name] = self.to_string()
		artifacts_main_conf.write()
		file_name = f'{artifacts_conf_dir}/{self.name}.conf'
		art_conf = ConfigObj(file_name, encoding='UTF8')
		for entry in art_conf:
			del art_conf[entry]
		for area in self.areas:
			for code in area.codes:
				art_conf[code] = area.to_string()
		art_conf.write()

	@staticmethod
	def get_contents_from_storage(name : str, code : str):
		artifacts_main_conf = ConfigObj(f'{artifacts_conf_dir}/__artifacts.conf', encoding='UTF8')
		if code is None:
			# When given only one input, we search through all artifact to find one that matches
			try_code = name
			for try_name in artifacts_main_conf:
				file_name = f'{artifacts_conf_dir}/{try_name}.conf'
				art_conf = ConfigObj(file_name, encoding='UTF8')
				if try_code in art_conf:
					return Artifact.get_contents_from_storage(try_name, try_code)

		if name is None:
			return f'Error: you must give the name of the entity you want to access.'
		if name not in artifacts_main_conf:
			return f'Error: entity \"{name}\" not found. Check the spelling.'
		file_name = f'{artifacts_conf_dir}/{name}.conf'
		art_conf = ConfigObj(file_name, encoding='UTF8')
		#if code is None:
		#	main = art_conf[main_index]
		#	if main is None or main == '':
		#		return f'Error: entity \"{name}\" cannot be accessed without a password / code. Use \".connect {name} <code>\"'
		#	else:
		#		return art_conf[main_index]
		#elif code not in art_conf:
		if code not in art_conf:
			return f'Error trying to access {name}: incorrect credentials \"{code}\".'
		else:
			area = FileArea.from_string(art_conf[code])
			return area.content


def create_artifact(name : str, main : str=None):
	if name is None:
		return 'Error: you must give a name for the artifact.'
	artifact = Artifact(
		name,
		main = main)
	if main is None:
		artifact.areas.append(
			FileArea(
				content = 'This is the description of the area, which contains a link to a Drive folder.',
				codes = ['example_code_1', 'example_code_2']
				)
			)
	artifact.store()
	return f'Created artifact {name}.'

def access_artifact(name : str, code : str):
	result = Artifact.get_contents_from_storage(name, code)
	return result
