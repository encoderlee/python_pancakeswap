import time
import web3
from web3 import Web3
from web3.middleware import geth_poa_middleware
from decimal import Decimal
import requests
from typing import Dict, List
from datetime import datetime, timedelta
import os
from dataclasses import dataclass

@dataclass
class Contract:
    symbol: str
    address: str
    decimals: int

    def __init__(self, symbol: str, address: str, decimals: int = None):
        self.symbol = symbol  # unimportant, only show
        self.address = Web3.to_checksum_address(address)
        self.decimals = decimals


class Known:
    busd = Contract("BUSD", "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56", 18)
    cake = Contract("Cake", "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", 18)
    pancakeswap = Contract("Routerv2", "0x10ED43C718714eb63d5aA57B78B54704E256024E")


class Pancake:
    abi_cache: Dict[str, Dict] = {}

    def __init__(self, address_wallet: str, private_key: str = None):
        self.wallet: str = Web3.to_checksum_address(address_wallet)
        self.private_key = private_key
        self.client = web3.Web3(web3.HTTPProvider("https://bsc-dataseed1.binance.org"))
        self.client.middleware_onion.inject(geth_poa_middleware, layer=0)

    # fetch contract abi if not cache
    def fetch_abi(self, address: str):
        address = Web3.to_checksum_address(address)
        abi = Pancake.abi_cache.get(address)
        if not abi:
            url = "https://api.bscscan.com/api"
            params = {
                "module": "contract",
                "action": "getabi",
                "address": address,
                "apikey": "6HQZV977GIY8FNT36XN1JJSE12IP2IYVTQ",
            }
            resp = requests.get(url, params=params).json()
            abi = resp["result"]
            Pancake.abi_cache[address] = abi
        return Pancake.abi_cache[address]

    def get_contract(self, contract: Contract):
        abi_contract = self.fetch_abi(contract.address)
        return self.client.eth.contract(address=contract.address, abi=abi_contract)

    # get ERC20 token balance of the account
    def erc20_balance(self, erc20: Contract) -> Decimal:
        contract = self.get_contract(erc20)
        # get the token decimals if not
        decimals = erc20.decimals
        if not decimals:
            decimals = contract.functions.decimals().call()
        #  get the balance of tokens and convert it
        balance = contract.functions.balanceOf(self.wallet).call()
        balance = Decimal(balance) / (10 ** decimals)
        return balance

    def send_transaction(self, txn):
        txn = txn.build_transaction({
            "chainId": self.client.eth.chain_id,
            "from": self.wallet,
            "nonce": self.client.eth.get_transaction_count(self.wallet),
            "gasPrice": self.client.eth.gas_price
        })
        signed_txn = self.client.eth.account.sign_transaction(txn, self.private_key)
        txn_hash = self.client.eth.send_raw_transaction(signed_txn.rawTransaction)
        txn_hash = self.client.to_hex(txn_hash)
        print("send transaction: {0}".format(txn_hash))
        txn_receipt = self.client.eth.wait_for_transaction_receipt(txn_hash)
        print("transaction ok: {0}".format(txn_receipt))
        return txn_receipt

    # approve the pancakeswap contract to use erc20 tokens
    def approve_erc20_to_pancakeswap(self,  erc20: Contract):
        contract = self.get_contract(erc20)
        approve_amount = 2 ** 256 - 1
        amount = contract.functions.allowance(self.wallet, Known.pancakeswap.address).call()
        if amount >= approve_amount / 2:
            print("already approved")
            return None
        txn = contract.functions.approve(Known.pancakeswap.address, approve_amount)
        return self.send_transaction(txn)

    # query the price of token pair
    def query_price(self, token_path: List[Contract]) -> Decimal:
        contract = self.get_contract(Known.pancakeswap)
        path = [item.address for item in token_path]
        amount = contract.functions.getAmountsOut(1 * 10 ** token_path[0].decimals, path).call()
        amount_in = Decimal(amount[0]) / (10 ** token_path[0].decimals)
        amount_out = Decimal(amount[1]) / (10 ** token_path[-1].decimals)
        return amount_in / amount_out

    # swap token
    def swap_token(self, amount_in: Decimal, token_path: List[Contract]):
        # approve token to pancakeswap if not
        self.approve_erc20_to_pancakeswap(token_path[0])

        contract = self.get_contract(Known.pancakeswap)
        path = [item.address for item in token_path]

        amount_in = int(amount_in * 10 ** token_path[0].decimals)
        amount = contract.functions.getAmountsOut(amount_in, path).call()
        # slippage 0.5% fee 0.25% ，minimum received 99.25 %
        minimum_out = int(amount[1] * (1 - Decimal("0.005") - Decimal("0.0025")))
        deadline = datetime.now() + timedelta(minutes=5)
        txn = contract.functions.swapExactTokensForTokens(amount_in, minimum_out, path,self.wallet, int(deadline.timestamp()))
        return self.send_transaction(txn)


def main():
    # change it to your wallet address
    address_wallet = "0xeaC7d998684F50b7A492EA68F27633a117Be201d"
    # set your private key to the environment variable 'key'
    private_key = os.getenv("key")
    pancake = Pancake(address_wallet, private_key)

    balance = pancake.erc20_balance(Known.busd)
    print("busd balance: {0}".format(balance))

    balance = pancake.erc20_balance(Known.cake)
    print("cake balance: {0}".format(balance))

    limit_price = Decimal("4.1")
    amount_buy = Decimal(1)
    print("if the price of cake is lower than {0} busd/cake, buy {1} busd of cake".format(limit_price, amount_buy))

    token_path = [Known.busd, Known.cake]

    while True:
        price = pancake.query_price(token_path)
        print("cake price: {0} busd/cake".format(price))
        if price <= limit_price:
            print("price ok, buy {0} busd of cake".format(amount_buy))
            pancake.swap_token(amount_buy, token_path)
            break
        time.sleep(2)


if __name__ == '__main__':
    main()
