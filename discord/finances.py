import channels
import handles
import actors
import players
from custom_types import Transaction, TransTypes, Handle, HandleTypes, PostTimestamp
from common import coin, transaction_collector, transaction_collected

from discord.ext import commands
from discord import app_commands, Interaction
from configobj import ConfigObj
from copy import deepcopy
import asyncio
import simplejson

### Module finances.py
# This module tracks and handles money and transactions between handles

class FinancesCog(commands.Cog, name='finances'):
    """Commands related to finances.
    Money is tracked separately for each handle (for more info, see \".help handles\")"""
    def __init__(self, bot):
        self.bot = bot
        self._last_member = None

    # Commands related to money
    # These only work in cmd_line channels

    @app_commands.command(
        name='create_money',
        description='Admin-only. Creates new money and deposits them in a handle.')
    @app_commands.checks.has_role('gm')
    async def create_money_command(self, interaction: Interaction, handle_id: str, amount: int):
        if handle_id == None:
            response = 'Error: no handle specified.'
        elif amount <= 0:
            response = f'Error: cannot create less than {coin} 1.'
        else:
            handle = handles.get_handle(handle_id)
            if can_have_finances(handle.handle_type):
                await add_funds(handle, amount)
                response = f'Added {amount} to the balance of {handle.handle_id}'
            else:
                response = f'Error: handle \"{handle_id}\" does not exist, or is not capable of having money.'
        await interaction.response.send_message(response, ephemeral=True)

    @app_commands.command(
        name='set_money',
        description='Admin-only. Sets the balance of an account.')
    @app_commands.checks.has_role('gm')
    async def set_money_command(self, interaction: Interaction, handle_id: str, amount: int):

        if handle_id == None:
            response = 'Error: no handle specified.'
        elif amount < 0:
            response = 'Error: you must set a new balance.'
        else:
            handle = handles.get_handle(handle_id)
            if can_have_finances(handle.handle_type):
                await overwrite_balance(handle, amount)
                response = f'Set the balance of {handle.handle_id} to {amount}'
            else:
                response = f'Error: handle \"{handle_id}\" does not exist, or is not capable of having money'
        await interaction.response.send_message(response, ephemeral=True)

    #TODO: move some of this error handling into try_to_pay_from_command
    @app_commands.command(
        name='pay',
        description=f'Pay money ({coin}) to another handle. The money will be paid from your current handle.',
#        help=(f'Pay money ({coin}) to another handle.\nThe money will be paid from your current handle. ' +
#            f'Minimum transfer is {coin} 1.' +
#            'Use /balance or check your personal finance channel to see if you have enough.\n' +
#            f'Example: \"/pay shadow_weaver 10\" to pay {coin} 10 to shadow_weaver.\n' +
#            'Note: this command is also used to transfer money between two handles you control.')
        )
    async def pay_money_command(self, interaction: Interaction, target_handle: str, amount: int):
        await interaction.response.defer(ephemeral=True)
        if target_handle == None:
            response = 'Error: no recipient specified. Use \"/pay <recipient> <amount>\", e.g. \"/pay shadow_weaver 500\".'
        elif amount <= 0:
            response = f'Error: cannot transfer less than {coin} 1. Use \"/pay <recipient> <amount>\", e.g. \"/pay {target_handle} 500\".'
        else:
            player_id = players.get_player_id(str(interaction.user.id))
            transaction : Transaction = await try_to_pay_from_actor(player_id, target_handle, amount)
            response = transaction.report
        await interaction.followup.send(response, ephemeral=True)

    @app_commands.command(name='balance', description='Show current balance (money) on all your handles.')
    async def show_balance_command(self, interaction: Interaction):
        player_id = players.get_player_id(str(interaction.user.id))
        response = get_all_handles_balance_report(player_id)
        await interaction.response.send_message(response, ephemeral=True)

    @app_commands.command(
        name='collect',
        description='Collect all your funds to the same handle. All money will end up at your current handle.'
        )
    async def collect_command(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        player_id = players.get_player_id(str(interaction.user.id))
        #await interaction.response.send_message('Collecting all funds to the account of the current handle...', ephemeral=True)
        report = await collect_all_funds(player_id)
        if report is not None:
            await interaction.followup.send(report, ephemeral=True)
        else:
            await interaction.followup.send("Unknown error. Contact system admin.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FinancesCog(bot))




class InternalTransRecord(object):
    def __init__(
        self,
        other_handle : str,
        other_actor : str,
        amount : int,
        cause : TransTypes=TransTypes.Transfer,
        timestamp : PostTimestamp=None,
        data : str=None,
        emoji : str=None
        ):
        self.other_handle = other_handle
        self.other_actor = other_actor
        self.amount = amount
        self.cause = cause
        self.timestamp = timestamp
        self.data = data
        self.emoji = emoji

    @staticmethod
    def from_string(string : str):
        obj = InternalTransRecord(None, None, 0)
        loaded_dict = simplejson.loads(string)
        obj.__dict__.update(loaded_dict)
        obj.timestamp : PostTimestamp = PostTimestamp.from_string(loaded_dict['timestamp'])
        return obj

    def to_string(self):
        dict_to_save = deepcopy(self.__dict__)
        if self.timestamp is not None:
            dict_to_save['timestamp'] = PostTimestamp.to_string(self.timestamp)
        return simplejson.dumps(dict_to_save)

    @staticmethod
    def from_transaction(transaction : Transaction, for_payer : bool):
        record = InternalTransRecord(
            transaction.payer,
            transaction.payer_actor,
            transaction.amount,
            cause = transaction.cause,
            timestamp = transaction.timestamp,
            data = transaction.data,
            emoji = transaction.emoji)
        if for_payer:
            record.other_handle = transaction.recip
            record.other_actor = transaction.recip_actor
            record.amount = -transaction.amount
        return record


# TODO: BITCOIN BITCOIN BITCOIN!!!

finances_conf_dir = 'finances'
balance_index = '___balance'
transactions_index = '___transactions'
highest_transaction_index = '___highest'

system_fake_handle = '[system]'

def init_finances():
    for handle in handles.get_all_handles():
        if can_have_finances(handle.handle_type):
            init_finances_for_handle(handle, overwrite=False)

def init_finances_for_handle(handle : Handle, overwrite : bool=True):
    file_name = f'{finances_conf_dir}/{handle.handle_id}.conf'
    finances_conf = ConfigObj(file_name)
    if overwrite:
        for entry in finances_conf:
            del finances_conf[entry]
    if balance_index not in finances_conf:
        finances_conf[balance_index] = '0'
    if transactions_index not in finances_conf:
        finances_conf[transactions_index] = {}
    if highest_transaction_index not in finances_conf[transactions_index]:
        finances_conf[transactions_index][highest_transaction_index] = '0'
    finances_conf.write()

async def deinit_finances_for_handle(handle : Handle, record : bool):
    file_name = f'{finances_conf_dir}/{handle.handle_id}.conf'
    finances_conf = ConfigObj(file_name)
    if finances_conf:
        for entry in finances_conf:
            del finances_conf[entry]
        finances_conf.write()
    if record:
        await actors.refresh_financial_statement(handle.actor_id)

def get_current_balance(handle : Handle):
    return get_current_balance_handle_id(handle.handle_id)

def get_current_balance_handle_id(handle_id : str):
    file_name = f'{finances_conf_dir}/{handle_id}.conf'
    finances_conf = ConfigObj(file_name)
    return int(finances_conf[balance_index])

def set_current_balance(handle : Handle, balance : int):
    set_current_balance_handle_id(handle.handle_id, balance)

def set_current_balance_handle_id(handle_id : str, balance : int):
    file_name = f'{finances_conf_dir}/{handle_id}.conf'
    finances_conf = ConfigObj(file_name)
    finances_conf[balance_index] = str(balance)
    finances_conf.write()


def add_internal_record(handle_id : str, record : InternalTransRecord):
    file_name = f'{finances_conf_dir}/{handle_id}.conf'
    finances_conf = ConfigObj(file_name)
    prev_highest = int(finances_conf[transactions_index][highest_transaction_index])
    new_index = str(prev_highest + 1)
    finances_conf[transactions_index][highest_transaction_index] = new_index
    finances_conf[transactions_index][new_index] = record.to_string()
    finances_conf.write()

async def overwrite_balance(handle : Handle, balance : int):
    old_balance = get_current_balance(handle)
    set_current_balance(handle, balance)
    transaction = Transaction(
        payer=handle.handle_id,
        payer_actor=None,
        recip=system_fake_handle,
        recip_actor=None,
        amount=old_balance,
        cause = TransTypes.Transfer,
        success=True)
    find_transaction_parties(transaction)
    await record_transaction(transaction)

    transaction = Transaction(
        payer=system_fake_handle,
        payer_actor=None,
        recip=handle.handle_id,
        recip_actor=None,
        amount=balance,
        cause = TransTypes.Transfer,
        success=True)
    find_transaction_parties(transaction)
    await record_transaction(transaction)

def can_have_finances(handle_type : HandleTypes):
    return Handle.is_active_handle_type(handle_type)

def get_all_handles_balance_report(actor_id : str):
    report = ''

    current_handle : Handle = handles.get_active_handle(actor_id)
    any_npc_found = False
    for handle in handles.get_handles_for_actor_of_types(actor_id, [HandleTypes.NPC]):
        if not any_npc_found:
            any_npc_found = True
            report += '[OFF: Current balance for NPC accounts you control:]\n'
        balance = get_current_balance(handle)
        if handle.handle_id == current_handle.handle_id:
            report = report + f'> [**{handle.handle_id}**: {coin} **{balance}**]\n'
        else:
            report = report + f'> [{handle.handle_id}: {coin} **{balance}**]\n'

    report += 'Current balance for all your accounts:\n'
    total = 0
    for handle in handles.get_handles_for_actor(actor_id, include_npc=False):
        balance = get_current_balance(handle)
        total += balance
        balance_str = str(balance)
        if handle.handle_id == current_handle.handle_id:
            report = report + f'> **{handle.handle_id}**: {coin} **{balance_str}**'
        else:
            report = report + f'> {handle.handle_id}: {coin} **{balance_str}**'
        if handle.handle_type == HandleTypes.Burner:
            report += '  🔥'
        report += '\n'
    report = report + f'Total: {coin} **{total}**'
    return report

def transfer_funds_if_available(transaction : Transaction):
    avail_at_payer = get_current_balance_handle_id(transaction.payer)
    if avail_at_payer >= transaction.amount:
        amount_at_recip = get_current_balance_handle_id(transaction.recip)
        set_current_balance_handle_id(transaction.recip, amount_at_recip + transaction.amount)
        set_current_balance_handle_id(transaction.payer, avail_at_payer - transaction.amount)
        transaction.success = True
    else:
        transaction.success = False
    #return transaction

async def transfer_from_burner(burner : Handle, new_active : Handle, amount : int):
    transaction = Transaction(
        payer=burner.handle_id,
        payer_actor=None,
        recip=new_active.handle_id,
        recip_actor=None,
        cause = TransTypes.Burn,
        amount=amount)
    find_transaction_parties(transaction)
    transfer_funds_if_available(transaction)
    await record_transaction(transaction)

async def add_funds(handle : Handle, amount : int):
    if amount == 0:
        return
    previous_balance = get_current_balance(handle)
    new_balance = previous_balance + amount
    set_current_balance_handle_id(handle.handle_id, new_balance)
    transaction = Transaction(payer=system_fake_handle, payer_actor=None, recip=handle.handle_id, recip_actor=None, amount=amount)
    find_transaction_parties(transaction)
    await record_transaction(transaction)

async def collect_all_funds(actor_id : str):
    current_handle : Handle = handles.get_active_handle(actor_id)
    if current_handle.handle_type in [HandleTypes.Burnt, HandleTypes.NPC]:
        return f'Error: cannot collect funds to {current_handle.handle_id}. [OFF: it is an NPC account]'
    total = 0
    transaction = Transaction(
        payer=None,
        payer_actor=actor_id,
        recip=transaction_collector,
        recip_actor=None,
        amount=0,
        success=True,
        cause=TransTypes.Collect)
    balance_on_current = 0
    for handle in handles.get_handles_for_actor(actor_id, include_npc=False):
        collected = get_current_balance(handle)
        if collected > 0:
            total += collected
            set_current_balance(handle, 0)
            if handle.handle_id == current_handle.handle_id:
                balance_on_current = collected
            else:
                transaction.amount = collected
                transaction.payer = handle.handle_id
                transaction.last_in_sequence = False
                await record_transaction(transaction)
    set_current_balance(current_handle, total)
    transaction.payer_actor = None
    transaction.recip_actor = actor_id
    transaction.amount = total - balance_on_current
    transaction.payer = transaction_collected
    transaction.recip = current_handle.handle_id
    transaction.last_in_sequence = True
    await record_transaction(transaction)
    return 'Done.'


# Related to transactions

async def try_to_pay_from_actor(actor_id : str, recip_handle_id : str, amount : int, from_reaction=False):
    # Some input checking has been done here, but we should move it from system_bot.py into here
    handle_payer : Handle = handles.get_active_handle(actor_id)
    transaction = Transaction(
        payer=handle_payer.handle_id,
        payer_actor=handle_payer.actor_id,
        recip=recip_handle_id,
        recip_actor=None,
        cause = TransTypes.Transfer,
        amount=amount)
    # TODO: right now a reaction on e.g. a burnt burner WILL cause error printout every time;
    # "from_reaction" only protects against printout on self-reacts
    find_transaction_parties(transaction)
    if transaction.report is None:
        await try_to_pay(transaction, from_reaction)
    return transaction


# TODO: on second thought, move this into try_to_pay again? We always want to abort and return if this does not succeed
def find_transaction_parties(transaction : Transaction):
    if transaction.payer is None:
        if transaction.payer_actor is None:
            transaction.report = f'Error: Attempted transaction without knowing either the handle or the user ID of the payer.'
        else:
            transaction.payer = handles.get_active_handle(transaction.payer_actor).handle_id
            if transaction.payer is None:
                transaction.report = f'Error: Attempted transaction for {transaction.payer_actor} but could not find current handle.'
    else:
        if transaction.payer_actor is None and transaction.payer_actor != system_fake_handle:
            payer_handle : Handle = handles.get_handle(transaction.payer)
            if not can_have_finances(payer_handle.handle_type):
                transaction.report = f'Error: Attempted transaction from handle {transaction.payer} which does not exist.'
            else:
                transaction.payer_actor = payer_handle.actor_id

    if transaction.recip is None:
        if transaction.recip_actor is None:
            transaction.report = f'Error: Attempted transaction without knowing either the handle or the user ID of the recipient.'
        else:
            transaction.recip = handles.get_active_handle(transaction.recip_actor).handle_id
            if transaction.recip is None:
                transaction.report = f'Error: Attempted transaction targeting {transaction.recip_actor} but could not find current handle.'
    else:
        if transaction.recip_actor is None and transaction.recip_actor != system_fake_handle:
            recip_handle : Handle = handles.get_handle(transaction.recip)
            if not can_have_finances(recip_handle.handle_type):
                transaction.report = f'Error: Attempted transaction targeting handle {transaction.recip} which does not exist.'
            else:
                transaction.recip_actor = recip_handle.actor_id

async def try_to_pay(transaction : Transaction, from_reaction : bool=False):
    if transaction.payer == transaction.recip:
        # Cannot transfer to yourself, and cannot transfer to unknown messages
        # On reactions, feedback in cmd_line would just be distracting
        # On a command, we want to give feedback anyway so we might as well say what happened
        if not from_reaction:
            transaction.report = f'Error: cannot transfer funds from account {transaction.recip} to itself.'
        return transaction

    if transaction.amount < 0:
        # Negative transaction: flip it around
        recip = transaction.payer
        transaction.payer = transaction.recip
        transaction.recip = recip
        recip_actor = transaction.payer_actor
        transaction.payer_actor = transaction.recip_actor
        transaction.recip_actor = recip_actor
        transaction.amount = -transaction.amount


    transfer_funds_if_available(transaction)
    if not transaction.success:
        avail = get_current_balance_handle_id(transaction.payer)
        if from_reaction:
            transaction.report = f'Tried to transfer {coin} **{transaction.amount}** from {transaction.payer} to {transaction.recip} based on your reaction (emoji), but your balance is {avail}.'
        else:
            transaction.report = f'Failed to transfer {coin} **{transaction.amount}** from {transaction.payer} to {transaction.recip}; current balance is {coin} **{avail}**.'
    elif from_reaction:
        # Success; no need for report to cmd_line
        await record_transaction(transaction)
    else:
        if transaction.payer_actor is not None and transaction.payer_actor == transaction.recip_actor:
            transaction.report = f'Successfully transferred {coin} **{transaction.amount}** from {transaction.payer} to **{transaction.recip}**. (Note: you control both accounts.)'
        else:
            transaction.report = f'Successfully transferred {coin} **{transaction.amount}** from {transaction.payer} to **{transaction.recip}**.'
        await record_transaction(transaction)
    return transaction


# Record for transactions:





async def record_transaction(transaction : Transaction):
    record_transaction_internal(transaction)
    if int(transaction.amount) == 0:
        # No need to write anything for 0-transactions, should they occur
        return
    record_payer = await generate_record_for_payer(transaction)
    record_recip = await generate_record_for_recip(transaction)
    await actors.write_financial_record(transaction, record_payer, record_recip)

def record_transaction_internal(transaction : Transaction):
    if transaction.payer_actor is not None:
        payer_record = InternalTransRecord.from_transaction(transaction, for_payer=True)
        add_internal_record(transaction.payer, payer_record)
    if transaction.recip_actor is not None:
        recip_record = InternalTransRecord.from_transaction(transaction, for_payer=False)
        add_internal_record(transaction.recip, recip_record)


async def generate_record_for_payer(transaction : Transaction):
    if transaction.payer_actor is None:
        return None
    if transaction.payer_actor == transaction.recip_actor:
        if transaction.cause == TransTypes.Burn:
            # Will be generated for the recipient
            return None
        else:
            return generate_record_self_transfer(transaction)
    if transaction.cause == TransTypes.Transfer:
        return generate_record_payer(transaction)
    if transaction.cause == TransTypes.ChatReact:
        # TODO
        return generate_record_payer(transaction)
    if transaction.cause == TransTypes.Collect:
        return generate_record_collected(transaction)
    if transaction.cause == TransTypes.ShopOrder:
        return generate_record_buyer(transaction)
    if transaction.cause == TransTypes.ShopRefund:
        # Will not be recorded -- the original transaction will just vanish instead
        await actors.refresh_financial_statement(transaction.payer_actor)


async def generate_record_for_recip(transaction : Transaction):
    if transaction.recip_actor is None:
        return None
    if transaction.payer_actor == transaction.recip_actor:
        if transaction.cause == TransTypes.Burn:
            return generate_record_burner(transaction)
        else:
            # This transaction will be recorded for payer, don't need it twice
            return None
    if transaction.cause == TransTypes.Transfer:
        return generate_record_recip(transaction)
    if transaction.cause == TransTypes.ChatReact:
        # TODO
        return generate_record_recip(transaction)
    if transaction.cause == TransTypes.Collect:
        return generate_record_collector(transaction)
    if transaction.cause == TransTypes.ShopOrder:
        return generate_record_recip_shop(transaction)
    if transaction.cause == TransTypes.ShopRefund:
        # Will not be recorded -- the original transaction will just vanish instead
        await actors.refresh_financial_statement(transaction.recip_actor)

# TODO: timestamp for transactions
def generate_record_self_transfer(transaction : Transaction):
    return f'🔁 **{transaction.payer}** --> **{transaction.recip}**: {coin} {transaction.amount}'

def generate_record_payer(transaction : Transaction):
    return f'🟥 **{transaction.payer}** --> {transaction.recip}: {coin} {transaction.amount}'

def generate_record_buyer(transaction : Transaction):
    if transaction.emoji is not None:
        return f'🟥 **{transaction.payer}** --> {transaction.recip}: {coin} {transaction.amount} for {transaction.emoji}'
    else:
        return generate_record_payer(transaction)

def generate_record_recip(transaction : Transaction):
    return f'🟩 {transaction.payer} --> **{transaction.recip}**: {coin} {transaction.amount}'

def generate_record_recip_shop(transaction : Transaction):
    if transaction.emoji is not None:
        return f'🟩 {transaction.payer} --> **{transaction.recip}**: {coin} {transaction.amount} for {transaction.emoji}'
    else:
        return generate_record_recip(transaction)

def generate_record_burner(transaction : Transaction):
    return f'🟩 🔥 ~~{transaction.payer}~~ --> **{transaction.recip}**: {coin} {transaction.amount}'

def generate_record_collected(transaction : Transaction):
    return f'⏬ Collected {coin} {transaction.amount} from **{transaction.payer}**'

def generate_record_collector(transaction : Transaction):
    return f'▶️ --> **{transaction.recip}**: total {coin} {transaction.amount} collected from your other handles.'
