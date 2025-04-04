import wx
import wx.adv
import wx.html
import wx.lib.mixins.listctrl as listmix
import requests
import os
import threading
import json
import time
import re
import string
import traceback
import io
import datetime
import hashlib
from urllib.parse import urlparse
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False
APP_NAME = "Gateway Guardian"
APP_VERSION = "1.0-alpha1"
API_BASE_URL = "https://api.cloudflare.com/client/v4"
MAX_DOMAINS_PER_LIST = 1000
MAX_LISTS = 300
TOTAL_DOMAIN_LIMIT = MAX_DOMAINS_PER_LIST * MAX_LISTS
LIST_CREATE_DELAY_SECONDS = 0.7
LIST_CREATE_TIMEOUT_SECONDS = 120
GET_ALL_LISTS_TIMEOUT_SECONDS = 90
DELETE_DELAY_SECONDS = 0.7
ID_TOOLBAR_LOAD_FILE = wx.NewIdRef()
ID_TOOLBAR_LOAD_URL = wx.NewIdRef()
ID_TOOLBAR_REFRESH = wx.NewIdRef()
ID_TOOLBAR_APPLY = wx.NewIdRef()
ID_TOOLBAR_EDIT = wx.NewIdRef()
ID_TOOLBAR_UPDATE = wx.NewIdRef()
ID_TOOLBAR_DELETE_RULE_LISTS = wx.NewIdRef()
ID_TOOLBAR_CANCEL = wx.NewIdRef()
ID_TOGGLE_LOG = wx.NewIdRef()
ID_TOGGLE_STATUS_BAR = wx.NewIdRef()
ID_LOAD_FILE = wx.NewIdRef()
ID_LOAD_URL = wx.NewIdRef()
ID_REFRESH = wx.NewIdRef()
ID_APPLY = wx.NewIdRef()
ID_UPDATE_RULE = wx.NewIdRef()
ID_DELETE_RULE_LISTS = wx.NewIdRef()
ID_CANCEL_OPERATION = wx.NewIdRef()
METADATA_MARKER_PREFIX = "[CF_ADBLOCK_MGR_V1:"
METADATA_MARKER_SUFFIX = "]"
METADATA_URL_KEY = "URL="
METADATA_PREFIX_KEY = "PREFIX="
METADATA_HASH_KEY = "HASH="
APP_ICON_URL = "https://raw.githubusercontent.com/john-holt4/Gateway-Gaurdian/refs/heads/main/logo/logo.png"
LOGIN_ICON_URL = "https://raw.githubusercontent.com/john-holt4/Gateway-Gaurdian/refs/heads/main/logo/logo-full.png"
class OperationCancelledError(Exception): pass
class CloudflareAPI:
    def __init__(self, api_token, account_id):
        if not api_token or not account_id: raise ValueError("API Token and Account ID cannot be empty.")
        self.api_token, self.account_id = api_token.strip(), account_id.strip()
        self.headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json", "User-Agent": f"Python-{APP_NAME}/{APP_VERSION} ({os.name})"}
        self.base_url = f"{API_BASE_URL}/accounts/{self.account_id}/gateway"
    def _request(self, method, endpoint, **kwargs):
        url = f"{self.base_url}{endpoint}"
        response = None
        timeout = kwargs.pop('timeout', 45)
        try:
            response = requests.request(method, url, headers=self.headers, timeout=timeout, **kwargs)
            response.raise_for_status()
            if response.status_code == 204 or (response.status_code == 200 and not response.content and method.upper() in ('DELETE', 'PUT', 'PATCH')):
                return {"success": True, "result": None}
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                try:
                    json_response = response.json()
                    is_list_or_rule_endpoint = '/lists' in endpoint or '/rules' in endpoint
                    if json_response.get("success") and json_response.get("result") is None and is_list_or_rule_endpoint:
                        return {"success": True, "result": []}
                    return json_response
                except json.JSONDecodeError:
                    if not response.content:
                        is_list_or_rule_endpoint = '/lists' in endpoint or '/rules' in endpoint
                        return {"success": True, "result": [] if is_list_or_rule_endpoint else None}
                    else:
                        raise ConnectionError(f"API ({method} {endpoint}) Invalid JSON: {response.text[:200]}")
            elif not response.content and response.status_code == 200:
                is_list_or_rule_endpoint = '/lists' in endpoint or '/rules' in endpoint
                return {"success": True, "result": [] if is_list_or_rule_endpoint else None}
            return {"success": True, "result": response.text}
        except requests.exceptions.ReadTimeout as e:
            error_body = response.text if response is not None else "N/A"
            status_code = response.status_code if response is not None else "N/A"
            raise ConnectionError(f"API timed out ({method} {endpoint}) - Status: {status_code} - Error: {e}. Timeout: {timeout}s. Resp: {error_body}") from e
        except requests.exceptions.RequestException as e:
            error_body, status_code = "", "N/A"
            if response is not None:
                status_code = response.status_code
                try: error_body = response.json()
                except json.JSONDecodeError: error_body = response.text
            if response is not None and response.status_code == 429:
                raise ConnectionError(f"API rate limit hit ({method} {endpoint}) - Status: 429 - Error: {e}. Body: {response.text if response else 'N/A'}")
            else:
                raise ConnectionError(f"API request failed ({method} {endpoint}) - Status: {status_code} - Error: {e}. Response: {error_body}") from e
        except json.JSONDecodeError as e:
            response_text = response.text if response is not None else 'N/A'
            status_code = response.status_code if response is not None else "N/A"
            raise ConnectionError(f"API returned invalid JSON ({method} {endpoint}) - Status: {status_code} - Error: {e}. Text: {response_text[:200]}") from e
        except Exception as e:
            raise ConnectionError(f"Unexpected error during API request ({method} {endpoint}): {e}") from e
    def get_lists(self, name_prefix="", timeout=GET_ALL_LISTS_TIMEOUT_SECONDS):
        try:
            response = self._request("GET", "/lists", timeout=timeout)
            if not response or not response.get("success"):
                if response and response.get("success") is True and response.get("result") is None: return []
                raise ConnectionError(f"API call to get lists failed. Response: {response}")
            lists = response.get("result", []) or []
            if name_prefix and isinstance(name_prefix, str):
                return [lst for lst in lists if lst.get("name", "").startswith(name_prefix)]
            return lists
        except Exception as e:
            raise ConnectionError(f"Error getting lists: {e}") from e
    def get_list_details(self, list_id, timeout=30):
        if not list_id: raise ValueError("List ID cannot be empty.")
        return self._request("GET", f"/lists/{list_id}", timeout=timeout)
    def get_list_items(self, list_id, timeout=60):
        if not list_id: raise ValueError("List ID cannot be empty.")
        return self._request("GET", f"/lists/{list_id}/items", timeout=timeout)
    def create_list(self, name, domains, timeout=LIST_CREATE_TIMEOUT_SECONDS):
        if not name: raise ValueError("List name cannot be empty.")
        if not isinstance(domains, list): raise ValueError("Domains must be provided as a list.")
        payload = {"name": name, "description": "Managed by Gateway Guardian", "type": "DOMAIN", "items": [{"value": domain} for domain in domains]}
        return self._request("POST", "/lists", json=payload, timeout=timeout)
    def update_list(self, list_id, name, description, items, timeout=LIST_CREATE_TIMEOUT_SECONDS):
        if not list_id: raise ValueError("List ID cannot be empty.")
        if not name: raise ValueError("List name cannot be empty.")
        if not isinstance(items, list): raise ValueError("Items must be a list.")
        payload = {"name": name, "description": description, "items": [{"value": item} for item in items]}
        return self._request("PUT", f"/lists/{list_id}", json=payload, timeout=timeout)
    def patch_list(self, list_id, name=None, description=None, timeout=30):
        if not list_id: raise ValueError("List ID cannot be empty.")
        payload = {}
        if name is not None: payload["name"] = name
        if description is not None: payload["description"] = description
        if not payload: raise ValueError("Nothing to patch (name or description must be provided).")
        return self._request("PATCH", f"/lists/{list_id}", json=payload, timeout=timeout)
    def delete_list(self, list_id):
        if not list_id: raise ValueError("List ID cannot be empty.")
        return self._request("DELETE", f"/lists/{list_id}")
    def get_rules(self, rule_name="", timeout=60):
        try:
            response = self._request("GET", "/rules", timeout=timeout)
            if not response or not response.get("success"):
                if response and response.get("success") is True and response.get("result") is None: return []
                raise ConnectionError(f"API call to get rules failed. Response: {response}")
            rules = response.get("result", []) or []
            if rule_name and isinstance(rule_name, str):
                return [rule for rule in rules if rule.get("name") == rule_name]
            return rules
        except Exception as e:
            raise ConnectionError(f"Error getting rules: {e}") from e
    def get_rule_details(self, rule_id, timeout=30):
        if not rule_id: raise ValueError("Rule ID cannot be empty.")
        try:
            return self._request("GET", f"/rules/{rule_id}", timeout=timeout)
        except Exception as e:
            raise ConnectionError(f"Error getting details for rule {rule_id}: {e}") from e
    def create_rule(self, name, list_ids, id_map, description="Managed by Gateway Guardian", action="block", enabled=True, filters=None, source_url=None, list_prefix=None, content_hash=None):
        if not name: raise ValueError("Rule name cannot be empty.")
        if not list_ids or not isinstance(list_ids, list): raise ValueError("Invalid list_ids provided.")
        if id_map is None: raise ValueError("ID map cannot be None for rule creation.")
        
        # ALWAYS start completely fresh with a clean description
        # We never want to inherit metadata or hash values from an existing description
        base_description = "Managed by Gateway Guardian"
        
        # Extract base description if provided, ignoring all metadata
        if description and description != base_description and METADATA_MARKER_PREFIX in description:
            start_idx = description.find(METADATA_MARKER_PREFIX)
            if start_idx > 0:
                base_part = description[:start_idx].rstrip()
                if base_part:
                    base_description = base_part
                    print(f"Using base description: {base_description}")
            
            # Only extract URL and prefix if needed and not already provided
            if not source_url or not list_prefix:
                end_idx = description.find(METADATA_MARKER_SUFFIX)
                if end_idx > start_idx:
                    # Extract metadata
                    metadata_content = description[start_idx+len(METADATA_MARKER_PREFIX):end_idx]
                    
                    # Extract URL if needed (handle URLs with colons)
                    if not source_url and METADATA_URL_KEY in metadata_content:
                        metadata_parts = metadata_content.split(':')
                        for i, part in enumerate(metadata_parts):
                            if part.startswith(METADATA_URL_KEY):
                                # Special handling for URLs
                                url_value = part[len(METADATA_URL_KEY):]
                                # If the next part doesn't have a key, it's part of the URL (has a colon)
                                j = i + 1
                                while j < len(metadata_parts) and not any(metadata_parts[j].startswith(key) for key in [METADATA_PREFIX_KEY, METADATA_HASH_KEY]):
                                    url_value += ":" + metadata_parts[j]
                                    j += 1
                                source_url = url_value
                                print(f"Extracted URL: {source_url}")
                                break
                    
                    # Extract prefix if needed
                    if not list_prefix and METADATA_PREFIX_KEY in metadata_content:
                        for part in metadata_content.split(':'):
                            if part.startswith(METADATA_PREFIX_KEY):
                                list_prefix = part[len(METADATA_PREFIX_KEY):]
                                print(f"Extracted prefix: {list_prefix}")
                                break
        
        # Create completely new metadata from scratch - NEVER reuse any old metadata
        final_description = base_description
        if source_url and list_prefix:
            # Start with a completely fresh metadata structure
            metadata_parts = [f"{METADATA_URL_KEY}{source_url}", f"{METADATA_PREFIX_KEY}{list_prefix}"]
            
            # Only add hash if provided
            if content_hash:
                metadata_parts.append(f"{METADATA_HASH_KEY}{content_hash}")
                print(f"Adding new hash: {content_hash}")
            
            # Create completely new metadata
            metadata = f"{METADATA_MARKER_PREFIX}{':'.join(metadata_parts)}{METADATA_MARKER_SUFFIX}"
            print(f"Created fresh metadata: {metadata}")
            
            max_desc_len, max_metadata_len = 500, len(metadata)
            allowed_desc_len = max_desc_len - max_metadata_len - 1
            if allowed_desc_len < 0:
                print(f"Warning: Metadata for rule '{name}' is too long, not embedding.")
            else:
                # Always add space between description and metadata
                final_description = base_description + " " + metadata
                print(f"Final description: {final_description}")
        expression_ids, missing_ids_in_map = [], []
        for list_id in list_ids:
            expression_id = id_map.get(list_id)
            if not expression_id: missing_ids_in_map.append(list_id)
            else: expression_ids.append(expression_id)
        if missing_ids_in_map: raise ValueError(f"Cannot create rule: ID(s) missing in map for list ID(s): {', '.join(missing_ids_in_map)}.")
        if len(expression_ids) != len(list_ids): raise ConnectionError("Internal Error: Mismatch between list IDs and expression IDs.")
        expressions = [f'any(dns.domains[*] in ${expr_id})' for expr_id in expression_ids]
        filter_expression = " or ".join(expressions)
        payload = {"name": name, "description": final_description, "action": action, "enabled": enabled, "filters": filters or ["dns"], "traffic": filter_expression}
        try:
            return self._request("POST", "/rules", json=payload)
        except Exception as e:
            if isinstance(e, ConnectionError) and 'Status: 400' in str(e):
                wx.CallAfter(wx.MessageBox, "Rule creation failed (400 Bad Request).\nLikely cause: Invalid syntax/UUIDs or description too long.", "API Error", wx.OK | wx.ICON_ERROR)
            raise ConnectionError(f"Error creating rule '{name}': {e}") from e
    def patch_rule(self, rule_id, name=None, description=None, enabled=None, timeout=30):
        if not rule_id: raise ValueError("Rule ID cannot be empty.")
        payload = {}
        if name is not None: payload["name"] = name
        
        # If description is provided, ensure it has consistent metadata formatting
        if description is not None:
            # Just use the description as provided - don't try to clean it
            # This ensures any HASH values added by the update process remain intact
            payload["description"] = description
            
        if enabled is not None: payload["enabled"] = enabled
        if not payload: raise ValueError("Nothing to patch (name, description, or enabled must be provided).")
        return self._request("PATCH", f"/rules/{rule_id}", json=payload, timeout=timeout)
    def delete_rule(self, rule_id):
        if not rule_id: raise ValueError("Rule ID cannot be empty.")
        return self._request("DELETE", f"/rules/{rule_id}")
class LoginDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Cloudflare Zero Trust Login", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.account_id, self.api_token = "", ""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        login_bitmap = self._load_bitmap_from_url(LOGIN_ICON_URL, 64)
        app_icon_bitmap = self._load_bitmap_from_url(APP_ICON_URL)
        if login_bitmap:
            icon_ctrl = wx.StaticBitmap(panel, wx.ID_ANY, login_bitmap)
            main_sizer.Add(icon_ctrl, 0, wx.ALIGN_CENTER | wx.TOP | wx.LEFT | wx.RIGHT, 15)
        else: main_sizer.AddSpacer(15)
        if app_icon_bitmap:
            try:
                dlg_icon = wx.Icon(); dlg_icon.CopyFromBitmap(app_icon_bitmap); self.SetIcon(dlg_icon)
            except Exception as icon_err: print(f"Error setting dialog icon: {icon_err}")
        grid_sizer = wx.FlexGridSizer(rows=2, cols=2, vgap=10, hgap=10)
        grid_sizer.AddGrowableCol(1, 1)
        lbl_account_id = wx.StaticText(panel, label="Account ID:")
        self.txt_account_id = wx.TextCtrl(panel)
        lbl_api_token = wx.StaticText(panel, label="API Token:")
        self.txt_api_token = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        grid_sizer.Add(lbl_account_id, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        grid_sizer.Add(self.txt_account_id, 1, wx.EXPAND)
        grid_sizer.Add(lbl_api_token, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        grid_sizer.Add(self.txt_api_token, 1, wx.EXPAND)
        main_sizer.Add(grid_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 20)
        main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 15)
        main_sizer.AddSpacer(5)
        btn_sizer = wx.StdDialogButtonSizer()
        login_btn = wx.Button(panel, wx.ID_OK, "Login")
        login_btn.SetDefault()
        btn_sizer.AddButton(login_btn)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 10)
        panel.SetSizer(main_sizer)
        self.Fit()
        self.SetMinSize(wx.Size(400, 280))
        self.CenterOnScreen()
        self.Bind(wx.EVT_BUTTON, self.OnLogin, id=wx.ID_OK)
    def _load_bitmap_from_url(self, icon_url, target_h=None):
        try:
            response = requests.get(icon_url, timeout=10)
            response.raise_for_status()
            image_data = io.BytesIO(response.content)
            image = wx.Image(image_data)
            if image.IsOk():
                if target_h:
                    W, H = image.GetWidth(), image.GetHeight()
                    if H > target_h:
                        new_w = int(W * target_h / H)
                        image.Rescale(new_w, target_h, wx.IMAGE_QUALITY_HIGH)
                return image.ConvertToBitmap()
            else:
                print(f"Error: Failed to load image data into wx.Image from {icon_url}.")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching icon from {icon_url}: {e}")
            return None
        except Exception as e:
            print(f"Error processing icon from {icon_url}: {e}")
            return None
    def OnLogin(self, event):
        acc_id, token = self.txt_account_id.GetValue().strip(), self.txt_api_token.GetValue().strip()
        if not acc_id or not token:
            wx.MessageBox("Please enter both Account ID and API Token.", "Input Required", wx.OK | wx.ICON_WARNING, self)
            return
        cursor = wx.BusyCursor()
        try:
            temp_api = CloudflareAPI(token, acc_id)
            test_response = temp_api._request("GET", "/lists", params={"per_page": 1}, timeout=15)
            if test_response and test_response.get("success"):
                self.account_id, self.api_token = acc_id, token
                self.EndModal(wx.ID_OK)
            else:
                wx.MessageBox("Login Failed: Invalid API response or credentials.", "Login Failed", wx.OK | wx.ICON_ERROR, self)
        except ConnectionError as e:
            err_msg = f"Login Failed: Connection error.\nCould not reach Cloudflare API.\nError: {e}"
            title = "Connection Error"
            if "Status: 401" in str(e) or "Status: 403" in str(e):
                err_msg, title = "Login Failed: Invalid Credentials.\nPlease check your Account ID and API Token.", "Authentication Error"
            elif "timed out" in str(e):
                err_msg, title = f"Login Failed: Connection timed out.\nPlease check your network connection.\nError: {e}", "Timeout Error"
            wx.MessageBox(err_msg, title, wx.OK | wx.ICON_ERROR, self)
        except Exception as e:
            wx.MessageBox(f"An unexpected error occurred during login:\n{e}", "Login Error", wx.OK | wx.ICON_ERROR, self)
            traceback.print_exc()
        finally:
            if 'cursor' in locals() and cursor: del cursor
