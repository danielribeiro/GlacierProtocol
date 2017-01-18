#!/usr/bin/env python

################################################################################################
#
# GlacierScript:  Part of the Glacier Protocol (http://glacierprotocol.org)
# 
# GlacierScript is designed specifically for use in the context of executing the broader Glacier 
# Protocol, a step-by-step procedure for high-security cold storage of Bitcoin.  It is not
# intended to be used as standalone software.
#
# GlacierScript primarily replaces tasks that users would otherwise be doing manually, such as
# typing things on the command line and copying-and-pasting strings.  It mostly consists of
# print statements, user input, a bit of string manipulation, and command-line wrappers around
# Bitcoin Core and other applications (e.g. those involved in reading and writing QR codes.)
#
# GlacierScript avoids cryptographic and other security-sensitive operations as much as possible.
#
# GlacierScript depends on the following command-line applications:
# - Bitcoin Core (http://bitcoincore.org)
# - qrencode (QR code writer: http://packages.ubuntu.com/xenial/qrencode)
# - zbarimg (QR code reader: http://packages.ubuntu.com/xenial/zbar-tools)
#
################################################################################################

# standard Python libraries
import time
import argparse
import sys
import hashlib
from hashlib import sha256, md5
import random
import subprocess
import json
from decimal import Decimal

# Pulled from Gavin Andresen's "bitcointools" python library (exact link in source file)
from base58 import b58encode

SATOSHI_PLACES = Decimal("0.00000001")


def ensure_bitcoind():
    """ 
    Ensures that the bitcoind daemon is running
    """

    devnull = open("/dev/null")

    subprocess.call("bitcoind -daemon -connect=0.0.0.0",
                    shell=True, stdout=devnull, stderr=devnull)

    times = 0
    while times < 10:
        times += 1
        if subprocess.call("bitcoin-cli getinfo", shell=True, stdout=devnull, stderr=devnull) == 0:
            return
        time.sleep(0.5)

    raise Exception("Timeout while starting bitcoin server")


def write_and_check_qr(name, filename, data):
    """ 
    Write a QR code and then read it back to try and detect any tricksy malware tampering with it.

    name: <string> short description of the data
    filename: <string> filename for storing the QR code
    data: <string> the data to be encoded
    """

    subprocess.call("qrencode -o {0} {1}".format(filename, data), shell=True)
    check = subprocess.check_output(
        "zbarimg --quiet --raw {}".format(filename), shell=True)

    if check.strip() != data:
        print "********************************************************************"
        print "WARNING: {} QR code could not be verified properly. This could be a sign of a security breach.".format(name)
        print "********************************************************************"

    print "QR code for {0} in {1}".format(name, filename)


def check_dice(dices):
    """
    Validates dice data.
    returns => <boolean>

    dices: <string> representing list of dice rolls. Each digit should be between 1 and 6
    """

    for dice in dices:
        try:
            i = int(dice)
            if i < 1 or i > 6:
                print "Error: dice rolls must be between 1 and 6"
                return False
        except ValueError:
            print "Error: dice values should be numbers between 1 and 6"
            return False

    return True


def read_dice_interactive(min_length):
    """
    Reads min_length dice from standard in and returns a string representing the dice rolls
    returns => <string>

    min_length: <+int> number of dice rolls required
    """

    def ask_for_dice_rolls(x):
        print "enter {0} dice rolls:".format(x)

    results = ""

    while len(results) < min_length:
        ask_for_dice_rolls(min_length - len(results))
        dices = raw_input()

        if check_dice(dices):
            results += dices

    return results


def check_seed(seed, min_length):
    """
    Validates random hex seed
    returns => <boolean>

    seed: <string> random hex string
    min_length: <int> number of characters required
    """

    if len(seed) < min_length:
        print "Error: seed must be at least {0} hex characters long".format(min_length)
        return False

    if len(seed) % 2 != 0:
        print "Error: seed must contain even number of characters"
        return False

    try:
        int(seed, 16)
    except ValueError:
        print "Error: Illegal character. Seed must be composed of hex characters"
        return False

    return True


