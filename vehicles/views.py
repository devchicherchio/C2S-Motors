# vehicles/views.py
import os
import re
import math
import json
import unicodedata
from typing import Optional, Tuple, List, Dict
from decimal import Decimal

from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.db.models import Q, QuerySet, Count, Min, Max, F
from django.utils.timezone import now

from .models import Vehicle

try:
    from openai import OpenAI, RateLimitError, APIError, APIConnectionError, AuthenticationError
except Exception:
    OpenAI = None  # type: ignore

###############################################################################
#                                  VISÃO GERAL                                  #
###############################################################################
# Esta view serve como um chat que faz as consultas ao estoque de veículos
#
# Objetivo desta implementação:
# 1) Extrair filtros de linguagem natural (português) como tipo do veículo,
#    transmissão, combustível, teto de preço, ano (mínimo ou intervalo) e nº de portas.

# 2) Consultar o banco de dados usando os filtros detectados.

# 3) Construir um "contexto" seguro para o LLM (sem alucinações) contendo:
#       - contagem total de resultados no estoque,
#       - um resumo agregado (por tipo/combustível/ano/preço),
#       - e algumas amostras (linhas) do catálogo correspondente.
#    Observação: NÃO enviamos todo o banco para o LLM por questões de custo/limite,
#    mas garantimos que TUDO que o LLM "vê" veio 100% do seu BD.

# 4) Produzir uma resposta amigável. Se a API da OpenAI falhar ou não estiver presente,
#    a resposta é gerada por um fallback determinístico usando o seu catálogo.

#
# Segurança / Boas práticas:
# - A API key NUNCA é hard-coded; vem de OPENAI_API_KEY no ambiente.
# - A resposta "manda" o LLM usar somente o contexto provido (estoque).
# - Limites e sumarização evitam estouros de tokens.
###############################################################################


# -----------------------------
# Dicionários e Regex de parsing
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

# Exemplos aceitos:
# "até R$ 120.000", "ate 120 mil", "<= 95.000", "no máximo 80 mil"
PRICE_PT_RE = re.compile(r"(?:até|ate|<=|<|por|no\s+máximo)\s*R?\$?\s*([\d\.\,]+)", re.IGNORECASE)
PRICE_NUM_RE = re.compile(r"(\d{2,3}[\.\d]{0,})\s*(?:mil)?", re.IGNORECASE)

# "a partir de 2018", ">= 2019", "de 2020"
YEAR_MIN_RE = re.compile(r"(?:a partir de|>=|de)\s*((?:19|20)\d{2})", re.IGNORECASE)

# "2017-2022"
YEAR_RANGE_RE = re.compile(r"((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})")

# "4 portas", "2 portas", "5 portas"
DOORS_RE = re.compile(r"(\b2\b|\b4\b|\b5\b)\s*portas", re.IGNORECASE)


# -----------------------------
# Utilidades
# -----------------------------
def _normalize(txt: str) -> str:
    """
    Remove acentos e normaliza para comparação robusta.
    """
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii").lower()


def _pt_money_to_decimal(txt: str) -> Optional[Decimal]:
    """
    Converte expressões como "120 mil", "120.000", "120,000" em Decimal.
    Heurística: se valor < 1000, interpretamos como "milhares" (ex.: "120" => 120.000).
    """
    txt = txt.strip()
    m = PRICE_NUM_RE.search(txt)
    if not m:
        return None
    raw = m.group(1)
    raw = raw.replace(".", "").replace(",", ".")
    try:
        val = float(raw)
        if val < 1000:
            val *= 1000.0
        return Decimal(f"{val:.2f}")
    except Exception:
        return None


