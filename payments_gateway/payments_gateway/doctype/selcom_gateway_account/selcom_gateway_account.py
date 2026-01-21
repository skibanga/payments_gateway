# Copyright (c) 2025, Sydney Kibanga and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def get_permission_query_conditions(user):
    """Restrict access to accounts linked to the current user."""
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
    return f"`tabSelcom Gateway Account`.name in ({account_names_str})"


class SelcomGatewayAccount(Document):
    def validate(self):
        if self.min_amount and self.max_amount and self.min_amount > self.max_amount:
            frappe.throw(_("Minimum Amount cannot be greater than Maximum Amount."))

        if self.account_users:
            seen_users = set()
            for row in self.account_users:
                if row.user in seen_users:
                    frappe.throw(_("Duplicate user in account users: {0}").format(row.user))
                seen_users.add(row.user)