def read_seed_interactive(min_length):
    """
    Reads random seed of at least min_length characters and returns it as string
    returns => string

    min_length: <int> the number of characters to read of the seed
    """

    def ask_for_random_seed(length):
        print "enter random seed as a hex string with at least {0} characters".format(length)

    ask_for_random_seed(min_length)
    seed = raw_input()

    while not check_seed(seed, min_length):
        ask_for_random_seed(min_length)
        seed = raw_input()

    return seed


def xor_hex_strings(str1, str2):
    """
    Return xor of two hex strings
    returns => <string> in hex format
    """
    str1_dec = int(str1, 16)
    str2_dec = int(str2, 16)

    xored = str1_dec ^ str2_dec

    return "{:02x}".format(xored)


def seed_to_privkey(seed):
    """ 
    Converts a 256 bit hex string to a bitcoin private key format
    returns => <string> in hex format
    """

    seed_80 = "80" + seed
    key = seed_80 + checksum(seed_80)
    return key


def key_to_WIF(key):
    """ 
    Converts a bitcoin private key in hex format to WIF
    returns => <string> WIF format
    """
    key_58 = b58encode(key.decode("hex"))
    return key_58


def hash_sha256(s):
    """A thin wrapper around the hashlib sha 256 library to provide a more functional interface"""
    m = sha256()
    m.update(s)
    return m.hexdigest()


def hash_md5(s):
    """A thin wrapper around the hashlib md5 library to provide a more functional interface"""
    m = md5()
    m.update(s)
    return m.hexdigest()


def checksum(s):
    h1 = hash_sha256(s.decode("hex"))
    h2 = hash_sha256(h1.decode("hex"))
    return h2[0:8]


def get_address_for_privkey(privkey):
    """A method for retrieving the address associated with a private key from bitcoin core
       <privkey> - a bitcoin private key in WIF format"""

    # Arbitrary label. A unique label ensures that we will get back only one public key
    # when we call the "getaddressesbyaccount" rpc later

    label = random.randint(0, 2**128)
    subprocess.call(
        "bitcoin-cli importprivkey {0} {1}".format(privkey, label), shell=True)
    addresses = subprocess.check_output(
        "bitcoin-cli getaddressesbyaccount {0}".format(label), shell=True)
    addresses_json = json.loads(addresses)
    return addresses_json[0]


def deposit_interactive(m, n, dice_length=62, seed_length=20):
    safety_checklist()
    ensure_bitcoind()

    print "Creating {0}-of-{1} multisig address....\n".format(m, n)

    keys = []

    while len(keys) < n:
        index = len(keys) + 1
        print "Generating address #{}".format(index)

        dice_string = read_dice_interactive(dice_length)
        dice_hash = hash_sha256(dice_string)

        seed_string = read_seed_interactive(seed_length)
        seed_hash = hash_sha256(seed_string)

        # back to hex string
        combined_seed = xor_hex_strings(dice_hash, seed_hash)
        privkey = seed_to_privkey(combined_seed)
        privkey_WIF = key_to_WIF(privkey)

        print "\nPrivate key #{}:".format(index)
        print "{}\n".format(privkey_WIF)

        keys.append(privkey_WIF)

    print "Keys created. Generating {0}-of-{1} multisig address....\n".format(m, n)

    addresses = [get_address_for_privkey(key) for key in keys]

    address_string = json.dumps(addresses)
    label = random.randint(0, 2**128)

    argstring = "{0} '{1}'".format(m, address_string)

    results = subprocess.check_output(
        "bitcoin-cli createmultisig {0}".format(argstring), shell=True)
    results = json.loads(results)

    print "Private keys:"
    for idx, key in enumerate(keys):
        print "key #{0}: {1}".format(idx + 1, key)

    print "\nMulitsig Address:"
    print "{}".format(results["address"])

    print "\nRedeem Script:"
    print "{}".format(results["redeemScript"])
    print ""

    write_and_check_qr("Multisig address", "address.png", results["address"])
    write_and_check_qr("Redeem Script", "redemption.png",
                       results["redeemScript"])


#### multisig redemption functions ####

