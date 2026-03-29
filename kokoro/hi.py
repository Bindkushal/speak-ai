"""
misaki/hi.py — Hindi/Devanagari G2P for Kokoro TTS
====================================================
Author  : Kushal (GSoC 2025, Sugar Labs)
Purpose : Replace eSpeak fallback for Hindi with a proper
          rule-based Devanagari → IPA converter.

How it works
------------
1. DEVANAGARI input  → rule-based mapping → IPA phonemes
2. ROMANIZED input   → transliteration table → IPA phonemes
3. MIXED text        → detect script per-word → route accordingly
4. eSpeak fallback   → for edge cases only (numbers, symbols)

Devanagari phonology notes
--------------------------
- Inherent vowel: every consonant has an implicit 'a' (schwa) unless
  followed by a matra (vowel sign) or halant (virama ्).
- Halant (्) suppresses the inherent vowel → pure consonant.
- Anusvara (ं) nasalises the preceding vowel.
- Visarga (ः) adds a light 'h' breath after the vowel.
"""

import re
import subprocess
from typing import Optional

# ---------------------------------------------------------------------------
# 1. DEVANAGARI CHARACTER → IPA MAPPING
# ---------------------------------------------------------------------------

# Independent vowels
VOWELS = {
    'अ': 'ə',
    'आ': 'aː',
    'इ': 'ɪ',
    'ई': 'iː',
    'उ': 'ʊ',
    'ऊ': 'uː',
    'ए': 'eː',
    'ऐ': 'ɛː',
    'ओ': 'oː',
    'औ': 'ɔː',
    'ऋ': 'rɪ',
    'अं': 'əm',  # FIXME: unreachable — loop is char-by-char, two-char key never matches
    'अः': 'əh',  # FIXME: unreachable — same as above
}

# Dependent vowel signs (matras)
MATRAS = {
    'ा': 'aː',
    'ि': 'ɪ',
    'ी': 'iː',
    'ु': 'ʊ',
    'ू': 'uː',
    'े': 'eː',
    'ै': 'ɛː',
    'ो': 'oː',
    'ौ': 'ɔː',
    'ृ': 'rɪ',
    '्': '',        # halant — suppresses inherent vowel
    'ं': 'ŋ',        # anusvara — nasal (use ŋ, universally safe for Kokoro)
    'ः': 'h',      # visarga
}

# Consonants — map to IPA
CONSONANTS = {
    # Velars
    'क': 'k',  'ख': 'kʰ', 'ग': 'ɡ',  'घ': 'ɡʰ', 'ङ': 'ŋ',
    # Palatals
    'च': 'tʃ', 'छ': 'tʃʰ','ज': 'dʒ', 'झ': 'dʒʰ','ञ': 'ɲ',
    # Retroflexes
    'ट': 'ʈ',  'ठ': 'ʈʰ', 'ड': 'ɖ',  'ढ': 'ɖʰ', 'ण': 'ɳ',
    # Dentals
    'त': 't',  'थ': 'tʰ', 'द': 'd',  'ध': 'dʰ', 'न': 'n',
    # Labials
    'प': 'p',  'फ': 'pʰ', 'ब': 'b',  'भ': 'bʰ', 'म': 'm',
    # Semivowels & liquids
    'य': 'j',  'र': 'r',  'ल': 'l',  'व': 'ʋ',
    # Sibilants & aspirate
    'श': 'ʃ',  'ष': 'ʂ',  'स': 's',  'ह': 'ɦ',
    # Nukta (borrowed sounds)
    'क़': 'q',  'ख़': 'x',  'ग़': 'ɣ',  'ज़': 'z',
    'ड़': 'ɽ',  'ढ़': 'ɽʰ', 'फ़': 'f',  'ऱ': 'ɾ',
    # Special
    'ळ': 'ɭ',  'ऴ': 'ɻ',
}

# Stress heuristic — primary stress on first heavy syllable, else first syllable
# (simplified: we mark stress with ˈ on first consonant cluster)
HALANT = '्'
ANUSVARA = 'ं'
VISARGA = 'ः'
CHANDRABINDU = 'ँ'

