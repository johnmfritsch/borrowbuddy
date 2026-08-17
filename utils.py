"""
Utility functions for BorrowBuddy
"""
import re
import os
from PIL import Image


def normalize_phone_number(phone):
    """
    Normalize phone number to E.164 format for SMS compatibility.

    E.164 format: +[country code][number]
    Example: +14848940830

    Handles various input formats:
    - (484) 894-0830
    - 484-894-0830
    - 484.894.0830
    - 4848940830
    - +1 (484) 894-0830

    Args:
        phone (str): Phone number in any format

    Returns:
        str: Phone number in E.164 format (+1XXXXXXXXXX) or None if invalid
    """
    if not phone:
        return None

    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)

    # If empty after cleaning, return None
    if not digits:
        return None

    # Handle different lengths
    if len(digits) == 10:
        # US number without country code
        return f'+1{digits}'
    elif len(digits) == 11 and digits.startswith('1'):
        # US number with country code
        return f'+{digits}'
    elif len(digits) > 11:
        # International number with country code
        return f'+{digits}'
    else:
        # Too short, invalid
        return None


def format_phone_for_display(phone):
    """
    Format phone number for human-readable display.

    Converts +14848940830 to (484) 894-0830

    Args:
        phone (str): Phone number in E.164 format

    Returns:
        str: Formatted phone number or original if can't parse
    """
    if not phone:
        return ''

    # Remove + and country code
    digits = re.sub(r'\D', '', phone)

    if len(digits) == 11 and digits.startswith('1'):
        # US format: +1XXXXXXXXXX -> (XXX) XXX-XXXX
        area = digits[1:4]
        prefix = digits[4:7]
        line = digits[7:11]
        return f'({area}) {prefix}-{line}'
    elif len(digits) == 10:
        # Already 10 digits: XXXXXXXXXX -> (XXX) XXX-XXXX
        area = digits[0:3]
        prefix = digits[3:6]
        line = digits[6:10]
        return f'({area}) {prefix}-{line}'
    else:
        # Return as-is for international or unrecognized formats
        return phone


def get_contact_initials(name):
    """
    Get initials from a contact name for avatar display.

    Args:
        name (str): Full name

    Returns:
        str: Two-character initials in uppercase
    """
    if not name:
        return '??'

    parts = name.strip().split()

    if len(parts) >= 2:
        # First and last name
        return (parts[0][0] + parts[-1][0]).upper()
    else:
        # Single name - take first two characters
        return name[:2].upper()


def validate_email(email):
    """
    Basic email validation.

    Args:
        email (str): Email address to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not email:
        return True  # Optional field

    # Basic regex for email validation
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def generate_image_variants(original_filepath, url_prefix='/BorrowBuddy_dev'):
    """
    Generate thumbnail and display variants of an image for performance optimization.

    Creates two resized versions of the original image:
    - Thumbnail: 150px (used in lists) - 75% quality
    - Display: 600px (used in detail views) - 85% quality
    - Original is kept at full resolution for lightbox/full view

    Args:
        original_filepath (str): Full filesystem path to original image
        url_prefix (str): URL prefix for serving images (default: /BorrowBuddy_dev)

    Returns:
        dict: Dictionary with URIs for all three versions:
        {
            'original': '/BorrowBuddy_dev/static/images/JPEG_20260211_...jpg',
            'thumb': '/BorrowBuddy_dev/static/images/JPEG_20260211_..._thumb.jpg',
            'display': '/BorrowBuddy_dev/static/images/JPEG_20260211_..._display.jpg'
        }

    Raises:
        FileNotFoundError: If original_filepath does not exist
        Exception: If image processing fails
    """
    if not os.path.exists(original_filepath):
        raise FileNotFoundError(f"Original image not found: {original_filepath}")

    try:
        # Open the original image
        img = Image.open(original_filepath)

        # Convert RGBA to RGB if necessary (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Get base path and filename without extension
        base_path = os.path.splitext(original_filepath)[0]
        original_filename = os.path.basename(original_filepath)

        # Generate thumbnail variant (150px, 75% quality)
        thumb_filepath = f"{base_path}_thumb.jpg"
        img_thumb = img.copy()
        img_thumb.thumbnail((150, 150), Image.Resampling.LANCZOS)
        img_thumb.save(thumb_filepath, 'JPEG', quality=75, optimize=True)

        # Generate display variant (600px, 85% quality)
        display_filepath = f"{base_path}_display.jpg"
        img_display = img.copy()
        img_display.thumbnail((600, 600), Image.Resampling.LANCZOS)
        img_display.save(display_filepath, 'JPEG', quality=85, optimize=True)

        # Build URIs using original filename pattern
        thumb_filename = original_filename.replace('.jpg', '_thumb.jpg').replace('.jpeg', '_thumb.jpg').replace('.png', '_thumb.jpg').replace('.gif', '_thumb.jpg')
        display_filename = original_filename.replace('.jpg', '_display.jpg').replace('.jpeg', '_display.jpg').replace('.png', '_display.jpg').replace('.gif', '_display.jpg')

        return {
            'original': f'{url_prefix}/static/images/{original_filename}',
            'thumb': f'{url_prefix}/static/images/{thumb_filename}',
            'display': f'{url_prefix}/static/images/{display_filename}'
        }

    except Exception as e:
        raise Exception(f"Error processing image variants: {str(e)}")