def parse_filters(user_msg: str) -> Dict:
    """
    Extrai filtros a partir da mensagem em PT-BR.

    Retorna dict:
        {
            "body_type": Optional[str],
            "transmission": Optional[str],
            "fuel": Optional[str],
            "price_max": Optional[Decimal],
            "year_min": Optional[int],
            "year_range": Optional[Tuple[int, int]],
            "doors": Optional[int],
        }
    """
    norm = _normalize(user_msg)

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
        if k in norm:
            f["body_type"] = v
            break

    # transmissão
    for k, v in TRANSMISSIONS.items():
        if k in norm:
            f["transmission"] = v
            break

    # combustível
    for k, v in FUELS.items():
        if k in norm:
            f["fuel"] = v
            break

    # preço máximo
    m = PRICE_PT_RE.search(norm)
    if m:
        val = _pt_money_to_decimal(m.group(1))
        if val:
            f["price_max"] = val
    else:
        # fallback: "até 120 mil" sem R$
        if "mil" in norm:
            m2 = PRICE_NUM_RE.search(norm)
            if m2:
                val = _pt_money_to_decimal(m2.group(0))
                if val:
                    f["price_max"] = val

    # ano mínimo
    m = YEAR_MIN_RE.search(norm)
    if m:
        f["year_min"] = int(m.group(1))

    # intervalo de anos 2017-2022
    m = YEAR_RANGE_RE.search(norm)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        f["year_range"] = (min(a, b), max(a, b))

    # portas
    m = DOORS_RE.search(norm)
    if m:
        f["doors"] = int(m.group(1))

    return f


def query_from_filters(f: Dict) -> QuerySet:
    """
    Constrói a QuerySet a partir dos filtros.
    """
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


def vehicle_to_dict(v: Vehicle) -> Dict:
    """
    Serializa um veículo para o front.
    """
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


def _price_band(price: Decimal) -> str:
    """
    Cria faixas de preço em blocos de 20 mil para sumarização.
    """
    try:
        val = float(price)
    except Exception:
        return "Indefinido"
    step = 20000.0
    bucket = math.floor(val / step)
    low, high = int(bucket * step), int((bucket + 1) * step - 1)
    return f"R$ {low:,.0f} - R$ {high:,.0f}".replace(",", ".").replace(".", ",").replace(",00", "")


def summarize_queryset(qs: QuerySet) -> Dict:
    """
    Gera um resumo agregado (contagens por carroceria e combustível) e
    faixas de preço/ano para orientar o LLM (e o usuário).
    """
    total = qs.count()

    # buckets simples (evita SQL complexo; pode ajustar conforme volume)
    by_body = (
        qs.values("body_type")
        .annotate(c=Count("id"))
        .order_by("-c")
    )
    by_fuel = (
        qs.values("fuel_type")
        .annotate(c=Count("id"))
        .order_by("-c")
    )
    # Faixas de ano
    minmax = qs.aggregate(min_year=Min("year"), max_year=Max("year"))
    min_year = minmax.get("min_year") or 0
    max_year = minmax.get("max_year") or 0

    # Amostragem rápida para faixas de preço
    price_samples = {}
    for v in qs.values("price")[:300]:  # limitar amostra
        band = _price_band(v["price"])
        price_samples[band] = price_samples.get(band, 0) + 1

    # Ordena faixas por contagem desc
    price_bands_sorted = sorted(price_samples.items(), key=lambda x: -x[1])[:10]

    return {
        "total": total,
        "by_body": [{"body_type": r["body_type"] or "Indefinido", "count": r["c"]} for r in by_body],
        "by_fuel": [{"fuel_type": r["fuel_type"] or "Indefinido", "count": r["c"]} for r in by_fuel],
        "year_span": {"min": min_year, "max": max_year},
        "top_price_bands": [{"band": b, "count": c} for b, c in price_bands_sorted],
    }


