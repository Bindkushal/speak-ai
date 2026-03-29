#!/usr/bin/env python3
# Copyright (C) 2025, Kushal Bindal
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""
download_models.py -- Auto-download Kokoro ONNX model files for speak-ai
=========================================================================
Downloads the Kokoro ONNX model and voices file needed for lightweight
TTS without PyTorch. Models are cached in ~/.cache/speak-ai/ so the
download only happens once.

Usage:
    python3 download_models.py

Also called automatically by KokoroOnnxBackend on first use.

Model files (~94MB total):
    kokoro-v1.0.int8.onnx  -- quantized voice engine (no torch needed)
    voices-v1.0.bin        -- all voice styles (hf_alpha, hf_beta, etc.)

Primary source : official kokoro-onnx GitHub release
Fallback source: Bindkushal HuggingFace mirror
"""

import os
import sys
import urllib.request
import logging

logger = logging.getLogger('speak.download_models')

# Cache directory
CACHE_DIR = os.path.expanduser('~/.cache/speak-ai')

# Model file definitions.
# Primary: official kokoro-onnx GitHub release.
# Fallback: Bindkushal HuggingFace mirror in case primary is down.
MODELS = {
    'kokoro-v1.0.int8.onnx': {
        'primary':  'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx',
        'fallback': 'https://huggingface.co/Bindkushal/speak-ai-models/resolve/main/kokoro-v1.0.int8.onnx',
        'size_mb':  88,
    },
    'voices-v1.0.bin': {
        'primary':  'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin',
        'fallback': 'https://huggingface.co/Bindkushal/speak-ai-models/resolve/main/voices-v1.0.bin',
        'size_mb':  5.5,
    },
}


def _progress(block_count, block_size, total_size):
    """Simple download progress bar."""
    if total_size <= 0:
        return
    downloaded = min(block_count * block_size, total_size)
    pct = downloaded / total_size * 100
    bar = '#' * int(pct / 2)
    sys.stdout.write('\r    [%-50s] %5.1f%%' % (bar, pct))
    sys.stdout.flush()
    if downloaded >= total_size:
        print()


def _download_file(filename, url, dest_dir):
    """
    Download a single file from url into dest_dir.
    Returns True on success, False on failure.
    """
    dest = os.path.join(dest_dir, filename)
    tmp = dest + '.tmp'
    try:
        urllib.request.urlretrieve(url, tmp, reporthook=_progress)
        os.replace(tmp, dest)
        return True
    except Exception as e:
        logger.warning('Download failed (%s): %s', url, e)
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def ensure_models(cache_dir=None):
    """
    Download missing model files into cache_dir (default ~/.cache/speak-ai/).
    Tries the primary URL first, falls back to the HuggingFace mirror.

    Returns a dict mapping filename -> full local path for all required files.
    Raises RuntimeError if any file cannot be downloaded from either source.
    """
    cache_dir = cache_dir or CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    paths = {}
    for filename, info in MODELS.items():
        dest = os.path.join(cache_dir, filename)

        if os.path.exists(dest):
            logger.info('Found cached: %s', dest)
            paths[filename] = dest
            continue

        print('Downloading %s (~%sMB)...' % (filename, info['size_mb']))

        if _download_file(filename, info['primary'], cache_dir):
            print('Downloaded %s' % filename)
            paths[filename] = dest
            continue

        print('Primary failed, trying fallback mirror...')
        if _download_file(filename, info['fallback'], cache_dir):
            print('Downloaded %s from fallback' % filename)
            paths[filename] = dest
            continue

        raise RuntimeError(
            'Could not download %s from either source.\n'
            '  Primary : %s\n'
            '  Fallback: %s\n'
            'Please check your internet connection and try again.'
            % (filename, info['primary'], info['fallback'])
        )

    return paths


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s  %(message)s')
    print('Kokoro ONNX model downloader')
    print('Cache directory: %s' % CACHE_DIR)
    print('-' * 40)
    try:
        paths = ensure_models()
        print('\nAll model files ready:')
        for name, path in paths.items():
            size = os.path.getsize(path) / 1024 / 1024
            print('   %s: %s (%.1fMB)' % (name, path, size))
    except RuntimeError as e:
        print('\nERROR: %s' % e)
        sys.exit(1)
