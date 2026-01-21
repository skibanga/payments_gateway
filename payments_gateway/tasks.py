from payments_gateway.api.selcom_gateway import refresh_pending_selcom_transactions


def hourly():
    refresh_pending_selcom_transactions()
