###################################################################################################################################################
#  This script helps clean up orphaned or unused Gateway lists in Cloudflare Zero Trust when manual deletion fails or mass removal is needed.     #
#  It safely deletes lists matching a given prefix only if not referenced in active DNS policies, preventing accidental removal of in-use rules.  #
###################################################################################################################################################
# Created by TantalusDrive (https://github.com/TantalusDrive) – Feel free to use and share!
# No official affiliation with Cloudflare or Gateway Gaurdian.
# Licensed under the MIT License (see LICENSE for details)



import requests

# Configuration
print("Enter Cloudflare data:")
ACCOUNT_ID = input("Account ID: ").strip()
API_TOKEN = input("API Token: ").strip()
PREFIX = input("Prefix of lists (list names) to delete: ").strip()

# Headers
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

# Correct endpoint for Zero Trust lists
url_lists = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/gateway/lists"
url_rules = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/gateway/rules"

# Check active Gateway rules
print("Checking rules in use...")
try:
    rules_response = requests.get(url_rules, headers=headers)
    used_list_names = set()
    if rules_response.status_code == 200:
        try:
            rules = rules_response.json().get("result", [])
            for rule in rules:
                expr = rule.get("filter", {}).get("expression", "")
                for lst_name in [n.strip("$") for n in expr.split() if n.startswith("$")]:
                    used_list_names.add(lst_name)
            print(f"Found references to {len(used_list_names)} lists in rules.")
        except requests.exceptions.JSONDecodeError:
            print("Error: Non-JSON response from rules API.")
    else:
        print(f"Rules API error: {rules_response.status_code}")
        print(f"Details: {rules_response.text}")
except Exception as e:
    print(f"Error fetching rules: {e}")

# Delete lists with pagination
deleted_count = 0
page = 1
per_page = 100

print(f"Searching for lists with prefix '{PREFIX}'...")

while True:
    try:
        params = {"page": page, "per_page": per_page}
        response = requests.get(url_lists, headers=headers, params=params)
        
        print(f"Status: {response.status_code}")
        print(f"Raw response: {response.text}")

        if response.status_code != 200:
            print("API request failed.")
            break

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            print("Error: Non-JSON response from lists API.")
            break

        if "result" not in data:
            print("Error: 'result' field missing.")
            break

        lists = data["result"]
        
        if "result_info" not in data:
            print("Warning: 'result_info' not present. Assuming single page.")
            total_pages = 1
        else:
            total_pages = data["result_info"]["total_pages"]

        for lst in lists:
            if lst["name"].startswith(PREFIX):
                if lst["name"] in used_list_names:
                    print(f"⚠️  Skipped (in use): {lst['name']}")
                    continue
                list_id = lst["id"]
                url_delete = f"{url_lists}/{list_id}"
                delete_response = requests.delete(url_delete, headers=headers)
                try:
                    result = delete_response.json()
                    if result.get("success"):
                        print(f"✅ Deleted: {lst['name']}")
                        deleted_count += 1
                    else:
                        print(f"❌ Error with {lst['name']}: {result.get('errors')}")
                except requests.exceptions.JSONDecodeError:
                    print(f"❌ Error: Non-JSON response after deleting {lst['name']}")

        if page >= total_pages:
            break
        page += 1
    except Exception as e:
        print(f"Error in pagination loop: {e}")
        break

print(f"✅ Deleted {deleted_count} lists with prefix '{PREFIX}'.")
input("Press ENTER to exit...")   