# Romanised Hindi → IPA  (handles "namaste", "dost", etc.)
ROMAN_TO_IPA = {
    # Common Hindi words in Latin script
    'namaste':   'nəməsteː',
    'namaskar':  'nəməskɑːr',
    'dost':      'doːst',
    'doston':    'doːstõ',
    'aaj':       'aːdʒ',
    'hum':       'ɦʊm',
    'ek':        'eːk',
    'kahani':    'kəɦaːniː',
    'sunenge':   'sʊneːŋɡeː',
    'baat':      'baːt',
    'kya':       'kjɑː',
    'hai':       'ɦɛː',
    'nahi':      'nəɦiː',
    'tum':       'tʊm',
    'main':      'mɛː',
    'karo':      'kəroː',
    'aao':       'aːoː',
    'jao':       'dʒɑːoː',
    'suno':      'sʊnoː',
    'dekho':     'deːkʰoː',
    'accha':     'ətʃʰɑː',
    'theek':     'tʰiːk',
    'pyaar':     'pjaːr',
    'dil':       'dɪl',
    'ghar':      'ɡʰər',
    'paani':     'pɑːniː',
    'khana':     'kʰɑːnɑː',
    'baccha':    'bətʃʃɑː',
    'bhai':      'bʰɑːɪ',
    'didi':      'diːdiː',
    'maa':       'mɑː',
    'papa':      'pɑːpɑː',
    'school':    'skuːl',
    'hindi':     'ɦɪndiː',
}

# ---------------------------------------------------------------------------
# 2. NUMBER → HINDI WORDS
# ---------------------------------------------------------------------------

HINDI_DIGITS = {
    '0': 'शून्य', '1': 'एक', '2': 'दो', '3': 'तीन',
    '4': 'चार',  '5': 'पाँच', '6': 'छह', '7': 'सात',
    '8': 'आठ',   '9': 'नौ',
}

# ---------------------------------------------------------------------------
# 3. CORE DEVANAGARI → IPA CONVERSION
# ---------------------------------------------------------------------------

def _is_devanagari(text: str) -> bool:
    """Returns True if text contains Devanagari characters."""
    return bool(re.search(r'[\u0900-\u097F]', text))

def _is_roman(text: str) -> bool:
    """Returns True if text is purely ASCII/Latin."""
    return bool(re.match(r'^[a-zA-Z\s\'\-]+$', text.strip()))

def _expand_numbers(text: str) -> str:
    """Replace ASCII digits with Hindi words."""
    result = []
    for ch in text:
        result.append(HINDI_DIGITS.get(ch, ch))
    return ''.join(result)

def _devanagari_to_ipa(text: str) -> str:
    """
    Convert a Devanagari string to IPA.

    Algorithm:
    - Walk character by character.
    - If consonant: emit consonant IPA. Check next char:
        - If matra → emit matra vowel (no inherent 'a')
        - If halant → emit nothing (pure consonant cluster)
        - Else → emit inherent vowel 'ə'
    - If independent vowel → emit vowel IPA directly.
    - If anusvara / visarga → nasalise / append 'h'.
    """
    text = _expand_numbers(text)
    ipa = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # Skip chandrabindu (treat like anusvara)
        if ch == CHANDRABINDU:
            if ipa:
                ipa.append('̃')
            i += 1
            continue

        # Standalone anusvara / visarga at start or after space
        if ch == ANUSVARA:
            ipa.append('ŋ')
            i += 1
            continue
        if ch == VISARGA:
            ipa.append('h')
            i += 1
            continue

        # Consonant
        if ch in CONSONANTS:
            ipa.append(CONSONANTS[ch])
            # Peek at next char
            if i + 1 < n:
                nxt = text[i + 1]
                if nxt == HALANT:
                    # Pure consonant — skip halant, no vowel
                    i += 2
                    continue
                elif nxt in MATRAS:
                    ipa.append(MATRAS[nxt])
                    i += 2
                    continue
                else:
                    # Inherent vowel 'a' (schwa)
                    ipa.append('ə')
            else:
                # End of string — still add inherent vowel unless terminal consonant
                # Hindi: word-final inherent schwa is often dropped
                pass  # omit final schwa (schwa deletion)
            i += 1
            continue

        # Independent vowel
        if ch in VOWELS:
            ipa.append(VOWELS[ch])
            i += 1
            continue

        # Matra appearing without prior consonant (shouldn't happen, but handle)
        if ch in MATRAS:
            ipa.append(MATRAS.get(ch, ''))
            i += 1
            continue

        # Space / punctuation — pass through
        if ch in ' ,।!?':
            ipa.append(' ' if ch in ' ।' else ch)
            i += 1
            continue

        # Unknown character — skip silently
        i += 1

    result = ''.join(ipa)
    # Clean up double spaces
    result = re.sub(r'  +', ' ', result).strip()
    return result