class SortableListCtrl(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin, listmix.ColumnSorterMixin):
    def __init__(self, parent, id=wx.ID_ANY, *args, **kw):
        wx.ListCtrl.__init__(self, parent, id, *args, **kw)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.itemDataMap = {}
    def InitializeColumnSorter(self, numColumns):
        try: listmix.ColumnSorterMixin.__init__(self, numColumns)
        except Exception as e: print(f"Error initializing column sorter: {e}"); traceback.print_exc()
    def GetListCtrl(self): return self
    def SetItemDataMap(self, itemDataMap): self.itemDataMap = itemDataMap
    def GetItemDataMap(self): return self.itemDataMap
    def GetSortImages(self): return (-1, -1)
class ListEditDialog(wx.Dialog):
    def __init__(self, parent, api_client, list_id, list_name):
        super().__init__(parent, title=f"Edit List: {list_name}", size=(600, 500), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.main_frame = parent
        self.api_client = api_client
        self.list_id = list_id
        self.original_name = list_name
        self.original_description = ""
        self.original_domains = []
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lbl_id = wx.StaticText(panel, label="ID:")
        txt_id = wx.TextCtrl(panel, value=self.list_id, style=wx.TE_READONLY)
        txt_id.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        lbl_name = wx.StaticText(panel, label="Name:")
        self.txt_name = wx.TextCtrl(panel, value=self.original_name)
        info_sizer.Add(lbl_id, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        info_sizer.Add(txt_id, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        info_sizer.Add(lbl_name, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        info_sizer.Add(self.txt_name, 2, wx.EXPAND)
        main_sizer.Add(info_sizer, 0, wx.EXPAND | wx.ALL, 10)
        lbl_domains = wx.StaticText(panel, label="Domains (one per line):")
        main_sizer.Add(lbl_domains, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.txt_domains = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.HSCROLL)
        main_sizer.Add(self.txt_domains, 1, wx.EXPAND | wx.ALL, 10)
        btn_sizer = wx.StdDialogButtonSizer()
        self.save_btn = wx.Button(panel, wx.ID_SAVE)
        self.save_btn.SetDefault()
        btn_sizer.AddButton(self.save_btn)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        panel.SetSizer(main_sizer)
        self.Bind(wx.EVT_BUTTON, self.OnSave, id=wx.ID_SAVE)
        self.Bind(wx.EVT_INIT_DIALOG, self.OnInit)
        self.CenterOnParent()
    def OnInit(self, event):
        self.save_btn.Disable()
        wx.CallAfter(self.LoadListData)
        event.Skip()
    def LoadListData(self):
        busy_cursor = wx.BusyCursor()
        gauge = self.main_frame.progress_gauge
        op_event = self.main_frame.operation_cancelled
        wx.CallAfter(gauge.SetRange, 2)
        wx.CallAfter(gauge.SetValue, 0)
        wx.CallAfter(gauge.Show)
        wx.CallAfter(self.main_frame.custom_status_bar.Layout)
        wx.CallAfter(self.main_frame.UpdateStatusBar, "Loading List Data...")
        wx.CallAfter(self.main_frame.EnableCancelButton, True)
        thread = threading.Thread(target=self._LoadListDataWorker, args=(gauge, op_event))
        thread.start()
    def _LoadListDataWorker(self, gauge, op_event):
        details_ok, items_ok = False, False
        error_msg = ""
        list_details, list_items_resp = None, None
        try:
            wx.CallAfter(gauge.SetValue, 0); wx.CallAfter(self.main_frame.UpdateStatusBar, "Fetching list details...")
            self.main_frame._check_cancel_request(op_event)
            list_details_resp = self.api_client.get_list_details(self.list_id)
            if not list_details_resp or not list_details_resp.get("success"):
                error_msg = f"Failed to fetch list details: {list_details_resp}"
            else:
                list_details = list_details_resp.get("result")
                if list_details:
                    self.original_description = list_details.get("description", "")
                    details_ok = True
                else: error_msg = "Failed to parse list details from API response."
            if details_ok:
                wx.CallAfter(gauge.SetValue, 1); wx.CallAfter(self.main_frame.UpdateStatusBar, "Fetching list items...")
                self.main_frame._check_cancel_request(op_event)
                list_items_resp = self.api_client.get_list_items(self.list_id)
                if not list_items_resp or not list_items_resp.get("success"):
                    error_msg = f"Failed to fetch list items: {list_items_resp}"
                else:
                    items_data = list_items_resp.get("result", [])
                    self.original_domains = sorted([item.get("value") for item in items_data if item.get("value")])
                    items_ok = True
                    wx.CallAfter(gauge.SetValue, 2)
        except OperationCancelledError:
             wx.CallAfter(self.main_frame.LogMessage, "List data loading cancelled.", "orange")
             wx.CallAfter(self.EndModal, wx.ID_CANCEL)
             return
        except Exception as e:
            error_msg = f"An error occurred while loading list data:\n{e}"
            traceback.print_exc()
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.main_frame.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.main_frame.EnableCancelButton, False)
            wx.CallAfter(self.main_frame.UpdateStatusBar, "Ready")
            if details_ok and items_ok:
                wx.CallAfter(self.txt_domains.SetValue, "\n".join(self.original_domains))
                wx.CallAfter(self.save_btn.Enable)
            elif not op_event.is_set():
                wx.CallAfter(wx.MessageBox, f"Error loading list data:\n{error_msg}", "Error", wx.OK | wx.ICON_ERROR, self)
                wx.CallAfter(self.EndModal, wx.ID_CANCEL)
            if 'busy_cursor' in locals(): del busy_cursor
    def OnSave(self, event):
        new_name = self.txt_name.GetValue().strip()
        if not new_name:
            wx.MessageBox("List name cannot be empty.", "Validation Error", wx.OK | wx.ICON_WARNING, self)
            self.txt_name.SetFocus()
            return
        new_domains_text = self.txt_domains.GetValue()
        new_domains_list = sorted(list(set(line.strip() for line in new_domains_text.splitlines() if line.strip())))
        if len(new_domains_list) > MAX_DOMAINS_PER_LIST:
            wx.MessageBox(f"Error: Number of domains ({len(new_domains_list)}) exceeds the maximum limit of {MAX_DOMAINS_PER_LIST} per list.", "Limit Exceeded", wx.OK | wx.ICON_ERROR, self)
            return
        name_changed = (new_name != self.original_name)
        domains_changed = (new_domains_list != self.original_domains)
        if not name_changed and not domains_changed:
            self.EndModal(wx.ID_CANCEL)
            return
        busy_cursor = wx.BusyCursor()
        self.save_btn.Disable()
        gauge = self.main_frame.progress_gauge
        op_event = self.main_frame.operation_cancelled
        wx.CallAfter(gauge.SetRange, 1)
        wx.CallAfter(gauge.SetValue, 0)
        wx.CallAfter(gauge.Show)
        wx.CallAfter(self.main_frame.custom_status_bar.Layout)
        wx.CallAfter(self.main_frame.UpdateStatusBar, "Saving List...")
        wx.CallAfter(self.main_frame.EnableCancelButton, True)
        thread = threading.Thread(target=self._SaveListDataWorker, args=(new_name, new_domains_list, name_changed, domains_changed, gauge, op_event))
        thread.start()
    def _SaveListDataWorker(self, new_name, new_domains_list, name_changed, domains_changed, gauge, op_event):
        success = False
        error_msg = ""
        try:
            self.main_frame._check_cancel_request(op_event)
            if domains_changed:
                wx.CallAfter(self.main_frame.UpdateStatusBar, f"Updating list '{new_name}' (PUT)...")
                response = self.api_client.update_list(self.list_id, new_name, self.original_description, new_domains_list)
            elif name_changed:
                wx.CallAfter(self.main_frame.UpdateStatusBar, f"Renaming list to '{new_name}' (PATCH)...")
                response = self.api_client.patch_list(self.list_id, name=new_name)
            else:
                 response = {"success": True}
            self.main_frame._check_cancel_request(op_event)
            wx.CallAfter(gauge.SetValue, 1)
            if response and response.get("success"):
                success = True
            else:
                error_msg = f"API call failed: {response}"
        except OperationCancelledError:
             wx.CallAfter(self.main_frame.LogMessage, "List saving cancelled.", "orange")
             success = False
        except Exception as e:
            error_msg = f"An error occurred while saving:\n{e}"
            traceback.print_exc()
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.main_frame.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.main_frame.EnableCancelButton, False)
            wx.CallAfter(self.main_frame.UpdateStatusBar, "Ready")
            wx.CallAfter(self.save_btn.Enable)
            if 'busy_cursor' in locals(): del busy_cursor
            if success:
                wx.CallAfter(self.EndModal, wx.ID_OK)
            elif not op_event.is_set():
                wx.CallAfter(wx.MessageBox, f"Failed to save list:\n{error_msg}", "Error", wx.OK | wx.ICON_ERROR, self)
class RuleEditDialog(wx.Dialog):
    def __init__(self, parent, api_client, rule_id, rule_name, rule_enabled, rule_description):
        super().__init__(parent, title=f"Edit Rule: {rule_name}", size=(500, 400), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.main_frame = parent
        self.api_client = api_client
        self.rule_id = rule_id
        self.original_name = rule_name
        self.original_enabled = rule_enabled
        self.original_description = rule_description
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        grid_sizer = wx.FlexGridSizer(rows=4, cols=2, vgap=10, hgap=10)
        grid_sizer.AddGrowableCol(1, 1)
        grid_sizer.AddGrowableRow(3, 1)
        lbl_id = wx.StaticText(panel, label="ID:")
        txt_id = wx.TextCtrl(panel, value=self.rule_id, style=wx.TE_READONLY)
        txt_id.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        lbl_name = wx.StaticText(panel, label="Name:")
        self.txt_name = wx.TextCtrl(panel, value=self.original_name)
        lbl_enabled = wx.StaticText(panel, label="Enabled:")
        self.chk_enabled = wx.CheckBox(panel)
        self.chk_enabled.SetValue(self.original_enabled)
        lbl_desc = wx.StaticText(panel, label="Description:")
        self.txt_desc = wx.TextCtrl(panel, value=self.original_description, style=wx.TE_MULTILINE)
        grid_sizer.Add(lbl_id, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        grid_sizer.Add(txt_id, 1, wx.EXPAND)
        grid_sizer.Add(lbl_name, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        grid_sizer.Add(self.txt_name, 1, wx.EXPAND)
        enabled_sizer = wx.BoxSizer(wx.HORIZONTAL)
        enabled_sizer.Add(self.chk_enabled, 0, wx.ALIGN_CENTER_VERTICAL)
        grid_sizer.Add(lbl_enabled, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        grid_sizer.Add(enabled_sizer, 0)
        grid_sizer.Add(lbl_desc, 0, wx.ALIGN_TOP | wx.ALIGN_RIGHT | wx.TOP, 5)
        grid_sizer.Add(self.txt_desc, 1, wx.EXPAND | wx.ALL, 0)
        main_sizer.Add(grid_sizer, 1, wx.EXPAND | wx.ALL, 10)
        btn_sizer = wx.StdDialogButtonSizer()
        self.save_btn = wx.Button(panel, wx.ID_SAVE)
        self.save_btn.SetDefault()
        btn_sizer.AddButton(self.save_btn)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        panel.SetSizer(main_sizer)
        self.Bind(wx.EVT_BUTTON, self.OnSave, id=wx.ID_SAVE)
        self.CenterOnParent()
    def OnSave(self, event):
        new_name = self.txt_name.GetValue().strip()
        new_enabled = self.chk_enabled.GetValue()
        new_description = self.txt_desc.GetValue()
        if not new_name:
            wx.MessageBox("Rule name cannot be empty.", "Validation Error", wx.OK | wx.ICON_WARNING, self)
            self.txt_name.SetFocus()
            return
        name_changed = (new_name != self.original_name)
        enabled_changed = (new_enabled != self.original_enabled)
        desc_changed = (new_description != self.original_description)
        if not name_changed and not enabled_changed and not desc_changed:
            self.EndModal(wx.ID_CANCEL)
            return
        payload = {}
        if name_changed: payload["name"] = new_name
        if enabled_changed: payload["enabled"] = new_enabled
        if desc_changed: payload["description"] = new_description
        busy_cursor = wx.BusyCursor()
        self.save_btn.Disable()
        gauge = self.main_frame.progress_gauge
        op_event = self.main_frame.operation_cancelled
        wx.CallAfter(gauge.Pulse)
        wx.CallAfter(gauge.Show)
        wx.CallAfter(self.main_frame.custom_status_bar.Layout)
        wx.CallAfter(self.main_frame.UpdateStatusBar, "Saving Rule...")
        wx.CallAfter(self.main_frame.EnableCancelButton, True)
        thread = threading.Thread(target=self._SaveRuleDataWorker, args=(payload, gauge, op_event))
        thread.start()
    def _SaveRuleDataWorker(self, payload, gauge, op_event):
        success = False
        error_msg = ""
        try:
            self.main_frame._check_cancel_request(op_event)
            response = self.api_client.patch_rule(self.rule_id, **payload)
            self.main_frame._check_cancel_request(op_event)
            if response and response.get("success"):
                success = True
            else:
                error_msg = f"API call failed: {response}"
        except OperationCancelledError:
             wx.CallAfter(self.main_frame.LogMessage, "Rule saving cancelled.", "orange")
             success = False
        except Exception as e:
            error_msg = f"An error occurred while saving:\n{e}"
            traceback.print_exc()
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.main_frame.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.main_frame.EnableCancelButton, False)
            wx.CallAfter(self.main_frame.UpdateStatusBar, "Ready")
            wx.CallAfter(self.save_btn.Enable)
            if 'busy_cursor' in locals(): del busy_cursor
            if success:
                wx.CallAfter(self.EndModal, wx.ID_OK)
            elif not op_event.is_set():
                wx.CallAfter(wx.MessageBox, f"Failed to save rule:\n{error_msg}", "Error", wx.OK | wx.ICON_ERROR, self)
class MainFrame(wx.Frame):
    def __init__(self, parent, account_id, api_token):
        super().__init__(parent, title=f"{APP_NAME} v{APP_VERSION}", size=(940, 550))
        self.account_id, self.api_token = account_id, api_token
        self.api_client = None
        try: self.api_client = CloudflareAPI(self.api_token, self.account_id)
        except Exception as e: wx.MessageBox(f"Failed to initialize Cloudflare API client:\n{e}", "Initialization Error", wx.OK | wx.ICON_ERROR, self); self.Close(); return
        icon = self._load_app_icon(); self.SetIcon(icon) if icon else None
        self.adblock_filepath, self.adblock_url = None, None
        self.txt_list_prefix, self.txt_rule_name = None, None
        self.list_ctrl_lists, self.list_ctrl_rules = None, None
        self.log_ctrl = None
        self.log_menu_item = None
        self.status_bar_menu_item = None
        self.notebook = None
        self.splitter = None
        self.main_panel, self.bottom_panel = None, None
        self.lbl_source_display = None
        self.custom_status_bar = None
        self.status_text = None
        self.progress_gauge = None
        self.log_visible = False
        self.status_bar_visible = True
        self.operation_cancelled = threading.Event()
        self.list_item_data_lists, self.list_item_data_rules = {}, {}
        self.toolbar_apply_item = None
        self.InitUI()
        self.InitMenu()
        self._update_log_visibility()
        self._update_status_bar_visibility()
        self._update_management_button_states()
        self.Center(); self.Show()
        wx.CallAfter(self.OnRefresh)
    def _load_app_icon(self):
        try:
            response = requests.get(APP_ICON_URL, timeout=10)
            response.raise_for_status()
            image_data = io.BytesIO(response.content)
            image = wx.Image(image_data)
            if image.IsOk():
                bitmap = image.ConvertToBitmap(); icon = wx.Icon(); icon.CopyFromBitmap(bitmap); return icon
            else: print("Error: Failed to load app icon data into wx.Image."); return None
        except requests.exceptions.RequestException as e: print(f"Error fetching app icon: {e}"); return None
        except Exception as e: print(f"Error processing app icon: {e}"); return None
    def InitToolBar(self):
        toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.TB_FLAT | wx.TB_TEXT)
        tsize = (24, 24)
        toolbar.SetToolBitmapSize(tsize)
        load_file_bmp = wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN, wx.ART_TOOLBAR, tsize)
        load_url_bmp = wx.ArtProvider.GetBitmap(wx.ART_NEW_DIR, wx.ART_TOOLBAR, tsize)
        refresh_bmp = wx.ArtProvider.GetBitmap(wx.ART_REDO, wx.ART_TOOLBAR, tsize)
        apply_bmp = wx.ArtProvider.GetBitmap(wx.ART_TICK_MARK, wx.ART_TOOLBAR, tsize)
        edit_bmp = wx.ArtProvider.GetBitmap(wx.ART_EDIT, wx.ART_TOOLBAR, tsize)
        update_bmp = wx.ArtProvider.GetBitmap(wx.ART_EXECUTABLE_FILE, wx.ART_TOOLBAR, tsize)
        delete_lists_bmp = wx.ArtProvider.GetBitmap(wx.ART_DELETE, wx.ART_TOOLBAR, tsize)
        cancel_bmp = wx.ArtProvider.GetBitmap(wx.ART_CROSS_MARK, wx.ART_TOOLBAR, tsize)
        toolbar.AddTool(ID_TOOLBAR_LOAD_FILE, "Load File", load_file_bmp, "Load adblock list from a local file")
        toolbar.AddTool(ID_TOOLBAR_LOAD_URL, "Load URL", load_url_bmp, "Load adblock list from a URL")
        toolbar.AddSeparator()
        toolbar.AddTool(ID_TOOLBAR_REFRESH, "Refresh", refresh_bmp, "Refresh Gateway Lists and Rules")
        toolbar.AddStretchableSpace()
        toolbar.AddTool(ID_TOOLBAR_APPLY, "Apply Config", apply_bmp, "Apply the loaded adblock configuration")
        toolbar.AddTool(ID_TOOLBAR_EDIT, "Edit Item", edit_bmp, "Edit Selected List or Rule")
        toolbar.AddTool(ID_TOOLBAR_UPDATE, "Update Rule", update_bmp, "Update Selected Rule from Source URL")
        toolbar.AddTool(ID_TOOLBAR_DELETE_RULE_LISTS, "Delete Rule", delete_lists_bmp, "Delete Selected Rule(s) and Associated Lists")
        toolbar.AddSeparator()
        toolbar.AddTool(ID_TOOLBAR_CANCEL, "Cancel", cancel_bmp, "Cancel the current background operation")
        toolbar.EnableTool(ID_TOOLBAR_APPLY, False)
        toolbar.EnableTool(ID_TOOLBAR_EDIT, False)
        toolbar.EnableTool(ID_TOOLBAR_UPDATE, False)
        toolbar.EnableTool(ID_TOOLBAR_DELETE_RULE_LISTS, False)
        toolbar.EnableTool(ID_TOOLBAR_CANCEL, False)
        toolbar.Realize()
        self.Bind(wx.EVT_TOOL, self.OnLoadFromFile, id=ID_TOOLBAR_LOAD_FILE)
        self.Bind(wx.EVT_TOOL, self.OnLoadFromURL, id=ID_TOOLBAR_LOAD_URL)
        self.Bind(wx.EVT_TOOL, self.OnRefresh, id=ID_TOOLBAR_REFRESH)
        self.Bind(wx.EVT_TOOL, self.OnApplyAdblock, id=ID_TOOLBAR_APPLY)
        self.Bind(wx.EVT_TOOL, self.OnEditItem, id=ID_TOOLBAR_EDIT)
        self.Bind(wx.EVT_TOOL, self.OnUpdateSelectedRule, id=ID_TOOLBAR_UPDATE)
        self.Bind(wx.EVT_TOOL, self.OnDeleteRuleAndLists, id=ID_TOOLBAR_DELETE_RULE_LISTS)
        self.Bind(wx.EVT_TOOL, self.OnCancelOperation, id=ID_TOOLBAR_CANCEL)
    def InitMenu(self):
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        file_menu.Append(ID_LOAD_FILE, "&Load from File...\tCtrl+O", "Load adblock list from a local file")
        file_menu.Append(ID_LOAD_URL, "Load from &URL...\tCtrl+U", "Load adblock list from a URL")
        file_menu.Append(ID_REFRESH, "&Refresh Lists/Rules\tF5", "Refresh the lists and rules from Cloudflare")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "&Exit\tCtrl+Q", "Exit the application")
        menu_bar.Append(file_menu, "&File")
        edit_menu = wx.Menu()
        edit_menu.Append(ID_TOOLBAR_EDIT, "&Edit Selected Item\tCtrl+E", "Edit the selected list or rule")
        menu_bar.Append(edit_menu, "&Edit")
        actions_menu = wx.Menu()
        actions_menu.Append(ID_APPLY, "&Apply Adblock Configuration\tCtrl+A", "Apply the loaded adblock list and create lists/rule")
        actions_menu.Append(ID_UPDATE_RULE, "Update Selected &Rule from Source\tCtrl+R", "Update the selected rule and its lists from its source URL")
        actions_menu.AppendSeparator()
        actions_menu.Append(ID_DELETE_RULE_LISTS, "Delete R&ule\tCtrl+D", "Delete selected rule(s) and their associated lists")
        actions_menu.AppendSeparator()
        actions_menu.Append(ID_CANCEL_OPERATION, "&Cancel Current Operation\tEsc", "Cancel the ongoing background task")
        menu_bar.Append(actions_menu, "&Actions")
        view_menu = wx.Menu()
        self.log_menu_item = view_menu.AppendCheckItem(ID_TOGGLE_LOG, "Show Status &Log\tCtrl+L", "Show/Hide Status Log")
        self.log_menu_item.Check(self.log_visible)
        menu_bar.Append(view_menu, "&View")
        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, "&About\tF1", f"About {APP_NAME}")
        menu_bar.Append(help_menu, "&Help")
        self.SetMenuBar(menu_bar)
        self.Bind(wx.EVT_MENU, self.OnLoadFromFile, id=ID_LOAD_FILE)
        self.Bind(wx.EVT_MENU, self.OnLoadFromURL, id=ID_LOAD_URL)
        self.Bind(wx.EVT_MENU, self.OnRefresh, id=ID_REFRESH)
        self.Bind(wx.EVT_MENU, self.OnExit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.OnEditItem, id=ID_TOOLBAR_EDIT)
        self.Bind(wx.EVT_MENU, self.OnApplyAdblock, id=ID_APPLY)
        self.Bind(wx.EVT_MENU, self.OnUpdateSelectedRule, id=ID_UPDATE_RULE)
        self.Bind(wx.EVT_MENU, self.OnDeleteRuleAndLists, id=ID_DELETE_RULE_LISTS)
        self.Bind(wx.EVT_MENU, self.OnCancelOperation, id=ID_CANCEL_OPERATION)
        self.Bind(wx.EVT_MENU, self.OnToggleLog, id=ID_TOGGLE_LOG)
        self.Bind(wx.EVT_MENU, self.OnAbout, id=wx.ID_ABOUT)
        menu_bar.Enable(ID_CANCEL_OPERATION, False)
    def InitUI(self):
        self.InitToolBar()
        base_panel = wx.Panel(self)
        outer_sizer = wx.BoxSizer(wx.VERTICAL)
        self.splitter = wx.SplitterWindow(base_panel, style=wx.SP_LIVE_UPDATE | wx.SP_BORDER | wx.SP_3DSASH)
        self.splitter.SetSashGravity(0.8)
        self.splitter.SetMinimumPaneSize(150)
        self.main_panel = self._CreateMainPanel(self.splitter)
        self.bottom_panel = self._CreateBottomPanel(self.splitter)
        self.splitter.SplitHorizontally(self.main_panel, self.bottom_panel)
        outer_sizer.Add(self.splitter, 1, wx.EXPAND | wx.ALL, 0)
        self.custom_status_bar = wx.Panel(base_panel, style=wx.BORDER_SUNKEN)
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.status_text = wx.StaticText(self.custom_status_bar, label="Ready", style=wx.ST_ELLIPSIZE_END)
        self.progress_gauge = wx.Gauge(self.custom_status_bar, range=100, size=(150, 15), style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        self.progress_gauge.Hide()
        status_sizer.Add(self.status_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
        status_sizer.Add(self.progress_gauge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.custom_status_bar.SetSizer(status_sizer)
        outer_sizer.Add(self.custom_status_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)
        base_panel.SetSizer(outer_sizer)
        self.Layout()
        self.LogMessage(f"Application UI Initialized ({APP_NAME} v{APP_VERSION}).")
    def _CreateMainPanel(self, parent):
        panel = wx.Panel(parent, style=wx.BORDER_NONE)
        sizer = wx.BoxSizer(wx.VERTICAL)
        config_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_source_display = wx.StaticText(panel, label="Source: None", style=wx.ST_ELLIPSIZE_END)
        lbl_list_prefix = wx.StaticText(panel, label="List Prefix:")
        self.txt_list_prefix = wx.TextCtrl(panel, value="", size=(180,-1))
        lbl_rule_name = wx.StaticText(panel, label="Rule Name:")
        self.txt_rule_name = wx.TextCtrl(panel, value="", size=(180,-1))
        self.txt_list_prefix.Bind(wx.EVT_TEXT, self.OnNamingOptionsChanged)
        self.txt_rule_name.Bind(wx.EVT_TEXT, self.OnNamingOptionsChanged)
        config_sizer.Add(self.lbl_source_display, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)
        config_sizer.Add(lbl_list_prefix, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        config_sizer.Add(self.txt_list_prefix, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
        config_sizer.Add(lbl_rule_name, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        config_sizer.Add(self.txt_rule_name, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(config_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 10)
        self.notebook = wx.Notebook(panel, style=wx.BK_DEFAULT)
        rule_panel = self._CreateRulesPanel(self.notebook)
        list_panel = self._CreateListsPanel(self.notebook)
        self.notebook.AddPage(rule_panel, " Gateway Rules ")
        self.notebook.AddPage(list_panel, " Gateway Lists ")
        sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)
        return panel
    def _CreateListsPanel(self, parent_notebook):
        panel = wx.Panel(parent_notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        list_style = wx.LC_REPORT | wx.LC_VRULES | wx.BORDER_SUNKEN | wx.LC_SORT_ASCENDING | wx.LC_SINGLE_SEL
        self.list_ctrl_lists = SortableListCtrl(panel, style=list_style)
        self.list_ctrl_lists.InsertColumn(0, "Name", width=350)
        self.list_ctrl_lists.InsertColumn(1, "ID", width=300)
        self.list_ctrl_lists.InsertColumn(2, "Item Count", width=120, format=wx.LIST_FORMAT_RIGHT)
        self.list_ctrl_lists.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnListItemSelected)
        self.list_ctrl_lists.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.OnListItemDeselected)
        self.list_ctrl_lists.Bind(wx.EVT_LIST_KEY_DOWN, self.OnListKeyDown)
        self.list_ctrl_lists.InitializeColumnSorter(3)
        sizer.Add(self.list_ctrl_lists, 1, wx.EXPAND | wx.ALL, 0)
        panel.SetSizer(sizer)
        return panel
    def _CreateRulesPanel(self, parent_notebook):
        panel = wx.Panel(parent_notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        list_style = wx.LC_REPORT | wx.LC_VRULES | wx.BORDER_SUNKEN | wx.LC_SORT_ASCENDING | wx.LC_SINGLE_SEL
        self.list_ctrl_rules = SortableListCtrl(panel, style=list_style)
        self.list_ctrl_rules.InsertColumn(0, "Name", width=300)
        self.list_ctrl_rules.InsertColumn(1, "ID", width=250)
        self.list_ctrl_rules.InsertColumn(2, "Enabled", width=80, format=wx.LIST_FORMAT_CENTER)
        self.list_ctrl_rules.InsertColumn(3, "Source Type", width=100, format=wx.LIST_FORMAT_CENTER)
        self.list_ctrl_rules.InsertColumn(4, "Update Status", width=120, format=wx.LIST_FORMAT_CENTER)
        self.list_ctrl_rules.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnListItemSelected)
        self.list_ctrl_rules.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.OnListItemDeselected)
        self.list_ctrl_rules.Bind(wx.EVT_LIST_KEY_DOWN, self.OnListKeyDown)
        self.list_ctrl_rules.InitializeColumnSorter(5)
        sizer.Add(self.list_ctrl_rules, 1, wx.EXPAND | wx.ALL, 0)
        panel.SetSizer(sizer)
        return panel
    def _CreateBottomPanel(self, parent):
        panel = wx.Panel(parent, style=wx.BORDER_SUNKEN)
        sizer = wx.BoxSizer(wx.VERTICAL)
        log_label = wx.StaticText(panel, label=" Status Log:")
        sizer.Add(log_label, 0, wx.LEFT | wx.TOP, 5)
        self.log_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_DONTWRAP | wx.BORDER_NONE)
        self.log_ctrl.SetMinSize(wx.Size(-1, 100))
        sizer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)
        return panel
    def OnExit(self, event):
        self.operation_cancelled.set()
        self.Close()
    def OnAbout(self, event):
        try:
            # Create a custom about dialog instead of using wx.adv.AboutBox
            about_dlg = wx.Dialog(self, title=f"About {APP_NAME}", size=(395, 370))
            panel = wx.Panel(about_dlg)
            sizer = wx.BoxSizer(wx.VERTICAL)
            
            # Logo
            try:
                response = requests.get("https://raw.githubusercontent.com/john-holt4/Gateway-Gaurdian/main/logo.png", timeout=10)
                response.raise_for_status()
                image_data = io.BytesIO(response.content)
                img = wx.Image(image_data)
                if img.IsOk():
                    # Keep original aspect ratio
                    original_width = img.GetWidth()
                    original_height = img.GetHeight()
                    target_height = 64
                    target_width = int(original_width * (target_height / original_height))
                    bitmap = img.Scale(target_width, target_height, wx.IMAGE_QUALITY_HIGH).ConvertToBitmap()
                    logo = wx.StaticBitmap(panel, -1, bitmap)
                    sizer.Add(logo, 0, wx.ALIGN_CENTER | wx.ALL, 10)
                else:
                    print("Error: Failed to load logo image.")
            except Exception as img_err:
                print(f"Error displaying logo: {img_err}")
            
            # App info
            app_name = wx.StaticText(panel, -1, f"{APP_NAME} v{APP_VERSION}")
            font = app_name.GetFont()
            font.SetPointSize(font.GetPointSize() + 2)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            app_name.SetFont(font)
            sizer.Add(app_name, 0, wx.ALIGN_CENTER | wx.ALL, 5)
            
            desc = wx.StaticText(panel, -1, f"Manage Cloudflare Zero Trust Gateway lists and rules for adblocking.")
            sizer.Add(desc, 0, wx.ALIGN_CENTER | wx.ALL, 5)
            
            not_affiliated = wx.StaticText(panel, -1, f"({APP_NAME} is not affiliated with Cloudflare, Inc.)")
            font = not_affiliated.GetFont()
            font.SetPointSize(font.GetPointSize() - 1)
            font.SetStyle(wx.FONTSTYLE_ITALIC)
            not_affiliated.SetFont(font)
            sizer.Add(not_affiliated, 0, wx.ALIGN_CENTER | wx.ALL, 5)
            
            copyright_text = wx.StaticText(panel, -1, f"{datetime.date.today().year}")
            sizer.Add(copyright_text, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 10)
            
            # GitHub link
            github_link = wx.adv.HyperlinkCtrl(panel, -1, "Visit on GitHub", "https://github.com/john-holt4/Gateway-Gaurdian")
            sizer.Add(github_link, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)
            
            # Add a donate button
            donate_btn = wx.Button(panel, -1, "☕ Buy me a coffee")
            donate_btn.Bind(wx.EVT_BUTTON, self.OnDonateButton)
            sizer.Add(donate_btn, 0, wx.ALIGN_CENTER | wx.ALL, 10)
            
            # Add a close handler
            about_dlg.Bind(wx.EVT_CLOSE, lambda e: about_dlg.EndModal(wx.ID_OK))
            
            panel.SetSizer(sizer)
            about_dlg.Layout()
            about_dlg.Center()
            about_dlg.ShowModal()
            about_dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Error displaying About dialog: {e}", "Error", wx.OK | wx.ICON_ERROR)
            
    def OnDonateButton(self, event):
        # Launch PayPal donate URL in default browser
        paypal_url = "https://www.paypal.com/donate/?business=243S6YP5USR38&no_recurring=0&item_name=Support+the+development+of+Gateway+Gaurdian&currency_code=USD"
        import webbrowser
        try:
            webbrowser.open(paypal_url)
        except Exception as e:
            wx.MessageBox(f"Error opening donation page: {e}", "Error", wx.OK | wx.ICON_ERROR)
    def OnToggleLog(self, event):
        self.log_visible = event.IsChecked()
        self._update_log_visibility()
    def OnToggleStatusBar(self, event):
        self.status_bar_visible = event.IsChecked()
        self._update_status_bar_visibility()
    def _update_log_visibility(self):
        if not all(hasattr(self, attr) and getattr(self, attr) for attr in ['splitter', 'bottom_panel', 'main_panel']):
            print("Warning: Splitter/panels not ready during log visibility update.")
            return
        if self.log_visible:
            self.bottom_panel.Show()
            if not self.splitter.IsSplit():
                try:
                    h = self.splitter.GetClientSize().height
                    s = self.splitter.GetSashSize()
                    m = self.splitter.GetMinimumPaneSize()
                    p = int(h * self.splitter.GetSashGravity())
                    p = max(m, p)
                    p = min(h - m - s, p)
                    if p >= m and h > (2 * m + s):
                        self.splitter.SplitHorizontally(self.main_panel, self.bottom_panel, p)
                    else:
                        self.splitter.SplitHorizontally(self.main_panel, self.bottom_panel)
                except Exception as e:
                    print(f"Error re-splitting window: {e}")
                    traceback.print_exc()
                    if not self.splitter.IsSplit():
                        try: self.splitter.SplitHorizontally(self.main_panel, self.bottom_panel)
                        except Exception as split_err: print(f"Error during fallback split: {split_err}")
        else:
            if self.splitter.IsSplit(): self.splitter.Unsplit(self.bottom_panel)
            self.bottom_panel.Hide()
        self.Layout()
        if hasattr(self, 'log_menu_item') and self.log_menu_item:
            self.log_menu_item.Check(self.log_visible)
    def _update_status_bar_visibility(self):
        if self.custom_status_bar:
            self.custom_status_bar.Show(True)  # Always show status bar
            self.Layout()
    def _calculate_content_hash(self, content):
        """Calculate a hash of content for update tracking based on size"""
        if not content:
            return None
        # Use content length as a simple hash
        content_size = len(content)
        content_lines = len(content.splitlines())
        hash_value = f"{content_size}"  # Simple size-based hash
        self.LogMessage(f"Content size: {content_size} bytes, {content_lines} lines", "grey")
        return hash_value
    
    def _parse_metadata(self, description):
        """Extract source URL and list prefix from rule description"""
        source_url, list_prefix = None, None
        
        # Use the improved extraction method
        metadata = self._extract_rule_metadata(description)
        if metadata:
            source_url = metadata.get("URL")
            list_prefix = metadata.get("PREFIX")
            
        return source_url, list_prefix
        
    def _extract_rule_metadata(self, description):
        """Extract metadata from rule description using a simpler approach"""
        self.LogMessage(f"Extracting metadata from: {description[:50]}{'...' if len(description) > 50 else ''}", "grey")
        
        metadata = {}
        
        try:
            # Find all metadata within the markers
            if METADATA_MARKER_PREFIX in description and METADATA_MARKER_SUFFIX in description:
                start_idx = description.find(METADATA_MARKER_PREFIX) + len(METADATA_MARKER_PREFIX)
                end_idx = description.find(METADATA_MARKER_SUFFIX, start_idx)
                if start_idx > 0 and end_idx > start_idx:
                    metadata_content = description[start_idx:end_idx]
                    self.LogMessage(f"Raw metadata: {metadata_content}", "grey")
                    
                    # Extract URL (handles URL with path)
                    url_parts = re.split(r':(?=PREFIX=|HASH=)', metadata_content)
                    if len(url_parts) > 0 and url_parts[0].startswith("URL="):
                        url = url_parts[0][4:]  # Remove "URL="
                        metadata["URL"] = url
                        self.LogMessage(f"Found URL: {url}", "grey")
                    
                    # Extract PREFIX
                    prefix_match = re.search(r'PREFIX=([^:]+)(?::|$)', metadata_content)
                    if prefix_match:
                        prefix = prefix_match.group(1)
                        metadata["PREFIX"] = prefix
                        self.LogMessage(f"Found PREFIX: {prefix}", "grey")
                    
                    # Always take the last HASH value
                    # First try numeric hashes
                    hash_parts = re.findall(r'HASH=(\d+)', metadata_content)
                    if hash_parts:
                        # Use only the last hash value
                        hash_value = hash_parts[-1]
                        metadata["HASH"] = hash_value
                        self.LogMessage(f"Found last hash: {hash_value}", "grey")
                    else:
                        # Fallback to last hash of any type
                        hash_matches = re.findall(r'HASH=([^:]+?)(?::|HASH=|$|\])', metadata_content)
                        if hash_matches:
                            hash_value = hash_matches[-1]
                            metadata["HASH"] = hash_value
                            self.LogMessage(f"Found last non-numeric hash: {hash_value}", "grey")
        except Exception as e:
            self.LogMessage(f"Error extracting metadata: {e}", "red")
            
        self.LogMessage(f"Extracted metadata: {metadata}", "grey")
        return metadata

    def _check_update_status(self, rule_description, source_url):
        """Check if a rule needs updating based on content size"""
        if not source_url:
            return "No source URL"
            
        # Extract metadata directly 
        metadata = self._extract_rule_metadata(rule_description)
        
        # Debug logging to understand what's happening
        self.LogMessage(f"Checking updates for URL: {source_url}", "grey")
        
        # Get the stored hash directly from the metadata
        stored_hash = metadata.get("HASH")
        
        # More debug logging
        self.LogMessage(f"Stored hash from metadata: {stored_hash} (type: {type(stored_hash).__name__})", "grey")
        
        if not stored_hash:
            return "No hash data"
            
        try:
            self.LogMessage(f"Fetching content from {source_url}...", "grey")
            response = requests.get(source_url, timeout=30)
            if response.status_code != 200:
                return "Check failed"
                
            current_content = response.text
            # For simplicity, just count the lines in the content and check its size
            content_lines = len(current_content.splitlines())
            content_size = len(current_content)
            
            self.LogMessage(f"Content length: {content_size} bytes, {content_lines} lines", "grey")
            
            # Calculate current hash (which is just the content size)
            current_hash = self._calculate_content_hash(current_content)
            
            # Convert both to strings for comparison
            if not isinstance(stored_hash, str):
                stored_hash = str(stored_hash)
            if not isinstance(current_hash, str):
                current_hash = str(current_hash)
                
            # Better logging to understand what's being compared
            self.LogMessage(f"Comparing stored hash '{stored_hash}' (type: {type(stored_hash).__name__}) with current hash '{current_hash}' (type: {type(current_hash).__name__})", "grey")
            
            # Compare hashes
            if stored_hash == current_hash:
                self.LogMessage(f"Hashes match: {stored_hash} == {current_hash}", "green")
                return "Up to date"
            else:
                self.LogMessage(f"Hashes don't match: {stored_hash} != {current_hash}", "orange") 
                return "Update available"
        except Exception as e:
            self.LogMessage(f"Update check failed: {e}", "red")
            return "Check failed"
    
    def sanitize_filename(self, filename):
        if not filename: return "default_name"
        base = os.path.splitext(os.path.basename(filename))[0]
        sanitized = re.sub(r'[\s\-.]+', '_', base)
        valid_chars = string.ascii_letters + string.digits + "_"
        sanitized = ''.join(c for c in sanitized if c in valid_chars)
        sanitized = sanitized.strip('_')[:50]
        return sanitized if sanitized else "default_name"
    def _sanitize_url_for_name(self, url):
        if not url: return "default_name"
        try:
            parsed = urlparse(url)
            base = parsed.netloc.split(':')[0]
            sanitized = re.sub(r'[\-.]+', '_', base)
            valid_chars = string.ascii_letters + string.digits + "_"
            sanitized = ''.join(c for c in sanitized if c in valid_chars)
            sanitized = sanitized.strip('_')[:50]
            return sanitized if sanitized else "default_name_from_url"
        except Exception as e:
            print(f"Error parsing URL for sanitization: {e}")
            return "url_parse_error"
    def OnLoadFromFile(self, event):
        style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        wildcard = "Text files (*.txt)|*.txt|All files (*.*)|*.*"
        with wx.FileDialog(self, "Open Adblock List File", wildcard=wildcard, style=style) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL: return
            self.adblock_filepath, self.adblock_url = fileDialog.GetPath(), None
            display_name = os.path.basename(self.adblock_filepath)
            self.lbl_source_display.SetLabel(f"Source: File - {display_name}")
            self.LogMessage(f"Selected adblock list file: {self.adblock_filepath}")
            self.UpdateStatusBar(f"Loaded file: {display_name}")
            sanitized_name = self.sanitize_filename(display_name)
            suggested_prefix, suggested_rule = f"{sanitized_name}_list_", f"{sanitized_name}_rule"
            self.txt_list_prefix.SetValue(suggested_prefix)
            self.txt_rule_name.SetValue(suggested_rule)
            self.LogMessage(f"Auto-populated naming options: Prefix='{suggested_prefix}', Rule='{suggested_rule}'")
            self._update_apply_button_state()
            self.Layout()
            self.main_panel.Layout()
    def OnLoadFromURL(self, event):
        dlg = wx.TextEntryDialog(self, "Enter the URL for the adblock list:", "Load from URL")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                self.adblock_url, self.adblock_filepath = url, None
                self.lbl_source_display.SetLabel(f"Source: URL - {url}")
                self.LogMessage(f"Selected adblock list URL: {url}")
                self.UpdateStatusBar(f"Loaded URL source")
                sanitized_name = ""
                try:
                    parsed_url = urlparse(url)
                    url_filename = os.path.basename(parsed_url.path)
                    if url_filename:
                        sanitized_name = self.sanitize_filename(url_filename)
                        self.LogMessage(f"Using filename '{url_filename}' from URL for auto-naming.")
                    else:
                        self.LogMessage("No filename found in URL path, using domain for auto-naming.", "grey")
                        sanitized_name = self._sanitize_url_for_name(url)
                except Exception as e:
                    self.LogMessage(f"Error parsing URL filename, falling back to domain: {e}", "orange")
                    sanitized_name = self._sanitize_url_for_name(url)
                suggested_prefix, suggested_rule = f"{sanitized_name}_list_", f"{sanitized_name}_rule"
                self.txt_list_prefix.SetValue(suggested_prefix)
                self.txt_rule_name.SetValue(suggested_rule)
                self.LogMessage(f"Auto-populated naming options: Prefix='{suggested_prefix}', Rule='{suggested_rule}'")
                self._update_apply_button_state()
                self.Layout()
                self.main_panel.Layout()
            else:
                self.ShowInfo("No URL entered.")
                self.UpdateStatusBar("URL load cancelled.")
        dlg.Destroy()
    def OnNamingOptionsChanged(self, event):
        self._update_apply_button_state()
        event.Skip()
    def _update_apply_button_state(self):
        toolbar = self.GetToolBar()
        if not toolbar: return
        has_source = bool(self.adblock_filepath or self.adblock_url)
        has_prefix = bool(self.txt_list_prefix.GetValue().strip())
        has_rule_name = bool(self.txt_rule_name.GetValue().strip())
        enable_apply = has_source and has_prefix and has_rule_name
        toolbar.EnableTool(ID_TOOLBAR_APPLY, enable_apply)
        mb = self.GetMenuBar()
        if mb: mb.Enable(ID_APPLY, enable_apply)
    def OnListItemSelected(self, event):
        self._update_management_button_states()
        event.Skip()
    def OnListItemDeselected(self, event):
        wx.CallAfter(self._update_management_button_states)
        event.Skip()
        
    def OnListKeyDown(self, event):
        """Handle key events on list controls"""
        key_code = event.GetKeyCode()
        
        # Block Ctrl+A in the list control to prevent "select all" behavior
        if key_code == ord('A') and (wx.GetKeyState(wx.WXK_CONTROL) or event.ControlDown()):
            # Don't call event.Skip() - this blocks the event from propagating
            # This allows the menu accelerator to handle Ctrl+A instead
            return
        
        # Let other key events continue
        event.Skip()
    def OnEditItem(self, event):
        active_list_ctrl, active_data_map = self._get_active_list_ctrl()
        if not active_list_ctrl or active_list_ctrl.GetSelectedItemCount() != 1:
            self.UpdateStatusBar("Select a single item to edit.")
            return
        index = active_list_ctrl.GetFirstSelected()
        if index == -1: return
        item_data_key = active_list_ctrl.GetItemData(index)
        item_data = active_data_map.get(item_data_key)
        if not item_data:
            self.ShowError("Could not retrieve data for the selected item.")
            return
        item_type = None
        if isinstance(item_data, tuple):
            item_type = item_data[0]
        elif isinstance(item_data, dict):
            item_type = item_data.get('type')
        if item_type == 'list':
            list_id = item_data[1] if isinstance(item_data, tuple) else item_data.get('id')
            list_name = active_list_ctrl.GetItemText(index)
            self.LogMessage(f"Opening edit dialog for list: {list_name} ({list_id})")
            self.UpdateStatusBar(f"Editing list: {list_name}")
            dlg = ListEditDialog(self, self.api_client, list_id, list_name)
            result = dlg.ShowModal()
            if result == wx.ID_OK:
                self.LogMessage(f"List '{list_name}' updated successfully.")
                self.UpdateStatusBar(f"List updated.")
                self.OnRefresh()
            else:
                self.LogMessage(f"Editing cancelled for list: {list_name}")
                self.UpdateStatusBar("List edit cancelled.")
            dlg.Destroy()
        elif item_type == 'rule':
            rule_id = item_data.get('id')
            rule_name = item_data.get('name')
            rule_enabled = item_data.get('enabled')
            full_desc = ""
            try:
                details_resp = self.api_client.get_rule_details(rule_id)
                if details_resp and details_resp.get("success"):
                    full_desc = details_resp.get("result", {}).get("description", "")
                else:
                    self.LogMessage(f"Warning: Could not fetch full description for rule {rule_name}", "orange")
            except Exception as e:
                 self.LogMessage(f"Warning: Error fetching full description for rule {rule_name}: {e}", "orange")
            self.LogMessage(f"Opening edit dialog for rule: {rule_name} ({rule_id})")
            self.UpdateStatusBar(f"Editing rule: {rule_name}")
            dlg = RuleEditDialog(self, self.api_client, rule_id, rule_name, rule_enabled, full_desc)
            result = dlg.ShowModal()
            if result == wx.ID_OK:
                self.LogMessage(f"Rule '{rule_name}' updated successfully.")
                self.UpdateStatusBar(f"Rule updated.")
                self.OnRefresh()
            else:
                self.LogMessage(f"Editing cancelled for rule: {rule_name}")
                self.UpdateStatusBar("Rule edit cancelled.")
            dlg.Destroy()
        else:
            self.ShowError(f"Cannot edit item of unknown type: {item_type}")
    def _update_management_button_states(self):
        selected_rule_count = 0
        selected_list_count = 0
        can_update_rule = False
        active_list_ctrl, _ = self._get_active_list_ctrl()
        toolbar = self.GetToolBar()
        mb = self.GetMenuBar()
        if not toolbar or not mb: return
        if self.list_ctrl_rules:
            selected_rule_count = self.list_ctrl_rules.GetSelectedItemCount()
            if selected_rule_count == 1:
                idx = self.list_ctrl_rules.GetFirstSelected()
                if idx != -1:
                    rule_data_key = self.list_ctrl_rules.GetItemData(idx)
                    rule_data = self.list_item_data_rules.get(rule_data_key)
                    if isinstance(rule_data, dict) and rule_data.get("source_url"):
                        can_update_rule = True
        if self.list_ctrl_lists:
            selected_list_count = self.list_ctrl_lists.GetSelectedItemCount()
        enable_edit = (selected_rule_count == 1 and active_list_ctrl == self.list_ctrl_rules) or \
                      (selected_list_count == 1 and active_list_ctrl == self.list_ctrl_lists)
        enable_delete_rule_lists = (selected_rule_count >= 1 and active_list_ctrl == self.list_ctrl_rules)
        enable_update_from_source = (selected_rule_count == 1 and can_update_rule and active_list_ctrl == self.list_ctrl_rules)
        toolbar.EnableTool(ID_TOOLBAR_EDIT, enable_edit)
        toolbar.EnableTool(ID_TOOLBAR_UPDATE, enable_update_from_source)
        toolbar.EnableTool(ID_TOOLBAR_DELETE_RULE_LISTS, enable_delete_rule_lists)
        mb.Enable(ID_TOOLBAR_EDIT, enable_edit)
        mb.Enable(ID_UPDATE_RULE, enable_update_from_source)
        mb.Enable(ID_DELETE_RULE_LISTS, enable_delete_rule_lists)
    def OnApplyAdblock(self, event):
        if not self._validate_naming_options(): return
        if not self.adblock_filepath and not self.adblock_url:
            self.ShowError("No adblock list source (file or URL) has been loaded.")
            self.UpdateStatusBar("Apply failed: No source loaded.")
            return
        list_prefix = self.txt_list_prefix.GetValue().strip()
        rule_name = self.txt_rule_name.GetValue().strip()
        cursor = wx.BusyCursor()
        self.UpdateStatusBar("Checking for existing items...")
        try:
            self.LogMessage(f"Checking for existing items with prefix '{list_prefix}' or rule name '{rule_name}'...")
            existing_lists = self.api_client.get_lists(name_prefix=list_prefix, timeout=30)
            existing_rules = self.api_client.get_rules(rule_name=rule_name, timeout=30)
            if existing_lists or existing_rules:
                error_detail = []
                if existing_lists: error_detail.append(f"{len(existing_lists)} list(s) starting with '{list_prefix}'")
                if existing_rules: error_detail.append(f"a rule named '{rule_name}'")
                err_msg = f"Cannot proceed: Pre-existing items found ({' and '.join(error_detail)}).\nPlease use different names or delete existing items."
                self.ShowError(err_msg)
                self.UpdateStatusBar("Apply failed: Item name conflict.")
                if 'cursor' in locals() and cursor: del cursor
                return
            self.LogMessage("Pre-check passed. No conflicts found.")
            self.UpdateStatusBar("Pre-check passed.")
        except ConnectionError as e:
            self.ShowError(f"Failed during pre-check for existing items: {e}")
            self.UpdateStatusBar("Apply failed: API connection error during pre-check.")
            if 'cursor' in locals() and cursor: del cursor
            return
        except Exception as e:
            self.ShowError(f"An unexpected error occurred during pre-check: {e}")
            self.UpdateStatusBar("Apply failed: Unexpected error during pre-check.")
            traceback.print_exc()
            if 'cursor' in locals() and cursor: del cursor
            return
        content, source_description = None, ""
        try:
            source_is_url = bool(self.adblock_url)
            if self.adblock_url:
                url = self.adblock_url
                self.LogMessage(f"Fetching adblock list from URL: {url}...")
                self.UpdateStatusBar("Fetching content from URL...")
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    response = requests.get(url, timeout=30, headers=headers, allow_redirects=True)
                    response.raise_for_status()
                    try: content = response.content.decode('utf-8')
                    except UnicodeDecodeError:
                        if HAS_CHARDET:
                            detected = chardet.detect(response.content)
                            encoding = detected.get('encoding', 'latin-1') if detected else 'latin-1'
                            self.LogMessage(f"Detected encoding (URL): {encoding}", "grey")
                            content = response.content.decode(encoding, errors='ignore')
                        else:
                            self.LogMessage("UTF-8 decode failed (URL), fallback to latin-1.", "orange")
                            if not HAS_CHARDET: self.LogMessage("Install 'chardet' package for better encoding detection.", "orange")
                            content = response.content.decode('latin-1', errors='ignore')
                    source_description = f"URL: {url}"; self.LogMessage("Successfully fetched content from URL.")
                    self.UpdateStatusBar("Content fetched from URL.")
                except requests.exceptions.Timeout: self.ShowError("Timeout occurred while fetching the adblock list from the URL."); self.UpdateStatusBar("Apply failed: URL fetch timeout."); return
                except requests.exceptions.RequestException as e: self.ShowError(f"Failed to fetch adblock list from URL: {e}"); self.UpdateStatusBar("Apply failed: URL fetch error."); return
                except Exception as e: self.ShowError(f"An unexpected error occurred while fetching from URL: {e}"); self.UpdateStatusBar("Apply failed: URL fetch processing error."); traceback.print_exc(); return
            elif self.adblock_filepath and os.path.exists(self.adblock_filepath):
                fpath = self.adblock_filepath
                self.LogMessage(f"Reading adblock list from file: {fpath}...")
                self.UpdateStatusBar("Reading content from file...")
                try:
                    content = self._read_file_with_encoding_detection(fpath)
                    if content is None: raise IOError("Failed to read file content.")
                    source_description = f"File: {os.path.basename(fpath)}"; self.LogMessage("Successfully read content from file.")
                    self.UpdateStatusBar("Content read from file.")
                except Exception as e: self.ShowError(f"Failed to read adblock list file: {e}"); self.UpdateStatusBar("Apply failed: File read error."); traceback.print_exc(); return
            else: self.ShowError("Internal error: No valid source after pre-check."); self.UpdateStatusBar("Apply failed: Internal source error."); return
        finally:
            if 'cursor' in locals() and cursor: del cursor
        if content is None: self.ShowError("Could not retrieve adblock list content."); self.UpdateStatusBar("Apply failed: No content retrieved."); return
        self.LogMessage(f"Processing content from: {source_description}..."); self.UpdateStatusBar("Processing content...")
        self._set_apply_enabled(False)
        try:
            wx.YieldIfNeeded(); domains = self._process_adblock_content(content)
            if not domains: self.ShowError("No valid domains were extracted from the source. Please check the list format."); self.UpdateStatusBar("Apply failed: No valid domains found."); self._set_apply_enabled(True); return
            if len(domains) > TOTAL_DOMAIN_LIMIT: self.ShowError(f"The number of extracted domains ({len(domains):,}) exceeds the Cloudflare account limit of {TOTAL_DOMAIN_LIMIT:,} across all lists."); self.UpdateStatusBar("Apply failed: Domain limit exceeded."); self._set_apply_enabled(True); return
            num_lists_needed = (len(domains) + MAX_DOMAINS_PER_LIST - 1) // MAX_DOMAINS_PER_LIST
            try:
                self.LogMessage("Checking current account list count...")
                self.UpdateStatusBar("Checking account limits...")
                existing_lists_total = self.api_client.get_lists(timeout=30)
                current_list_count = len(existing_lists_total)
                self.LogMessage(f" -> Account currently has {current_list_count} lists.")
                if num_lists_needed + current_list_count > MAX_LISTS: self.ShowError(f"Error: Creating {num_lists_needed} new list(s) would exceed the account limit of {MAX_LISTS} lists (currently have {current_list_count}).\nPlease delete some existing lists."); self.UpdateStatusBar("Apply failed: Account list limit exceeded."); self._set_apply_enabled(True); return
                self.UpdateStatusBar("Account limits OK.")
            except Exception as e: self.ShowError(f"Error checking current list count: {e}"); self.UpdateStatusBar("Apply failed: Error checking limits."); self._set_apply_enabled(True); return
            self.LogMessage(f"Extracted {len(domains):,} valid domains. This will require creating {num_lists_needed} list(s). Account limit check passed.")
            max_progress = num_lists_needed + 1; self.operation_cancelled.clear()
            wx.CallAfter(self.progress_gauge.SetRange, max_progress)
            wx.CallAfter(self.progress_gauge.SetValue, 0)
            wx.CallAfter(self.progress_gauge.Show)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(self.UpdateStatusBar, "Applying Configuration...")
            wx.CallAfter(self.EnableCancelButton, True)
            source_url_for_worker = self.adblock_url if source_is_url else None
            # Pass the original content for hash calculation
            thread = threading.Thread(target=self._load_and_create_worker, args=(self.progress_gauge, self.operation_cancelled, domains, list_prefix, rule_name, source_url_for_worker, content))
            thread.start()
        except Exception as e:
            self.ShowError(f"Error during adblock preprocessing: {e}")
            self.UpdateStatusBar("Apply failed: Preprocessing error.")
            self.LogMessage(f"Preprocessing Traceback:\n{traceback.format_exc()}", "red")
            self._set_apply_enabled(True)
    def _set_apply_enabled(self, enabled):
        toolbar = self.GetToolBar()
        if toolbar: toolbar.EnableTool(ID_TOOLBAR_APPLY, enabled)
        mb = self.GetMenuBar()
        if mb: mb.Enable(ID_APPLY, enabled)
    def EnableCancelButton(self, enable):
        toolbar = self.GetToolBar()
        if toolbar: toolbar.EnableTool(ID_TOOLBAR_CANCEL, enable)
        mb = self.GetMenuBar()
        if mb: mb.Enable(ID_CANCEL_OPERATION, enable)
    def _read_file_with_encoding_detection(self, filepath):
        self.LogMessage(f"Reading file: {filepath}", "grey")
        try:
            if HAS_CHARDET:
                with open(filepath, 'rb') as f_raw: raw_data = f_raw.read()
                if not raw_data: self.LogMessage("File appears to be empty.", "orange"); return ""
                detection = chardet.detect(raw_data); encoding, confidence = detection['encoding'], detection['confidence']
                if encoding and confidence > 0.7:
                    self.LogMessage(f" -> Detected encoding: {encoding} (Confidence: {confidence:.2f})", "grey")
                    try: return raw_data.decode(encoding, errors='ignore')
                    except Exception as decode_err: self.LogMessage(f" -> Decode with detected encoding failed: {decode_err}. Falling back.", "orange")
                else: self.LogMessage(f" -> Low confidence detection ({encoding} @ {confidence:.2f}). Falling back.", "grey")
            else:
                 self.LogMessage(" -> 'chardet' module not found. Trying UTF-8 then Latin-1.", "grey")
            common_encodings = ['utf-8', 'latin-1']
            for enc in common_encodings:
                try:
                    with open(filepath, 'r', encoding=enc) as f: content = f.read()
                    self.LogMessage(f" -> Successfully read file using encoding: {enc}", "grey"); return content
                except UnicodeDecodeError: self.LogMessage(f" -> Failed to read file with encoding: {enc}", "grey"); continue
                except Exception as e: self.LogMessage(f" -> Error reading file with encoding {enc}: {e}", "red"); raise e
            self.LogMessage("Could not read file with common encodings.", "red"); return None
        except FileNotFoundError: self.LogMessage(f"Error: File not found at path: {filepath}", "red"); raise
        except Exception as e: self.LogMessage(f"An unexpected error occurred while reading file {filepath}: {e}", "red"); raise
    def OnRefresh(self, event=None):
        if not self.api_client: self.ShowError("API client is not initialized. Cannot refresh."); return
        self.LogMessage("Refreshing Gateway Lists and Rules...")
        self.UpdateStatusBar("Refreshing...")
        if self.list_ctrl_lists: self.list_ctrl_lists.DeleteAllItems()
        if self.list_ctrl_rules: self.list_ctrl_rules.DeleteAllItems()
        self.list_item_data_lists, self.list_item_data_rules = {}, {}
        self.operation_cancelled.clear()
        wx.CallAfter(self.progress_gauge.SetRange, 2)
        wx.CallAfter(self.progress_gauge.SetValue, 0)
        wx.CallAfter(self.progress_gauge.Show)
        wx.CallAfter(self.custom_status_bar.Layout)
        wx.CallAfter(self.UpdateStatusBar, "Refreshing Items...")
        wx.CallAfter(self.EnableCancelButton, True)
        thread = threading.Thread(target=self._refresh_worker, args=(self.progress_gauge, self.operation_cancelled)); thread.start()
    def _get_active_list_ctrl(self):
        if not self.notebook: return None, None
        selection = self.notebook.GetSelection()
        if selection == 0: return self.list_ctrl_rules, self.list_item_data_rules
        elif selection == 1: return self.list_ctrl_lists, self.list_item_data_lists
        else: return None, None
    def OnListKeyDown(self, event):
        keycode = event.GetKeyCode()
        # ListEvent doesn't have ControlDown(), so we need to use GetControl()
        ctrl_key = wx.GetKeyState(wx.WXK_CONTROL)
        if ctrl_key and keycode == ord('A'):
            # Use Ctrl+A for Apply Adblock Configuration instead of Select All
            self.OnApplyAdblock(event)
        elif keycode == wx.WXK_ESCAPE:
             self.OnCancelOperation(event)
        else:
            event.Skip()
    def OnSelectAll(self, event):
        active_list_ctrl, _ = self._get_active_list_ctrl()
        if not active_list_ctrl: return
        count = active_list_ctrl.GetItemCount()
        if count == 0: self.LogMessage("Cannot select all: List is empty.", "grey"); return
        for i in range(count): active_list_ctrl.Select(i)
        self.LogMessage(f"Selected all {count} items.")
        self.UpdateStatusBar(f"Selected {count} items.")
        self._update_management_button_states()
    def OnDeselectAll(self, event):
        active_list_ctrl, _ = self._get_active_list_ctrl()
        if not active_list_ctrl: return
        count = active_list_ctrl.GetItemCount()
        if count == 0: self.LogMessage("Cannot deselect all: List is empty.", "grey"); return
        selected_idx = active_list_ctrl.GetFirstSelected()
        num_deselected = 0
        while selected_idx != -1:
            active_list_ctrl.Select(selected_idx, False)
            num_deselected += 1
            selected_idx = active_list_ctrl.GetNextSelected(selected_idx)
        self.LogMessage("Deselected all items.")
        self.UpdateStatusBar(f"Deselected {num_deselected} items.")
        self._update_management_button_states()
    def OnCancelOperation(self, event):
        self.operation_cancelled.set()
        self.LogMessage("Cancel requested by user.", "orange")
        self.UpdateStatusBar("Cancel requested...")
        self.EnableCancelButton(False)
    def OnDeleteRuleAndLists(self, event):
        if not self.api_client: self.ShowError("API client not initialized."); return
        selected_indices = []
        if not self.list_ctrl_rules: return
        idx = self.list_ctrl_rules.GetFirstSelected()
        while idx != -1: selected_indices.append(idx); idx = self.list_ctrl_rules.GetNextSelected(idx)
        if not selected_indices: self.ShowError("Please select at least one rule to delete."); self.UpdateStatusBar("Select rule(s) to delete."); return
        selected_rule_ids, selected_rule_names = [], []
        for selected_idx in selected_indices:
            rule_data_key = self.list_ctrl_rules.GetItemData(selected_idx); rule_data = self.list_item_data_rules.get(rule_data_key)
            if isinstance(rule_data, dict) and rule_data.get('type') == 'rule':
                rule_id = rule_data.get('id'); rule_name = rule_data.get('name', self.list_ctrl_rules.GetItemText(selected_idx))
                if rule_id: selected_rule_ids.append(rule_id); selected_rule_names.append(rule_name)
                else: self.LogMessage(f"Warning: Missing ID for rule data at index {selected_idx}, key {rule_data_key}", "orange")
            else: self.ShowError(f"Could not retrieve valid rule data for selected rule at index {selected_idx}, key {rule_data_key}."); return
        if not selected_rule_ids: self.ShowError("Failed to identify IDs for selected rules."); return
        num_rules_to_delete = len(selected_rule_ids); self.LogMessage(f"Preparing deletion for {num_rules_to_delete} rule(s): {', '.join(selected_rule_names)}")
        self.UpdateStatusBar("Fetching rule details...")
        wx.BeginBusyCursor(); all_associated_list_uuids = set(); all_associated_list_names_map = {}; fetch_errors = []
        try:
            self.LogMessage(" -> Fetching rule details to identify associated lists...")
            uuid_to_name_map = {}
            try:
                all_lists_for_naming = self.api_client.get_lists()
                uuid_to_name_map = {lst.get('id'): lst.get('name', 'Unnamed List') for lst in all_lists_for_naming if lst.get('id')}
            except Exception as name_err: self.LogMessage(f" -> Warning: Could not fetch all lists for naming: {name_err}", "orange")
            for rule_id, rule_name in zip(selected_rule_ids, selected_rule_names):
                try:
                    self.LogMessage(f"   -> Fetching details for rule '{rule_name}' ({rule_id})...", "grey")
                    rule_details_resp = self.api_client.get_rule_details(rule_id)
                    if not rule_details_resp or not rule_details_resp.get("success"): raise ConnectionError(f"Failed to fetch details for rule '{rule_name}': {rule_details_resp}")
                    rule_obj = rule_details_resp.get("result")
                    if not rule_obj: raise ValueError(f"Rule details missing for '{rule_name}'.")
                    traffic_expr = rule_obj.get("traffic", "")
                    if not traffic_expr: self.LogMessage(f"   -> Rule '{rule_name}' has no traffic expression.", "grey"); continue
                    extracted_uuids = set(re.findall(r'\$([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})', traffic_expr))
                    if not extracted_uuids:
                        extracted_vars = set(re.findall(r'\$([a-zA-Z0-9_]+)', traffic_expr))
                        msg = f"   -> Could not parse list variables from expression for rule '{rule_name}'."
                        if extracted_vars: msg = f"   -> Rule '{rule_name}' uses non-UUID variables: {', '.join(extracted_vars)}. Cannot reliably determine associated lists."
                        self.LogMessage(msg, "orange"); continue
                    self.LogMessage(f"   -> Found {len(extracted_uuids)} potential list UUID(s) for rule '{rule_name}'.", "grey")
                    all_associated_list_uuids.update(extracted_uuids)
                    for uuid in extracted_uuids:
                        if uuid not in all_associated_list_names_map: all_associated_list_names_map[uuid] = uuid_to_name_map.get(uuid, f"Unknown List ({uuid[:8]}...)")
                except Exception as e: fetch_errors.append(f"Rule '{rule_name}': {e}"); self.LogMessage(f"   -> Error fetching/parsing details for rule '{rule_name}': {e}", "red")
            if fetch_errors: error_summary = "Errors occurred while fetching rule details:\n- " + "\n- ".join(fetch_errors); wx.MessageBox(error_summary, "Rule Detail Fetch Errors", wx.OK | wx.ICON_WARNING, self)
        except Exception as e: self.ShowError(f"Error preparing deletion: {e}"); traceback.print_exc(); self.LogMessage(f"Error preparing deletion: {e}", "red"); self.UpdateStatusBar("Error preparing deletion.");
        finally: wx.EndBusyCursor()
        num_assoc_lists = len(all_associated_list_uuids); confirm_message = f"Delete {num_rules_to_delete} selected rule(s)?\n"
        confirm_message += "\n".join([f"- {name}" for name in selected_rule_names]) if num_rules_to_delete <= 10 else "(Too many rule names to display)"
        if num_assoc_lists > 0:
            confirm_message += f"\n\nALSO delete {num_assoc_lists} uniquely associated list(s):\n"
            display_list_names = [all_associated_list_names_map.get(uuid, f"ID: {uuid}") for uuid in sorted(list(all_associated_list_uuids))]
            confirm_message += "\n".join([f"- {name}" for name in display_list_names]) if num_assoc_lists <= 10 else f"(Too many list names to display)"
        else: confirm_message += "\n\nNo associated lists identified (or errors occurred during detection)."
        confirm_message += "\n\nProceed with deletion?"
        dialog_result = wx.MessageBox(confirm_message, "Confirm Delete Rule(s) and Associated Lists", wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT, self)
        if dialog_result == wx.NO: self.LogMessage("Deletion cancelled by user."); self.UpdateStatusBar("Deletion cancelled."); return
        self.LogMessage(f"Starting deletion worker for {num_rules_to_delete} rule(s) and {num_assoc_lists} associated list(s)...")
        self.UpdateStatusBar(f"Deleting {num_rules_to_delete} rule(s) and {num_assoc_lists} list(s)...")
        self.operation_cancelled.clear(); max_progress = num_rules_to_delete + num_assoc_lists
        wx.CallAfter(self.progress_gauge.SetRange, max(1, max_progress))
        wx.CallAfter(self.progress_gauge.SetValue, 0)
        wx.CallAfter(self.progress_gauge.Show)
        wx.CallAfter(self.custom_status_bar.Layout)
        wx.CallAfter(self.UpdateStatusBar, f"Deleting Rule(s) and Lists...")
        wx.CallAfter(self.EnableCancelButton, True)
        thread = threading.Thread(target=self._delete_rule_and_lists_worker, args=(selected_rule_ids, selected_rule_names, list(all_associated_list_uuids), self.progress_gauge, self.operation_cancelled)); thread.start()
    def OnUpdateSelectedRule(self, event):
        if not self.list_ctrl_rules or self.list_ctrl_rules.GetSelectedItemCount() != 1: self.ShowError("Please select exactly one rule to update."); self.UpdateStatusBar("Select one rule to update."); return
        selected_idx = self.list_ctrl_rules.GetFirstSelected()
        if selected_idx == -1: return
        rule_data_key = self.list_ctrl_rules.GetItemData(selected_idx); rule_data = self.list_item_data_rules.get(rule_data_key)
        if not isinstance(rule_data, dict) or not rule_data.get("source_url") or not rule_data.get("list_prefix"): self.ShowError("The selected rule does not appear to be managed by this script or lacks source URL/prefix metadata."); self.UpdateStatusBar("Cannot update: Rule missing metadata."); return
        rule_id = rule_data.get("id"); rule_name = rule_data.get("name"); source_url = rule_data.get("source_url"); list_prefix = rule_data.get("list_prefix")
        if not all([rule_id, rule_name, source_url, list_prefix]): self.ShowError("Could not retrieve necessary information (ID, Name, URL, Prefix) for the selected rule."); self.UpdateStatusBar("Cannot update: Incomplete rule info."); return
        msg = f"This will update the rule '{rule_name}' and its associated lists by:\n\n1. Fetching the latest list from:\n   {source_url}\n2. Deleting the existing rule and its current lists.\n3. Creating new lists (named '{list_prefix}...') and a new rule ('{rule_name}').\n\nProceed with update?"
        dialog_result = wx.MessageBox(msg, "Confirm Rule Update from URL", wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT, self)
        if dialog_result == wx.NO: self.LogMessage("Rule update cancelled by user."); self.UpdateStatusBar("Rule update cancelled."); return
        self.LogMessage(f"Starting update process for rule '{rule_name}' from {source_url}...")
        self.UpdateStatusBar(f"Updating rule '{rule_name}'...")
        self.operation_cancelled.clear()
        wx.CallAfter(self.progress_gauge.Pulse)
        wx.CallAfter(self.progress_gauge.Show)
        wx.CallAfter(self.custom_status_bar.Layout)
        wx.CallAfter(self.UpdateStatusBar, f"Updating Rule '{rule_name}'...")
        wx.CallAfter(self.EnableCancelButton, True)
        thread = threading.Thread(target=self._update_rule_worker, args=(rule_id, rule_name, source_url, list_prefix, self.progress_gauge, self.operation_cancelled)); thread.start()
    def _update_rules_status(self, op_event=None):
        """Update status of all rules in the list control - called after refresh"""
        if not self.list_ctrl_rules or not self.api_client:
            return
        
        wx.CallAfter(self.LogMessage, "Checking rules for updates...", "grey")
        wx.CallAfter(self.UpdateStatusBar, "Checking rules for updates...")
        
        # Process in a separate thread to avoid freezing UI
        thread = threading.Thread(target=self._update_rules_status_worker, args=(op_event,))
        thread.daemon = True
        thread.start()
    
    def _update_rules_status_worker(self, op_event=None):
        """Worker thread for updating rule status"""
        try:
            if op_event:
                self._check_cancel_request(op_event)
                
            # Get all rules from the list control
            count = self.list_ctrl_rules.GetItemCount()
            wx.CallAfter(self.LogMessage, f"Checking update status for {count} rules...", "grey")
            
            for i in range(count):
                if op_event:
                    self._check_cancel_request(op_event)
                    
                # Get rule data
                rule_data_key = self.list_ctrl_rules.GetItemData(i)
                rule_data = self.list_item_data_rules.get(rule_data_key)
                
                if not rule_data:
                    continue
                    
                # Get rule name and ID for logging
                rule_name = rule_data.get("name", f"Rule {i+1}")
                rule_id = rule_data.get("id", "")
                    
                # Find and extract source URL
                description = ""
                source_url = ""
                
                try:
                    # Get detailed rule information
                    rule_details = self.api_client.get_rule_details(rule_id)
                    if rule_details and rule_details.get("success"):
                        rule_result = rule_details.get("result", {})
                        if rule_result:
                            description = rule_result.get("description", "")
                            source_url, list_prefix = self._parse_metadata(description)
                            
                            # Store source URL in rule data if found
                            if source_url:
                                rule_data["source_url"] = source_url
                                rule_data["list_prefix"] = list_prefix
                            
                    # Check update status if we have a source URL
                    if source_url:
                        wx.CallAfter(self.LogMessage, f"Checking updates for rule '{rule_name}'...", "grey")
                        update_status = self._check_update_status(description, source_url)
                        
                        # Update the list control with status
                        wx.CallAfter(self.list_ctrl_rules.SetItem, i, 4, update_status)
                        
                        # Update data map
                        rule_data["update_status"] = update_status
                        self.list_item_data_rules[rule_data_key] = rule_data
                    else:
                        # No source URL found
                        wx.CallAfter(self.list_ctrl_rules.SetItem, i, 4, "No source URL")
                        rule_data["update_status"] = "No source URL"
                        self.list_item_data_rules[rule_data_key] = rule_data
                        
                except Exception as e:
                    wx.CallAfter(self.LogMessage, f"Error checking rule '{rule_name}': {e}", "red")
                    wx.CallAfter(self.list_ctrl_rules.SetItem, i, 4, "Check failed")
                    rule_data["update_status"] = "Check failed"
                    self.list_item_data_rules[rule_data_key] = rule_data
                    
            # Update the item data map for sorting
            wx.CallAfter(lambda: self.list_ctrl_rules.SetItemDataMap(self.list_item_data_rules))
            wx.CallAfter(self.LogMessage, "Update check complete.", "green")
            wx.CallAfter(self.UpdateStatusBar, "Ready")
            
        except OperationCancelledError:
            wx.CallAfter(self.LogMessage, "Update check cancelled.", "orange")
            wx.CallAfter(self.UpdateStatusBar, "Ready")
        except Exception as e:
            wx.CallAfter(self.LogMessage, f"Error during update check: {e}", "red")
            wx.CallAfter(self.UpdateStatusBar, "Update check failed")
        
    def _update_progress_task(self, gauge, progress, message):
        def task():
            if gauge and gauge.IsShown():
                try:
                    gauge.SetValue(progress)
                    self.UpdateStatusBar(message)
                except Exception as e: print(f"Error updating gauge/statusbar: {e}")
        wx.CallAfter(task)
    def _pulse_progress_task(self, gauge, message):
        def task():
            if gauge and gauge.IsShown():
                try:
                    gauge.Pulse()
                    self.UpdateStatusBar(message)
                except Exception as e: print(f"Error pulsing gauge/statusbar: {e}")
        wx.CallAfter(task)
    def _check_cancel_request(self, cancelled_event):
        time.sleep(0.01)
        if cancelled_event.is_set(): raise OperationCancelledError("Operation cancelled by user.")
    def _load_and_create_worker(self, gauge, op_event, domains, prefix, rule_name, source_url=None, original_content=None):
        created_list_ids, created_rule_id, success = [], None, False; id_map_for_rule_expr = {}
        try:
            if not self.api_client: raise RuntimeError("API client is not available in worker thread.")
            num_lists_to_create = (len(domains) + MAX_DOMAINS_PER_LIST - 1) // MAX_DOMAINS_PER_LIST; current_progress = 0
            def log_and_progress(prog, msg, color=None): wx.CallAfter(lambda: (self.LogMessage(msg, color), self._update_progress_task(gauge, prog, msg)))
            domain_chunks = [domains[i:i + MAX_DOMAINS_PER_LIST] for i in range(0, len(domains), MAX_DOMAINS_PER_LIST)]
            wx.CallAfter(self.LogMessage, f"Creating {num_lists_to_create} list(s)...")
            num_digits = len(str(num_lists_to_create)) if num_lists_to_create > 0 else 1
            for i, chunk in enumerate(domain_chunks):
                list_num_str = str(i + 1).zfill(num_digits); list_name = f"{prefix}{list_num_str}"; current_progress += 1
                msg = f"Creating list '{list_name}' ({i + 1}/{num_lists_to_create})..."; log_and_progress(current_progress, msg); self._check_cancel_request(op_event)
                try:
                    response = self.api_client.create_list(list_name, chunk, timeout=LIST_CREATE_TIMEOUT_SECONDS)
                    if not response or not response.get("success"): errors = response.get("errors", [{"message": "Unknown API error"}]) if response else [{"message": "No response from API"}]; raise ValueError(f"API call failed to create list '{list_name}'. Error: {errors[0].get('message', 'N/A')}")
                    result = response.get("result"); list_id = result.get("id") if result else None
                    if not list_id: raise ValueError(f"API response missing ID for created list '{list_name}'.")
                    created_list_ids.append(list_id); id_map_for_rule_expr[list_id] = list_id
                    wx.CallAfter(self.LogMessage, f"Successfully created list '{list_name}' (ID: {list_id})")
                    if LIST_CREATE_DELAY_SECONDS > 0: time.sleep(LIST_CREATE_DELAY_SECONDS); self._check_cancel_request(op_event)
                except Exception as e: raise RuntimeError(f"Error creating list #{i+1} ('{list_name}'): {e}") from e
            if len(created_list_ids) != num_lists_to_create: raise RuntimeError(f"List creation count mismatch. Expected {num_lists_to_create}, created {len(created_list_ids)}.")
            current_progress += 1; msg = f"Creating rule '{rule_name}'..."; log_and_progress(current_progress, msg); self._check_cancel_request(op_event)
            if not created_list_ids: raise ValueError("Cannot create rule: No list IDs were generated.")
            try:
                # Calculate content hash for the original content
                content_hash = self._calculate_content_hash(original_content) if original_content else str(len("\n".join(domains)))
                self.LogMessage(f"Creating rule with hash: {content_hash}", "grey")
                rule_response = self.api_client.create_rule(rule_name, created_list_ids, id_map_for_rule_expr, enabled=True, source_url=source_url, list_prefix=prefix, content_hash=content_hash)
                if not rule_response or not rule_response.get("success"): errors = rule_response.get("errors", [{"message": "Unknown API error"}]) if rule_response else [{"message": "No response from API"}]; raise ConnectionError(f"API call failed to create rule '{rule_name}'. Error: {errors[0].get('message', 'N/A')}")
                result = rule_response.get("result"); created_rule_id = result.get("id") if result else None
                if not created_rule_id: raise ConnectionError("API response missing ID for created rule.")
                wx.CallAfter(self.LogMessage, f"Successfully created rule '{rule_name}' (ID: {created_rule_id})", "green"); success = True
            except Exception as e: raise RuntimeError(f"Error creating rule '{rule_name}': {e}") from e
            if success: wx.CallAfter(self.LogMessage, "Adblock configuration applied successfully!", "green"); wx.CallAfter(self.UpdateStatusBar, "Configuration applied successfully."); wx.CallAfter(self.OnRefresh)
        except OperationCancelledError as e:
            wx.CallAfter(self.LogMessage, f"Operation cancelled by user: {e}", "orange"); wx.CallAfter(self.UpdateStatusBar, "Apply cancelled.")
            if created_list_ids: wx.CallAfter(self.LogMessage, "Attempting to clean up partially created lists..."); cleanup_thread = threading.Thread(target=self._cleanup_items, args=(created_list_ids, [])); cleanup_thread.start()
            wx.CallAfter(self.OnRefresh)
        except Exception as e:
            wx.CallAfter(self.ShowError, f"Error during adblock application: {e}"); wx.CallAfter(self.LogMessage, f"PROCESS FAILED: {e}", "red"); wx.CallAfter(self.UpdateStatusBar, "Apply failed.")
            if not isinstance(e, RuntimeError) or "Pre-existing" not in str(e): wx.CallAfter(self.LogMessage, f"Traceback:\n{traceback.format_exc()}", "red")
            if created_list_ids or created_rule_id:
                wx.CallAfter(self.LogMessage, "Attempting to clean up partially created items...")
                rule_ids_to_cleanup = [created_rule_id] if created_rule_id else []; cleanup_thread = threading.Thread(target=self._cleanup_items, args=(created_list_ids, rule_ids_to_cleanup)); cleanup_thread.start()
            wx.CallAfter(self.OnRefresh)
        finally:
            wx.CallAfter(self._set_apply_enabled, True); wx.CallAfter(wx.EndBusyCursor)
            wx.CallAfter(self.lbl_source_display.SetLabel, "Source: None")
            wx.CallAfter(self.txt_list_prefix.SetValue, ""); wx.CallAfter(self.txt_rule_name.SetValue, "")
            self.adblock_filepath, self.adblock_url = None, None
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.EnableCancelButton, False)
            wx.CallAfter(self.UpdateStatusBar, "Ready")
    def _refresh_worker(self, gauge, op_event):
        fetched_lists, fetched_rules = [], []
        try:
            if not self.api_client: raise ConnectionError("API Client not initialized.")
            def log_and_progress(prog, msg, color=None): wx.CallAfter(lambda: (self.LogMessage(msg, color), self._update_progress_task(gauge, prog, msg)))
            msg = "Fetching Gateway Lists..."; log_and_progress(1, msg, "grey"); self._check_cancel_request(op_event)
            try: fetched_lists = self.api_client.get_lists(); wx.CallAfter(self.LogMessage, f"Found {len(fetched_lists)} lists.", "grey")
            except Exception as e: wx.CallAfter(self.LogMessage, f"Error fetching lists: {e}", "orange")
            msg = "Fetching Gateway Rules..."; log_and_progress(2, msg, "grey"); self._check_cancel_request(op_event)
            try: fetched_rules = self.api_client.get_rules(); wx.CallAfter(self.LogMessage, f"Found {len(fetched_rules)} rules.", "grey")
            except Exception as e: wx.CallAfter(self.LogMessage, f"Error fetching rules: {e}", "orange")

            # Populate the lists, then immediately check for updates
            wx.CallAfter(self._populate_list_ctrl, fetched_lists, fetched_rules)
            wx.CallAfter(self._update_rules_status, op_event)
            wx.CallAfter(self.LogMessage, "Refresh complete - checking for updates.") 
            wx.CallAfter(self.UpdateStatusBar, "Refresh complete.")
        except OperationCancelledError as e: wx.CallAfter(self.LogMessage, f"Refresh operation cancelled: {e}", "orange"); wx.CallAfter(self.UpdateStatusBar, "Refresh cancelled.")
        except ConnectionError as e: wx.CallAfter(self.ShowError, f"Refresh Error: Could not connect to Cloudflare API.\n{e}"); wx.CallAfter(self.UpdateStatusBar, "Refresh failed: Connection error.")
        except Exception as e: wx.CallAfter(self.ShowError, f"An unexpected error occurred during refresh: {e}"); wx.CallAfter(self.LogMessage, f"Refresh Traceback:\n{traceback.format_exc()}", "red"); wx.CallAfter(self.UpdateStatusBar, "Refresh failed: Unexpected error.")
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.EnableCancelButton, False)
            wx.CallAfter(self.UpdateStatusBar, "Ready")
    def _delete_items_worker(self, items_to_delete, gauge, op_event):
        deleted_count, failed_items, total_items = 0, [], len(items_to_delete)
        try:
            if not self.api_client: raise RuntimeError("API client is not available in worker thread.")
            def log_and_progress(prog, msg, color=None): wx.CallAfter(lambda: (self.LogMessage(msg, color), self._update_progress_task(gauge, prog, msg)))
            for i, item in enumerate(items_to_delete):
                item_type = item.get("type", "unknown"); item_id = item.get("id"); item_name = item.get("name", f"Unnamed {item_type}")
                current_progress = i + 1; self._check_cancel_request(op_event)
                if not item_id: msg = f"Skipping item '{item_name}' - No ID found."; wx.CallAfter(lambda m=msg: self.LogMessage(m, "orange")); failed_items.append(f"{item_name} (Missing ID)"); continue
                msg = f"Deleting {item_type} '{item_name}' ({current_progress}/{total_items})..."; log_and_progress(current_progress, msg)
                try:
                    if item_type.lower() == "list": self.api_client.delete_list(item_id)
                    elif item_type.lower() == "rule": self.api_client.delete_rule(item_id)
                    else: raise ValueError(f"Unknown item type encountered: '{item_type}'")
                    deleted_count += 1; wx.CallAfter(self.LogMessage, f"Successfully deleted '{item_name}'.")
                    if DELETE_DELAY_SECONDS > 0: time.sleep(DELETE_DELAY_SECONDS); self._check_cancel_request(op_event)
                except Exception as e: fail_msg = f"FAILED to delete {item_type} '{item_name}': {e}"; wx.CallAfter(self.LogMessage, fail_msg, "orange"); failed_items.append(f"'{item_name}' ({item_type})")
            final_color = "green" if not failed_items else "orange"
            final_msg = f"Deletion process finished. Successfully deleted {deleted_count}/{total_items} item(s)."
            status_msg = f"Deleted {deleted_count}/{total_items} items."
            if failed_items: final_msg += f" Failed to delete {len(failed_items)} item(s)."; status_msg += f" ({len(failed_items)} failed)"
            wx.CallAfter(self.LogMessage, final_msg, final_color); wx.CallAfter(self.UpdateStatusBar, status_msg)
            if failed_items: error_summary = f"Failed to delete the following items:\n - " + "\n - ".join(failed_items); wx.CallAfter(self.ShowError, error_summary)
            wx.CallAfter(self.OnRefresh)
        except OperationCancelledError as e: wx.CallAfter(self.LogMessage, f"Deletion operation cancelled: {e}", "orange"); wx.CallAfter(self.UpdateStatusBar, "Deletion cancelled."); wx.CallAfter(self.OnRefresh)
        except Exception as e: error_msg = f"An unexpected error occurred during item deletion: {e}"; wx.CallAfter(self.ShowError, error_msg); wx.CallAfter(self.LogMessage, f"Deletion Process FAILED: {e}\n{traceback.format_exc()}", "red"); wx.CallAfter(self.UpdateStatusBar, "Deletion failed: Unexpected error."); wx.CallAfter(self.OnRefresh)
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.EnableCancelButton, False)
            wx.CallAfter(self.UpdateStatusBar, "Ready")
    def _delete_rule_and_lists_worker(self, rule_ids, rule_names, list_uuids, gauge, op_event):
        deleted_rules_count, deleted_lists_count, failed_rules, failed_lists = 0, 0, [], []
        total_rules, total_lists, current_progress = len(rule_ids), len(list_uuids), 0
        total_ops = total_rules + total_lists
        try:
            if not self.api_client: raise RuntimeError("API client is not available in worker thread.")
            def log_and_progress(prog, msg, color=None): wx.CallAfter(lambda: (self.LogMessage(msg, color), self._update_progress_task(gauge, prog, msg)))
            if total_rules > 0:
                wx.CallAfter(self.LogMessage, f"Deleting {total_rules} rule(s)...")
                for i, (rule_id, rule_name) in enumerate(zip(rule_ids, rule_names)):
                    current_progress += 1; msg = f"Deleting rule '{rule_name}' ({i + 1}/{total_rules})..."; log_and_progress(current_progress, msg); self._check_cancel_request(op_event)
                    try: self.api_client.delete_rule(rule_id); deleted_rules_count += 1; wx.CallAfter(self.LogMessage, f"Successfully deleted rule '{rule_name}'."); time.sleep(DELETE_DELAY_SECONDS if DELETE_DELAY_SECONDS > 0 else 0); self._check_cancel_request(op_event)
                    except Exception as e: fail_msg = f"FAILED to delete rule '{rule_name}': {e}"; wx.CallAfter(self.LogMessage, fail_msg, "red"); failed_rules.append(rule_name)
            if total_lists > 0:
                wx.CallAfter(self.LogMessage, f"Deleting {total_lists} associated list(s)...")
                for i, list_uuid in enumerate(list_uuids):
                    current_progress += 1; display_uuid = f"{list_uuid[:8]}..." if len(list_uuid) > 8 else list_uuid; msg = f"Deleting associated list {i + 1}/{total_lists} (ID: {display_uuid})..."; log_and_progress(current_progress, msg); self._check_cancel_request(op_event)
                    try: self.api_client.delete_list(list_uuid); deleted_lists_count += 1; time.sleep(DELETE_DELAY_SECONDS if DELETE_DELAY_SECONDS > 0 else 0); self._check_cancel_request(op_event)
                    except Exception as e: fail_msg = f"FAILED to delete associated list ID {list_uuid}: {e}"; wx.CallAfter(self.LogMessage, fail_msg, "orange"); failed_lists.append(list_uuid)
            final_color = "green" if not failed_rules and not failed_lists else "orange"
            final_message = f"Deletion process finished. Rules: {deleted_rules_count}/{total_rules} deleted"; final_message += f" ({len(failed_rules)} failed)." if failed_rules else "."
            final_message += f" Lists: {deleted_lists_count}/{total_lists} deleted"; final_message += f" ({len(failed_lists)} failed)." if failed_lists else "."
            status_msg = f"Deleted {deleted_rules_count} rule(s), {deleted_lists_count} list(s)."
            if failed_rules or failed_lists: status_msg += f" ({len(failed_rules) + len(failed_lists)} failed)"
            wx.CallAfter(self.LogMessage, final_message, final_color); wx.CallAfter(self.UpdateStatusBar, status_msg)
            if failed_rules or failed_lists:
                error_summary = f"Deletion completed with errors:\n";
                if failed_rules: error_summary += f"- Failed Rules:\n   - " + "\n   - ".join(failed_rules) + "\n"
                if failed_lists: error_summary += f"- Failed Lists (UUIDs):\n   - " + "\n   - ".join(failed_lists)
                wx.CallAfter(self.ShowError, error_summary)
            wx.CallAfter(self.OnRefresh)
        except OperationCancelledError as e: wx.CallAfter(self.LogMessage, f"Deletion operation cancelled: {e}", "orange"); wx.CallAfter(self.UpdateStatusBar, "Deletion cancelled."); wx.CallAfter(self.OnRefresh)
        except Exception as e: error_msg = f"An unexpected error occurred during rule/list deletion: {e}"; wx.CallAfter(self.ShowError, error_msg); wx.CallAfter(self.LogMessage, f"Deletion Process FAILED: {e}\n{traceback.format_exc()}", "red"); wx.CallAfter(self.UpdateStatusBar, "Deletion failed: Unexpected error."); wx.CallAfter(self.OnRefresh)
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.EnableCancelButton, False)
            wx.CallAfter(self.UpdateStatusBar, "Ready")
    def _update_rule_worker(self, old_rule_id, rule_name, source_url, list_prefix, gauge, op_event):
        newly_created_list_ids, newly_created_rule_id, success = [], None, False; progress_step = 0
        def update_gauge(message): nonlocal progress_step; progress_step += 1; wx.CallAfter(self._pulse_progress_task, gauge, message)
        try:
            if not self.api_client: raise RuntimeError("API client not available.")
            update_gauge("Fetching updated list from URL..."); wx.CallAfter(self.LogMessage, f"Fetching updated content from {source_url}...")
            new_content = None
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}; response = requests.get(source_url, timeout=60, headers=headers, allow_redirects=True); response.raise_for_status()
                try: new_content = response.content.decode('utf-8')
                except UnicodeDecodeError:
                    if HAS_CHARDET: detected = chardet.detect(response.content); encoding = detected.get('encoding', 'latin-1') if detected else 'latin-1'; wx.CallAfter(self.LogMessage, f"Detected encoding: {encoding}", "grey"); new_content = response.content.decode(encoding, errors='ignore')
                    else: wx.CallAfter(self.LogMessage,"UTF-8 decode failed, fallback to latin-1.", "orange"); new_content = response.content.decode('latin-1', errors='ignore')
                wx.CallAfter(self.LogMessage, "Successfully fetched updated content.")
            except Exception as e: raise RuntimeError(f"Failed to fetch updated content from URL: {e}") from e
            if new_content is None: raise RuntimeError("Failed to decode content from URL.")
            update_gauge("Processing updated domain list..."); wx.CallAfter(self.LogMessage, "Processing updated domain list...")
            new_domains = self._process_adblock_content(new_content)
            if not new_domains: raise RuntimeError("No valid domains found in the updated list content.")
            wx.CallAfter(self.LogMessage, f"Found {len(new_domains):,} valid domains in updated list."); num_new_lists_needed = (len(new_domains) + MAX_DOMAINS_PER_LIST - 1) // MAX_DOMAINS_PER_LIST
            update_gauge("Fetching details of existing rule..."); wx.CallAfter(self.LogMessage, f"Fetching details for old rule ID: {old_rule_id}...")
            old_list_uuids = set()
            try:
                rule_details_resp = self.api_client.get_rule_details(old_rule_id)
                if not rule_details_resp or not rule_details_resp.get("success"): raise ConnectionError(f"Failed to fetch details for rule '{rule_name}': {rule_details_resp}")
                rule_obj = rule_details_resp.get("result")
                if not rule_obj: raise ValueError(f"Rule details missing for '{rule_name}'.")
                traffic_expr = rule_obj.get("traffic", "")
                if traffic_expr:
                    extracted = set(re.findall(r'\$([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})', traffic_expr))
                    if extracted: old_list_uuids = extracted; wx.CallAfter(self.LogMessage, f"Found {len(old_list_uuids)} associated list UUID(s) in old rule.")
                    else: wx.CallAfter(self.LogMessage, "Could not parse list UUIDs from old rule traffic expression.", "orange")
                else: wx.CallAfter(self.LogMessage, "Old rule has no traffic expression.", "orange")
            except Exception as e: raise RuntimeError(f"Error getting details or parsing old rule '{rule_name}': {e}") from e
            update_gauge("Deleting existing rule..."); wx.CallAfter(self.LogMessage, f"Deleting old rule '{rule_name}' ({old_rule_id})...")
            try: self.api_client.delete_rule(old_rule_id); wx.CallAfter(self.LogMessage, "Successfully deleted old rule.")
            except Exception as e: raise RuntimeError(f"Failed to delete old rule '{rule_name}': {e}") from e
            if old_list_uuids:
                wx.CallAfter(self.LogMessage, f"Deleting {len(old_list_uuids)} old associated list(s)...")
                for i, list_uuid in enumerate(old_list_uuids):
                    update_gauge(f"Deleting old list {i+1}/{len(old_list_uuids)}...")
                    try:
                        self.api_client.delete_list(list_uuid); wx.CallAfter(self.LogMessage, f"Deleted old list {list_uuid[:8]}...")
                        if DELETE_DELAY_SECONDS > 0: time.sleep(DELETE_DELAY_SECONDS); self._check_cancel_request(op_event)
                    except Exception as e: wx.CallAfter(self.LogMessage, f"WARNING: Failed to delete old list {list_uuid}: {e}. Continuing update...", "orange")
            else: wx.CallAfter(self.LogMessage, "No old lists found to delete.", "grey")
            wx.CallAfter(self.LogMessage, f"Creating {num_new_lists_needed} new list(s)...")
            new_domain_chunks = [new_domains[i:i + MAX_DOMAINS_PER_LIST] for i in range(0, len(new_domains), MAX_DOMAINS_PER_LIST)]
            num_digits = len(str(num_new_lists_needed)) if num_new_lists_needed > 0 else 1; new_id_map = {}
            for i, chunk in enumerate(new_domain_chunks):
                list_num_str = str(i + 1).zfill(num_digits); new_list_name = f"{list_prefix}{list_num_str}"
                update_gauge(f"Creating new list {i+1}/{num_new_lists_needed}..."); wx.CallAfter(self.LogMessage, f"Creating new list '{new_list_name}'...")
                try:
                    response = self.api_client.create_list(new_list_name, chunk, timeout=LIST_CREATE_TIMEOUT_SECONDS)
                    if not response or not response.get("success"): raise ValueError(f"API call failed: {response.get('errors', 'Unknown error')}")
                    result = response.get("result"); list_id = result.get("id") if result else None;
                    if not list_id: raise ValueError("API response missing ID.")
                    newly_created_list_ids.append(list_id); new_id_map[list_id] = list_id
                    wx.CallAfter(self.LogMessage, f"Created new list '{new_list_name}' (ID: {list_id})")
                    if LIST_CREATE_DELAY_SECONDS > 0: time.sleep(LIST_CREATE_DELAY_SECONDS); self._check_cancel_request(op_event)
                except Exception as e: raise RuntimeError(f"Error creating new list '{new_list_name}': {e}") from e
            if len(newly_created_list_ids) != num_new_lists_needed: raise RuntimeError("New list creation count mismatch.")
            update_gauge("Creating new rule..."); wx.CallAfter(self.LogMessage, f"Creating new rule '{rule_name}'...")
            if not newly_created_list_ids: raise ValueError("Cannot create rule: No new list IDs were generated.")
            try:
                # Calculate content hash from the updated content
                content_hash = self._calculate_content_hash(new_content)
                wx.CallAfter(self.LogMessage, f"Calculated content hash for update: {content_hash}", "grey")
                
                rule_response = self.api_client.create_rule(rule_name, newly_created_list_ids, new_id_map, 
                                                          enabled=True, source_url=source_url, 
                                                          list_prefix=list_prefix, content_hash=content_hash)
                
                if not rule_response or not rule_response.get("success"): raise ConnectionError(f"API call failed: {rule_response.get('errors', 'Unknown error')}")
                result = rule_response.get("result"); newly_created_rule_id = result.get("id") if result else None
                if not newly_created_rule_id: raise ConnectionError("API response missing ID for new rule.")
                wx.CallAfter(self.LogMessage, f"Successfully created new rule '{rule_name}' (ID: {newly_created_rule_id}) with hash: {content_hash}", "green"); success = True
            except Exception as e: raise RuntimeError(f"Error creating new rule '{rule_name}': {e}") from e
            if success: wx.CallAfter(self.LogMessage, f"Rule '{rule_name}' updated successfully!", "green"); wx.CallAfter(self.UpdateStatusBar, f"Rule '{rule_name}' updated.")
        except OperationCancelledError as e:
            wx.CallAfter(self.LogMessage, f"Rule update cancelled: {e}", "orange"); wx.CallAfter(self.UpdateStatusBar, "Rule update cancelled.")
            if newly_created_list_ids or newly_created_rule_id:
                wx.CallAfter(self.LogMessage, "Attempting cleanup of partially created items during update...")
                rule_ids_to_cleanup = [newly_created_rule_id] if newly_created_rule_id else []; cleanup_thread = threading.Thread(target=self._cleanup_items, args=(newly_created_list_ids, rule_ids_to_cleanup)); cleanup_thread.start()
        except Exception as e:
            wx.CallAfter(self.ShowError, f"Error during rule update: {e}"); wx.CallAfter(self.LogMessage, f"UPDATE FAILED for rule '{rule_name}': {e}", "red"); wx.CallAfter(self.LogMessage, f"Traceback:\n{traceback.format_exc()}", "red"); wx.CallAfter(self.UpdateStatusBar, "Rule update failed.")
            if newly_created_list_ids or newly_created_rule_id:
                wx.CallAfter(self.LogMessage, "Attempting cleanup of partially created items during update...")
                rule_ids_to_cleanup = [newly_created_rule_id] if newly_created_rule_id else []; cleanup_thread = threading.Thread(target=self._cleanup_items, args=(newly_created_list_ids, rule_ids_to_cleanup)); cleanup_thread.start()
        finally:
            wx.CallAfter(self.OnRefresh)
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.EnableCancelButton, False)
            wx.CallAfter(self.UpdateStatusBar, "Ready")
    def _delete_all_worker(self, lists_to_delete, rules_to_delete, gauge, op_event):
        deleted_rules, deleted_lists, failed_rules, failed_lists = 0, 0, [], []
        current_progress, total_items = 0, len(lists_to_delete) + len(rules_to_delete)
        try:
            if not self.api_client: raise RuntimeError("API client unavailable.")
            def log_and_progress(prog, msg, color=None): wx.CallAfter(lambda: (self.LogMessage(msg, color), self._update_progress_task(gauge, prog, msg)))
            current_progress += 1; start_msg = f"Starting 'Delete All (Legacy)' for {total_items} item(s)..."; log_and_progress(current_progress, start_msg); self._check_cancel_request(op_event)
            num_rules = len(rules_to_delete)
            if num_rules > 0:
                wx.CallAfter(self.LogMessage, f"Deleting {num_rules} rule(s)...")
                for i, rule in enumerate(rules_to_delete):
                    rule_id, rule_name = rule.get("id"), rule.get("name", "Unknown Rule"); current_progress += 1
                    msg = f"Deleting rule '{rule_name}' ({i+1}/{num_rules})..."; log_and_progress(current_progress, msg); self._check_cancel_request(op_event)
                    if rule_id:
                        try: self.api_client.delete_rule(rule_id); deleted_rules += 1; wx.CallAfter(self.LogMessage, f"Deleted rule '{rule_name}'."); time.sleep(DELETE_DELAY_SECONDS if DELETE_DELAY_SECONDS > 0 else 0); self._check_cancel_request(op_event)
                        except Exception as e: fail_msg = f"FAILED delete rule '{rule_name}': {e}"; wx.CallAfter(self.LogMessage, fail_msg, "orange"); failed_rules.append(f"'{rule_name}'")
                    else: skip_msg = f"SKIPPED rule '{rule_name}' (No ID)."; wx.CallAfter(self.LogMessage, skip_msg, "orange"); failed_rules.append(f"'{rule_name}' (No ID)")
            num_lists = len(lists_to_delete)
            if num_lists > 0:
                wx.CallAfter(self.LogMessage, f"Deleting {num_lists} list(s)...")
                for i, lst in enumerate(lists_to_delete):
                    list_id, list_name = lst.get("id"), lst.get("name", "Unknown List"); current_progress += 1
                    msg = f"Deleting list '{list_name}' ({i+1}/{num_lists})..."; log_and_progress(current_progress, msg); self._check_cancel_request(op_event)
                    if list_id:
                        try: self.api_client.delete_list(list_id); deleted_lists += 1; wx.CallAfter(self.LogMessage, f"Deleted list '{list_name}'."); time.sleep(DELETE_DELAY_SECONDS if DELETE_DELAY_SECONDS > 0 else 0); self._check_cancel_request(op_event)
                        except Exception as e: fail_msg = f"FAILED delete list '{list_name}': {e}"; wx.CallAfter(self.LogMessage, fail_msg, "orange"); failed_lists.append(f"'{list_name}'")
                    else: skip_msg = f"SKIPPED list '{list_name}' (No ID)."; wx.CallAfter(self.LogMessage, skip_msg, "orange"); failed_lists.append(f"'{list_name}' (No ID)")
            total_deleted, total_failed = deleted_lists + deleted_rules, len(failed_lists) + len(failed_rules)
            final_color = "green" if total_failed == 0 else "orange"
            completion_msg = f"'Delete All (Legacy)' finished. Deleted: {total_deleted}. Failed: {total_failed}."; wx.CallAfter(self.LogMessage, completion_msg, final_color); wx.CallAfter(self.UpdateStatusBar, f"Delete All finished: {total_deleted} deleted, {total_failed} failed.")
            if total_failed > 0:
                errors = []
                if failed_rules: errors.append(f"Failed Rules:\n   - " + "\n   - ".join(failed_rules))
                if failed_lists: errors.append(f"Failed Lists:\n   - " + "\n   - ".join(failed_lists))
                wx.CallAfter(self.ShowError, f"Failed to delete {total_failed} items:\n\n" + "\n".join(errors))
            wx.CallAfter(self.OnRefresh)
        except OperationCancelledError as e: wx.CallAfter(self.LogMessage, f"'Delete All (Legacy)' operation cancelled: {e}", "orange"); wx.CallAfter(self.UpdateStatusBar, "Delete All cancelled."); wx.CallAfter(self.OnRefresh)
        except Exception as e: error_msg = f"Unexpected error during 'Delete All (Legacy)': {e}"; wx.CallAfter(self.ShowError, error_msg); wx.CallAfter(self.LogMessage, f"'Delete All (Legacy)' FAILED: {e}\n{traceback.format_exc()}", "red"); wx.CallAfter(self.UpdateStatusBar, "Delete All failed: Unexpected error."); wx.CallAfter(self.OnRefresh)
        finally:
            wx.CallAfter(gauge.Hide)
            wx.CallAfter(self.custom_status_bar.Layout)
            wx.CallAfter(gauge.SetValue, 0)
            wx.CallAfter(self.EnableCancelButton, False)
            wx.CallAfter(self.UpdateStatusBar, "Ready")
    def _process_adblock_content(self, content):
        domains = set()
        domain_pattern = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")
        ip_hosts_pattern = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1)\s+(.*)")
        dnsmasq_pattern = re.compile(r"^local=/(.+?)/")
        wildcard_pattern = re.compile(r"^\*\.(.+)$")
        rpz_pattern = re.compile(r"^(?:\*\.)?([a-zA-Z0-9.-]+)\s+CNAME\s+\.$")
        adblock_patterns = [
            re.compile(r"^\|\|([a-zA-Z0-9.-]+)[\^|/$]?(?:$|\s|,)"),
            re.compile(r"^([a-zA-Z0-9.-]+)$")
        ]
        lines = content.splitlines()
        processed_lines = 0
        if len(lines) > 100:
            wx.CallAfter(self.LogMessage, f"Processing {len(lines):,} lines...")
            wx.CallAfter(self.UpdateStatusBar, f"Processing {len(lines):,} lines...")
        for line in lines:
            processed_lines += 1
            line = line.strip()
            if not line or line.startswith(('#', '!', '[', '/', ';')) or 'localhost' in line or line.startswith('@@'):
                continue
            potential_domain = None
            matched = False
            ip_match = ip_hosts_pattern.match(line)
            if ip_match:
                potential_domains_str = ip_match.group(1).split('#')[0].strip()
                potential_domains = potential_domains_str.split()
                for p_dom in potential_domains:
                    p_dom = p_dom.strip('.').lower()
                    if p_dom and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", p_dom) and domain_pattern.match(p_dom):
                        domains.add(p_dom)
                matched = True
                continue
            dnsmasq_match = dnsmasq_pattern.match(line)
            if dnsmasq_match:
                potential_domain = dnsmasq_match.group(1)
                matched = True
            if not matched:
                wildcard_match = wildcard_pattern.match(line)
                if wildcard_match:
                    potential_domain = wildcard_match.group(1)
                    matched = True
            if not matched:
                rpz_pattern = rpz_pattern.match(line)
                if rpz_match:
                    potential_domain = rpz_match.group(1)
                    matched = True
            if not matched:
                for pattern in adblock_patterns:
                    match = pattern.match(line)
                    if match:
                        potential_domain = match.group(1).lower().strip('.').split('#')[0].strip().split(';')[0].strip()
                        matched = True
                        break
            if potential_domain:
                potential_domain = potential_domain.lower().strip('.')
                if potential_domain and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", potential_domain) and domain_pattern.match(potential_domain):
                    domains.add(potential_domain)
        if not domains:
            wx.CallAfter(self.LogMessage, "Warning: No valid domains were extracted from the provided content.", "orange")
            wx.CallAfter(self.UpdateStatusBar, "Warning: No valid domains extracted.")
        else:
             wx.CallAfter(self.UpdateStatusBar, f"Processed {len(domains):,} domains.")
        return sorted(list(domains))
    def _cleanup_items(self, list_ids_to_delete, rule_ids_to_delete):
        if not list_ids_to_delete and not rule_ids_to_delete: wx.CallAfter(self.LogMessage, "Cleanup: No items specified for cleanup.", "grey"); return
        temp_api_client = None
        try: temp_api_client = CloudflareAPI(self.api_token, self.account_id)
        except Exception as api_err: wx.CallAfter(self.LogMessage, f"Cleanup Error: Failed to initialize API client for cleanup: {api_err}", "red"); return
        num_rules, num_lists = len(rule_ids_to_delete), len(list_ids_to_delete)
        wx.CallAfter(self.LogMessage, f"Cleanup: Attempting to delete {num_rules} rule(s) and {num_lists} list(s)...", "grey")
        wx.CallAfter(self.UpdateStatusBar, f"Cleaning up {num_rules + num_lists} items...")
        deleted_rules, deleted_lists = 0, 0
        for rule_id in rule_ids_to_delete:
            if not rule_id: continue
            try: wx.CallAfter(self.LogMessage, f"Cleanup: Deleting rule {rule_id}...", "grey"); temp_api_client.delete_rule(rule_id); deleted_rules += 1; wx.CallAfter(self.LogMessage, f"Cleanup: Successfully deleted rule {rule_id}.", "grey"); time.sleep(DELETE_DELAY_SECONDS if DELETE_DELAY_SECONDS > 0 else 0)
            except Exception as ex: wx.CallAfter(self.LogMessage, f"Cleanup WARNING: Failed to delete rule {rule_id}: {ex}", "orange")
        for list_id in list_ids_to_delete:
            if not list_id: continue
            try: wx.CallAfter(self.LogMessage, f"Cleanup: Deleting list {list_id}...", "grey"); temp_api_client.delete_list(list_id); deleted_lists += 1; wx.CallAfter(self.LogMessage, f"Cleanup: Successfully deleted list {list_id}.", "grey"); time.sleep(DELETE_DELAY_SECONDS if DELETE_DELAY_SECONDS > 0 else 0)
            except Exception as ex: wx.CallAfter(self.LogMessage, f"Cleanup WARNING: Failed to delete list {list_id}: {ex}", "orange")
        wx.CallAfter(self.LogMessage, f"Cleanup finished. Deleted {deleted_rules}/{num_rules} rules, {deleted_lists}/{num_lists} lists.", "grey")
        wx.CallAfter(self.UpdateStatusBar, f"Cleanup finished.")
    def _parse_metadata(self, description):
        url, prefix = None, None
        if description and METADATA_MARKER_PREFIX in description and METADATA_MARKER_SUFFIX in description:
            start_marker_idx = description.find(METADATA_MARKER_PREFIX); end_marker_idx = description.find(METADATA_MARKER_SUFFIX, start_marker_idx)
            if start_marker_idx != -1 and end_marker_idx != -1:
                content_start = start_marker_idx + len(METADATA_MARKER_PREFIX); metadata_content = description[content_start:end_marker_idx]
                url_key_idx = metadata_content.find(METADATA_URL_KEY); prefix_key_idx = metadata_content.find(METADATA_PREFIX_KEY)
                if url_key_idx != -1:
                    url_start_val_idx = url_key_idx + len(METADATA_URL_KEY); url_end_val_idx = prefix_key_idx if prefix_key_idx != -1 and prefix_key_idx > url_key_idx else len(metadata_content)
                    url = metadata_content[url_start_val_idx:url_end_val_idx].strip().rstrip(':')
                if prefix_key_idx != -1:
                    prefix_start_val_idx = prefix_key_idx + len(METADATA_PREFIX_KEY); prefix_end_val_idx = url_key_idx if url_key_idx != -1 and url_key_idx > prefix_key_idx else len(metadata_content)
                    prefix = metadata_content[prefix_start_val_idx:prefix_end_val_idx].strip().rstrip(':')
        return url, prefix
    def _populate_list_ctrl(self, fetched_lists, fetched_rules):
        if not self.list_ctrl_lists or not self.list_ctrl_rules: print("Error: List controls not available during UI population."); self.LogMessage("Internal Error: UI List controls not ready.", "red"); return
        try:
            self.list_ctrl_lists.Freeze(); self.list_ctrl_lists.DeleteAllItems(); self.list_item_data_lists = {}; list_idx_counter = 0
            valid_lists = fetched_lists if isinstance(fetched_lists, list) else []
            list_data_to_display = [{"id": l.get("id"), "name": l.get("name"), "count": l.get("count", 0)} for l in valid_lists if l.get("id") and l.get("name") is not None]
            list_data_to_display.sort(key=lambda x: x.get('name', '').lower())
            for list_data in list_data_to_display:
                list_id = list_data["id"]; list_name = list_data["name"]; item_count = list_data.get("count", 0)
                idx = self.list_ctrl_lists.InsertItem(list_idx_counter, list_name); self.list_ctrl_lists.SetItem(idx, 1, list_id); self.list_ctrl_lists.SetItem(idx, 2, f"{item_count:,}")
                item_tuple = ("list", list_id); self.list_ctrl_lists.SetItemData(idx, list_idx_counter); self.list_item_data_lists[list_idx_counter] = item_tuple; list_idx_counter += 1
            self.list_ctrl_lists.SetItemDataMap(self.list_item_data_lists)
        except Exception as e: print(f"Error populating lists tab: {e}"); traceback.print_exc(); self.LogMessage(f"Error updating lists tab display: {e}", "red")
        finally:
            if self.list_ctrl_lists: self.list_ctrl_lists.Thaw()
        try:
            self.list_ctrl_rules.Freeze(); self.list_ctrl_rules.DeleteAllItems(); self.list_item_data_rules = {}; rule_idx_counter = 0
            valid_rules = fetched_rules if isinstance(fetched_rules, list) else []
            rule_data_to_display = [{"id": r.get("id"), "name": r.get("name"), "enabled": r.get("enabled", False), "description": r.get("description","")} for r in valid_rules if r.get("id") and r.get("name") is not None]
            rule_data_to_display.sort(key=lambda x: x.get('name', '').lower())
            for rule_data in rule_data_to_display:
                rule_id = rule_data["id"]; rule_name = rule_data["name"]; enabled_status = "Yes" if rule_data.get("enabled", False) else "No"; description = rule_data.get("description", "")
                source_url, list_prefix = self._parse_metadata(description); source_display = "URL" if source_url else "Manual"
                idx = self.list_ctrl_rules.InsertItem(rule_idx_counter, rule_name); self.list_ctrl_rules.SetItem(idx, 1, rule_id); self.list_ctrl_rules.SetItem(idx, 2, enabled_status); self.list_ctrl_rules.SetItem(idx, 3, source_display)
                item_dict = {"type": "rule", "id": rule_id, "name": rule_name, "enabled": rule_data.get("enabled", False), "source_url": source_url, "list_prefix": list_prefix}
                self.list_ctrl_rules.SetItemData(idx, rule_idx_counter); self.list_item_data_rules[rule_idx_counter] = item_dict; rule_idx_counter += 1
            self.list_ctrl_rules.SetItemDataMap(self.list_item_data_rules)
        except Exception as e: print(f"Error populating rules tab: {e}"); traceback.print_exc(); self.LogMessage(f"Error updating rules tab display: {e}", "red")
        finally:
            if self.list_ctrl_rules: self.list_ctrl_rules.Thaw()
            self._update_management_button_states()
    def _validate_naming_options(self):
        if not all(hasattr(self, ctrl) and getattr(self, ctrl) for ctrl in ['txt_list_prefix', 'txt_rule_name']): print("Error: Naming UI elements not initialized during validation."); self.ShowError("Internal UI Error: Naming fields are not ready."); return False
        prefix = self.txt_list_prefix.GetValue().strip(); rule_name = self.txt_rule_name.GetValue().strip()
        if not prefix: self.ShowError("Please enter a 'List Name Prefix' before applying."); self.txt_list_prefix.SetFocus(); return False
        if not rule_name: self.ShowError("Please enter a 'Rule Name' before applying."); self.txt_rule_name.SetFocus(); return False
        return True
    def LogMessage(self, message, color=None):
        if not hasattr(self, 'log_ctrl') or not self.log_ctrl: print(f"LOG (UI Not Ready): {message}"); return
        wx.CallAfter(self._do_log, message, color)
    def _do_log(self, message, color):
        if not self.log_ctrl: return
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S"); log_entry = f"[{timestamp}] {message}\n"
            insertion_point = self.log_ctrl.GetLastPosition(); self.log_ctrl.AppendText(log_entry); end_point = self.log_ctrl.GetLastPosition()
            if color:
                color_map = {"red": wx.RED, "green": wx.Colour(0, 128, 0), "blue": wx.BLUE, "orange": wx.Colour(255, 165, 0), "grey": wx.Colour(128, 128, 128), "gray": wx.Colour(128, 128, 128)}
                text_color = color_map.get(str(color).lower())
                if text_color: style = wx.TextAttr(text_color); self.log_ctrl.SetStyle(insertion_point, end_point, style)
            self.log_ctrl.ShowPosition(end_point)
        except Exception as e: print(f"Error writing to log control: {e}\nOriginal Message: {message}"); traceback.print_exc()
    def UpdateStatusBar(self, text):
        if self.status_text:
             wx.CallAfter(self.status_text.SetLabel, text)
    def ShowError(self, message):
        def show_and_log(): wx.MessageBox(message, "Error", wx.OK | wx.ICON_ERROR, self); self.LogMessage(f"ERROR: {message}", "red")
        if wx.IsMainThread(): show_and_log()
        else: wx.CallAfter(show_and_log)
    def ShowInfo(self, message):
        def show_and_log(): wx.MessageBox(message, "Information", wx.OK | wx.ICON_INFORMATION, self); self.LogMessage(f"INFO: {message}", "grey")
        if wx.IsMainThread(): show_and_log()
        else: wx.CallAfter(show_and_log)
if __name__ == '__main__':
    app = wx.App(redirect=False)
    app.SetAppName(APP_NAME)
    app.SetAppDisplayName(APP_NAME)
    login_dialog = LoginDialog(None)
    result = login_dialog.ShowModal()
    account_id, api_token = login_dialog.account_id, login_dialog.api_token
    login_dialog.Destroy()
    if result == wx.ID_OK: frame = MainFrame(None, account_id=account_id, api_token=api_token); app.MainLoop()
    else: print("Login cancelled or failed. Exiting application.")

