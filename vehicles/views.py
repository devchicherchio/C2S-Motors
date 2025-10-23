# vehicles/views.py
import os
import re
import math
from decimal import Decimal
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.db.models import Q
from .models import Vehicle

# OpenAI SDK (usa a key do ambiente)
from openai import OpenAI

# -----------------------------
# Helpers de parsing de filtro
# -----------------------------
BODY_TYPES = {
    "suv": "SUV",
    "hatch": "Hatch",
    "sedan": "Sedan",
    "picape": "Picape",
    "pickup": "Picape",
    "perua": "Perua",
    "wagon": "Perua",
    "coupe": "Coupé",
    "coupé": "Coupé",
}
TRANSMISSIONS = {
    "manual": "Manual",
    "automatica": "Automática",
    "automática": "Automática",
    "auto": "Automática",
    "cvt": "CVT",
}
FUELS = {
    "flex": "flex",
    "gasolina": "gasolina",
    "alcool": "alcool",
    "álcool": "alcool",
    "etanol": "alcool",
    "diesel": "diesel",
    "elétrico": "eletrico",
    "eletrico": "eletrico",
    "híbrido": "hibrido",
    "hibrido": "hibrido",
}
PRICE_PT_RE = re.compile(r"(?:até|ate|<=|<|por|no\s+máximo)\s*R?\$?\s*([\d\.\,]+)", re.IGNORECASE)
PRICE_NUM_RE = re.compile(r"(\d{2,3}[\.\d]{0,})\s*(?:mil)?", re.IGNORECASE)
YEAR_MIN_RE = re.compile(r"(?:a partir de|>=|de)\s*(19|20)\d{2}", re.IGNORECASE)
YEAR_RANGE_RE = re.compile(r"(19|20)\d{2}\s*-\s*(19|20)\d{2}")
DOORS_RE = re.compile(r"(\b2\b|\b4\b|\b5\b)\s*portas", re.IGNORECASE)

def _pt_money_to_decimal(txt: str) -> Decimal | None:
    txt = txt.strip()
    # normaliza "120 mil", "120.000", "120,000" etc
    m = PRICE_NUM_RE.search(txt)
    if not m:
        return None
    raw = m.group(1)
    raw = raw.replace(".", "").replace(",", ".")
    try:
        val = float(raw)
        # heurística: se usuário disse "120" pode ser "120 mil"
        if val < 1000:
            val *= 1000
        return Decimal(f"{val:.2f}")
    except Exception:
        return None

def parse_filters(user_msg: str) -> dict:
    msg = user_msg.lower()
    f = {
        "body_type": None,
        "transmission": None,
        "fuel": None,
        "price_max": None,
        "year_min": None,
        "year_range": None,
        "doors": None,
    }
    # carroceria
    for k, v in BODY_TYPES.items():
        if k in msg:
            f["body_type"] = v
            break
    # transmissão
    for k, v in TRANSMISSIONS.items():
        if k in msg:
            f["transmission"] = v
            break
    # combustível
    for k, v in FUELS.items():
        if k in msg:
            f["fuel"] = v
            break
    # preço máximo
    m = PRICE_PT_RE.search(msg)
    if m:
        val = _pt_money_to_decimal(m.group(1))
        if val:
            f["price_max"] = val
    else:
        # fallback: "até 120 mil" sem R$
        if "mil" in msg:
            m2 = PRICE_NUM_RE.search(msg)
            if m2:
                val = _pt_money_to_decimal(m2.group(0))
                if val:
                    f["price_max"] = val
    # ano mínimo
    m = YEAR_MIN_RE.search(msg)
    if m:
        f["year_min"] = int(m.group(0)[-4:])
    # intervalo de anos 2017-2022
    m = YEAR_RANGE_RE.search(msg)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        f["year_range"] = (min(a, b), max(a, b))
    # portas
    m = DOORS_RE.search(msg)
    if m:
        f["doors"] = int(m.group(1))
    return f

def query_from_filters(f: dict):
    qs = Vehicle.objects.all()
    if f["body_type"]:
        qs = qs.filter(body_type__iexact=f["body_type"])
    if f["transmission"]:
        qs = qs.filter(transmission__iexact=f["transmission"])
    if f["fuel"]:
        qs = qs.filter(fuel_type__iexact=f["fuel"])
    if f["price_max"]:
        qs = qs.filter(price__lte=f["price_max"])
    if f["year_min"]:
        qs = qs.filter(year__gte=f["year_min"])
    if f["year_range"]:
        a, b = f["year_range"]
        qs = qs.filter(year__gte=a, year__lte=b)
    if f["doors"]:
        qs = qs.filter(doors=f["doors"])
    return qs

