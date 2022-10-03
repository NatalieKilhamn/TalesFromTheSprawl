# module scenarios.py

# This module handles the creation and execution of scenarios, which are automated sequences of in-game events.
# A scenario could be for example a simulated network crash, automated spam messages, or creation of a new group.

import asyncio
import simplejson
from configobj import ConfigObj
from enum import Enum
from typing import List
from copy import deepcopy

import players
import handles
import groups
import game


class EventType(str, Enum):
	Wait = 'wait'
	NetworkOutage = 'outage'
	NetworkDown = 'down'
	NetworkRestored = 'up'
	MessagePlayersByHandles = 'msg_handles'
	MessageAllPlayersExceptHandles = 'msg_except_handles'
	MessageGroups = 'msg_groups'
	MessageExceptGroups = 'msg_except_groups'
	Unknown = 'NA'


async def send_message_to_channels(message : str, channel_list):
	task_list = [asyncio.create_task(c.send(message)) for c in channel_list]
	await asyncio.gather(*task_list)

class WaitEvent(object):
	def __init__(
		self,
		time_in_seconds : int = 60
		):
		self.time_in_seconds = time_in_seconds

	@staticmethod
	def from_string(string : str):
		obj = WaitEvent()
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.Wait

	async def execute(self):
		await asyncio.sleep(self.time_in_seconds)



class NetworkOutageEvent(object):
	def __init__(
		self,
		time_in_seconds : int = 60
		):
		self.time_in_seconds = time_in_seconds

	@staticmethod
	def from_string(string : str):
		obj = NetworkOutageEvent()
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.NetworkOutage

	async def execute(self):
		down = NetworkDownEvent()
		await down.execute()
		await asyncio.sleep(self.time_in_seconds)
		restored = NetworkRestoredEvent()
		await restored.execute()


class NetworkDownEvent(object):
	def __init__(self):
		pass

	@staticmethod
	def from_string(string : str):
		obj = NetworkDownEvent()
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.NetworkDown

	async def execute(self):
		channel_list = [players.get_cmd_line_channel(p) for p in players.get_all_players()]
		await send_message_to_channels('```Error: Network connection lost```', channel_list)
		game.set_network_down()

class NetworkRestoredEvent(object):
	def __init__(self):
		pass

	@staticmethod
	def from_string(string : str):
		obj = NetworkRestoredEvent()
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.NetworkRestored

	async def execute(self):
		channel_list = [players.get_cmd_line_channel(p) for p in players.get_all_players()]
		game.set_network_restored()
		await send_message_to_channels('```Network connection restored```', channel_list)



