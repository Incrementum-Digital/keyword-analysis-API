"""
Campaign Naming Engine

Ported from CampaignForge namingEngine.ts
Generates campaign names from templates with token substitution.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime


# Match type abbreviations
MATCH_ABBREV: Dict[str, str] = {
    'exact': 'EX',
    'phrase': 'PH',
    'broad': 'BR',
    'product': 'PAT',
    'auto': 'Auto',
}


@dataclass
class NamingTemplate:
    """Campaign naming template configuration."""
    tokens: List[str]
    separator: str = "_"
    custom_tokens: Dict[str, str] = None

    def __post_init__(self):
        if self.custom_tokens is None:
            self.custom_tokens = {}


@dataclass
class NamingContext:
    """Context for generating a campaign name."""
    sku: str
    match_type: str
    root_group: str
    tier: Optional[str] = None
    date: Optional[str] = None
    index: Optional[int] = None


def format_date(date_str: Optional[str] = None) -> str:
    """Format date as DDMMYY."""
    if not date_str:
        d = datetime.now()
    else:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            d = datetime.now()

    return f"{d.day:02d}{d.month:02d}{str(d.year)[-2:]}"


def resolve_token(token: str, context: NamingContext, custom_tokens: Dict[str, str]) -> str:
    """Resolve a single token to its value."""
    token_upper = token.upper()

    if token_upper == 'SKU':
        return context.sku or 'SKU'
    elif token_upper == 'SP':
        return 'SP'
    elif token_upper in ('AD TYPE', 'AD_TYPE'):
        return 'Auto' if context.match_type.lower() == 'auto' else 'M'
    elif token_upper in ('MATCH', 'MATCH TYPE', 'MATCH_TYPE'):
        return MATCH_ABBREV.get(context.match_type.lower(), context.match_type)
    elif token_upper == 'GROUP':
        return context.root_group.replace(' ', '_')
    elif token_upper == 'TIER':
        return context.tier or ''
    elif token_upper in ('DATE', 'START DATE', 'START_DATE'):
        return format_date(context.date)
    else:
        return custom_tokens.get(token, token)


def generate_campaign_name(template: NamingTemplate, context: NamingContext) -> str:
    """
    Generate a campaign name from a template and context.

    Args:
        template: The naming template with tokens and separator
        context: The context containing values for token substitution

    Returns:
        Generated campaign name
    """
    parts = [
        resolve_token(token, context, template.custom_tokens or {})
        for token in template.tokens
    ]
    # Filter out empty parts
    parts = [p for p in parts if p]

    name = template.separator.join(parts)

    # Add index suffix if provided and > 0
    if context.index is not None and context.index > 0:
        name += f" {context.index + 1}"

    return name