def multisig_gen_trx(addresses, redeem_script, in_txid, in_vout, in_script_pub_key, privkeys):
    """generate a signed multisig transaction
    addresses: a dictionary of base58 bitcoin destination addresses to decimal bitcoin ammounts
    redeem_script: hex string,
    in_txid: txid of an input transaction to the multisig address
    in_vout: which output you are sending
    in_output_script: the scriptPubKey of the output
    privkeys: an array of private keys to sign with"""

    data_1 = [{
        "txid": in_txid,
        "vout": int(in_vout)
    }]

    argstring_1 = "'{0}' '{1}'".format(
        json.dumps(data_1), json.dumps(addresses))

    tx_hex = subprocess.check_output(
        "bitcoin-cli createrawtransaction {0}".format(argstring_1), shell=True).strip()

    data_2 = [{
        "txid": in_txid,
        "vout": int(in_vout),
        "scriptPubKey": in_script_pub_key,
        "redeemScript": redeem_script
    }]

    argstring_2 = "{0} '{1}' '{2}'".format(
        tx_hex, json.dumps(data_2), json.dumps(privkeys))
    signed_tx_hex = subprocess.check_output(
        "bitcoin-cli signrawtransaction {0}".format(argstring_2), shell=True).strip()

    return signed_tx_hex


def yes_no_interactive():
    def confirm_prompt():
        return raw_input("Confirm? (y/n): ")

    confirm = confirm_prompt()

    while True:
        if confirm.upper() == "Y":
            return True
        if confirm.upper() == "N":
            return False
        else:
            print "You must enter y or n"
            confirm = confirm_prompt()


def create_unsigned_transaction(source_address, destinations, redeem_script, txs):
    """
    Returns a hex string representing an unsigned bitcoin transaction
    output => <string>

    source_address: <string> 
    destinations: {address <string>: amount<string>} dictionary mapping destination addresses to amount in BTC
    redeem_script: <string>
    txs: List<dict> List of transactions in dictionary form (bitcoind decoded format)
    """

    # prune addresses sent 0 btc
    for address, value in destinations.items():
        if value == "0":
            del destinations[address]

    # For each UTXO used as input, we need the txid and vout index to generate
    # a transaction
    inputs = []
    for tx in txs:
        utxos = get_utxos(tx, source_address)
        txid = tx["txid"]

        for utxo in utxos:
            inputs.append({
                "txid": txid,
                "vout": int(utxo["n"])
            })

    argstring = "'{0}' '{1}'".format(
        json.dumps(inputs), json.dumps(destinations))

    tx_unsigned_hex = subprocess.check_output(
        "bitcoin-cli createrawtransaction {0}".format(argstring), shell=True).strip()

    return tx_unsigned_hex


def sign_transaction(source_address, keys, redeem_script, unsigned_hex, txs):
    """
    Creates a signed transaction
    output => dictionary {"hex": transaction <string>, "complete": <boolean>}

    source_address: <string>
    keys: List<string> The private keys you wish to sign with
    redeem_script: <string> 
    unsigned_hex: <string> The unsigned transaction, in hex format
    txs: List<dict> A list of transactions to use as input (bitcoind decoded format)
    """

    # For each UTXO used as input, we need the txid, vout index, scriptPubKey, and redeemScript
    # to generate a signature
    inputs = []
    for tx in txs:
        utxos = get_utxos(tx, source_address)
        txid = tx["txid"]
        for utxo in utxos:
            inputs.append({
                "txid": txid,
                "vout": int(utxo["n"]),
                "scriptPubKey": utxo["scriptPubKey"]["hex"],
                "redeemScript": redeem_script
            })

    argstring_2 = "{0} '{1}' '{2}'".format(
        unsigned_hex, json.dumps(inputs), json.dumps(keys))
    signed_hex = subprocess.check_output(
        "bitcoin-cli signrawtransaction {0}".format(argstring_2), shell=True).strip()
    signed_tx = json.loads(signed_hex)
    return signed_tx


def satoshi_to_btc(satoshi):
    """ 
    Converts a value in satoshi to a value in BTC
    outputs => Decimal

    satoshi: <int>
    """
    value = Decimal(satoshi) / Decimal(100000000)
    return value.quantize(SATOSHI_PLACES)


def btc_to_satoshi(btc):
    """ 
    Converts a value in BTC to satoshi
    outputs => <int>

    btc: <Decimal> or <Float> 
    """
    value = btc * 100000000
    return int(value)