def vehicle_to_dict(v: Vehicle) -> dict:
    return {
        "brand": v.brand,
        "model": v.model,
        "year": v.year,
        "engine": v.engine,
        "fuel_type": v.fuel_type,
        "color": v.color,
        "mileage_km": v.mileage_km,
        "doors": v.doors,
        "transmission": v.transmission,
        "body_type": v.body_type,
        "price": float(v.price),
        "vin": v.vin,
    }

def make_catalog_context(qs, limit=8) -> str:
    """
    Constrói um 'snapshot' legível do catálogo para o LLM usar como contexto.
    """
    rows = []
    for v in qs[:limit]:
        rows.append(
            f"- {v.brand} {v.model} {v.year} | {v.body_type}, {v.transmission}, "
            f"{v.fuel_type}, {v.engine}, {v.doors} portas, {v.color}, "
            f"{v.mileage_km} km | R$ {v.price:.2f} | VIN {v.vin}"
        )
    if not rows:
        return "Nenhum veículo correspondente encontrado no estoque."
    return "Estoque relevante:\n" + "\n".join(rows)

# -----------------------------
# View principal do chat
# -----------------------------

@csrf_protect
@require_http_methods(["GET", "POST"])
def vehicle_chat_view(request):
    """
    GET: renderiza a página do chat
    POST: recebe {message, history?} e responde com {reply, suggestions[]}
    """
    if request.method == "GET":
        return render(request, "vehicles/chat.html", {})

    # POST (AJAX)
    try:
        data = request.json if hasattr(request, "json") else None
        if data is None:
            # fallback: parse body
            import json
            data = json.loads(request.body.decode("utf-8"))
        user_msg = (data.get("message") or "").strip()
        history = data.get("history") or []
        if not user_msg:
            return HttpResponseBadRequest("Mensagem vazia.")
    except Exception:
        return HttpResponseBadRequest("Payload inválido.")

    # 1) gera filtros + consulta
    filters = parse_filters(user_msg)
    qs = query_from_filters(filters).order_by("-created_at")
    # fallback: se muito restritivo, mostra algo do catálogo recente
    if qs.count() == 0:
        qs = Vehicle.objects.all().order_by("-created_at")

    # seleciona alguns para contexto e para cards no front
    candidates = list(qs[:8])
    suggestions = [vehicle_to_dict(v) for v in candidates]
    context_text = make_catalog_context(qs, limit=8)

    # 2) chama LLM
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # fallback determinístico sem IA
        reply = (
            "Não encontrei a chave da OpenAI. Seguem opções do nosso estoque:\n\n"
            + context_text
        )
        return JsonResponse({"reply": reply, "suggestions": suggestions})

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "Você é um consultor de vendas de uma loja de veículos no Brasil. "
        "Responda de forma clara, amigável e objetiva, SEM inventar estoque. "
        "Use apenas as opções do contexto fornecido. "
        "Quando o cliente pedir algo específico (ex.: SUV automático até R$ 120.000), "
        "explique o raciocínio e sugira de 3 a 5 opções compatíveis. "
        "Se nada for compatível, sugira alternativas próximas (ano ou preço próximos). "
        "Mostre preços em reais com duas casas (ex.: R$ 85.900,00)."
    )

    user_prompt = (
        f"Pergunta do cliente: {user_msg}\n\n"
        f"{context_text}\n\n"
        "Monte sua resposta considerando apenas o estoque acima."
    )

    # histórico opcional (mantemos curto para não gastar tokens)
    msgs = [{"role": "system", "content": system_prompt}]
    for h in history[-6:]:
        role = "user" if h.get("role") == "user" else "assistant"
        msgs.append({"role": role, "content": h.get("content", "")})
    msgs.append({"role": "user", "content": user_prompt})

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=msgs,
        temperature=0.6,
        max_tokens=600,
    )
    reply = completion.choices[0].message.content

    return JsonResponse({
        "reply": reply,
        "suggestions": suggestions
    })
