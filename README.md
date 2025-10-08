# <img src="https://raw.githubusercontent.com/john-holt4/Gateway-Gaurdian/refs/heads/main/logo/logo.png" width="32" alt="Logo"> Gateway Guardian

[![Version](https://img.shields.io/badge/version-1.0--alpha1-blue)](https://github.com/john-holt4/Gateway-Gaurdian)
[![Python Version](https://img.shields.io/badge/python-3.x-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/john-holt4/Gateway-Gaurdian)](https://github.com/john-holt4/Gateway-Gaurdian/issues)
[![GitHub forks](https://img.shields.io/github/forks/john-holt4/Gateway-Gaurdian?style=social)](https://github.com/john-holt4/Gateway-Gaurdian/network)
[![GitHub stars](https://img.shields.io/github/stars/john-holt4/Gateway-Gaurdian?style=social)](https://github.com/john-holt4/Gateway-Gaurdian/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/john-holt4/Gateway-Gaurdian)](https://github.com/john-holt4/Gateway-Gaurdian/commits/main)

**Effortlessly manage Cloudflare Gateway adblock lists & rules.**

Gateway Guardian is a desktop app to easily apply and manage adblock lists (from files or URLs) within your Cloudflare Zero Trust Gateway configuration.

---

## ✨ Key Features

* **Simple GUI:** Easy-to-use interface built with `wxPython`.
* **Load Sources:** Import lists from local files (`.txt`) or directly via URL.
* **Smart Parsing:** Understands various adblock list formats (hosts, AdBlock syntax, plain domains, etc.).
* **Auto-Splitting:** Automatically splits large domain lists to fit Cloudflare's limits (1000 domains/list).
* **Cloudflare Integration:** Creates/Updates/Deletes Gateway Lists & Rules via the API.
* **Refresh & Update:** Fetches current Cloudflare config and checks for updates for URL-based rules.
* **Direct Editing:** Modify managed lists and rules from within the app.
* **Clean Deletion:** Option to remove rules and their associated lists together.
* **User Feedback:** Clear progress indication, cancellation support, and detailed logging.
* **Metadata Tracking:** Stores source info (URL, prefix, hash) in rule descriptions for easy updates.

---

## 📸 Screenshots

* *Main Window*
<img src="https://github.com/john-holt4/Gateway-Gaurdian/blob/main/screenshots/main.png" alt="Main Window Rules">
<img src="https://github.com/john-holt4/Gateway-Gaurdian/blob/main/screenshots/main1.png" alt="Main Window Lists">

* *Edit Window*
<img src="https://github.com/john-holt4/Gateway-Gaurdian/blob/main/screenshots/edit.png" alt="Edit Window">

* *Login Window*
<img src="https://github.com/john-holt4/Gateway-Gaurdian/blob/main/screenshots/login.png" alt="Main Window">

---

## 🚀 Getting Started

### Prerequisites

* Python 3.x
* A Cloudflare Account with Zero Trust configured.
* Your Cloudflare **Account ID** and an **API Token**.

<details>
<summary><strong>How to find your Cloudflare Account ID & create an API Token</strong> (Click to expand)</summary>

**Finding Your Account ID:**

1.  Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2.  Select any domain or stay on the account home page.
3.  Your **Account ID** is typically on the right sidebar or main Overview page.
4.  It's also in the dashboard URL: `https://dash.cloudflare.com/ACCOUNT_ID/...`
5.  Copy this long hexadecimal string.

**Creating the API Token:**

This application needs permissions to read and edit Gateway Lists and Rules.

1.  In the Cloudflare Dashboard, go to **My Profile** > **API Tokens**.
2.  Click **Create Token**.
3.  **Option 1 (Easier):** Use the **"Edit Cloudflare Zero Trust"** template.
    * Click **Use template**.
    * Verify **Account Resources** is set to your desired account.
    * Click **Continue to summary** -> **Create Token**.
4.  **Option 2 (More Specific):** Use a **Custom Token**.
    * Click **Get started**.
    * Name: `GatewayGuardianAppToken` (or similar).
    * Permissions: Select `Account` | `Zero Trust` | `Edit`.
    * Account Resources: Select your specific account.
    * Click **Continue to summary** -> **Create Token**.
5.  **VERY IMPORTANT:** Cloudflare will show the token **once**. Copy it immediately and store it securely (e.g., password manager). This is the token for the app login.

</details>

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/john-holt4/Gateway-Gaurdian.git
cd Gateway-Gaurdian

# 2. Install dependencies
pip install -r requirements.txt
```

### Running the App

```bash
python gateway_guardian.py
```

* Log in using your Cloudflare **Account ID** and **API Token** when prompted.

---

## ⚡ Quick Guide

1.  **Load:** Use `Load File` or `Load URL` to choose your adblock list.
2.  **Name:** Enter a unique `List Prefix` and `Rule Name`.
3.  **Apply:** Click `Apply Config`. The app creates the necessary lists and rule on Cloudflare.

**Other Actions:**

* `Refresh`: Fetches your latest Cloudflare Gateway config.
* `Edit Item`: Modifies a selected list (domains) or rule (name, enabled, description).
* `Update Rule`: Updates a selected rule (and its lists) from its original URL source.
* `Delete Rule`: Removes selected rule(s) and prompts to optionally remove associated lists.
* `Cancel`: Stops the current background task (if possible).

---

## 🤔 How it Works (Briefly)

Gateway Guardian connects to the Cloudflare API, parses your adblock list (handling various formats), splits it into 1000-domain chunks, creates numbered Gateway Lists using your prefix, and finally creates a Gateway Rule linking them all. For URL-based rules, it cleverly stores the source URL, prefix, and a content hash (size) in the rule's description, enabling the update feature.

---

## ⚠️ Limitations

* Subject to Cloudflare API rate limits and account limits (e.g., max 300 lists).
* The update check is basic (based on content size only).
* This is an alpha version – use with care and expect potential bugs.

---

## 🛠️ Community Tools

* [Bulk Delete Gateway Lists by Prefix](https://github.com/TantalusDrive/Gateway-Gaurdian/blob/main/Scripts/Delete_lists_by_prefix.py) – A script to remove orphaned or leftover Gateway lists when manual cleanup fails or is interrupted. Useful after partially deleted DNS rules.
> Created by [TantalusDrive](https://github.com/TantalusDrive) for community use.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/john-holt4/Gateway-Gaurdian/issues).

---

## 📜 License

This project is licensed under the MIT License - see the `LICENSE` file for details.

---

## 🙏 Support

If you find Gateway Guardian useful, consider supporting its development:

[![Donate via PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif)](https://www.paypal.com/donate/?business=243S6YP5USR38&no_recurring=0&item_name=Support+the+development+of+Gateway+Gaurdian&currency_code=USD)
