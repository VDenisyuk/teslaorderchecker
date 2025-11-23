import requests
import time
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from auth import main as run_tesla_auth
import apprise

timezone='Europe/Berlin'

HISTORY_TRANSLATIONS_IGNORED = {
    "tasks.registration.orderDetails.vin",
    "tasks.registration.regData.orderDetails.vin",
    "tasks.finalPayment.data.vin",
    "tasks.tradeIn.isMatched",
    "tasks.registration.isMatched",
    "tasks.registration.orderDetails.vehicleModelYear",
    "state",
    "strings",
    "scheduling.card",
    "scheduling.strings",
    "tasks.carbonCredit.card",
    "tasks.carbonCredit.strings.",
    "tasks.finalPayment.card.",
    "tasks.finalPayment.strings.",
    "tasks.scheduling.card.",
    "tasks.scheduling.strings.",
    "tasks.scheduling.isDeliveryEstimatesEnabled",
    "tasks.registration.orderDetails.isAvailableForMatch",
    "tasks.finalPayment.data.isAvailableForMatch",
    "tasks.finalPayment.data.deliveryReadinessDetail.",
    "tasks.finalPayment.data.deliveryReadiness.",
    "tasks.finalPayment.data.agreementDetails",
    "tasks.finalPayment.data.vehicleId",
    "tasks.deliveryAcceptance.gates",
    "tasks.deliveryAcceptance.card.",
    "tasks.deliveryAcceptance.strings.",
    "tasks.deliveryDetails.regData.reggieRegistrationStatus",
    "tasks.deliveryDetails.strings.",
    "tasks.deliveryDetails.card.",
    "tasks.registration.card.",
    "tasks.registration.regData.reggieRegistrationStatus",
    "tasks.registration.strings.",
    "tasks.finalPayment.complete",
    "tasks.finalPayment.data.finalPaymentStatus",
    "tasks.scheduling.apptDateTimeAddressStr",
    "tasks.scheduling.isInventoryOrMatched",
    "tasks.finalPayment.data.hasFinalInvoice",
    "tasks.finalPayment.data.hasActiveInvoice",
    "tasks.finalPayment.data.selfSchedulingDetails.deliveryLocationId",
    "tasks.finalPayment.data.selfSchedulingDetails.",
    "tasks.financing.card.",
    "tasks.financing.strings.",
    "tasks.tradeIn.card.",
    "tasks.tradeIn.strings."
}

# Load the config file
try: 
    with open('config.json', 'r') as f:
        config = json.load(f)
    reservation_number = config['reservation_number']
    apprisestr = config['apprisestr']
    wantnotification = config['notifications_enabled']
    interval = config['interval']

except Exception as e:
    # If the file is not found, print the message and exit
    print("config.json not found, please run 'cp config.json.sample config.json' and double check your variables")
    sys.exit(1)
    
headers = {
    "accept": "*/*",
    "x-tesla-user-agent": "TeslaApp/4.50.1-3578",
    "charset": "utf-8",
    "cache-control": "no-cache",
    "accept-language": "en",
    "authorization": "Bearer",
    "Connection": "Keep-Alive",
    "User-Agent": "okhttp/4.10.0",
}

params = {
    "deviceLanguage": "en",
    "deviceCountry": "US",
    "referenceNumber": reservation_number,
    "appVersion": "4.50.1-3578",
}


def fetch_data(access_token):
    headers["authorization"] = f"Bearer {access_token}"
    response = requests.get(
        "https://akamai-apigateway-vfx.tesla.com/tasks", params=params, headers=headers
    )
    if response.status_code != 200:
        print(f"[!] Something went wrong: {response.status_code}, {response.text}")
    else:
        return response.json()


# Notify using Apprise
def notify(message):
    apobj = apprise.Apprise()
    # Initialize apprise from config up in the file
    apobj.add(apprisestr)
    # Send notification
    apobj.notify(title="Something changed in your tesla status", body=message)


# Save data to file
def savedata(new_data):
    with open('./data/lastdata.json', 'w') as file:
        json.dump(new_data, file, indent=4)

# Function to compare JSON data
def compare_data(old_data, new_data, parent_key=""):
    for key, value in old_data.items():
        full_key = f"{parent_key}.{key}" if parent_key else key
        if full_key in HISTORY_TRANSLATIONS_IGNORED:
            continue
        if (key != "ssn") and (key in new_data):
            if isinstance(value, dict) and isinstance(new_data[key], dict):
                # Recursive call for nested dictionaries
                compare_data(
                    value, new_data[key], parent_key=full_key
                )
            elif new_data[key] != value:
                message = (
                    f"`{full_key}`: \n <b>Old Value:</b> <s>'{value}'</s> \n<b>Updated Value:</b> \n> '{new_data[key]}'"
                )
                print(f"[!] Data Changed: \n{message}")
                if wantnotification:
                    notify(message)

# Debug notification
#notify("Tesla Order Update Script started...")

# Set access token for the first time
access_token = run_tesla_auth()
# Try to load initial data from lastdata.json
try:
    with open('./data/lastdata.json', 'r') as file:
        print("[i] Continuing from last session")
        previous_data = json.load(file)
except FileNotFoundError:
    print("[!] No previous data found, doing intial call and saving")
    previous_data = fetch_data(access_token)  # Fetch new data if file doesn't exist
    savedata(previous_data)
    print(json.dumps(previous_data, indent=4))

# uncomment if you want to print initial values
# print(json.dumps(previous_data, indent=4))

while True:
    try:
        # Make the API request
        access_token = run_tesla_auth()
        new_data = fetch_data(access_token)
        print(f"{datetime.now(tz=ZoneInfo(timezone))} - Checking for differences")
        compare_data(previous_data, new_data)
        previous_data = new_data

        # Overwrite lastdata.json with new data
        with open('./data/lastdata.json', 'w') as file:
            json.dump(new_data, file, indent=4)

        # Sleep for a while before the next request
        time.sleep(interval)

    except Exception as e:
        print(f"An error occurred: {e}")
        # Optional: delay before continuing
        time.sleep(120)
