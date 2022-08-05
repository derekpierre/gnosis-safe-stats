import os
import sys
from decimal import Decimal
from eth_utils.currency import from_wei
from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.api.transaction_service_api import TransactionServiceApi
from gnosis.safe.safe import Safe
from gnosis.safe.safe_tx import SafeTx
from hexbytes import HexBytes
from maya import MayaDT
from statistics import mean, median, stdev
from typing import Any, Dict, NamedTuple, Optional

class SummaryStats(NamedTuple):
    min: float
    max: float
    mean: float
    median: float
    stdev: float

#
# Safe Signer Stats
#
class SafeSignerStats:
    def __init__(self, address: str):
        self.signer_address = address
        self.num_txs_created = 0
        self.num_signings = 0
        self._signing_times = []
        self.num_executions = 0
        self.gas_spent = Decimal(0)


    def increment_tx_creation_count(self):
        self.num_txs_created += 1

    def increment_signing_count(self):
        self.num_signings += 1

    def increment_execution_count(self):
        self.num_executions += 1

    def add_gas_spent(self, gas_spent: int):
        gas_spent = from_wei(gas_spent, unit='ether')
        self.gas_spent += gas_spent

    def add_signing_time(self, tx_creation_date: MayaDT, signing_date: MayaDT):
        time_taken = (signing_date - tx_creation_date).seconds
        self._signing_times.append(time_taken)

    def signing_summary_stats(self) -> SummaryStats:
        mean_time = mean(self._signing_times)
        min_time = min(self._signing_times)
        max_time = max(self._signing_times)
        median_time = median(self._signing_times)

        stdev_time = 0
        if len(self._signing_times) > 1:
            # requires at least 2 data points
            stdev_time = stdev(self._signing_times)

        return SummaryStats(
            min=min_time,
            max=max_time,
            mean=mean_time,
            median=median_time,
            stdev=stdev_time
        )


#
# Safe information
#
def print_safe_stats(safe_address: str, eth_endpoint: str, from_block_number: Optional[int] = 0):
    eth_client = EthereumClient(eth_endpoint)
    safe = Safe(address=safe_address, ethereum_client=eth_client)
    safe_info = safe.retrieve_all_info()

    print('='*55)
    print(f'Gnosis Safe: {safe_info.address}')
    print('='*55)

    if from_block_number != 0:
        print(f'\n*NOTE*: Only transactions from block number {from_block_number}\n')

    print(f'\n** OVERVIEW **\n')
    print(f'Contract Version .............. {safe_info.version}')
    print(f'Threshold ..................... {safe_info.threshold}')
    print(f'Signers ....................... {len(safe_info.owners)}')
    for owner_address in safe_info.owners:
        print(f'\t{owner_address}')

    # Tx Info
    print('\n** TRANSACTION INFO **\n')
    transaction_service = TransactionServiceApi.from_ethereum_client(ethereum_client=eth_client)
    transactions = transaction_service.get_transactions(safe_address=safe_address)
    executed_transactions = []
    for transaction in transactions:
        if not transaction['isExecuted'] or not transaction['isSuccessful']:
            # don't include non-executed or non-successful transactions
            continue

        if transaction['blockNumber'] < from_block_number:
            # don't include transactions prior to block number
            continue

        executed_transactions.append(transaction)

    num_executed_transactions = len(executed_transactions)
    print(f'Num Executed Txs ............. {num_executed_transactions}')

    signer_stats_dict = {}
    total_execution_time = 0
    num_externally_executed_transactions = 0
    for tx in executed_transactions:
        tx_creation_date = MayaDT.from_iso8601(tx['submissionDate'])
        tx_execution_date = MayaDT.from_iso8601(tx['executionDate'])
        total_execution_time += (tx_execution_date - tx_creation_date).seconds

        # execution
        executor = tx['executor']
        if executor not in safe_info.owners:
            num_externally_executed_transactions += 1
        else:
            if executor not in signer_stats_dict:
                signer_stats_dict[executor] = SafeSignerStats(address=executor)
            executor_stats = signer_stats_dict[executor]
            executor_stats.increment_execution_count()
            executor_stats.add_gas_spent(gas_spent=int(tx['fee']))

        # signing
        confirmations = tx['confirmations']
        for index, confirmation in enumerate(confirmations):
            signer = confirmation['owner']
            if signer not in signer_stats_dict:
                signer_stats_dict[signer] = SafeSignerStats(address=signer)
            signer_stats = signer_stats_dict[signer]
            signer_stats.increment_signing_count()
            if index == 0:
                # creator of the transaction
                signer_stats.increment_tx_creation_count()
            else:
                # only count signing time when signer is not the creator
                signer_stats.add_signing_time(tx_creation_date=tx_creation_date,
                                              signing_date=MayaDT.from_iso8601(confirmation['submissionDate']))

    print(f'Non-owner Executions ......... {num_externally_executed_transactions}')
    print('Avg Time to Execution ........ {0:.2f} mins.'.format((total_execution_time/num_executed_transactions)/60))
    print('Signer Stats')
    for signer, signer_stats in signer_stats_dict.items():
        print(f'\tSigner: {signer_stats.signer_address}')
        print('\t\tNum Txs Created ............ {} ({:.0%})'.format(signer_stats.num_txs_created, (signer_stats.num_txs_created / num_executed_transactions)))
        print('\t\tNum Txs Signed ............. {} ({:.0%})'.format(signer_stats.num_signings, (signer_stats.num_signings/num_executed_transactions)))

        # summary stats
        signing_summary_stats = signer_stats.signing_summary_stats()
        print(f'\t\tStatistics for txs signed but not created ({signer_stats.num_signings - signer_stats.num_txs_created} txs):')
        print('\t\t\tMin Tx Signing Time ........ {0:.2f} mins.'.format(signing_summary_stats.min / 60))
        print('\t\t\tMax Tx Signing Time ........ {0:.2f} mins.'.format(signing_summary_stats.max / 60))
        print('\t\t\tMean Tx Signing Time ....... {0:.2f} mins.'.format(signing_summary_stats.mean / 60))
        print('\t\t\tMedian Tx Signing Time ..... {0:.2f} mins.'.format(signing_summary_stats.median / 60))
        print('\t\t\tStdev Tx Signing Time ...... {0:.2f} mins.'.format(signing_summary_stats.stdev / 60))

        print('\t\tNum Txs Executed ........... {} ({:.0%})'.format(signer_stats.num_executions, (signer_stats.num_executions/num_executed_transactions)))
        print('\t\t\tGas Spent .................. {0:.2f} ETH'.format(signer_stats.gas_spent))
        print('\n')


def print_usage():
    usage = """
Usage:
    python safe_stats.py <safe_address> <eth_endpoint> [from_block_number]
    
    where
        safe_address: address of the Gnosis Safe Multisig
        eth_endpoint: ETH node endpoint URI
        from_block (Optional): the starting block number for the data collection
"""
    print(usage)


if __name__ == "__main__":
    num_args = len(sys.argv)
    if num_args != 3 and num_args != 4:
        print("Insufficient parameters provided")
        print_usage()
        sys.exit(-1)

    safe_address = sys.argv[1]
    eth_endpoint = sys.argv[2]
    from_block_number = 0  # default is 0
    if num_args == 4:
        from_block_number = int(sys.argv[3])
    print_safe_stats(safe_address=safe_address, eth_endpoint=eth_endpoint, from_block_number=from_block_number)