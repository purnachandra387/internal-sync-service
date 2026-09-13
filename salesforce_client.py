"""
Salesforce API Client
----------------------
Authenticates with Salesforce using the OAuth2 Client Credentials flow
(no browser login needed — good for a server-to-server script) and pulls
records via Salesforce's REST API.

Credentials are read from environment variables (via a local .env file
that is NEVER committed to git) — see .env.example for the required keys.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

SF_CONSUMER_KEY = os.environ.get("SF_CONSUMER_KEY")
SF_CONSUMER_SECRET = os.environ.get("SF_CONSUMER_SECRET")
SF_LOGIN_URL = os.environ.get("SF_LOGIN_URL", "https://login.salesforce.com")

API_VERSION = "v60.0"


class SalesforceAuthError(Exception):
    """Raised when Salesforce authentication fails (bad/missing credentials)."""
    pass


class SalesforceAPIError(Exception):
    """Raised when a Salesforce API call fails after successful auth."""
    pass


def get_access_token():
    """
    Authenticate via the OAuth2 Client Credentials flow.
    Returns (access_token, instance_url).
    """
    if not SF_CONSUMER_KEY or not SF_CONSUMER_SECRET:
        raise SalesforceAuthError(
            "Missing SF_CONSUMER_KEY or SF_CONSUMER_SECRET. "
            "Set them in a local .env file (see .env.example)."
        )

    token_url = f"{SF_LOGIN_URL}/services/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": SF_CONSUMER_KEY,
        "client_secret": SF_CONSUMER_SECRET,
    }

    response = requests.post(token_url, data=payload, timeout=10)

    if response.status_code != 200:
        raise SalesforceAuthError(
            f"Salesforce auth failed ({response.status_code}): {response.text}"
        )

    data = response.json()
    return data["access_token"], data["instance_url"]


def fetch_contacts(limit=25):
    """
    Fetch a batch of Contact records from Salesforce via SOQL query
    through the REST API. Returns a list of dicts.
    """
    access_token, instance_url = get_access_token()

    query = f"SELECT Id, Name, Email, Phone, Title, LastModifiedDate FROM Contact LIMIT {limit}"
    query_url = f"{instance_url}/services/data/{API_VERSION}/query"

    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(query_url, headers=headers, params={"q": query}, timeout=10)

    if response.status_code != 200:
        raise SalesforceAPIError(
            f"Salesforce query failed ({response.status_code}): {response.text}"
        )

    return response.json().get("records", [])


def create_contact(first_name, last_name, email=None):
    """
    Create a Contact record in Salesforce. Demonstrates writing data
    back to the vendor system, not just reading it.
    """
    access_token, instance_url = get_access_token()

    url = f"{instance_url}/services/data/{API_VERSION}/sobjects/Contact/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {"FirstName": first_name, "LastName": last_name}
    if email:
        body["Email"] = email

    response = requests.post(url, headers=headers, json=body, timeout=10)

    if response.status_code != 201:
        raise SalesforceAPIError(
            f"Salesforce create failed ({response.status_code}): {response.text}"
        )

    return response.json()
