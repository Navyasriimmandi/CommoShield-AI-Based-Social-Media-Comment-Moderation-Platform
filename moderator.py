"""
moderator.py — ML-powered comment moderation for Nexus Social

Loads the trained TF-IDF + Logistic Regression model and provides
a single predict() function used by Flask routes.

4 Moderation Levels:
  0 — CLEAN  : Auto-approved, published immediately
  1 — MILD   : Auto-approved, user receives a soft warning
  2 — TOXIC  : Held for admin review (flagged)
  3 — SEVERE : Auto-blocked, never published

Run the Jupyter notebook first to generate model/moderation_model.pkl
and model/tfidf_vectorizer.pkl. Until the model is trained, this module
falls back to a rule-based system so the app still works.
"""

import re
import os
import joblib

# ── Paths ────────────────────────────────────────────────────────────────────
MODEL_DIR  = os.path.join(os.path.dirname(__file__), 'model')
MODEL_PATH = os.path.join(MODEL_DIR, 'moderation_model.pkl')
VEC_PATH   = os.path.join(MODEL_DIR, 'tfidf_vectorizer.pkl')

# ── Level metadata ────────────────────────────────────────────────────────────
LEVELS = {
    0: {
        'name':        'CLEAN',
        'status':      'approved',
        'color':       '#00e578',
        'icon':        '✅',
        'user_msg':    None,   # no message shown to user
        'admin_label': 'Clean',
    },
    1: {
        'name':        'MILD',
        'status':      'approved',   # still published, but user warned
        'color':       '#7c6bff',
        'icon':        '⚠️',
        'user_msg':    'Your comment was published but may be borderline. '
                       'Please keep discussions respectful.',
        'admin_label': 'Mild',
    },
    2: {
        'name':        'TOXIC',
        'status':      'flagged',
        'color':       '#ffa53d',
        'icon':        '🔶',
        'user_msg':    'Your comment has been held for review due to '
                       'potentially toxic language.',
        'admin_label': 'Toxic',
    },
    3: {
        'name':        'SEVERE',
        'status':      'blocked',
        'color':       '#ff4444',
        'icon':        '🚫',
        'user_msg':    'Your comment was blocked. It appears to contain '
                       'threats, hate speech, or severe abuse. '
                       'This may result in account action.',
        'admin_label': 'Severe',
    },
}

# ── Fallback rule-based lists (used if model not loaded) ─────────────────────
_SEVERE_WORDS = [
    'kill you', 'i will find you', 'death threat', 'bomb', 'shoot you',
    'die nigger', 'kys', 'kill yourself', 'white supremac', 'nazi',
    'genocide', 'rape you',
]
_TOXIC_WORDS = [
    'idiot', 'moron', 'stupid', 'dumbass', 'asshole', 'bitch', 'bastard',
    'fuck', 'shit', 'crap', 'wtf', 'stfu', 'loser', 'retard', 'faggot',
    'slut', 'whore', 'piss off', 'screw you', 'go to hell',
]
_MILD_WORDS = ['damn', 'hell', 'crap', 'sucks', 'lame', 'bad', 'wrong',
               'disagree', 'hate this', 'terrible', 'awful']

# ── Load model ────────────────────────────────────────────────────────────────
_model = None
_vectorizer = None
_model_loaded = False

def _load_model():
    global _model, _vectorizer, _model_loaded
    if _model_loaded:
        return
    if os.path.exists(MODEL_PATH) and os.path.exists(VEC_PATH):
        try:
            _model      = joblib.load(MODEL_PATH)
            _vectorizer = joblib.load(VEC_PATH)
            _model_loaded = True
            print('[Moderator] ✅ ML model loaded from disk')
        except Exception as e:
            print(f'[Moderator] ⚠️  Could not load model: {e}')
    else:
        print('[Moderator] ℹ️  No trained model found — using rule-based fallback')
        print('[Moderator]    Run the Jupyter notebook to train the ML model.')

_load_model()


# ── Text cleaning (must match notebook) ──────────────────────────────────────
def _clean(text: str) -> str:
    if not text:
        return ''
    text = text.lower()
    text = re.sub(r'https?://\S+', ' url ', text)
    text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', ' ip ', text)
    text = re.sub(r'[^a-z0-9\s!?.,:;]', ' ', text)
    text = re.sub(r'(.)\1{3,}', r'\1\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Rule-based fallback ───────────────────────────────────────────────────────
def _rule_based(text: str):
    lower = text.lower()
    for phrase in _SEVERE_WORDS:
        if phrase in lower:
            return 3, 0.95, f'Severe language detected: "{phrase}"'
    for word in _TOXIC_WORDS:
        if word in lower:
            return 2, 0.85, f'Toxic language detected: "{word}"'
    cap_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
    if cap_ratio > 0.7 and len(text) > 8:
        return 2, 0.75, 'Excessive capitalisation (spam/anger indicator)'
    if text.count('!') > 5:
        return 1, 0.70, 'Excessive exclamation marks'
    for word in _MILD_WORDS:
        if word in lower:
            return 1, 0.65, f'Mild borderline language: "{word}"'
    return 0, 0.99, None


# ── Public API ────────────────────────────────────────────────────────────────
def predict(text: str) -> dict:
    """
    Analyse a comment and return a moderation decision.

    Returns
    -------
    {
        'level'      : int  (0–3),
        'level_name' : str  ('CLEAN' | 'MILD' | 'TOXIC' | 'SEVERE'),
        'status'     : str  ('approved' | 'flagged' | 'blocked'),
        'confidence' : float (0–1),
        'flag_reason': str | None,
        'user_msg'   : str | None,
        'color'      : str,
        'icon'       : str,
        'ml_used'    : bool,
    }
    """
    # Basic validation
    if not text or len(text.strip()) < 2:
        return _build(0, 0.99, 'Too short', ml=False)
    if len(text) > 2000:
        return _build(2, 0.99, 'Comment exceeds 2000 characters', ml=False)

    if _model_loaded:
        cleaned = _clean(text)
        vec     = _vectorizer.transform([cleaned])
        level   = int(_model.predict(vec)[0])
        conf    = float(_model.predict_proba(vec)[0][level])
        reason  = _flag_reason(level, conf)
        return _build(level, conf, reason, ml=True)
    else:
        level, conf, reason = _rule_based(text)
        return _build(level, conf, reason, ml=False)


def _flag_reason(level: int, conf: float) -> str | None:
    if level == 0:
        return None
    labels = {1: 'Mild/borderline language', 2: 'Toxic or obscene language',
              3: 'Severe: threat/hate speech/abuse'}
    return f"{labels[level]} (confidence: {conf:.0%})"


def _build(level: int, confidence: float, flag_reason, ml: bool) -> dict:
    meta = LEVELS[level]
    return {
        'level'      : level,
        'level_name' : meta['name'],
        'status'     : meta['status'],
        'confidence' : round(confidence, 4),
        'flag_reason': flag_reason,
        'user_msg'   : meta['user_msg'],
        'color'      : meta['color'],
        'icon'       : meta['icon'],
        'admin_label': meta['admin_label'],
        'ml_used'    : ml,
    }
