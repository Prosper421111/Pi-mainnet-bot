from flask import Flask, request, jsonify, render_template_string
from stellar_sdk import Keypair, Server, TransactionBuilder, Asset
from bip_utils import Bip39SeedGenerator, Bip39MnemonicValidator, Bip39Languages, Bip32Slip10Ed25519
import time
import os

app = Flask(__name__)

# Pi Network configuration
NETWORK_PASSPHRASE = "Pi Network"
API_BASE = "https://api.mainnet.minepi.com"
RESERVE_AMOUNT = 0.01

def get_server():
    return Server(API_BASE)

def derive_pi_keypair(mnemonic: str):
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
    bip32 = Bip32Slip10Ed25519.FromSeed(seed_bytes)
    key = bip32.DerivePath("m/44'/314159'/0'").PrivateKey().Raw().ToBytes()
    sender_secret = Keypair.from_raw_ed25519_seed(key).secret
    sender_keypair = Keypair.from_secret(sender_secret)
    return sender_keypair.public_key, sender_secret

def send_pi(sender_pub, sender_secret, dest_address, amount, available_balance, sweep=False, max_attempts=50):
    server = get_server()
    sender_kp = Keypair.from_secret(sender_secret)
    attempts = 0
    last_error = None

    send_amount = max(0, available_balance - RESERVE_AMOUNT) if sweep or amount <= 0 else min(amount, max(0, available_balance - RESERVE_AMOUNT))

    try:
        account = server.load_account(sender_pub)
        base_fee = server.fetch_base_fee()
    except Exception as e:
        return {"success": False, "error": f"Failed to load account: {str(e)}", "attempts": 0}

    while attempts < max_attempts:
        attempts += 1
        print(f"Attempts: {attempts}/50")
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
            if "429" in str(e):
                time.sleep(0.1)

    return {"success": False, "error": last_error or "No attempts made", "attempts": attempts}

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        mnemonic = request.form.get('mnemonic', '').strip().lower()
        destination = request.form.get('destination', '')
        amount = float(request.form.get('amount', 0) or 0)
        sweep = request.form.get('sweep', 'off') == 'on'

        validator = Bip39MnemonicValidator(Bip39Languages.ENGLISH)
        if not validator.IsValid(mnemonic) or len(mnemonic.split()) != 24:
            return render_template_string(HTML_TEMPLATE, error="Invalid mnemonic phrase", output="")

        try:
            pub_key, secret = derive_pi_keypair(mnemonic)
            server = get_server()
            account = server.accounts().account_id(pub_key).call()
            balances = {bal['asset_type']: float(bal['balance']) for bal in account['balances']}
            available_balance = balances.get("native", 0.0)
        except Exception as e:
            return render_template_string(HTML_TEMPLATE, error=f"Failed to load account: {str(e)}", output="")

        start_time = time.time()
        result = send_pi(pub_key, secret, destination, amount, available_balance, sweep=sweep)
        end_time = time.time()

        output = f"Available Pi balance: {available_balance} PI\n"
        output += f"Sending {'all available' if sweep or amount <= 0 else amount} PI to {destination} (50 attempts)...\n"
        output += f"Attempts: {result['attempts']}/50 | Time: {end_time - start_time:.2f}s\n"
        if result["success"]:
            output += f"✅ Sent {result['amount']} PI! TX Hash: {result['txHash']}"
        else:
            output += f"❌ Failed after {result['attempts']} attempts: {result['error']}"

        return render_template_string(HTML_TEMPLATE, error="", output=output)

    return render_template_string(HTML_TEMPLATE, error="", output="")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Pi Super Bot</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; }
        input, textarea { width: 100%; padding: 8px; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        .output { margin-top: 20px; white-space: pre-wrap; }
        .error { color: red; }
    </style>
</head>
<body>
    <h1>🚀 Pi Super Bot (Mainnet)</h1>
    <form method="POST">
        <div class="form-group">
            <label for="mnemonic">Enter your 24-word Pi Wallet Mnemonic</label>
            <textarea id="mnemonic" name="mnemonic" placeholder="Enter your 24-word mnemonic phrase" rows="4" required></textarea>
        </div>
        <div class="form-group">
            <label for="destination">Destination Wallet Address</label>
            <input id="destination" name="destination" placeholder="Enter a valid Pi address (starts with G...)" required>
        </div>
        <div class="form-group">
            <label for="amount">Amount to Send (leave 0 for available balance)</label>
            <input id="amount" name="amount" type="number" step="0.01" min="0" value="0">
        </div>
        <div class="form-group">
            <label><input type="checkbox" name="sweep"> Sweep Wallet (send all available balance, leave 0.01 PI)</label>
        </div>
        <button type="submit">Start Pi Bot</button>
    </form>
    {% if error %}
        <p class="error">{{ error }}</p>
    {% endif %}
    {% if output %}
        <div class="output">{{ output }}</div>
    {% endif %}
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
