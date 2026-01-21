# Copyright (c) 2025, Sydney Kibanga and contributors
# For license information, please see license.txt

import secrets
import frappe
from frappe.model.document import Document


class SelcomGatewayAPI(Document):
    def before_insert(self):
        if not self.api_key:
            self.api_key = self.generate_api_key()

        if not self.api_secret:
            self.api_secret = self.generate_api_secret()

    def validate(self):
        if frappe.db.exists(
            "Selcom Gateway API", {"api_key": self.api_key, "name": ["!=", self.name]}
        ):
            frappe.throw("API key must be unique")

        if self.expiry_date and frappe.utils.getdate(self.expiry_date) < frappe.utils.getdate():
            frappe.throw("Expiry date must be in the future")

    def generate_api_key(self):
        return f"sel_{secrets.token_hex(16)}"

    def generate_api_secret(self):
        return secrets.token_hex(32)
