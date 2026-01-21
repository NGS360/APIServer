"""
Email service for sending transactional emails
"""
import logging
from core.config import get_settings

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
    settings = get_settings()

    if not settings.EMAIL_ENABLED:
        logger.warning(
            f"Email disabled. Would send password reset to {email}"
        )
        return False

    # Build reset URL
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

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
    settings = get_settings()

    if not settings.EMAIL_ENABLED:
        logger.warning(
            f"Email disabled. Would send verification to {email}"
        )
        return False

    # Build verification URL
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

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
    settings = get_settings()

    if not settings.EMAIL_ENABLED:
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


def _send_email(to_email: str, subject: str, body: str) -> None:
    """
    Internal function to send email using AWS SES

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body (plain text)

    Raises:
        Exception: If email sending fails
    """
    settings = get_settings()

    try:
        import boto3
        from botocore.exceptions import ClientError

        # Create SES client
        ses_client = boto3.client(
            'ses',
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )

        # Send email
        response = ses_client.send_email(
            Source=f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>",
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.debug(f"Email sent. Message ID: {response['MessageId']}")

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"SES error {error_code}: {error_message}")
        raise Exception(f"Failed to send email: {error_message}")
    except ImportError:
        logger.error("boto3 not installed. Cannot send emails via SES.")
        raise Exception("Email service not configured")
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        raise
