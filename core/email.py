"""
Email service for sending transactional emails
"""
import logging
from core.app_settings import app_settings

logger = logging.getLogger(__name__)


def send_password_reset_email(
    email: str,
    token: str,
    user_name: str
) -> bool:
    """
    Send password reset email to user

    Args:
        email: User email address
        token: Password reset token
        user_name: User's name

    Returns:
        True if email was sent successfully
    """
    if not app_settings.get_bool("EMAIL_ENABLED"):
        logger.warning(
            f"Email disabled. Would send password reset to {email}"
        )
        return False

    # Build reset URL
    frontend_url = app_settings.get(
        "FRONTEND_URL", "http://localhost:3000"
    )
    reset_url = f"{frontend_url}/reset-password?token={token}"

    subject = "Password Reset Request"
    body = f"""
Hello {user_name},

You requested to reset your password for your NGS360 account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you didn't request this, please ignore this email.

Best regards,
The NGS360 Team
"""

    try:
        _send_email(email, subject, body)
        logger.info(f"Password reset email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")
        return False


def send_verification_email(
    email: str,
    token: str,
    user_name: str
) -> bool:
    """
    Send email verification email to user

    Args:
        email: User email address
        token: Email verification token
        user_name: User's name

    Returns:
        True if email was sent successfully
    """
    if not app_settings.get_bool("EMAIL_ENABLED"):
        logger.warning(
            f"Email disabled. Would send verification to {email}"
        )
        return False

    # Build verification URL
    frontend_url = app_settings.get(
        "FRONTEND_URL", "http://localhost:3000"
    )
    verify_url = f"{frontend_url}/verify-email?token={token}"

    subject = "Verify Your Email Address"
    body = f"""
Hello {user_name},

Welcome to NGS360! Please verify your email address to activate your account.

Click the link below to verify your email:
{verify_url}

This link will expire in 7 days.

If you didn't create this account, please ignore this email.

Best regards,
The NGS360 Team
"""

    try:
        _send_email(email, subject, body)
        logger.info(f"Verification email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        return False


def send_welcome_email(email: str, user_name: str) -> bool:
    """
    Send welcome email to new user

    Args:
        email: User email address
        user_name: User's name

    Returns:
        True if email was sent successfully
    """
    if not app_settings.get_bool("EMAIL_ENABLED"):
        logger.warning(f"Email disabled. Would send welcome to {email}")
        return False

    subject = "Welcome to NGS360"
    body = f"""
Hello {user_name},

Welcome to NGS360! Your account has been successfully created.

You can now log in and start using our platform.

If you have any questions, please don't hesitate to contact us.

Best regards,
The NGS360 Team
"""

    try:
        _send_email(email, subject, body)
        logger.info(f"Welcome email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        return False


def _send_email_aws_ses(to_email: str, subject: str, body: str) -> None:
    """
    Internal function to send email using AWS SES

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body (plain text)

    Raises:
        Exception: If email sending fails
    """
    from core.config import get_settings

    try:
        import boto3
        from botocore.exceptions import ClientError

        bootstrap = get_settings()
        from_name = app_settings.get("FROM_NAME", "NGS360")
        from_email = app_settings.get("FROM_EMAIL", "noreply@example.com")

        # Create SES client
        ses_client = boto3.client(
            'ses',
            region_name=bootstrap.AWS_REGION,
            aws_access_key_id=bootstrap.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=bootstrap.AWS_SECRET_ACCESS_KEY
        )

        # Send email
        response = ses_client.send_email(
            Source=f"{from_name} <{from_email}>",
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.debug(
            f"Email sent. Message ID: {response['MessageId']}"
        )

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"SES error {error_code}: {error_message}")
        raise Exception(f"Failed to send email: {error_message}")
    except ImportError:
        logger.error(
            "boto3 not installed. Cannot send emails via SES."
        )
        raise Exception("Email service not configured")
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        raise


def _send_email(to_email: str, subject: str, body: str) -> None:
    """
    Internal function to send email using SMTP

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body (plain text)

    Raises:
        Exception: If email sending fails
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.utils import formataddr

    mail_server = app_settings.get("MAIL_SERVER")
    mail_port = app_settings.get("MAIL_PORT")
    from_name = app_settings.get("FROM_NAME", "NGS360")
    from_email = app_settings.get("FROM_EMAIL", "noreply@example.com")
    mail_username = app_settings.get("MAIL_USERNAME")
    mail_password = app_settings.get("MAIL_PASSWORD")
    mail_use_tls = app_settings.get_bool("MAIL_USE_TLS")

    # Validate SMTP configuration
    if not mail_server:
        logger.error("MAIL_SERVER not configured")
        raise Exception(
            "Email service not configured: MAIL_SERVER is required"
        )

    if not mail_port:
        logger.error("MAIL_PORT not configured")
        raise Exception(
            "Email service not configured: MAIL_PORT is required"
        )

    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = formataddr((from_name, from_email))
        msg['To'] = to_email
        msg['Subject'] = subject

        # Attach body as plain text
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Connect to SMTP server
        port = int(mail_port)

        logger.debug(
            f"Connecting to SMTP server {mail_server}:{port}"
        )

        # Create SMTP connection
        smtp_server = smtplib.SMTP(mail_server, port, timeout=30)

        try:
            # Enable TLS if configured
            if mail_use_tls:
                logger.debug("Starting TLS")
                smtp_server.starttls()

            # Authenticate if credentials provided
            if mail_username and mail_password:
                logger.debug(
                    f"Authenticating as {mail_username}"
                )
                smtp_server.login(mail_username, mail_password)

            # Send email
            smtp_server.send_message(msg)
            logger.debug(f"Email sent successfully to {to_email}")

        finally:
            # Always close the connection
            smtp_server.quit()

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        raise Exception(
            "Failed to send email: Authentication failed"
        )
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        raise Exception(f"Failed to send email: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid MAIL_PORT value: {e}")
        raise Exception(
            "Email service misconfigured: Invalid port number"
        )
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        raise Exception(f"Failed to send email: {str(e)}")
