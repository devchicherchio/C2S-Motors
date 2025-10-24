# vehicles/management/commands/seed_vehicles_ai.py
import os
import re
import json
import time
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from vehicles.models import Vehicle

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ---------- Helpers ----------

_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
#Regex para pegar JSON dentro de bloco json ... se a IA retornar assim
CODEBLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
[]
def fallback_vin():
    return "".join(random.choices(_VIN_CHARS, k=17))

def retry_backoff(fn, tries=4, base=1.0):
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(base * (2 ** i) + random.random())

def parse_json_safe(text: str):
    text = text.strip()

    # 1) bloco ```json ... ```
    m = CODEBLOCK_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        return json.loads(candidate)

    # 2) JSON puro
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        return json.loads(text)

    # 3) tentar isolar
    start_brace = text.find("{")
    start_brack = text.find("[")
    starts = [i for i in [start_brace, start_brack] if i != -1]
    if not starts:
        raise ValueError("Resposta não contém JSON")
    start = min(starts)

    end_brace = text.rfind("}")
    end_brack = text.rfind("]")
    end = max(end_brace, end_brack)
    if end == -1 or end <= start:
        raise ValueError("Não foi possível isolar o JSON")

    candidate = text[start:end+1].strip()
    return json.loads(candidate)

# ---------- Prompts ----------

SYSTEM_PROMPT = (
    "Você é um gerador confiável de dados automotivos. "
    "Responda APENAS com JSON válido. "
    "Esquema: objeto com chaves [brand, model, year, engine, fuel_type, color, mileage_km, doors, "
    "transmission, body_type, price, vin] OU um array desses objetos. "
    "Regras: year entre 1995 e 2025; fuel_type em ['gasolina','alcool','diesel','flex','eletrico','hibrido']; "
    "doors em [2,4,5]; transmission em ['manual','automatica','cvt']; body_type em "
    "['hatch','sedan','suv','pickup','coupe','wagon']; price decimal (2 casas); "
    "vin: 17 caracteres A-Z/0-9 SEM I,O,Q. Sem comentários, sem markdown."
)
USER_PROMPT_BATCH = "Gere uma lista JSON de {n} veículos seguindo fielmente o esquema."

DEFAULT_MODEL = os.getenv("OPENAI_MODEL") 

# ---------- Command ----------

class Command(BaseCommand):
    help = "Popula o banco com veículos gerados por LLM (ChatGPT)."

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=100, help="Quantidade total de veículos")
        parser.add_argument("--batch", type=int, default=10, help="Tamanho do batch por chamada")
        parser.add_argument("--wipe", action="store_true", help="Apaga todos os veículos antes")
        parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Modelo OpenAI")

    def handle(self, *args, **options):
        if OpenAI is None:
            self.stderr.write(self.style.ERROR("Instale: pip install openai"))
            return

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.stderr.write(self.style.ERROR("Defina OPENAI_API_KEY no ambiente (.env)."))
            return

        client = OpenAI(api_key=api_key)
        total = options["n"]
        batch = options["batch"]
        model = options["model"]

        if options["wipe"]:
            Vehicle.objects.all().delete()
            self.stdout.write(self.style.WARNING("Tabela Vehicle limpa (wipe=True)"))

        created = 0

        while created < total:
            to_create = min(batch, total - created)
            prompt = USER_PROMPT_BATCH.format(n=to_create)

            def call_api():

                return client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT},
                              {"role": "user", "content": prompt}],
                    temperature=0.6,
                    max_tokens=2000,
                )

            resp = retry_backoff(call_api, tries=4, base=1.0)
            msg = resp.choices[0].message
            text = getattr(msg, "content", None)
            if text is None:
                try:
                    text = msg["content"]
                except Exception:
                    text = str(resp)

            try:
                parsed = parse_json_safe(text)
                if isinstance(parsed, dict):
                    parsed = [parsed]
                if not isinstance(parsed, list):
                    raise ValueError("JSON retornou tipo inesperado (esperado array ou objeto).")
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Falha ao parsear JSON (batch). Resp (início): {text[:300]}"))
                raise

            with transaction.atomic():
                for item in parsed:
                    vin = (item.get("vin") or fallback_vin()).upper()
                    vin = "".join([c for c in vin if c in _VIN_CHARS])[:17]
                    if len(vin) < 17:
                        vin = vin + fallback_vin()[: (17 - len(vin))]

                    # unique VIN
                    if Vehicle.objects.filter(vin=vin).exists():
                        tmp = fallback_vin()
                        while Vehicle.objects.filter(vin=tmp).exists():
                            tmp = fallback_vin()
                        vin = tmp

                    # price
                    price_raw = item.get("price", 0)
                    try:
                        price = Decimal(str(price_raw))
                    except Exception:
                        price = Decimal(f"{random.uniform(20000, 200000):.2f}")

                    Vehicle.objects.create(
                        brand=item.get("brand", "Desconhecido"),
                        model=item.get("model", "Desconhecido"),
                        year=int(item.get("year", 2020)),
                        engine=item.get("engine", ""),
                        fuel_type=item.get("fuel_type", "flex"),
                        color=item.get("color", "preto"),
                        mileage_km=int(item.get("mileage_km", 0)),
                        doors=int(item.get("doors", 4)),
                        transmission=item.get("transmission", "manual"),
                        body_type=item.get("body_type", "sedan"),
                        price=price,
                        vin=vin,
                    )
                    created += 1

            self.stdout.write(self.style.SUCCESS(f"Batch criado: {len(parsed)} (total={created}/{total})"))
            time.sleep(0.4)

        self.stdout.write(self.style.SUCCESS(f"Finalizado. Veículos criados: {created}"))