class MessagePlayersByHandleEvent(object):
	def __init__(
		self,
		message : str,
		handles : List[str]=None
		):
		self.message = message
		self.handles = [] if handles is None else handles

	@staticmethod
	def from_string(string : str):
		obj = MessagePlayersByHandleEvent(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.MessagePlayersByHandles

	async def execute(self):
		channel_list = players.get_cmd_line_channels_for_handles(self.handles)
		await send_message_to_channels(self.message, channel_list)


class MessagePlayersExceptHandlesEvent(object):
	def __init__(
		self,
		message : str,
		handles : List[str]=None
		):
		self.message = message
		self.handles = [] if handles is None else handles

	@staticmethod
	def from_string(string : str):
		obj = MessagePlayersExceptHandlesEvent(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.MessageAllPlayersExceptHandles

	async def execute(self):
		channel_ids_to_avoid = [c.id for c in players.get_cmd_line_channels_for_handles(self.handles)]
		channel_list = []
		for player_id in players.get_all_players():
			channel = players.get_cmd_line_channel(player_id)
			if channel is not None and channel.id not in channel_ids_to_avoid:
				channel_list.append(channel)
		await send_message_to_channels(self.message, channel_list)

# groups:

class MessageGroupsEvent(object):
	def __init__(
		self,
		message : str,
		groups : List[str]=None
		):
		self.message = message
		self.groups = [] if groups is None else handles

	@staticmethod
	def from_string(string : str):
		obj = MessageGroupsEvent(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.MessageGroups

	async def execute(self):
		channel_list = [
			players.get_cmd_line_channel(c)
			for c
			in groups.get_members_of_groups(self.groups)
			]
		for channel in channel_list:
			print(f'Found channel {channel}')
		await send_message_to_channels(self.message, channel_list)


class MessageExceptGroupsEvent(object):
	def __init__(
		self,
		message : str,
		groups : List[str]=None
		):
		self.message = message
		self.groups = [] if groups is None else groups

	@staticmethod
	def from_string(string : str):
		obj = MessageExceptGroupsEvent(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def get_type(self):
		return EventType.MessageExceptGroups

	async def execute(self):
		channel_ids_to_avoid = [
			players.get_cmd_line_channel(c).id
			for c
			in groups.get_members_of_groups(self.groups)
			]		
		channel_list = []
		for player_id in players.get_all_players():
			channel = players.get_cmd_line_channel(player_id)
			if channel is not None and channel.id not in channel_ids_to_avoid:
				channel_list.append(channel)
		await send_message_to_channels(self.message, channel_list)




class Event(object):
	def __init__(
		self,
		event_type : EventType,
		data : str,
		repetitions : int = 1,
		spacing : int = 0 # in seconds
		):
		self.event_type = event_type
		self.data = data
		self.repetitions = repetitions
		self.spacing = spacing

	def from_specific_event(event_obj, repetitions : int=1, spacing : int=0):
		return Event(event_obj.get_type(), event_obj.to_string(), repetitions=repetitions, spacing=spacing)

	@staticmethod
	def from_string(string : str):
		obj = Event(EventType.Unknown, None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def to_specific_type(self):
		if self.event_type == EventType.Wait:
			return WaitEvent.from_string(self.data)
		elif self.event_type == EventType.NetworkOutage:
			return NetworkOutageEvent.from_string(self.data)
		elif self.event_type == EventType.NetworkDown:
			return NetworkDownEvent.from_string(self.data)
		elif self.event_type == EventType.NetworkRestored:
			return NetworkRestoredEvent.from_string(self.data)
		elif self.event_type == EventType.MessagePlayersByHandles:
			return MessagePlayersByHandleEvent.from_string(self.data)
		elif self.event_type == EventType.MessageAllPlayersExceptHandles:
			return MessagePlayersExceptHandlesEvent.from_string(self.data)
		elif self.event_type == EventType.MessageGroups:
			return MessageGroupsEvent.from_string(self.data)
		elif self.event_type == EventType.MessageExceptGroups:
			return MessageExceptGroupsEvent.from_string(self.data)
		else:
			print(f'Scenario event type {self.event_type} not implemented yet.')
			return None

	async def execute(self):
		for i in range(self.repetitions):
			event = self.to_specific_type()
			if event is None:
				return
			await event.execute()
			print(f'  Executed repetition {i+1} out of {self.repetitions}')
			await asyncio.sleep(self.spacing)



class Scenario(object):
	def __init__(
		self,
		name : str,
		steps : List[Event] = None):
		self.name = name
		self.steps = [] if steps is None else steps

	@staticmethod
	def from_string(string : str):
		obj = Scenario(None)
		loaded_dict = simplejson.loads(string)
		obj.__dict__.update(loaded_dict)
		for i, step_str in enumerate(loaded_dict['steps']):
			obj.steps[i] = Event.from_string(step_str)
		return obj

	def to_string(self):
		dict_to_save = deepcopy(self.__dict__)
		list_of_strings = [step.to_string() for step in dict_to_save['steps']]
		dict_to_save['steps'] = list_of_strings
		return simplejson.dumps(dict_to_save)

	async def execute(self):
		print(f'Executing scenario \"{self.name}\"...')
		for i, step in enumerate(self.steps):
			repetition_string = '' if step.repetitions == 1 else f' x{step.repetitions}'
			print(f'Executing step #{i} ({step.event_type}{repetition_string}) of scenario \"{self.name}\"...')
			await step.execute()
			print(f'Finished executing step #{i} ({step.event_type}{repetition_string}) of scenario \"{self.name}\".')
		print(f'Finished scenario \"{self.name}\".')



scenarios_conf_dir = 'scenarios'
name_index = '___name'

def store_scenario(scenario : Scenario):
	file_name = f'{scenarios_conf_dir}/{scenario.name}.conf'
	scenario_conf = ConfigObj(file_name)
	scenario_conf[name_index] = scenario.name
	for i, step in enumerate(scenario.steps):
		scenario_conf[str(i)] = scenario.steps[i].to_string()
	scenario_conf.write()

def read_scenario(name : str):
	file_name = f'{scenarios_conf_dir}/{name}.conf'
	scenario_conf = ConfigObj(file_name)
	if name_index in scenario_conf and scenario_conf[name_index] == name:
		scenario = Scenario(name)
		index = 0
		while str(index) in scenario_conf:
			scenario.steps.append(Event.from_string(scenario_conf[str(index)]))
			index += 1
		return scenario



async def create_scenario(name : str):
	if name is None:
		return 'Error: you must give a name for the scenario.'
	scenario = Scenario(name)
	scenario.steps.append(
		Event.from_specific_event(
			NetworkOutageEvent(time_in_seconds=1)
			)
		)
	scenario.steps.append(
		Event.from_specific_event(
			NetworkDownEvent()
			)
		)
	scenario.steps.append(
		Event.from_specific_event(
			WaitEvent(time_in_seconds=5)
			)
		)
	scenario.steps.append(
		Event.from_specific_event(
			NetworkRestoredEvent()
			)
		)
	scenario.steps.append(
		Event.from_specific_event(
			MessagePlayersByHandleEvent(message=f'This is a message from {name}.', handles=['switch', 'trinity_taskbar', 'u2701', 'u2702'])
			)
		)
	scenario.steps.append(
		Event.from_specific_event(
			MessagePlayersExceptHandlesEvent(message=f'This is a secret message from {name}.', handles=['switch', 'sandwich', 'u2701'])
			)
		)


	store_scenario(scenario)

async def run_scenario(name : str):
	if name is None:
		return 'Error: you must give a name for the scenario.'
	scenario = read_scenario(name)
	await scenario.execute()
