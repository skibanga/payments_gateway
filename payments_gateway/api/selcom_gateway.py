import hmac
import re
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from selcom_apigw_client import apigwClient

PHONE_PATTERN = re.compile(r"^255\d{9}$")

SUCCESS_CODES = {"000"}
IN_PROGRESS_CODES = {"111", "927"}
AMBIGUOUS_CODES = {"999"}


@frappe.whitelist(allow_guest=True)
def send_ussd_push():
    """Send a Selcom Wallet Push USSD request using a selected account."""
    data = frappe.request.get_json() or {}

    required_fields = ["api_key", "api_secret", "utilityref", "amount", "msisdn"]
    for field in required_fields:
        if not data.get(field):
            return error_response(_("Missing required field: {0}").format(field))

    api_key = data.get("api_key")
    api_secret = data.get("api_secret")
    account_name = data.get("account")

    api_doc = get_api_doc(api_key, api_secret)
    if not api_doc:
        return error_response(_("Invalid API credentials."))

    if api_doc.enabled == 0:
        return error_response(_("API key is disabled."))

    if api_doc.expiry_date and frappe.utils.getdate(api_doc.expiry_date) < frappe.utils.getdate():
        return error_response(_("API key has expired."))

    allowed_accounts = frappe.get_all(
        "Selcom Gateway API Allowed Account",
        filters={"parent": api_doc.name},
        pluck="account",
    )

    if not account_name:
        if len(allowed_accounts) == 1:
            account_name = allowed_accounts[0]
        else:
            return error_response(_("Account is required for this request."))

    if allowed_accounts and account_name not in allowed_accounts:
        return error_response(_("Account is not allowed for this API key."))

    try:
        account_doc = frappe.get_doc("Selcom Gateway Account", account_name)
    except frappe.DoesNotExistError:
        return error_response(_("Account not found."))

    if not account_doc.enabled:
        return error_response(_("Account is disabled."))

    if account_doc.account_users:
        allowed_users = [
            row.user for row in account_doc.account_users if frappe.utils.cint(row.enabled)
        ]
        if allowed_users and api_doc.user not in allowed_users:
            return error_response(_("User is not allowed to use this account."))

    amount = flt(data.get("amount"))
    if amount <= 0:
        return error_response(_("Amount must be greater than zero."))

    if account_doc.min_amount and amount < flt(account_doc.min_amount):
        return error_response(_("Amount is below the minimum allowed."))

    if account_doc.max_amount and amount > flt(account_doc.max_amount):
        return error_response(_("Amount is above the maximum allowed."))

    msisdn = normalize_msisdn(data.get("msisdn"))
    if not PHONE_PATTERN.match(msisdn):
        return error_response(_("Invalid MSISDN format. Use 255XXXXXXXXX."))

    utilityref = str(data.get("utilityref")).strip()
    if not utilityref:
        return error_response(_("Utility reference is required."))

    transid = data.get("transid") or frappe.generate_hash(length=20)

    if not account_doc.vendor:
        return error_response(_("Account vendor is not configured."))

    payload = {
        "transid": transid,
        "utilityref": utilityref,
        "amount": amount,
        "vendor": account_doc.vendor,
        "msisdn": msisdn,
    }

    transaction_doc = frappe.get_doc(
        {
            "doctype": "Selcom Gateway Transaction",
            "api_key": api_doc.name,
            "account": account_doc.name,
            "transid": transid,
            "utilityref": utilityref,
            "msisdn": msisdn,
            "amount": amount,
            "currency": account_doc.currency,
            "status": "PENDING",
            "attempts": 1,
            "request_payload": frappe.as_json(payload),
        }
    )
    transaction_doc.insert(ignore_permissions=True)

    try:
        response = send_selcom_request(account_doc, payload)
        update_transaction_from_response(transaction_doc, response)

        return {
            "status": "success",
            "message": "USSD push request submitted",
            "data": {
                "transaction": transaction_doc.name,
                "transid": transid,
                "status": transaction_doc.status,
                "reference": transaction_doc.reference,
                "resultcode": transaction_doc.resultcode,
                "message": transaction_doc.message,
            },
        }
    except Exception as exc:
        transaction_doc.status = "FAILED"
        transaction_doc.message = str(exc)
        transaction_doc.save(ignore_permissions=True)
        frappe.log_error(str(exc), "Selcom USSD Push Error")
        return error_response(_("Failed to submit USSD push request."))


