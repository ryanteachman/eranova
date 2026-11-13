"""LLM freight classification, cached in the classifications table."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from .. import config, db

WORKERS = 8

Category = Literal[
    "FOOD", "BEVERAGE", "CHEMICAL", "HAZMAT", "WASTE", "WOOD", "STEEL",
    "SCRAP", "PACKAGING", "RETAIL_RETURNS", "MACHINERY", "GENERAL",
]

SYSTEM_PROMPT = (
    "You classify freight for a US freight brokerage. Given a shipment's freight lines, "
    "hazmat flags and trailer equipment code (V dry van, R reefer, F flatbed, SD step deck, "
    "SB straight box, SV sprinter van, HS hotshot), pick the single best category.\n"
    "Categories:\n"
    "- FOOD: anything people or animals eat, including dry, shelf-stable, frozen and "
    "refrigerated food and groceries. Always FOOD, never GENERAL, because food-safety rules "
    "depend on it.\n"
    "- BEVERAGE: drinks.\n"
    "- CHEMICAL: non-hazmat chemicals, fertilizers, cleaners, coatings.\n"
    "- HAZMAT: hazardous materials, for example anything with a UN number.\n"
    "- WASTE: waste or refuse.\n"
    "- WOOD: lumber, wood or composite wood products.\n"
    "- STEEL: steel or metal parts, components and fabrications.\n"
    "- SCRAP: scrap metal.\n"
    "- PACKAGING: cartons, corrugated, pallets and packaging materials.\n"
    "- RETAIL_RETURNS: returned retail merchandise.\n"
    "- MACHINERY: machines and equipment.\n"
    "- GENERAL: other dry consumer or industrial goods.\n"
    "temp_controlled is true when the freight needs refrigeration or freezing. "
    "hazmat is true for hazardous materials (for example anything with a UN number). "
    "Give the rationale in one sentence."
)


class Classification(BaseModel):
    category: Category
    temp_controlled: bool
    hazmat: bool
    confidence: float = Field(ge=0, le=1)
    rationale: str


def _client():
    return OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)


def describe_shipment(shipment):
    """Return the text sent to the model for one shipment: equipment plus each freight line."""
    lines = [f"Equipment: {shipment.get('equipment_type') or 'unknown'}"]
    for line in shipment.get("freight_lines") or []:
        lines.append(
            f"- {line.get('description') or 'no description'}; "
            f"{line.get('pieces')} x {line.get('package_type') or 'unit'}, "
            f"{line.get('weight_lb')} lb, hazmat={bool(line.get('hazmat'))}"
        )
    return "\n".join(lines)


def classify_shipment(shipment, client=None):
    """Ask the model to classify one shipment and return a Classification."""
    client = client or _client()
    completion = client.chat.completions.parse(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": describe_shipment(shipment)},
        ],
        response_format=Classification,
        temperature=0,
    )
    result = completion.choices[0].message.parsed
    # The hazmat flag in Meridian is ground truth and overrides the model.
    if any(line.get("hazmat") for line in shipment.get("freight_lines") or []):
        result.category = "HAZMAT"
        result.hazmat = True
    return result


def save_classification(shipment_id, result):
    """Store one shipment's classification in the cache."""
    with db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO classifications "
            "(shipment_id, category, temp_controlled, hazmat, confidence, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                shipment_id,
                result.category,
                int(result.temp_controlled),
                int(result.hazmat),
                result.confidence,
                result.rationale,
            ),
        )


def get_classifications():
    """Return all cached classifications as a dict keyed by shipment_id."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM classifications").fetchall()
    return {row["shipment_id"]: dict(row) for row in rows}


def classify_all():
    """Classify every cached shipment not classified yet and return {classified, skipped, failed}."""
    done = get_classifications()
    todo = [s for s in db.load_records("shipments") if s["shipment_id"] not in done]
    client = _client()
    failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(classify_shipment, s, client): s["shipment_id"] for s in todo}
        for future in as_completed(futures):
            shipment_id = futures[future]
            try:
                save_classification(shipment_id, future.result())
            except Exception as exc:
                failed += 1
                print(f"classify failed for {shipment_id}: {exc}")
    counts = {"classified": len(todo) - failed, "skipped": len(done), "failed": failed}
    print(f"classified {counts['classified']}, skipped {counts['skipped']}, failed {counts['failed']}")
    db.audit("system", "classify", str(counts))
    return counts