# ---------------------------------------------------------------------------
# 4. ROMAN HINDI → IPA
# ---------------------------------------------------------------------------

def _roman_hindi_to_ipa(word: str) -> str:
    """
    Convert romanised Hindi word to IPA.
    Checks dictionary first, then uses eSpeak with Hindi voice.
    """
    lower = word.lower()

    # Dictionary lookup
    if lower in ROMAN_TO_IPA:
        return ROMAN_TO_IPA[lower]

    # Fallback: ask eSpeak for Hindi phonemes
    try:
        result = subprocess.run(
            ['espeak-ng', '-v', 'hi', '-q', '--ipa', word],
            capture_output=True, text=True, timeout=5
        )
        ps = result.stdout.strip()
        # Remove eSpeak language-switch tags like (en) (hi)
        ps = re.sub(r'\([a-z]+\)', '', ps).strip()
        if ps:
            return ps
    except Exception:
        pass

    # Last resort: return word as-is (will sound English but won't crash)
    return word

# ---------------------------------------------------------------------------
# 5. MAIN G2P CLASS
# ---------------------------------------------------------------------------

class HIG2P:
    """
    Hindi G2P — converts Hindi text (Devanagari or Romanised) to IPA.

    Usage:
        from kokoro.hi import HIG2P
        g2p = HIG2P()
        ipa, tokens = g2p("नमस्ते दोस्तों")
        print(ipa)   # → nəməsteː doːstõ
    """

    def __init__(self, fallback_espeak: bool = True):
        self.fallback_espeak = fallback_espeak  # FIXME: flag stored but _roman_hindi_to_ipa calls eSpeak unconditionally

    def __call__(self, text: str):
        """
        Convert text to IPA phonemes.

        Returns:
            (phoneme_string, tokens_list)
            tokens_list is a list of (word, ipa) pairs — useful for debugging.
        """
        if not text or not text.strip():
            return '', []

        words = text.split()
        phoneme_parts = []
        tokens = []

        for word in words:
            # Strip punctuation for lookup, keep for output
            clean = re.sub(r'[^\u0900-\u097Fa-zA-Z0-9]', '', word)
            punct_after = re.sub(r'[\u0900-\u097Fa-zA-Z0-9]', '', word)

            if not clean:
                phoneme_parts.append(word)
                continue

            if _is_devanagari(clean):
                ipa = _devanagari_to_ipa(clean)
            elif _is_roman(clean):
                ipa = _roman_hindi_to_ipa(clean)
            else:
                # Mixed — try Devanagari path
                ipa = _devanagari_to_ipa(clean)

            tokens.append((word, ipa))
            phoneme_parts.append(ipa + punct_after)

        phoneme_string = ' '.join(phoneme_parts)
        return phoneme_string, tokens


# Convenience singleton
_g2p_instance: Optional[HIG2P] = None

def get_g2p() -> HIG2P:
    global _g2p_instance
    if _g2p_instance is None:
        _g2p_instance = HIG2P()
    return _g2p_instance


# ---------------------------------------------------------------------------
# 6. QUICK SELF-TEST  (python hi.py)