def get_fee_interactive(source_address, keys, destinations, redeem_script, txs, satoshis_per_byte=None):
    """ Returns a recommended transaction fee, given market fee data provided by the user interactively
    Parameters:
      keys: A list of signing keys
      addresses: A dictionary of format {"address": "amount"}
      redeem_script: String
      tx: A dictionary representing a transaction (bitcoin core format)
      utxo: A dictionary representing a transaction output (bitcoin core format)
      satoshis_per_byte: an INT 
    """

    MAX_FEE = .005  # in btc

    approve = False

    while not approve:

        if not satoshis_per_byte:
            print "What is the current recommended fee amount?"
            satoshis_per_byte = int(raw_input("Satoshis per byte:"))

        unsigned_tx = create_unsigned_transaction(
            source_address, destinations, redeem_script, txs)

        signed_tx = sign_transaction(source_address, keys,
                                     redeem_script, unsigned_tx, txs)

        size = len(signed_tx["hex"]) / 2

        fee = size * satoshis_per_byte
        fee = satoshi_to_btc(fee)

        if fee > MAX_FEE:
            print "Fee is too high. Must be under {}".format(MAX_FEE)
        else:
            print "\nBased on your input, the fee is {} bitcoin".format(fee)
            confirm = yes_no_interactive()

            if confirm:
                approve = True
            else:
                print "\nFee calculation aborted. Starting over...."

    return fee


def get_utxos(tx, address):
    """ 
    Given a transaction, find all the outputs that were sent to an address
    return => List<Dictionary> list of UTXOs in bitcoin core format

    tx - <Dictionary> in bitcoind core format
    address - <string>
    """
    utxos = []

    for output in tx["vout"]:
        out_addresses = output["scriptPubKey"]["addresses"]
        amount_btc = output["value"]
        if address in out_addresses:
            utxos.append(output)

    return utxos


def withdraw_interactive():
    safety_checklist()
    ensure_bitcoind()

    approve = False

    while not approve:
        addresses = {}

        print """
        Welcome to the multisig funds withdrawal script!
        We will need several pieces of information to create a withdrawal transaction.
        \n*** PLEASE BE SURE TO ENTER THE CORRECT DESTINATION ADDRESS ***\n"""

        dest_address = raw_input("\nDestination address: ")
        addresses[dest_address] = 0

        source_address = raw_input("\nSource multisig address: ")
        addresses[source_address] = 0

        print "\nPlease provide the redeem script for this multisig address."
        redeem_script = raw_input("Redeem script: ")

        print "\nHow many input transactions will you be using for this withdrawal?"
        num_tx = int(raw_input("Tx #:"))

        txs = []
        utxos = []
        utxo_sum = Decimal(0).quantize(SATOSHI_PLACES)

        while len(txs) < num_tx:
            print "\nPlease provide raw transaction #{} (hex format) with unspent outputs for this source address:".format(len(txs) + 1)
            hex_tx = raw_input()
            tx = json.loads(subprocess.check_output(
                "bitcoin-cli decoderawtransaction {0}".format(hex_tx), shell=True))
            txs.append(tx)
            utxos += get_utxos(tx, source_address)

        if len(utxos) == 0:
            print "\nTransaction data not found for source address: {}".format(source_address)
            sys.exit()
        else:
            print "\nTransaction data found for source address."

            for utxo in utxos:
                value = Decimal(utxo["value"]).quantize(SATOSHI_PLACES)
                print "Amount: {} btc".format(value)
                utxo_sum += value

            print "TOTAL: {} btc".format(utxo_sum)

        print "How many private keys will you be signing with?"
        key_count = int(raw_input("#: "))

        keys = []
        while len(keys) < key_count:
            key = raw_input("key #{0}: ".format(len(keys) + 1))
            keys.append(key)

        ###### fees, amount, and change #######

        input_amount = utxo_sum
        fee = get_fee_interactive(
            source_address, keys, addresses, redeem_script, txs)
        # Got this far
        if fee > input_amount:
            print "ERROR: Input amount is less than recommended fee. Try using a larger input transaction. Exiting...."
            sys.exit()

        print "\nPlease enter the decimal amount (in bitcoin) to send to destination"
        print "\nExample: 2.3 for 2.3 bitcoin.\n"
        print "*** All balance not sent to destination or as fee will be returned to source address as change ***\n"
        print "\nAfter fees of {0} you have {1} bitcoin to send".format(fee, input_amount - fee)
        amount = raw_input(
            "Amount to send to {0} (leave blank for all): ".format(dest_address))
        if amount == "":
            amount = input_amount - fee
        else:
            amount = Decimal(amount).quantize(SATOSHI_PLACES)

        if fee + amount > input_amount:
            print "Error: fee + destination amount greater than input amount"
            raise Exception("Output values greater than input value")

        change_amount = input_amount - amount - fee

        # less than a satoshi due to weird floating point imprecision
        if change_amount < 1e-8:
            change_amount = 0

        if change_amount > 0:
            print "{0} going to change address {1}".format(change_amount, source_address)

        addresses[dest_address] = str(amount)
        addresses[source_address] = str(change_amount)

        # check data
        print "\nIs this data correct?"
        print "*** WARNING: incorrect data may lead to loss of funds ***"

        print "{0} input value".format(input_amount)
        for address, value in addresses.iteritems():
            if address == source_address:
                print "{0} btc going to change address {1}".format(value, address)
            else:
                print "{0} btc going to destination address {1}".format(value, address)
        print "Fee amount: {0}".format(fee)
        print "Signing with private keys:"
        for key in keys:
            print "{}".format(key)

        confirm = yes_no_interactive()

        if confirm:
            approve = True
        else:
            print "\nProcess aborted. Starting over...."

    #### Calculate Transaction ####
    print "\nCalculating transaction.....\n"

    unsigned_tx = create_unsigned_transaction(
        source_address, addresses, redeem_script, txs)

    signed_tx = sign_transaction(source_address, keys,
                                 redeem_script, unsigned_tx, txs)

    print "\nComplete signature?"
    print signed_tx["complete"]

    print "\nSigned transaction (hex):"
    print signed_tx["hex"]

    print "\nTransaction checksum (md5):"
    print hash_md5(signed_tx["hex"])

    write_and_check_qr("Transaction", "tx.png", signed_tx["hex"])


