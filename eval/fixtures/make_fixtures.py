#!/usr/bin/env python3
"""Generate the synthetic .eml fixtures — written, never exported from a real mailbox.

    python3 make_fixtures.py          # rewrites every .eml under personal/ and work/

Every sender, vendor, amount, order number and Message-ID here is invented.
Domains are reserved example domains. The fixtures are laid out as two
"accounts" (one folder each) so the cross-account duplicate case can be tested:
work/ holds a second copy of one receipt with the SAME Message-ID as personal/.

expected.jsonl next to this script says what a correct sweep does with each.
"""
import base64
import os
from email.message import EmailMessage
from email.utils import formatdate

HERE = os.path.dirname(os.path.abspath(__file__))

# A minimal but valid single-page PDF ("Invoice 1001"), ~400 bytes.
TINY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 84>>stream\n"
    b"BT /F1 18 Tf 24 100 Td (Contoso Cloud - Invoice 1001) Tj 0 -32 Td (Total due: $19.00) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def msg(from_, to, subject, date, message_id, text=None, html=None, pdf=None):
    m = EmailMessage()
    m["From"] = from_
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = formatdate(date, localtime=False)
    m["Message-ID"] = message_id
    if text and html:
        m.set_content(text)
        m.add_alternative(html, subtype="html")
    elif html:
        m.set_content("This message is best viewed as HTML.")
        m.add_alternative(html, subtype="html")
    else:
        m.set_content(text or "")
    if pdf:
        m.add_attachment(TINY_PDF, maintype="application", subtype="pdf", filename=pdf)
    return m


TO = "someone@example.com"
T0 = 1788600000  # 2026-09-05T09:20:00Z — fixed so the files are reproducible

FIXTURES = {
    "personal/receipt-html.eml": msg(
        "Northwind Stationery <receipts@northwind.example>", TO,
        "Your Northwind Stationery receipt — order #NW-2231", T0,
        "<nw-2231-receipt@northwind.example>",
        html="""<html><body>
<h1>Thanks for your order</h1>
<p>Order <b>#NW-2231</b> placed 5 September 2026.</p>
<table>
<tr><td>Fountain pen ink, 50 ml (2)</td><td>$24.00</td></tr>
<tr><td>Dot-grid notebook A5</td><td>$14.50</td></tr>
<tr><td>Shipping</td><td>$0.00</td></tr>
<tr><td>Tax</td><td>$3.67</td></tr>
<tr><td><b>Total charged to card ending 4242</b></td><td><b>$42.17</b></td></tr>
</table>
<p>Questions? Reply to this email.</p>
</body></html>"""),

    "personal/receipt-pdf-attachment.eml": msg(
        "Contoso Cloud Billing <billing@contoso-cloud.example>", TO,
        "Invoice #1001 for September", T0 + 3600,
        "<inv-1001@contoso-cloud.example>",
        text="Your invoice for September is attached.\n\nAmount charged: $19.00\nPayment method: card on file\n\nContoso Cloud",
        pdf="invoice-1001.pdf"),

    "personal/renewal-notice.eml": msg(
        "Fabrikam Plus <no-reply@fabrikam.example>", TO,
        "Your Fabrikam Plus plan renews on October 1", T0 + 7200,
        "<renew-2026-10@fabrikam.example>",
        html="""<html><body>
<p>Hi there,</p>
<p>This is a reminder that your <b>Fabrikam Plus (monthly)</b> plan will automatically renew on
<b>1 October 2026</b>. Your card on file will be charged <b>$9.99</b> on that date.</p>
<p>No action is needed. To change or cancel your plan, visit your account settings before the renewal date.</p>
</body></html>"""),

    "personal/statement-available.eml": msg(
        "Woodgrove Bank <alerts@woodgrove-bank.example>", TO,
        "Your September statement is ready", T0 + 10800,
        "<stmt-2026-09@woodgrove-bank.example>",
        text="Your statement for the period ending September 4, 2026 is now available.\n\n"
             "Sign in to view or download it. For security, statement details are not included in this email.\n\n"
             "Woodgrove Bank"),

    "personal/marketing.eml": msg(
        "Northwind Stationery <news@northwind.example>", TO,
        "Order now: 30% off everything this weekend", T0 + 14400,
        "<promo-fall-2026@northwind.example>",
        html="""<html><body>
<h1>Fall sale — 30% off</h1>
<p>Dot-grid notebooks from <b>$9.99</b>. Ink from <b>$8.40</b>. Free shipping over <b>$50.00</b>.</p>
<p><a href="https://northwind.example/sale">Shop the sale</a> — ends Sunday.</p>
<p><small>You are receiving this because you bought from us. <a href="#">Unsubscribe</a></small></p>
</body></html>"""),

    "personal/receipt-and-renewal.eml": msg(
        "Fabrikam Plus <no-reply@fabrikam.example>", TO,
        "Receipt for your Fabrikam Plus renewal", T0 + 18000,
        "<renew-receipt-2026-09@fabrikam.example>",
        html="""<html><body>
<h2>Payment received</h2>
<p>We charged <b>$9.99</b> to your card on file on 5 September 2026 for <b>Fabrikam Plus (monthly)</b>.</p>
<p>Receipt number: FP-88410</p>
<p>Your next renewal is on <b>5 October 2026</b> for the same amount.</p>
</body></html>"""),

    "personal/shipping-notice.eml": msg(
        "Northwind Stationery <no-reply@northwind.example>", TO,
        "Your Northwind order #NW-2231 has shipped", T0 + 21600,
        "<nw-2231-shipped@northwind.example>",
        html="""<html><body>
<p>Good news — order <b>#NW-2231</b> is on its way.</p>
<p>Tracking: 1Z-EXAMPLE-000. Expected delivery: 9 September.</p>
</body></html>"""),

    # Cross-account duplicate: identical Message-ID to personal/receipt-html.eml,
    # as when one receipt is delivered to two addresses that both feed the sweep.
    "work/receipt-html-duplicate.eml": msg(
        "Northwind Stationery <receipts@northwind.example>", "work@example.com",
        "Your Northwind Stationery receipt — order #NW-2231", T0,
        "<nw-2231-receipt@northwind.example>",
        html="<html><body><p>Order <b>#NW-2231</b>. <b>Total $42.17</b> charged to card ending 4242.</p></body></html>"),

    "work/refund.eml": msg(
        "Contoso Cloud Billing <billing@contoso-cloud.example>", "work@example.com",
        "Refund issued for invoice #0998", T0 + 25200,
        "<refund-0998@contoso-cloud.example>",
        text="We have refunded $19.00 to your original payment method for invoice #0998.\n"
             "Refunds take 5–10 business days to appear.\n\nContoso Cloud"),
}


def main():
    for rel, m in FIXTURES.items():
        path = os.path.join(HERE, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(m.as_bytes())
        print("wrote", rel)


if __name__ == "__main__":
    main()
