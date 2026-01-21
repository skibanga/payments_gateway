### Payments Gateway

 

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app payments_gateway
```

### Selcom Gateway Usage

This app provides a Selcom multi-account gateway with API keys linked to users.

#### Setup

1. Create one or more Selcom accounts:
   - DocType: `Selcom Gateway Account`
   - Required fields: `Account Name`, `Base URL`, `Vendor`, `API Key`, `API Secret`
   - Optional: `PIN`, `Min/Max Amount`, `Currency`
2. Link users to each account:
   - In the `Users` child table of the account, add allowed users.
3. Create API keys for clients:
   - DocType: `Selcom Gateway API`
   - Set `User`, `Enabled`, and optional `Expiry Date`
   - Add allowed accounts in `Allowed Accounts`

#### API Endpoints

All calls use Frappe method endpoints.

1) Send USSD Push

`POST /api/method/payments_gateway.api.selcom_gateway.send_ussd_push`

Request JSON:
```json
{
  "api_key": "sel_1234567890abcdef",
  "api_secret": "abcdef1234567890abcdef1234567890",
  "account": "SELCOM-ACCOUNT-1",
  "utilityref": "INV-0001",
  "amount": 10000,
  "msisdn": "255712345678",
  "transid": "TX-00001"
}
```

Notes:
- `account` is required if the API key has more than one allowed account.
- `transid` is optional; if omitted, one is generated.
- `msisdn` must be in `255XXXXXXXXX` format.

Success response:
```json
{
  "status": "success",
  "message": "USSD push request submitted",
  "data": {
    "transaction": "SGT-2025-05-06-00001",
    "transid": "TX-00001",
    "status": "PENDING",
    "reference": "0289999288",
    "resultcode": "111",
    "message": "Request in progress. You will receive a callback shortly."
  }
}
```

Error response:
```json
{
  "status": "error",
  "message": "Account is not allowed for this API key."
}
```

2) Query Status

`POST /api/method/payments_gateway.api.selcom_gateway.query_transaction_status`

Request JSON (by transaction name):
```json
{
  "api_key": "sel_1234567890abcdef",
  "api_secret": "abcdef1234567890abcdef1234567890",
  "transaction": "SGT-2025-05-06-00001"
}
```

Request JSON (by transid):
```json
{
  "api_key": "sel_1234567890abcdef",
  "api_secret": "abcdef1234567890abcdef1234567890",
  "transid": "TX-00001"
}
```

Response:
```json
{
  "status": "success",
  "message": "Status fetched successfully",
  "data": {
    "transaction": "SGT-2025-05-06-00001",
    "transid": "TX-00001",
    "status": "SUCCESS",
    "reference": "0289999288",
    "resultcode": "000",
    "message": "Transaction successful"
  }
}
```

#### Status Mapping

The gateway maps Selcom result codes:
- `000` -> `SUCCESS`
- `111`, `927` -> `INPROGRESS`
- `999` -> `AMBIGUOUS`
- Others -> `FAILED`

#### Background Refresh

Pending transactions are refreshed hourly via:
- Scheduler: `payments_gateway.tasks.hourly`
- Method: `payments_gateway.api.selcom_gateway.refresh_pending_selcom_transactions`

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/payments_gateway
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