@frappe.whitelist(allow_guest=True)
def query_transaction_status():
    """Query transaction status using Selcom reference or transid."""
    data = frappe.request.get_json() or {}

    required_fields = ["api_key", "api_secret"]
    for field in required_fields:
        if not data.get(field):
            return error_response(_("Missing required field: {0}").format(field))

    api_doc = get_api_doc(data.get("api_key"), data.get("api_secret"))
    if not api_doc:
        return error_response(_("Invalid API credentials."))

    transaction_name = data.get("transaction")
    transid = data.get("transid")

    if not transaction_name and not transid:
        return error_response(_("Provide transaction or transid."))

    if transaction_name:
        transaction_doc = frappe.get_doc("Selcom Gateway Transaction", transaction_name)
    else:
        transactions = frappe.get_all(
            "Selcom Gateway Transaction",
            filters={"transid": transid, "api_key": api_doc.name},
            fields=["name"],
            order_by="modified desc",
            limit=1,
        )
        if not transactions:
            return error_response(_("Transaction not found."))
        transaction_doc = frappe.get_doc("Selcom Gateway Transaction", transactions[0].name)

    if transaction_doc.api_key != api_doc.name:
        return error_response(_("Transaction does not belong to this API key."))

    try:
        response = fetch_transaction_status(transaction_doc)

        return {
            "status": "success",
            "message": "Status fetched successfully",
            "data": {
                "transaction": transaction_doc.name,
                "transid": transaction_doc.transid,
                "status": transaction_doc.status,
                "reference": transaction_doc.reference,
                "resultcode": transaction_doc.resultcode,
                "message": transaction_doc.message,
            },
        }
    except Exception as exc:
        frappe.log_error(str(exc), "Selcom Status Query Error")
        return error_response(_("Failed to query transaction status."))


def refresh_pending_selcom_transactions(minutes_ago=3, limit=50):
    """Refresh pending transactions for background jobs."""
    cutoff = now_datetime() - timedelta(minutes=minutes_ago)
    transactions = frappe.get_all(
        "Selcom Gateway Transaction",
        filters={"status": ["in", ["PENDING", "INPROGRESS", "AMBIGUOUS"]], "modified": ["<", cutoff]},
        fields=["name"],
        limit=limit,
    )

    for row in transactions:
        try:
            transaction_doc = frappe.get_doc("Selcom Gateway Transaction", row.name)
            fetch_transaction_status(transaction_doc)
        except Exception:
            continue


def fetch_transaction_status(transaction_doc):
    account_doc = frappe.get_doc("Selcom Gateway Account", transaction_doc.account)

    payload = {"transid": transaction_doc.transid}
    if transaction_doc.reference:
        payload["reference"] = transaction_doc.reference

    response = send_selcom_request(account_doc, payload, method="GET", path="/c2b/query-status")
    update_transaction_from_response(transaction_doc, response, increment_attempt=True)
    return response


def send_selcom_request(account_doc, payload, method="POST", path="/wallet/pushussd"):
    base_url = account_doc.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        path = f"/v1{path}" if not path.startswith("/v1") else path

    client = apigwClient.Client(
        base_url,
        account_doc.get_password("api_key"),
        account_doc.get_password("api_secret"),
    )

    if method == "GET":
        return client.getFunc(path, payload)
    return client.postFunc(path, payload)


def update_transaction_from_response(transaction_doc, response, increment_attempt=False):
    if not isinstance(response, dict):
        response = {"message": str(response)}

    resultcode = str(response.get("resultcode") or "").strip()
    result = str(response.get("result") or "").strip().upper()

    status = map_status(resultcode, result)

    transaction_doc.resultcode = resultcode
    transaction_doc.result = response.get("result")
    transaction_doc.reference = response.get("reference") or transaction_doc.reference
    transaction_doc.message = response.get("message")
    transaction_doc.status = status
    transaction_doc.response_payload = frappe.as_json(response)

    if increment_attempt:
        transaction_doc.attempts = (transaction_doc.attempts or 0) + 1

    transaction_doc.save(ignore_permissions=True)


def map_status(resultcode, result):
    if resultcode in SUCCESS_CODES or result == "SUCCESS":
        return "SUCCESS"
    if resultcode in IN_PROGRESS_CODES or result == "INPROGRESS":
        return "INPROGRESS"
    if resultcode in AMBIGUOUS_CODES or result in {"AMBIGOUS", "AMBIGUOUS"}:
        return "AMBIGUOUS"
    return "FAILED"


def normalize_msisdn(msisdn):
    clean = re.sub(r"[^\d]", "", str(msisdn or "").strip())
    if clean.startswith("0"):
        return "255" + clean[1:]
    if clean.startswith("255"):
        return clean
    if clean:
        return "255" + clean
    return clean


def get_api_doc(api_key, api_secret):
    api_docs = frappe.get_all(
        "Selcom Gateway API",
        filters={"api_key": api_key},
        fields=["name", "user", "enabled", "expiry_date"],
    )

    if not api_docs:
        return None

    api_doc = frappe.get_doc("Selcom Gateway API", api_docs[0].name)
    stored_secret = api_doc.get_password("api_secret")

    if not hmac.compare_digest(api_secret, stored_secret):
        return None

    return api_doc


def error_response(message):
    frappe.local.response.http_status_code = 400
    return {"status": "error", "message": message}
