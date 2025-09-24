import streamlit as st
from stellar_sdk import Keypair, Server, TransactionBuilder, Asset
from bip_utils import Bip39SeedGenerator, Bip39MnemonicValidator, Bip39Languages, Bip32Slip10Ed25519
import time

# Pi Network configuration
NETWORK_PASSPHRASE = "Pi Network"  # Verify at developers.pi.network
API_BASE = "https://api.mainnet.minepi.com"
RESERVE_AMOUNT = 0.01

# Cache Server instance
@st.cache_resource
def get_server():
    return Server(API_BASE)

# Cache keypair derivation
@st.cache_data
def derive_pi_keypair(mnemonic: str):
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
    bip32 = Bip32Slip10Ed25519.FromSeed(seed_bytes)
    key = bip32.DerivePath("m/44'/314159'/0'").PrivateKey().Raw().ToBytes()
    sender_secret = Keypair.from_raw_ed25519_seed(key).secret
    sender_keypair = Keypair.from_secret(sender_secret)
    return sender_keypair.public_key, sender_secret

# Send Pi with 50 attempts, minimal UI
def send_pi(sender_pub, sender_secret, dest_address, amount, available_balance, sweep=False, max_attempts=50):
    server = get_server()
    sender_kp = Keypair.from_secret(sender_secret)
    attempts = 0
    last_error = None

    # Use available balance (minus reserve) for sweep or if amount is 0, else cap at available balance
    send_amount = max(0, available_balance - RESERVE_AMOUNT) if sweep or amount <= 0 else min(amount, max(0, available_balance - RESERVE_AMOUNT))

    # Cache account and base fee
    try:
        account = server.load_account(sender_pub)
        base_fee = server.fetch_base_fee()
    except Exception as e:
        return {"success": False, "error": f"Failed to load account: {str(e)}", "attempts": 0}

    while attempts < max_attempts:
        attempts += 1
        try:
            if send_amount <= 0:
                return {"success": False, "error": "Amount too small or insufficient balance", "attempts": attempts}
            tx = (
                TransactionBuilder(
                    source_account=account,
                    network_passphrase=NETWORK_PASSPHRASE,
                    base_fee=base_fee,
                )
                .append_payment_op(destination=dest_address, amount=str(send_amount), asset=Asset.native())
                .set_timeout(30)
                .build()
            )
            tx.sign(sender_kp)
            result = server.submit_transaction(tx)
            if "hash" in result:
                return {"success": True, "txHash": result["hash"], "amount": send_amount, "attempts": attempts}
            last_error = "Transaction failed"
        except Exception as e:
            last_error = str(e)
            if "429" in str(e):  # Fallback for rate limit
                time.sleep(0.1)

    return {"success": False, "error": last_error or "No attempts made", "attempts": attempts}

# Streamlit interface
st.title("🚀 Pi Super Bot (Mainnet)")

mnemonic = st.text_area(
    "Enter your 24-word Pi Wallet Mnemonic",
    placeholder="Enter your 24-word mnemonic phrase",
    help="Enter a valid 24-word BIP-39 mnemonic. Move locked coins to available balance in Wallet.Pi first."
)
destination = st.text_input(
    "Destination Wallet Address",
    placeholder="Enter a valid Pi address (starts with G...)"
)
amount_input = st.number_input(
    "Amount to Send (leave 0 for available balance)",
    value=0.0,
    step=0.01,
    min_value=0.0
)
sweep_wallet = st.checkbox("Sweep Wallet (send all available balance, leave 0.01 PI)")
start_bot = st.button("Start Pi Bot")

if start_bot:
    if not mnemonic or not destination:
        st.error("Enter both mnemonic and destination address.")
    else:
        normalized_mnemonic = mnemonic.strip().lower()
        validator = Bip39MnemonicValidator(Bip39Languages.ENGLISH)
        try:
            if not validator.IsValid(normalized_mnemonic):
                st.error("❌ Invalid mnemonic phrase!")
            elif len(normalized_mnemonic.split()) != 24:
                st.error("❌ Requires 24-word mnemonic.")
            else:
                with st.spinner("🔄 Processing..."):
                    pub_key, secret = derive_pi_keypair(normalized_mnemonic)
                    server = get_server()
                    try:
                        account = server.accounts().account_id(pub_key).call()
                        balances = {bal['asset_type']: float(bal['balance']) for bal in account['balances']}
                        available_balance = balances.get("native", 0.0)
                        st.info(f"Available Pi balance: {available_balance} PI")
                    except Exception as e:
                        st.error(f"❌ Failed to load account: {str(e)}")
                        st.stop()

                    send_amount = amount_input
                    with st.spinner(f"🔄 Sending {'all available' if sweep_wallet or send_amount <= 0 else send_amount} PI to {destination} (50 attempts)..."):
                        start_time = time.time()
                        result = send_pi(pub_key, secret, destination, send_amount, available_balance, sweep=sweep_wallet)
                        end_time = time.time()
                        st.info(f"Attempts: {result['attempts']}/50 | Time: {end_time - start_time:.2f}s")
                        if result["success"]:
                            st.success(f"✅ Sent {result['amount']} PI! TX Hash: {result['txHash']}")
                        else:
                            st.error(f"❌ Failed after {result['attempts']} attempts: {result['error']}")

        except Exception as e:
            st.error(f"❌ Error validating mnemonic: {str(e)}")