def make_catalog_context(qs: QuerySet, max_lines: int = 120) -> str:
    """
    Constrói um contexto textual para o LLM estritamente derivado do BD.
    Inclui:
      - resumo agregado do conjunto,
      - e até `max_lines` exemplos detalhados (uma linha por veículo).

    Observações:
    - Não "inventa" nada; cada linha vem do BD.
    - Mantemos o formato humano-legível para o modelo se orientar.
    """
    summary = summarize_queryset(qs)
    lines = [
        f"Resumo do estoque filtrado: total = {summary['total']}",
        f"Intervalo de anos: {summary['year_span']['min']} a {summary['year_span']['max']}",
    ]

    if summary["by_body"]:
        body_str = ", ".join(f"{b['body_type']}: {b['count']}" for b in summary["by_body"][:8])
        lines.append(f"Por carroceria: {body_str}")

    if summary["by_fuel"]:
        fuel_str = ", ".join(f"{f['fuel_type']}: {f['count']}" for f in summary["by_fuel"][:8])
        lines.append(f"Por combustível: {fuel_str}")

    if summary["top_price_bands"]:
        pb_str = ", ".join(f"{pb['band']} ({pb['count']})" for pb in summary["top_price_bands"][:8])
        lines.append(f"Faixas de preço (amostra): {pb_str}")

    lines.append("")  # quebra

    # Exemplos detalhados (ordenados por mais novos)
    examples = []
    # Evita contar de novo; usa slice sem estourar memória
    for v in qs.order_by("-created_at").values(
        "brand", "model", "year", "body_type", "transmission", "fuel_type",
        "engine", "doors", "color", "mileage_km", "price", "vin"
    )[:max_lines]:
        examples.append(
            f"- {v['brand']} {v['model']} {v['year']} | {v['body_type']}, {v['transmission']}, "
            f"{v['fuel_type']}, {v['engine']}, {v['doors']} portas, {v['color']}, "
            f"{v['mileage_km']} km | R$ {Decimal(v['price']):.2f} | VIN {v['vin']}"
        )

    if not examples:
        lines.append("Nenhum veículo correspondente encontrado no estoque.")
    else:
        lines.append("Amostras do estoque:")
        lines.extend(examples)

    return "\n".join(lines)


def build_suggestions(filters: Dict, qs_total: int) -> List[str]:
    """
    Sugestões de follow-up para o usuário (chips no front).
    """
    s = []
    # Direciona a refinar se resultado enorme:
    if qs_total > 40:
        s.append("Filtrar por ano mínimo (ex.: a partir de 2020)")
        s.append("Definir um teto de preço (ex.: até R$ 120.000)")
        s.append("Escolher transmissão (Manual/Automática/CVT)")
    # Dicas adicionais
    if not filters.get("body_type"):
        s.append("Mostrar apenas SUVs")
        s.append("Ver Hatch até R$ 80.000")
    if not filters.get("fuel"):
        s.append("Apenas Flex")
        s.append("Diesel para uso rodoviário")
    if not filters.get("doors"):
        s.append("Quero 4 portas")
    return s[:6]

print(f'mensagem do usuario {"user_msg"}')

print(f'historico da conversa {"history"}')

print(f'contexto do catalogo {"context_text"}')

def build_llm_messages(user_msg: str, history: List[Dict], context_text: str) -> List[Dict]:
    """
    Monta as mensagens com instruções estritas para o LLM.
    """
    system_prompt = (
        "Você é um consultor de vendas de uma loja de veículos no Brasil. "
        "Responda de forma clara, amigável e objetiva. "
        "NÃO invente estoque: use SOMENTE o 'Resumo/Amostras' fornecidos no contexto. "
        "Quando o cliente pedir algo específico (ex.: SUV automático até R$ 120.000), "
        "explique o raciocínio e cite de 3 a 5 opções compatíveis que estejam no contexto. "
        "Se nada for compatível, sugira alternativas próximas (ano, preço ou categoria). "
        "Mostre preços em reais com duas casas (ex.: R$ 85.900,00)."
    )

    user_prompt = (
        f"Pergunta do cliente: {user_msg}\n\n"
        f"=== CONTEXTO (derivado do banco de dados) ===\n"
        f"{context_text}\n"
        f"=== FIM DO CONTEXTO ===\n\n"
        "Monte a resposta considerando APENAS o contexto acima."
    )

    msgs = [{"role": "system", "content": system_prompt}]
    for h in history[-6:]:
        role = "user" if h.get("role") == "user" else "assistant"
        msgs.append({"role": role, "content": h.get("content", "")})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs


