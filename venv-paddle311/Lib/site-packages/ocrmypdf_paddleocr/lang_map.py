# SPDX-License-Identifier: MPL-2.0

"""Map Tesseract language codes to PaddleOCR language codes."""

from __future__ import annotations

# Tesseract code -> PaddleOCR code
_LANG_MAP: dict[str, str] = {
    'eng': 'en',
    'kor': 'korean',
    'chi_sim': 'ch',
    'chi_tra': 'chinese_cht',
    'jpn': 'japan',
    'deu': 'german',
    'fra': 'french',
    'spa': 'es',
    'por': 'pt',
    'ita': 'it',
    'rus': 'ru',
    'ara': 'ar',
    'hin': 'hi',
    'vie': 'vi',
    'tha': 'th',
    'tur': 'tr',
    'ukr': 'uk',
    'pol': 'pl',
    'nld': 'nl',
    'nor': 'no',
    'swe': 'sv',
    'dan': 'da',
    'fin': 'fi',
    'hun': 'hu',
    'ces': 'cs',
    'ron': 'ro',
    'bul': 'bg',
    'hrv': 'hr',
    'slk': 'sk',
    'slv': 'sl',
    'ell': 'el',
    'heb': 'he',
    'ind': 'id',
    'msa': 'ms',
    'tam': 'ta',
    'tel': 'te',
    'kan': 'ka',
    'mar': 'mr',
    'nep': 'ne',
    'ben': 'bn',
    'urd': 'ur',
    'fas': 'fa',
    'mya': 'my',
    'khm': 'km',
    'lao': 'lo',
    'lat': 'la',
    'est': 'et',
    'lav': 'lv',
    'lit': 'lt',
}

SUPPORTED_LANGUAGES: set[str] = set(_LANG_MAP.keys())


def tesseract_to_paddle(lang: str) -> str:
    """Convert Tesseract language code to PaddleOCR code.

    Args:
        lang: Tesseract language code (e.g., 'eng', 'kor', 'chi_sim')

    Returns:
        PaddleOCR language code (e.g., 'en', 'korean', 'ch')
    """
    return _LANG_MAP.get(lang, lang)