def make_seeds(n, length):
    safety_checklist()

    print "Making {} seeds....".format(n)
    print "Please move your mouse to generate randomness if seeds don't appear right away\n"

    seeds = 0
    while seeds < n:
        seed = subprocess.check_output(
            "xxd -l {} -p /dev/random".format(length), shell=True)
        seeds += 1
        print "Seed #{0}: {1}".format(seeds, seed.replace('\n', ''))


def safety_checklist():

    print "YOU ARE DOING THIS AT YOUR OWN RISK."

    checks = [
        "Are you running this on a computer WITHOUT a network connection of any kind?",
        "Have the wireless cards in this computer been physically removed?",
        "Are you running on battery power?",
        "Is your battery fully charged?",
        "Are you running on an operating system booted from a USB drive?",
        "Is your screen hidden from view of windows, cameras, and other people?",
        "Are smartphones and all other nearby devices turned off and in a Faraday bag?"]

    for check in checks:
        answer = raw_input(check + " (y/n)?")
        if answer.upper() != "Y":
            print "\n Safety check failed. Exiting....."
            sys.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('program', choices=[
                        'make_seeds', 'deposit', 'withdraw'])

    parser.add_argument("--num_seeds", type=int,
                        help="The number of random seeds to make", default=1)
    parser.add_argument("-d", "--dice", type=int,
                        help="The minimum number of dice rolls to use for entropy when generating private keys (default: 62)", default=62)
    parser.add_argument("-s", "--seed", type=int,
                        help="Minimum number of 8-bit bytes to use for seed entropy when generating private keys (default: 20)", default=20)
    parser.add_argument(
        "-m", type=int, help="Number of signing keys required in an m-of-n multisig address creation (default m-of-n = 1-of-2)", default=1)
    parser.add_argument(
        "-n", type=int, help="Number of total keys required in an m-of-n multisig address creation (default m-of-n = 1-of-2)", default=2)
    args = parser.parse_args()

    if args.program == "make_seeds":
        make_seeds(args.num_seeds, args.seed)

    if args.program == "deposit":
        deposit_interactive(args.m, args.n, args.dice, args.seed)

    if args.program == "withdraw":
        withdraw_interactive()
