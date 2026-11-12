"""Currency-aware formatting and explicit budget matching for LAPENG AI."""
import re
from decimal import Decimal, InvalidOperation

SYMBOLS = {'USD': '$', 'ZAR': 'R', 'EUR': '€', 'GBP': '£'}

def format_price(amount, currency):
    code = (currency or '').upper().strip()
    try:
        value = Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        return 'price unavailable'
    symbol = SYMBOLS.get(code)
    if code in ('USD', 'ZAR'):
        return f'{symbol}{value:,.2f} {code}'
    return f'{value:,.2f} {code or "UNKNOWN CURRENCY"}'

def budget_mentioned(question):
    """Only extract amounts when the currency is explicit, never infer one."""
    patterns = [
       ('USD', r'(?<![a-zA-Z])(?:US\s*\$|USD\s*|\$\s*)([0-9][0-9,]*(?:\.[0-9]{1,2})?)'),
       ('ZAR', r'(?<![a-zA-Z])(?:ZAR\s*|R\s*)([0-9][0-9,]*(?:\.[0-9]{1,2})?)'),
       ('EUR', r'(?<![a-zA-Z])(?:EUR\s*|€\s*)([0-9][0-9,]*(?:\.[0-9]{1,2})?)'),
       ('GBP', r'(?<![a-zA-Z])(?:GBP\s*|£\s*)([0-9][0-9,]*(?:\.[0-9]{1,2})?)')]
    found=[]
    for currency, pattern in patterns:
        for match in re.finditer(pattern, question, re.I):
            found.append((match.start(), currency, Decimal(match.group(1).replace(',',''))))
    return [(code, amount) for _, code, amount in sorted(found)]

def compare_to_budget(listing, currency, budget):
    listing_currency = str(listing['currency']).upper()
    if currency != listing_currency:
        return 'Cannot compare directly: different currencies. No live FX rate is configured.'
    value = Decimal(str(listing['price']))
    return 'Within stated numerical budget before fees or delivery' if value <= budget else 'Above stated numerical budget before fees or delivery'

def price_answer(question, listings):
    """Deterministic pricing statements; returns None for non-price queries."""
    q=question.lower()
    amounts=budget_mentioned(question)
    price_intent=bool(amounts or any(t in q for t in ('price','cost','how much','expensive','cheap','budget','under ','below ','more than','less than','currency','dollar','rand','zar','usd','convert','conversion')))
    if not price_intent:
        return None
    if not listings:
        return ('R49 means 49 South African rand (ZAR); $49 normally means 49 US dollars (USD) in LAPENG. '
            'They are not the same amount. Currency conversion is not available without a current verified exchange rate. '
            'I could not locate a matching catalogue listing to quote.')
    lines=[]
    for listing in listings[:5]:
        line=f"{listing['title']} from {listing['provider_name']}: {format_price(listing['price'], listing['currency'])} (listed starting price)"
        if len(amounts)==1:
            line+=' — '+compare_to_budget(listing, *amounts[0])
        lines.append(line)
    end='Prices are stored per listing; do not treat R49 and $49 as equivalent. No exchange-rate conversion, shipping, tax or final checkout amount is implied.'
    if len(amounts)>1:
        end='Your question includes different currencies; these cannot be combined or compared numerically without a verified exchange rate. '+end
    return '; '.join(lines)+'. '+end
