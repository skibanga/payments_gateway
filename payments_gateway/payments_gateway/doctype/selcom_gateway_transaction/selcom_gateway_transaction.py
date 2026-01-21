# Copyright (c) 2025, Sydney Kibanga and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


SUCCESS_STATUSES = {"SUCCESS"}
FAILED_STATUSES = {"FAILED"}


def get_permission_query_conditions(user):
    """Restrict transactions to accounts linked to the current user."""
    if not user:
        user = frappe.session.user

    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return ""

    account_names = frappe.get_all(
        "Selcom Gateway Account User",
        filters={"user": user, "enabled": 1},
        pluck="parent",
    )

    if not account_names:
        return "1=0"

    account_names_str = ", ".join([f"'{name}'" for name in account_names])
    return f"`tabSelcom Gateway Transaction`.account in ({account_names_str})"


class SelcomGatewayTransaction(Document):
    def validate(self):
        if self.amount is not None and flt(self.amount) <= 0:
            frappe.throw(_("Amount must be greater than zero."))

    def after_insert(self):
        if self.account:
            frappe.db.set_value(
                "Selcom Gateway Account", self.account, "last_used_on", now_datetime()
            )

    def on_update(self):
        previous = self.get_doc_before_save()
        previous_status = previous.status if previous else None
        current_status = self.status

        if not self.account or previous_status == current_status:
            return

        self._adjust_account_metrics(previous_status, current_status)

    def _adjust_account_metrics(self, previous_status, current_status):
        account = self.account

        success_count = frappe.db.get_value(
            "Selcom Gateway Account", account, "success_count"
        ) or 0
        failed_count = frappe.db.get_value(
            "Selcom Gateway Account", account, "failed_count"
        ) or 0
        total_amount = frappe.db.get_value(
            "Selcom Gateway Account", account, "total_amount"
        ) or 0

        if previous_status in SUCCESS_STATUSES and current_status not in SUCCESS_STATUSES:
            success_count = max(0, success_count - 1)
            total_amount = flt(total_amount) - flt(self.amount)

        if previous_status in FAILED_STATUSES and current_status not in FAILED_STATUSES:
            failed_count = max(0, failed_count - 1)

        if current_status in SUCCESS_STATUSES and previous_status not in SUCCESS_STATUSES:
            success_count += 1
            total_amount = flt(total_amount) + flt(self.amount)

        if current_status in FAILED_STATUSES and previous_status not in FAILED_STATUSES:
            failed_count += 1

        frappe.db.set_value(
            "Selcom Gateway Account",
            account,
            {
                "success_count": success_count,
                "failed_count": failed_count,
                "total_amount": total_amount,
            },
        )