def fallback_reply(user_msg: str, qs: QuerySet, limit: int = 5) -> str:
    """
    Gera uma resposta amigável SEM LLM, usando as amostras do catálogo.
    Útil quando:
      - OPENAI_API_KEY não está configurada;
      - houve erro de rede/limite/autenticação.
    """
    total = qs.count()
    header = [f"Encontrei {total} opções no nosso estoque para o que você descreveu."]
    if total == 0:
        return (
            "Não encontrei opções exatamente como você pediu. "
            "Posso sugerir alternativas próximas (ano/preço/categoria)?"
        )
    header.append("Algumas sugestões iniciais:")

    lines = []
    for v in qs.order_by("-created_at")[:limit]:
        lines.append(
            f"- {v.brand} {v.model} {v.year} "
            f"({v.body_type}, {v.transmission}, {v.fuel_type}) "
            f"— R$ {v.price:.2f}, {v.mileage_km} km"
        )
    lines.append("Se quiser, posso filtrar por ano mínimo, teto de preço ou tipo de combustível.")
    return "\n".join(header + lines)


# -----------------------------
# View principal do chat
# -----------------------------
@csrf_protect
@require_http_methods(["GET", "POST"])
def vehicle_chat_view(request):
    if request.method == "GET":
        return render(request, "vehicles/chat.html", {})

    # POST (AJAX/Fetch)
    try:
        data = getattr(request, "json", None)
        if data is None:
            data = json.loads(request.body.decode("utf-8"))
        user_msg = (data.get("message") or "").strip()
        history = data.get("history") or []
        if not user_msg:
            return HttpResponseBadRequest("Mensagem vazia.")
    except Exception:
        return HttpResponseBadRequest("Payload inválido.")

    # 1) Parsing de filtros + consulta
    filters = parse_filters(user_msg)
    qs = query_from_filters(filters).order_by("-created_at")

    total_matches = qs.count()

    # Fallback se muito restritivo: mostra catálogo recente
    if total_matches == 0:
        qs = Vehicle.objects.all().order_by("-created_at")
        total_matches = qs.count()

    # 2) Seleção de itens para cards do front
    candidates = list(qs[:12345678])
    items = [vehicle_to_dict(v) for v in candidates]

    # 3) Contexto (resumo + amostras) para o LLM, sempre derivado do BD
    #    max_lines controla o "tamanho" enviado ao modelo.
    context_text = make_catalog_context(qs, max_lines=140)

    # 4) Chamada ao LLM (se disponível), com fallback determinístico seguro
    api_key = os.getenv("OPENAI_API_KEY")
    reply_text: str

    client = None
    if OpenAI and api_key:
        try:
            client = OpenAI(api_key=api_key)
        except Exception:
            client = None  # se falhar a inicialização, cai no fallback

    if client:
        try:
            msgs = build_llm_messages(user_msg, history, context_text)
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=msgs,
                temperature=0.5,
                max_tokens=650,
            )
            reply_text = completion.choices[0].message.content or ""
        except (RateLimitError, APIError, APIConnectionError, AuthenticationError, Exception):
            reply_text = fallback_reply(user_msg, qs, limit=5)
    else:
        reply_text = fallback_reply(user_msg, qs, limit=5)

    # 5) Sugestões de próximos passos (para chips no front)
    suggestions = build_suggestions(filters, total_matches)

    return JsonResponse(
        {
            "reply": reply_text,
            "suggestions": suggestions,
            "items": items,
            "total_matches": total_matches,
            "filters_applied": {
                k: (str(v) if isinstance(v, Decimal) else v)
                for k, v in filters.items()
            },
            "generated_at": now().isoformat(),
        },
        status=200,
        json_dumps_params={"ensure_ascii": False},
    )
