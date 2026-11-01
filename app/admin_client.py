
import imaplib
import smtplib
import email
from email.message import EmailMessage
from email.header import decode_header
from email.utils import parseaddr
from typing import Any

from app.config import settings


def _decode_header_value(value: str | None) -> str:
    """Decode an email header into a readable string."""

    if not value:
        return ""

    decoded_parts = decode_header(value)
    result = []

    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(part)

    return "".join(result)


def _get_email_body(message: email.message.Message) -> str:
    """Extract plain-text content from an email."""

    body_parts = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)

                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(
                        payload.decode(charset, errors="replace")
                    )
    else:
        payload = message.get_payload(decode=True)

        if payload:
            charset = message.get_content_charset() or "utf-8"
            body_parts.append(
                payload.decode(charset, errors="replace")
            )

    return "\n".join(body_parts).strip()


def send_approval_request(
    request_id: str,
    reservation_details: dict[str, Any],
) -> None:
    """
    Send a reservation approval request to the administrator.

    The request ID is included in both the subject and body
    so that administrator responses can be correlated.
    """

    subject = f"Parking Reservation Approval Request [{request_id}]"

    details = "\n".join(
        f"{key.replace('_', ' ').title()}: {value}"
        for key, value in reservation_details.items()
    )

    body = f"""
Hello Administrator,

A new parking reservation requires your approval.

Request ID: {request_id}

Reservation Details:
{details}

Please reply to this email using one of the following formats:

APPROVE: {request_id}
Reason: Optional approval remarks

OR

REJECT: {request_id}
Reason: Reason for rejection

Please include the exact request ID in your response.

Regards,
Parking Reservation Bot
"""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.admin_email_from
    message["To"] = settings.admin_email_to
    message.set_content(body)

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=30,
        ) as server:
            server.login(
                settings.smtp_username,
                settings.smtp_password,
            )
            server.send_message(message)

    else:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=30,
        ) as server:
            server.ehlo()

            if settings.smtp_starttls:
                server.starttls()
                server.ehlo()

            server.login(
                settings.smtp_username,
                settings.smtp_password,
            )
            server.send_message(message)


def fetch_admin_replies() -> list[dict[str, str]]:
    """
    Fetch unread emails from the configured administrator.

    BODY.PEEK prevents IMAP from automatically marking
    messages as read.

    Returns a list containing sender, subject, body and
    message ID for each matching email.
    """

    replies = []
    mailbox = None

    try:
        if settings.imap_use_ssl:
            mailbox = imaplib.IMAP4_SSL(
                settings.imap_host,
                settings.imap_port,
            )
        else:
            mailbox = imaplib.IMAP4(
                settings.imap_host,
                settings.imap_port,
            )

        mailbox.login(
            settings.imap_username,
            settings.imap_password,
        )

        status, _ = mailbox.select("INBOX")

        if status != "OK":
            return replies

        admin_address = parseaddr(settings.admin_email_to)[1]

        status, data = mailbox.search(
            None,
            "UNSEEN",
            "FROM",
            f'"{admin_address}"',
        )

        if status != "OK" or not data or not data[0]:
            return replies

        for message_number in data[0].split():
            status, message_data = mailbox.fetch(
                message_number,
                "(BODY.PEEK[])",
            )

            if status != "OK":
                continue

            raw_email = next(
                (
                    item[1]
                    for item in message_data
                    if isinstance(item, tuple)
                ),
                None,
            )

            if not raw_email:
                continue

            parsed_email = email.message_from_bytes(raw_email)

            sender = parseaddr(parsed_email.get("From", ""))[1]

            # Verify the sender again before processing.
            if sender.lower() != admin_address.lower():
                continue

            replies.append(
                {
                    "sender": sender,
                    "subject": _decode_header_value(
                        parsed_email.get("Subject")
                    ),
                    "body": _get_email_body(parsed_email),
                    "message_id": parsed_email.get("Message-ID", ""),
                }
            )

    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except Exception:
                pass

    return replies
