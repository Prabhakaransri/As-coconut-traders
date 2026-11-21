# AS Coconut Traders V81 Rev-1 — Master acceptance checklist

This is a preservation-first checklist assembled from the owner's earlier and current requests. **Do not treat a checkbox as passed without testing.** Never delete or reset live customer data to run tests.

## Preserve all existing application modules
- [ ] Dashboard and KPI totals
- [ ] Daily & Customer Sales
- [ ] Customer Ledger, outstanding balances, advances
- [ ] New Bill, bill history, payment splits
- [ ] Customers
- [ ] Products & Stock
- [ ] Purchases and supplier ledger
- [ ] Payments & History
- [ ] Reports & Backup
- [ ] Recycle Bin / restore / audit
- [ ] Shop Settings and business identity

## Stock and transaction integrity (highest priority)
- [ ] Deleted 150 Packing Bags purchase and related sale must NOT remain as 150 IN / 150 OUT in the Daily Stock Register.
- [ ] Purchase edit reflects corrected quantity exactly once; delete removes linked stock movement.
- [ ] Sale edit/delete reverses or recomputes linked stock movement exactly once.
- [ ] Opening + valid IN - valid OUT + adjustments = Closing for each product/unit.
- [ ] Dashboard, Daily Stock Register and transaction history agree; audit history remains available.
- [ ] Tests run against a separate disposable test DB; never mutate production data.

## 80 mm thermal printing and original branding
- [ ] 80 mm paper (not A4), printer-safe margins and variable receipt length.
- [ ] Compact readable font, no oversized headings or blank receipt tail.
- [ ] Original owner-provided AS Coconut Traders coconut/gold-badge logo only; NEVER ChatGPT or generated replacement.
- [ ] Logo appears on app header, thermal PDF, receipt preview, and printed receipt.
- [ ] Bill number, date/time, customer details, product, quantity, rate, amount, previous balance, payment, pending/advance and thank-you footer.
- [ ] Black-and-white thermal output legible; preview and printed content consistent.
- [ ] Build includes authentic PNG assets; missing assets must not be silently substituted.

## Daily owner closing report
- [ ] At 11:30 PM IST when app is running, remind if not confirmed sent.
- [ ] On application close, check today's report; offer prepare/send, exit without sending, or cancel.
- [ ] Owner-only WhatsApp report: customer-wise sales/receipts/pending/advance, purchases/suppliers, product sales, opening/IN/OUT/closing stock, collection, expenses and alerts.
- [ ] Backup before preparing closing report.
- [ ] Do not mark report delivered merely because WhatsApp Web opened; user confirmation is not delivery proof.
- [ ] Prevent duplicate popups and flag reports stale after subsequent transactions.
- [ ] When app is closed before 11:30 PM, an in-app timer cannot send a notification; OS scheduler or separate service would be required for unattended delivery.

## Reset and security
- [ ] Owner PIN required, wrong-PIN lockout, verified backup and explicit destructive confirmation.
- [ ] Latest user instruction: no WhatsApp OTP/API needed for **Complete Business Reset**. Do not reintroduce mandatory WhatsApp verification.
- [ ] Keep branding/settings as specified; protect existing customer/business data during upgrade.
- [ ] Test reset only with disposable database and independently verify backup can restore.

## Release gate
- [ ] Python syntax/compile and isolated unit tests pass.
- [ ] Windows GitHub Actions build passes and EXE artifact is downloadable.
- [ ] Launch Windows EXE; verify original logo assets, 80mm print preview and actual thermal output.
- [ ] Confirm closing report behavior and stock regression.
- [ ] Create final ZIP only after successful checks; preserve old ZIP and database backup.

Source branch: `v81-rev1-stock-fix`.
