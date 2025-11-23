import os
import base64
import hashlib
import json
import time
import urllib.parse
import webbrowser
import requests
import sys
from pathlib import Path
from typing import Dict, Union
import json as jsonlib

CLIENT_ID = 'ownerapi'
REDIRECT_URI = 'https://auth.tesla.com/void/callback'
AUTH_URL = 'https://auth.tesla.com/oauth2/v3/authorize'
TOKEN_URL = 'https://auth.tesla.com/oauth2/v3/token'
SCOPE = 'openid email offline_access'
CODE_CHALLENGE_METHOD = 'S256'
STATE = os.urandom(16).hex()
BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "data" / 'tesla_tokens.json'


def request_with_retry(url, headers=None, data=None, json=None, max_retries=3, exit_on_error=True):
    """Perform a GET or POST request with exponential backoff retries.

    Parameters
    ----------
    url : str
        Target endpoint.
    headers : dict, optional
        Headers to include with the request.
    data : Any, optional
        Data payload for ``POST`` requests.
    json : Any, optional
        JSON payload for ``POST`` requests.
    max_retries : int
        Number of attempts before giving up.
    exit_on_error : bool
        When ``True`` (default) the function prints a user friendly message
        and terminates the program on failure. When ``False`` a ``RuntimeError``
        is raised instead so callers can handle network issues gracefully.
    """
    _STATUS_TEXTS: Dict[Union[int, str], str] = {
        400: "Invalid request (400): Please check parameters.",
        401: "Unauthorized (401): Token/login seems incorrect.",
        403: "Forbidden (403): Data not accessible. Try again later.",
        404: "Not found (404): Resource does not exist or is not visible.",
        422: "Unprocessable Entity (422): Invalid/missing fields in request.",
        429: "Too Many Requests (429): Rate limit reached. Please wait and try again.",
        '5xx': "API unreachable - please try again later."
    }
    for attempt in range(max_retries):
        try:
            if data is None and json is None:
                response = requests.get(url, headers=headers)
            else:
                if json is not None:
                    response = requests.post(url, headers=headers, json=json)
                else:
                    # Falls string/bytes: direkt senden; falls dict: sauber als JSON senden
                    if isinstance(data, (dict, list)):
                        response = requests.post(
                            url,
                            headers={"Content-Type": "application/json", **(headers or {})},
                            data=jsonlib.dumps(data, separators=(",", ":")),
                        )
                    else:
                        response = requests.post(url, headers=headers, data=data)

            try:
                response.raise_for_status()
            except Exception:
                if response.status_code >= 500:
                    if attempt == max_retries - 1:
                        if exit_on_error:
                            print(f"\n{_STATUS_TEXTS['5xx']}")
                            sys.exit(1)
                        else:
                            raise RuntimeError(_STATUS_TEXTS['5xx'])

                    time.sleep(5 ** attempt)
                    continue
                else:
                    error_text = _STATUS_TEXTS.get(response.status_code, _STATUS_TEXTS['5xx'])
                    if exit_on_error:
                        print(f"\n{error_text}")
                        sys.exit(1)
                    else:
                        raise RuntimeError(error_text)

            return response
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                if exit_on_error:
                    print(f"\n{_STATUS_TEXTS['5xx']}")
                    sys.exit(1)
                else:
                    raise RuntimeError(_STATUS_TEXTS['5xx'])
            time.sleep(2 ** attempt)
    return None

def _generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode('utf-8')).digest()).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge


def _get_auth_code(code_challenge: str):
    auth_params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPE,
        'state': STATE,
        'code_challenge': code_challenge,
        'code_challenge_method': CODE_CHALLENGE_METHOD,
    }

    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print("To retrieve your order status, you need to authenticate with your Tesla account.")
    print('A browser window will open with the Tesla login page. After logging in you will likely see a \"Page Not Found\" page. That is CORRECT!')
    print("Copy the full URL of that page and return here. The authentication happens only between you and Tesla; no data leaves your system.")
    if input("Proceed to open the login page? (y/n): ").lower() != 'y':
        print("Authentication cancelled.")
        sys.exit(0)
    print(f"{auth_url}")
    try:
        if not webbrowser.open(auth_url):
            print("No GUI detected. Open this URL manually:")
            print(f"{auth_url}")
    except Exception:
        print("No GUI detected. Open this URL manually:")
        print(f"{auth_url}")
    redirected_url = input("Please enter the redirected URL here: ")
    parsed_url = urllib.parse.urlparse(redirected_url)
    params = urllib.parse.parse_qs(parsed_url.query)
    code = params.get('code')
    if not code:
        print(f"\nNo authentication code found in the redirected URL.")
        sys.exit(1)
    return code[0]

def _exchange_code_for_tokens(auth_code,code_verifier):
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'code': auth_code,
        'redirect_uri': REDIRECT_URI,
        'code_verifier': code_verifier,
    }
    response = request_with_retry(TOKEN_URL, None, token_data)
    return response.json()


def _save_tokens_to_file(tokens):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f)
        print(f"> Tokens saved to '{TOKEN_FILE}'")


def _load_tokens_from_file():
    with open(TOKEN_FILE, 'r') as f:
        return json.load(f)


def _is_token_valid(access_token):
    jwt_decoded = json.loads(base64.b64decode(access_token.split('.')[1] + '==').decode('utf-8'))
    return jwt_decoded['exp'] > time.time()


def _refresh_tokens(refresh_token):
    token_data = {
        'grant_type': 'refresh_token',
        'client_id': CLIENT_ID,
        'refresh_token': refresh_token,
    }
    response = request_with_retry(TOKEN_URL, None, token_data)
    return response.json()



# ---------------------------
# Main-Logic
# ---------------------------
def main() -> str:
    code_verifier, code_challenge = _generate_code_verifier_and_challenge()

    if os.path.exists(TOKEN_FILE):
        try:
            token_file = _load_tokens_from_file()
            access_token = token_file['access_token']
            refresh_token = token_file['refresh_token']

            if not _is_token_valid(access_token):
                print("> Access token is not valid anymore. Refreshing tokens...")
                token_response = _refresh_tokens(refresh_token)
                access_token = token_response['access_token']
                # refresh access token in file
                token_file['access_token'] = access_token
                _save_tokens_to_file(token_file)

        except (json.JSONDecodeError, KeyError) as e:
            print("> Error loading tokens from file. Re-authenticating...")
            token_response = _exchange_code_for_tokens(_get_auth_code(code_challenge), code_verifier)
            access_token = token_response['access_token']
            _save_tokens_to_file(token_response)


    else:
        token_response = _exchange_code_for_tokens(_get_auth_code(code_challenge), code_verifier)
        access_token = token_response['access_token']
        if input("Would you like to save the tokens to a file in the current directory for use in future requests? (y/n): ").lower() == 'y':
            _save_tokens_to_file(token_response)

    return access_token