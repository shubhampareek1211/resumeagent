"""Read local, ignored candidate settings; public defaults are fictional."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_profile(root=ROOT):
    path = root / 'profile.local.json'
    if not path.exists():
        path = root / 'profile.example.json'
    profile = json.loads(path.read_text(encoding='utf-8'))
    for key in ('header_tokens', 'adjacent_terms', 'forbidden_terms'):
        value = profile.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f'{key} must be a list of nonempty strings in {path.name}')
    if not profile['header_tokens']:
        raise ValueError('header_tokens cannot be empty')
    if not isinstance(profile.get('max_skills_lines'), int) or profile['max_skills_lines'] < 1:
        raise ValueError('max_skills_lines must be a positive integer')
    fill = profile.get('min_fill_ratio')
    if not isinstance(fill, (int, float)) or not 0 <= fill <= 1:
        raise ValueError('min_fill_ratio must be between 0 and 1')
    return profile
