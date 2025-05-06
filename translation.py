"""
translation.py - Translation module for AgroAssist

This module provides translation functionality using Google Translate API
with efficient caching to reduce API calls and improve performance.
"""

from flask import session, request, jsonify
from functools import lru_cache
# from googletrans import Translator
from deep_translator import GoogleTranslator
import json
import os
import time

# Initialize translator with multiple fallback servers for reliability
translator = GoogleTranslator(service_urls=[
    'translate.google.com',
    'translate.google.co.kr',
    'translate.google.co.in',
])

# Create a translations cache directory if it doesn't exist
os.makedirs('translations_cache', exist_ok=True)

# Dictionary to store translations in memory for quick access
translation_cache = {'hi': {}, 'ta': {}, 'te': {}}

def test_translation_service():
    test_text = "Hello World"
    print("\nTesting translation service:")
    
    for lang in ['hi', 'ta', 'te']:
        try:
            # Directly use GoogleTranslator
            translated = GoogleTranslator(source='en', target=lang).translate(test_text)
            print(f"{lang.upper()}: {translated}")
        except Exception as e:
            print(f"Error translating to {lang}: {str(e)}")
    
    return "Check console for translation test results"

# Load existing translations from files
def load_cached_translations():
    """Load previously cached translations from disk to memory"""
    global translation_cache
    try:
        for lang in ['hi', 'ta', 'te']:
            cache_file = f'translations_cache/{lang}.json'
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    lang_cache = json.load(f)
                    translation_cache[lang] = lang_cache
                    print(f"Loaded {len(lang_cache)} cached translations for {lang}")
    except Exception as e:
        print(f"Error loading translation cache: {e}")
        translation_cache = {'hi': {}, 'ta': {}, 'te': {}}

# Save translations to file periodically
def save_translations_to_cache():
    """Save in-memory translations to disk cache files"""
    for lang, translations in translation_cache.items():
        try:
            with open(f'translations_cache/{lang}.json', 'w', encoding='utf-8') as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving translation cache for {lang}: {e}")

# Decorator for throttling API calls if needed
def throttled(max_per_second=5):
    """Decorator to throttle function calls to avoid API rate limits"""
    min_interval = 1.0 / max_per_second
    last_time_called = [0.0]

    def decorate(func):
        def throttled_function(*args, **kwargs):
            elapsed = time.time() - last_time_called[0]
            left_to_wait = min_interval - elapsed

            if left_to_wait > 0:
                time.sleep(left_to_wait)

            last_time_called[0] = time.time()
            return func(*args, **kwargs)
        return throttled_function
    return decorate

# Function to translate text with integrated caching
@throttled(max_per_second=10)
@lru_cache(maxsize=500)

def translate_text(text, source_lang="en", target_lang="hi"):
    # Skip empty or same-language requests
    if not text or not text.strip() or source_lang == target_lang:
        return text
    
    text = str(text).strip()
    
    # Create a simple cache key
    cache_key = f"{target_lang}:{text}"
    
    # Check memory cache first
    if cache_key in translation_cache:
        return translation_cache[cache_key]
    
    try:
        # Get translation
        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
        
        # Store in cache
        translation_cache[cache_key] = translated
        
        # Simple validation
        if not translated or translated == text:
            return text
            
        return translated
        
    except Exception as e:
        print(f"Translation error for '{text}': {str(e)}")
        return text  # Fallback to original text
    
def register_translation_handlers(app):
    """
    Register translation handlers with the Flask app
    
    Args:
        app: Flask application instance
    """
    # Load cached translations on startup
    load_cached_translations()
    
    @app.template_filter('translate')
    def translate_filter(text):
        """
        Template filter to translate text
        
        Usage in templates: {{ 'Text to translate' | translate }}
        """
        current_lang = session.get('language', 'en')
        if current_lang == 'en':
            return text
        return translate_text(str(text), 'en', current_lang)
    
    @app.route('/translate', methods=['POST'])
    def translate_route():
        """Route handler for language change requests"""
        if 'user_id' not in session:
            return jsonify({"success": False, "error": "Not logged in"}), 401
        
        lang = request.args.get('lang', 'en')
        if lang not in ['en', 'hi', 'ta', 'te']:
            return jsonify({"success": False, "error": "Unsupported language"}), 400
        
        # Update user's language preference in session
        session['language'] = lang
        return jsonify({"success": True, "language": lang})
    
    # Save translations when app is shutting down
    @app.teardown_appcontext
    def save_translations_on_shutdown(exception=None):
        save_translations_to_cache()

# If this file is run directly, print some debug info
if __name__ == "__main__":
    print("Translation module - Debug info:")
    sample_text = "Hello, welcome to AgroAssist!"
    for lang in ['hi', 'ta', 'te']:
        translated = translate_text(sample_text, 'en', lang)
        print(f"Sample translation ({lang}): {translated}")