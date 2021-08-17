import channels
import handles
import actors
from custom_types import Transaction, ReactionPaymentResult
import common
from common import coin

from configobj import ConfigObj
import asyncio

### Module finances.py
# This module tracks and handles money and transactions between handles



# TODO: BITCOIN BITCOIN BITCOIN!!!

balance_index = '___balance'
system_fake_handle = '___system'


# 'finances' holds the money associated with each 
finances = ConfigObj('finances.conf')

def init_finances():
    for handle in handles.get_all_handles():
        if not handle in finances:
            init_finances_for_handle(handle)

def init_finances_for_handle(handle : str):
    finances[handle] = {}
    finances[handle][balance_index] = '0'
    finances.write()

async def deinit_finances_for_handle(handle : str, actor_id : str, record : bool):
    del finances[handle]
    finances.write()
    if record:
        await actors.write_financial_record(content=None, actor_id=actor_id, last_in_sequence=True)

def get_current_balance(handle : str):
    return int(finances[handle][balance_index])

def set_current_balance(handle : str, balance : int):
    finances[handle][balance_index] = str(balance)
    finances.write()

async def overwrite_balance(handle : str, balance : int):
    old_balance = finances[handle][balance_index]
    set_current_balance(handle, balance)
    transaction = Transaction(handle, system_fake_handle, old_balance, success=True)
    await actors.record_transaction(transaction)

    transaction = Transaction(system_fake_handle, handle, balance, success=True)
    await actors.record_transaction(transaction)

def get_all_handles_balance_report(actor_id : str):
    current_handle = handles.get_handle(actor_id)
    report = 'Current balance for all your accounts:\n'
    total = 0
    for handle in handles.get_handles_for_actor(actor_id):
        balance = get_current_balance(handle)
        total += balance
        balance_str = str(balance)
        if handle == current_handle:
            report = report + f'> **{handle}**: {coin} **{balance_str}**\n'
        else:
            report = report + f'> {handle}: {coin} **{balance_str}**\n'
    report = report + f'Total: {coin} **{total}**'
    return report

def transfer_funds(transaction : Transaction):
    avail_at_payer = int(finances[transaction.payer][balance_index])
    if avail_at_payer >= transaction.amount:
        amount_at_recip = get_current_balance(transaction.recip)
        set_current_balance(transaction.recip, amount_at_recip + transaction.amount)
        set_current_balance(transaction.payer, avail_at_payer - transaction.amount)
        transaction.success = True
    else:
        transaction.success = False
    return transaction

async def transfer_from_burner(burner : str, new_active : str, amount : int):
    transaction = Transaction(burner, new_active, amount)
    transaction.payer = burner
    transaction.recip = new_active
    transaction.amount = amount
    transfer_funds(transaction)
    await actors.record_transaction(transaction)

async def add_funds(handle : str, amount : int):
    previous_balance = int(finances[handle][balance_index])
    new_balance = previous_balance + amount
    finances[handle][balance_index] = str(new_balance)
    finances.write()
    transaction = Transaction(system_fake_handle, handle, amount, success=True)
    await actors.record_transaction(transaction)

async def collect_all_funds(actor_id : str):
    current_handle = handles.get_handle(actor_id)
    total = 0
    transaction = Transaction(None, common.transaction_collector, 0, success=True)
    balance_on_current = 0
    for handle in handles.get_handles_for_actor(actor_id):
        collected = get_current_balance(handle)
        if collected > 0:
            total += collected
            set_current_balance(handle, 0)
            if handle == current_handle:
                balance_on_current = collected
            else:
                transaction.amount = collected
                transaction.payer = handle
                transaction.last_in_sequence = False
                await actors.record_transaction(transaction)
    set_current_balance(current_handle, total)
    transaction.amount = total - balance_on_current
    transaction.payer = common.transaction_collected
    transaction.recip = current_handle
    transaction.last_in_sequence = True
    await actors.record_transaction(transaction)


# Related to transactions

# TODO: timestamp for transactions
def generate_record_self_transfer(transaction : Transaction):
    return f'🔁 **{transaction.payer}** --> **{transaction.recip}**: {coin} {transaction.amount}'

def generate_record_payer(transaction : Transaction):
    return f'🟥 **{transaction.payer}** --> {transaction.recip}: {coin} {transaction.amount}'

def generate_record_recip(transaction : Transaction):
    return f'🟩 {transaction.payer} --> **{transaction.recip}**: {coin} {transaction.amount}'

def generate_record_collected(transaction : Transaction):
    return f'⏬ Collected {coin} {transaction.amount} from **{transaction.payer}**'

def generate_record_collector(transaction : Transaction):
    return f'▶️ --> **{transaction.recip}**: total {coin} {transaction.amount} collected from your other handles.'

async def try_to_pay(actor_id : str, handle_recip : str, amount : int, from_reaction=False):
    handle_payer = handles.get_handle(actor_id)
    transaction = Transaction(handle_payer, handle_recip, amount)
    if handle_payer == handle_recip or handle_recip == None:
        # Cannot transfer to yourself, and cannot transfer to unknown messages
        # On reactions, feedback in cmd_line would just be distracting
        # On a command, we want to give feedback anyway so we might as well say what happened
        if not from_reaction:
            transaction.report = f'Error: cannot transfer funds from account {handle_recip} to itself.'
        return transaction
    recip_status : HandleStatus = handles.get_handle_status(handle_recip)
    if not recip_status.exists:
        if from_reaction:
            transaction.report = f'Tried to transfer {coin} **{amount}** based on your reaction (emoji), but recipient {handle_recip} does not exist.'
        else:
            transaction.report = f'Failed to transfer {coin} **{amount}** from {handle_payer} to {handle_recip}; recipient does not exist. Check the spelling.'
    else:
        transaction = transfer_funds(transaction)
        if not transaction.success:
            avail = get_current_balance(handle_payer)
            if from_reaction:
                transaction.report = f'Tried to transfer {coin} **{amount}** from {handle_payer} to {handle_recip} based on your reaction (emoji), but your balance is {avail}.'
            else:
                transaction.report = f'Failed to transfer {coin} **{amount}** from {handle_payer} to {handle_recip}; current balance is {coin} **{avail}**.'
        elif from_reaction:
            # Success; no need for report to cmd_line
            await actors.record_transaction(transaction)
        else:
            if recip_status.actor_id == actor_id:
                transaction.report = f'Successfully transferred {coin} **{amount}** from {handle_payer} to **{handle_recip}**. (Note: you control both accounts.)'
            else:
                transaction.report = f'Successfully transferred {coin} **{amount}** from {handle_payer} to **{handle_recip}**.'
            await actors.record_transaction(transaction)
    return transaction