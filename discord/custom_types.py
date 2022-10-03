import simplejson
from enum import Enum
from typing import List
from copy import deepcopy

class ActionResult(object):
	def __init__(self, success : bool=False, report : str = None):
		self.success = success
		self.report = report

class PostTimestamp(object):
	def __init__(self, hour : int, minute : int):
		self.hour = hour % 24 # Sometimes we need to adjust for DST manually
		self.minute = minute

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.__dict__ == other.__dict__
		else:
			return False

	@staticmethod
	def from_string(string : str):
		obj = PostTimestamp(0, 0)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	@staticmethod
	def from_datetime(timestamp, dst_diff : int=0):
		return PostTimestamp(timestamp.hour + dst_diff, timestamp.minute)

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def pretty_print(self, second : int=-1):
		# Manual DST fix
		hour_str = str(self.hour) if self.hour >= 10 else f'0{self.hour}'
		minute_str = str(self.minute) if self.minute >= 10 else f'0{self.minute}'
		result = f'{hour_str}:{minute_str}'
		if second >= 0 and second < 60:
			second_str = str(second) if second >= 10 else f'0{second}'
			result += f':{second_str}'
		return result

	@staticmethod
	def get_time_diff(older, newer):
		old_total = older.hour * 60 + older.minute
		new_total = newer.hour * 60 + newer.minute
		if old_total > new_total:
			# The new timestamp must be after a midnight wraparound
			# (we don't support LARPs that run for more than one day)
			new_total += 24 * 60
		return new_total - old_total

class TransTypes(str, Enum):
	Transfer = 't'
	Collect = 'c'
	Burn = 'b'
	ChatReact = 'r'
	ShopOrder = 'o'
	ShopRefund = 'sr'

class Transaction(object):
	def __init__(
		self,
		payer : str, # handle ID
		recip : str, # handle ID
		payer_actor : str,
		recip_actor : str,
		amount : int,
		cause : TransTypes=TransTypes.Transfer,
		report : str=None,
		timestamp : PostTimestamp=None, # TODO: add timestamp for regular payments 
		success : bool=False,
		last_in_sequence : bool=True,
		payer_msg_id : str=None,
		recip_msg_id : str=None,
		data : str=None,
		emoji : str=None
		):
		self.payer = payer
		self.recip = recip
		self.payer_actor = payer_actor
		self.recip_actor = recip_actor
		self.amount = amount
		self.cause = cause
		self.report = report
		self.timestamp = timestamp
		self.success = success
		self.last_in_sequence = last_in_sequence
		self.data = data
		self.emoji = emoji
		self.payer_msg_id = payer_msg_id
		self.recip_msg_id = recip_msg_id

	@staticmethod
	def from_string(string : str):
		obj = Transaction(None, None, None, None, 0)
		loaded_dict = simplejson.loads(string)
		obj.__dict__.update(loaded_dict)
		obj.timestamp : PostTimestamp = PostTimestamp.from_string(loaded_dict['timestamp'])
		return obj

	def to_string(self):
		dict_to_save = deepcopy(self.__dict__)
		dict_to_save['timestamp'] = PostTimestamp.to_string(self.timestamp)
		return simplejson.dumps(dict_to_save)

	def get_undo_hooks_list(self):
		return (
			[(a, m)
			for (a, m)
			in (
				[(self.payer_actor, self.payer_msg_id),
				(self.recip_actor, self.recip_msg_id)]
				)
			if a is not None and m is not None]
			)


class Actor(object):
	def __init__(
		self,
		role_name : str,
		actor_id : str,
		guild_id: int,
		finance_channel_id : int,
		finance_stmt_msg_id : int,
		chat_channel_id : int):
		self.role_name = role_name
		self.actor_id = actor_id
		self.guild_id = guild_id
		self.finance_channel_id = finance_channel_id
		self.finance_stmt_msg_id = finance_stmt_msg_id
		self.chat_channel_id = chat_channel_id

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.__dict__ == other.__dict__
		else:
			return False
	def __hash__(self):
		return hash(tuple(sorted(self.__dict__.items())))

	@staticmethod
	def from_string(string : str):
		obj = Actor(None, None, 0, 0, 0, 0)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)


class PlayerData(object):
	def __init__(
		self,
		player_id : str,
		cmd_line_channel_id : int,
		shops : List[str] = None,
		groups : List[str] = None):
		self.player_id = player_id
		self.cmd_line_channel_id = cmd_line_channel_id
		self.shops = [] if shops is None else shops
		self.groups = [] if groups is None else groups

	@staticmethod
	def from_string(string : str):
		obj = PlayerData(None, 0)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

class HandleTypes(str, Enum):
	Unused = 'unused'
	Invalid = 'invalid'
	Reserved = 'reserved'
	Regular = 'regular'
	Burner = 'burner'
	Burnt = 'burnt'
	NPC = 'npc'


class Handle(object):
	def __init__(
		self,
		handle_id : str,
		handle_type : HandleTypes = HandleTypes.Unused,
		actor_id : str=None,
		auto_respond_message=None):
		self.handle_id = handle_id.lower() if handle_id is not None else None
		self.handle_type = handle_type
		self.actor_id = actor_id
		self.auto_respond_message = auto_respond_message

	@staticmethod
	def from_string(string : str):
		obj = Handle(None)
		obj.__dict__.update(simplejson.loads(string))
		return obj

	def to_string(self):
		return simplejson.dumps(self.__dict__)

	def is_active(self):
		return Handle.is_active_handle_type(self.handle_type)

	@staticmethod
	def is_active_handle_type(handle_type : HandleTypes):
		return handle_type not in [HandleTypes.Burnt, HandleTypes.Unused, HandleTypes.Invalid, HandleTypes.Reserved]

