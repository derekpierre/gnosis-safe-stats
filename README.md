Simple tool to gleam statistics from Gnosis Safe Multisig operations.

# Installation

```bash
$ pip install -r requirements.txt
```
  
# Usage

```bash  
$ python safe_stats.py <safe_address> <eth_endpoint> [from_block_number]
```
where:  
* *safe_address*: address of the Gnosis Safe Multisig
* *eth_endpoint*: ETH node endpoint URI
* *from_block_number* (Optional): the starting block number for the data collection
